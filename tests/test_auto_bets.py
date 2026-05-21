import unittest
from unittest.mock import patch

from app.auto_bets import AutoBetRuntime
from app.runtime_state import InMemoryRuntimeStateStore


class AutoBetThresholdTests(unittest.TestCase):
    def test_threshold_uses_exact_admin_range(self) -> None:
        for _ in range(50):
            threshold = AutoBetRuntime._threshold_from_range(
                current_value=0,
                minimum=15,
                maximum=23,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            self.assertGreaterEqual(threshold, 15)
            self.assertLessEqual(threshold, 23)

    def test_threshold_respects_current_value_floor(self) -> None:
        threshold = AutoBetRuntime._threshold_from_range(
            current_value=20,
            minimum=15,
            maximum=23,
            absolute_minimum=0,
            absolute_maximum=999,
        )
        self.assertGreaterEqual(threshold, 21)
        self.assertLessEqual(threshold, 23)

    def test_threshold_clamps_when_current_value_is_above_max(self) -> None:
        threshold = AutoBetRuntime._threshold_from_range(
            current_value=99,
            minimum=15,
            maximum=23,
            absolute_minimum=0,
            absolute_maximum=999,
        )
        self.assertEqual(threshold, 23)

    def test_prediction_open_lock_is_shared_via_runtime_state(self) -> None:
        runtime = AutoBetRuntime()
        store = InMemoryRuntimeStateStore(namespace='test-autobet')

        with patch('app.auto_bets.runtime_state', new=store):
            self.assertTrue(runtime._begin_prediction_open('channel-1'))
            self.assertFalse(runtime._begin_prediction_open('channel-1'))
            runtime._finish_prediction_open('channel-1')
            self.assertTrue(runtime._begin_prediction_open('channel-1'))
