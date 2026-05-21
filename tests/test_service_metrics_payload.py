import unittest
from unittest.mock import patch

import app.web_site_presence as web_site_presence


class ServiceMetricsPayloadTests(unittest.TestCase):
    def test_service_metrics_payload_is_shaped_for_ui(self) -> None:
        snapshot = {
            "uptime_seconds": 125,
            "counters": {
                "chat.send.attempts": 11,
                "chat.send.app_token.success": 7,
                "chat.send.user_token.success": 3,
                "chat.send.app_token.fallbacks": 1,
                "twitch.get_live_streams.calls": 5,
                "twitch.get_live_streams.failures": 1,
                "runtime_ticker.loops": 9,
            },
            "gauges": {},
            "timings": {
                "runtime.tick": {"count": 3, "avg_ms": 10.0, "max_ms": 20.0, "last_ms": 12.0},
                "timers.tick": {"count": 3, "avg_ms": 5.0, "max_ms": 9.0, "last_ms": 4.0},
                "autobet.tick": {"count": 3, "avg_ms": 7.0, "max_ms": 11.0, "last_ms": 8.0},
                "twitch.get_live_streams": {"count": 2, "avg_ms": 30.0, "max_ms": 40.0, "last_ms": 20.0},
            },
            "recent_errors": [{"key": "twitch.get_live_streams", "message": "boom", "age_seconds": 3}],
            "heartbeats": {"runtime_ticker": {"age_seconds": 2.0}},
        }

        with patch.object(web_site_presence.service_metrics, "snapshot", return_value=snapshot):
            payload = web_site_presence._build_service_metrics_payload()

        self.assertEqual(payload["health"]["status"], "healthy")
        self.assertEqual(payload["overview_cards"][0]["label"], "Uptime")
        self.assertEqual(payload["recent_errors"][0]["key"], "twitch.get_live_streams")
        self.assertFalse(any(item["label"].startswith("OpenDota") for item in payload["pipelines"]))

    def test_twitch_streams_pipeline_ignores_old_errors(self) -> None:
        snapshot = {
            "uptime_seconds": 125,
            "counters": {
                "twitch.get_live_streams.calls": 15,
                "twitch.get_live_streams.failures": 4,
            },
            "gauges": {},
            "timings": {},
            "recent_errors": [{"key": "twitch.get_live_streams", "message": "old boom", "age_seconds": 900}],
            "heartbeats": {"runtime_ticker": {"age_seconds": 2.0}},
        }

        with patch.object(web_site_presence.service_metrics, "snapshot", return_value=snapshot):
            payload = web_site_presence._build_service_metrics_payload()

        twitch_streams = next(item for item in payload["pipelines"] if item["label"] == "Twitch streams API")
        self.assertEqual(twitch_streams["status_label"], "Ок")

    def test_twitch_streams_pipeline_shows_fresh_errors(self) -> None:
        snapshot = {
            "uptime_seconds": 125,
            "counters": {
                "twitch.get_live_streams.calls": 15,
                "twitch.get_live_streams.failures": 4,
            },
            "gauges": {},
            "timings": {},
            "recent_errors": [{"key": "twitch.get_live_streams", "message": "fresh boom", "age_seconds": 12}],
            "heartbeats": {"runtime_ticker": {"age_seconds": 2.0}},
        }

        with patch.object(web_site_presence.service_metrics, "snapshot", return_value=snapshot):
            payload = web_site_presence._build_service_metrics_payload()

        twitch_streams = next(item for item in payload["pipelines"] if item["label"] == "Twitch streams API")
        self.assertEqual(twitch_streams["status_label"], "С ошибками")

    def test_twitch_streams_pipeline_treats_stale_cache_fallback_as_healthy(self) -> None:
        snapshot = {
            "uptime_seconds": 125,
            "counters": {
                "twitch.get_live_streams.calls": 15,
                "twitch.get_live_streams.failures": 4,
                "twitch.get_live_streams.stale_cache_hits": 2,
            },
            "gauges": {},
            "timings": {},
            "recent_errors": [{"key": "twitch.get_live_streams", "message": "dns boom (using stale cache)", "age_seconds": 12}],
            "heartbeats": {"runtime_ticker": {"age_seconds": 2.0}},
        }

        with patch.object(web_site_presence.service_metrics, "snapshot", return_value=snapshot):
            payload = web_site_presence._build_service_metrics_payload()

        twitch_streams = next(item for item in payload["pipelines"] if item["label"] == "Twitch streams API")
        self.assertEqual(twitch_streams["status_label"], "Из кэша")
