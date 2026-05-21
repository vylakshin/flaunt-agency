import copy
import importlib
import json
import logging
import math
import threading
import time
from typing import Any, Optional

from .config import settings


logger = logging.getLogger(__name__)


class InMemoryRuntimeStateStore:
    def __init__(self, namespace: str = 'app') -> None:
        self._namespace = str(namespace or 'app').strip() or 'app'
        self._lock = threading.Lock()
        self._values: dict[str, tuple[Optional[float], Any]] = {}
        self._seen_keys: dict[str, float] = {}
        self._locks: dict[str, float] = {}

    def _scoped_key(self, key: str) -> str:
        normalized_key = str(key or '').strip()
        return f'{self._namespace}:{normalized_key}' if normalized_key else self._namespace

    def _prune(self, now: float) -> None:
        expired_value_keys = [
            key
            for key, (expires_at, _) in self._values.items()
            if expires_at is not None and expires_at <= now
        ]
        for key in expired_value_keys:
            self._values.pop(key, None)

        expired_seen_keys = [key for key, expires_at in self._seen_keys.items() if expires_at <= now]
        for key in expired_seen_keys:
            self._seen_keys.pop(key, None)

        expired_lock_keys = [key for key, expires_at in self._locks.items() if expires_at <= now]
        for key in expired_lock_keys:
            self._locks.pop(key, None)

    def get(self, key: str, *, now: Optional[float] = None) -> Any:
        current_time = float(time.time() if now is None else now)
        scoped_key = self._scoped_key(key)
        with self._lock:
            self._prune(current_time)
            entry = self._values.get(scoped_key)
            if not entry:
                return None
            return copy.deepcopy(entry[1])

    def set(self, key: str, value: Any, *, ttl_seconds: Optional[float] = None, now: Optional[float] = None) -> None:
        current_time = float(time.time() if now is None else now)
        scoped_key = self._scoped_key(key)
        expires_at: Optional[float] = None
        if ttl_seconds is not None:
            expires_at = current_time + max(0.0, float(ttl_seconds))
        with self._lock:
            self._prune(current_time)
            self._values[scoped_key] = (expires_at, copy.deepcopy(value))

    def delete(self, key: str) -> None:
        scoped_key = self._scoped_key(key)
        with self._lock:
            self._values.pop(scoped_key, None)
            self._seen_keys.pop(scoped_key, None)
            self._locks.pop(scoped_key, None)

    def mark_seen(self, key: str, *, ttl_seconds: float, now: Optional[float] = None) -> bool:
        current_time = float(time.time() if now is None else now)
        scoped_key = self._scoped_key(key)
        with self._lock:
            self._prune(current_time)
            expires_at = self._seen_keys.get(scoped_key)
            if expires_at is not None and expires_at > current_time:
                return True
            self._seen_keys[scoped_key] = current_time + max(0.0, float(ttl_seconds))
            return False

    def acquire_lock(self, key: str, *, ttl_seconds: float, now: Optional[float] = None) -> bool:
        current_time = float(time.time() if now is None else now)
        scoped_key = self._scoped_key(key)
        with self._lock:
            self._prune(current_time)
            expires_at = self._locks.get(scoped_key)
            if expires_at is not None and expires_at > current_time:
                return False
            self._locks[scoped_key] = current_time + max(0.0, float(ttl_seconds))
            return True

    def release_lock(self, key: str) -> None:
        scoped_key = self._scoped_key(key)
        with self._lock:
            self._locks.pop(scoped_key, None)


class RedisRuntimeStateStore:
    def __init__(self, client: Any, namespace: str = 'app') -> None:
        self._client = client
        self._namespace = str(namespace or 'app').strip() or 'app'

    def _scoped_key(self, key: str) -> str:
        normalized_key = str(key or '').strip()
        return f'{self._namespace}:{normalized_key}' if normalized_key else self._namespace

    @staticmethod
    def _normalize_ttl(ttl_seconds: Optional[float]) -> Optional[int]:
        if ttl_seconds is None:
            return None
        return max(1, int(math.ceil(float(ttl_seconds))))

    def get(self, key: str, *, now: Optional[float] = None) -> Any:
        del now
        payload = self._client.get(self._scoped_key(key))
        if payload in (None, b'', ''):
            return None
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8')
        return json.loads(str(payload))

    def set(self, key: str, value: Any, *, ttl_seconds: Optional[float] = None, now: Optional[float] = None) -> None:
        del now
        scoped_key = self._scoped_key(key)
        serialized = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        ttl = self._normalize_ttl(ttl_seconds)
        if ttl is None:
            self._client.set(scoped_key, serialized)
        else:
            self._client.set(scoped_key, serialized, ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(self._scoped_key(key))

    def mark_seen(self, key: str, *, ttl_seconds: float, now: Optional[float] = None) -> bool:
        del now
        created = self._client.set(self._scoped_key(key), '1', ex=self._normalize_ttl(ttl_seconds), nx=True)
        return not bool(created)

    def acquire_lock(self, key: str, *, ttl_seconds: float, now: Optional[float] = None) -> bool:
        del now
        return bool(self._client.set(self._scoped_key(key), '1', ex=self._normalize_ttl(ttl_seconds), nx=True))

    def release_lock(self, key: str) -> None:
        self._client.delete(self._scoped_key(key))


def _build_redis_runtime_state_store(namespace: str) -> Optional[RedisRuntimeStateStore]:
    redis_url = str(getattr(settings, 'runtime_state_redis_url', '') or '').strip()
    if not redis_url:
        logger.warning('Runtime state backend is redis, but RUNTIME_STATE_REDIS_URL is empty; falling back to memory')
        return None
    try:
        redis_module = importlib.import_module('redis')
    except ImportError:
        logger.warning('Runtime state backend is redis, but python package redis is not installed; falling back to memory')
        return None

    try:
        client = redis_module.Redis.from_url(redis_url)
        client.ping()
    except Exception as exc:
        logger.warning('Unable to initialize redis runtime state backend: %s; falling back to memory', exc)
        return None
    return RedisRuntimeStateStore(client, namespace=namespace)


def build_runtime_state_store() -> InMemoryRuntimeStateStore | RedisRuntimeStateStore:
    backend = str(getattr(settings, 'runtime_state_backend', 'memory') or 'memory').strip().lower()
    namespace = str(getattr(settings, 'runtime_state_namespace', 'app') or 'app').strip() or 'app'
    if backend == 'redis':
        redis_store = _build_redis_runtime_state_store(namespace)
        if redis_store is not None:
            return redis_store
    elif backend != 'memory':
        logger.warning('Unsupported runtime state backend=%s, falling back to in-memory store', backend)
    return InMemoryRuntimeStateStore(namespace=namespace)


runtime_state = build_runtime_state_store()
