import asyncio
import unittest
from unittest.mock import patch

from app.game import GameChannelConfig, GameManager


class GameManagerPassiveModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabling_passive_mode_starts_next_round_immediately(self) -> None:
        questions = [
            {
                "category": "Кино",
                "hint": "Подсказка",
                "answer": "ответ",
                "aliases": [],
            }
        ]

        with patch("app.game.load_questions_payload_from_source", return_value=questions):
            manager = GameManager(
                GameChannelConfig(
                    scope_id="user:1",
                    broadcaster_id="1",
                    channel_name="owner",
                    questions_path="db-preset://preset-1",
                    questions_path_main="",
                    questions_path_dota="",
                    passive_mode=True,
                )
            )

        manager.next_round_at = 9999999999.0
        manager._next_round_delay_remaining = 600
        manager._next_round_task = asyncio.create_task(asyncio.sleep(60))

        manager.update_config(passive_mode=False, turbo_mode=True)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertFalse(manager.config.passive_mode)
        self.assertTrue(manager.config.turbo_mode)
        self.assertIsNotNone(manager.current_round)
        self.assertTrue(bool(manager.current_round and manager.current_round.is_active))
        self.assertIsNone(manager.next_round_at)

        if manager._round_task and not manager._round_task.done():
            manager._round_task.cancel()
        if manager._next_round_task and not manager._next_round_task.done():
            manager._next_round_task.cancel()

    async def test_turbo_correct_answer_keeps_result_visible_before_next_round(self) -> None:
        questions = [
            {
                "category": "Кино",
                "hint": "Подсказка",
                "answer": "ответ",
                "aliases": [],
            }
        ]

        with patch("app.game.load_questions_payload_from_source", return_value=questions):
            manager = GameManager(
                GameChannelConfig(
                    scope_id="user:1",
                    broadcaster_id="1",
                    channel_name="owner",
                    questions_path="db-preset://preset-1",
                    questions_path_main="",
                    questions_path_dota="",
                    turbo_mode=True,
                )
            )

        await manager.start_round()
        assert manager.current_round is not None
        manager.current_round.started_at -= 12

        guessed, _ = await manager.handle_guess("alpha", "ответ")

        self.assertTrue(guessed)
        self.assertEqual(manager._next_round_delay_remaining, 5)

        if manager._round_task and not manager._round_task.done():
            manager._round_task.cancel()
        if manager._next_round_task and not manager._next_round_task.done():
            manager._next_round_task.cancel()
