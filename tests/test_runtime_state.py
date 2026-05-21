import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.runtime_state import InMemoryRuntimeStateStore
from app.runtime_state import RedisRuntimeStateStore
from app.runtime_state import build_runtime_state_store


class RuntimeStateStoreTests(unittest.TestCase):
    def test_mark_seen_expires_after_ttl(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test')

        self.assertFalse(store.mark_seen('event-1', ttl_seconds=10, now=100.0))
        self.assertTrue(store.mark_seen('event-1', ttl_seconds=10, now=105.0))
        self.assertFalse(store.mark_seen('event-1', ttl_seconds=10, now=111.0))

    def test_lock_expires_and_can_be_reacquired(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test')

        self.assertTrue(store.acquire_lock('lock-1', ttl_seconds=10, now=50.0))
        self.assertFalse(store.acquire_lock('lock-1', ttl_seconds=10, now=55.0))
        self.assertTrue(store.acquire_lock('lock-1', ttl_seconds=10, now=61.0))

    def test_set_get_and_delete_respect_ttl(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test')

        store.set('payload', {'ok': True}, ttl_seconds=10, now=10.0)
        self.assertEqual(store.get('payload', now=15.0), {'ok': True})
        self.assertIsNone(store.get('payload', now=21.0))

        store.set('payload', {'ok': False}, ttl_seconds=10, now=30.0)
        store.delete('payload')
        self.assertIsNone(store.get('payload', now=31.0))

    def test_build_runtime_state_store_falls_back_when_redis_package_is_missing(self) -> None:
        with patch('app.runtime_state.settings.runtime_state_backend', 'redis'):
            with patch('app.runtime_state.settings.runtime_state_namespace', 'test'):
                with patch('app.runtime_state.settings.runtime_state_redis_url', 'redis://localhost:6379/0'):
                    with patch('app.runtime_state.importlib.import_module', side_effect=ImportError):
                        store = build_runtime_state_store()

        self.assertIsInstance(store, InMemoryRuntimeStateStore)

    def test_build_runtime_state_store_uses_redis_backend_when_available(self) -> None:
        class FakeRedisClient:
            def __init__(self) -> None:
                self.values: dict[str, tuple[object, int | None]] = {}

            def ping(self) -> bool:
                return True

            def get(self, key: str):
                entry = self.values.get(key)
                return entry[0] if entry else None

            def set(self, key: str, value, ex=None, nx=False):
                if nx and key in self.values:
                    return False
                self.values[key] = (value, ex)
                return True

            def delete(self, key: str):
                self.values.pop(key, None)

        class FakeRedisFactory:
            @staticmethod
            def from_url(url: str):
                self.assertEqual(url, 'redis://localhost:6379/0')
                return FakeRedisClient()

        fake_module = SimpleNamespace(Redis=FakeRedisFactory)

        with patch('app.runtime_state.settings.runtime_state_backend', 'redis'):
            with patch('app.runtime_state.settings.runtime_state_namespace', 'test'):
                with patch('app.runtime_state.settings.runtime_state_redis_url', 'redis://localhost:6379/0'):
                    with patch('app.runtime_state.importlib.import_module', return_value=fake_module):
                        store = build_runtime_state_store()

        self.assertIsInstance(store, RedisRuntimeStateStore)
        store.set('payload', {'ok': True}, ttl_seconds=10)
        self.assertEqual(store.get('payload'), {'ok': True})
