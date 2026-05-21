import threading
import time
from collections import deque
from typing import Any


class ServiceMetrics:
    def __init__(self) -> None:
        self._recent_errors_limit = 25
        self._reset()

    def _reset(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._timings: dict[str, dict[str, float]] = {}
        self._recent_errors: deque[dict[str, Any]] = deque(maxlen=self._recent_errors_limit)
        self._heartbeats: dict[str, float] = {}

    def reset(self) -> None:
        with self._lock:
            self._started_at = time.time()
            self._counters.clear()
            self._gauges.clear()
            self._timings.clear()
            self._recent_errors.clear()
            self._heartbeats.clear()

    def increment(self, key: str, amount: int = 1) -> None:
        normalized_key = str(key or '').strip()
        if not normalized_key:
            return
        with self._lock:
            self._counters[normalized_key] = int(self._counters.get(normalized_key, 0)) + int(amount)

    def set_gauge(self, key: str, value: float) -> None:
        normalized_key = str(key or '').strip()
        if not normalized_key:
            return
        with self._lock:
            self._gauges[normalized_key] = float(value)

    def observe_duration(self, key: str, duration_seconds: float) -> None:
        normalized_key = str(key or '').strip()
        if not normalized_key:
            return
        duration_ms = max(0.0, float(duration_seconds)) * 1000.0
        with self._lock:
            current = self._timings.get(normalized_key) or {'count': 0.0, 'sum_ms': 0.0, 'max_ms': 0.0, 'last_ms': 0.0}
            current['count'] += 1.0
            current['sum_ms'] += duration_ms
            current['last_ms'] = duration_ms
            current['max_ms'] = max(float(current['max_ms']), duration_ms)
            self._timings[normalized_key] = current

    def record_error(self, key: str, message: str, *, context: dict[str, Any] | None = None) -> None:
        normalized_key = str(key or '').strip() or 'unknown'
        with self._lock:
            self._recent_errors.appendleft(
                {
                    'key': normalized_key,
                    'message': str(message or '').strip(),
                    'context': dict(context or {}),
                    'created_at': time.time(),
                }
            )
            self._counters[f'{normalized_key}.errors'] = int(self._counters.get(f'{normalized_key}.errors', 0)) + 1

    def heartbeat(self, key: str) -> None:
        normalized_key = str(key or '').strip()
        if not normalized_key:
            return
        with self._lock:
            self._heartbeats[normalized_key] = time.time()

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            counters = {key: int(value) for key, value in self._counters.items()}
            gauges = {key: float(value) for key, value in self._gauges.items()}
            timings = {
                key: {
                    'count': int(value.get('count', 0)),
                    'avg_ms': round((float(value.get('sum_ms', 0.0)) / float(value.get('count', 1.0))) if float(value.get('count', 0.0)) else 0.0, 2),
                    'max_ms': round(float(value.get('max_ms', 0.0)), 2),
                    'last_ms': round(float(value.get('last_ms', 0.0)), 2),
                }
                for key, value in self._timings.items()
            }
            recent_errors = [
                {
                    **item,
                    'age_seconds': int(max(0.0, now - float(item.get('created_at') or now))),
                }
                for item in list(self._recent_errors)
            ]
            heartbeats = {
                key: {
                    'last_seen_at': value,
                    'age_seconds': round(max(0.0, now - value), 2),
                }
                for key, value in self._heartbeats.items()
            }

        return {
            'started_at': self._started_at,
            'uptime_seconds': int(max(0.0, now - self._started_at)),
            'generated_at': now,
            'counters': counters,
            'gauges': gauges,
            'timings': timings,
            'recent_errors': recent_errors,
            'heartbeats': heartbeats,
        }


service_metrics = ServiceMetrics()
