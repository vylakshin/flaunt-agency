import unittest

from app.service_metrics import ServiceMetrics


class ServiceMetricsTests(unittest.TestCase):
    def test_snapshot_contains_counters_timings_and_errors(self) -> None:
        metrics = ServiceMetrics()
        metrics.increment('chat.send.attempts')
        metrics.set_gauge('channels.active', 12)
        metrics.observe_duration('runtime.tick', 0.125)
        metrics.record_error('opendota.live', 'boom', context={'source': 'test'})
        metrics.heartbeat('runtime_ticker')

        snapshot = metrics.snapshot()

        self.assertEqual(snapshot['counters']['chat.send.attempts'], 1)
        self.assertEqual(snapshot['gauges']['channels.active'], 12.0)
        self.assertEqual(snapshot['timings']['runtime.tick']['count'], 1)
        self.assertEqual(snapshot['recent_errors'][0]['key'], 'opendota.live')
        self.assertIn('runtime_ticker', snapshot['heartbeats'])

    def test_reset_clears_state(self) -> None:
        metrics = ServiceMetrics()
        metrics.increment('chat.send.attempts')
        metrics.record_error('chat.send', 'boom')
        metrics.reset()

        snapshot = metrics.snapshot()

        self.assertEqual(snapshot['counters'], {})
        self.assertEqual(snapshot['recent_errors'], [])
