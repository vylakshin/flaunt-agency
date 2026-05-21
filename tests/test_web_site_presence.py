import unittest
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from fastapi import UploadFile

from app.runtime_state import InMemoryRuntimeStateStore
import app.web_site_presence as web_site_presence


def _db_timestamp(seconds_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S")


class AdminAccessTests(unittest.TestCase):
    def test_bot_manager_is_not_admin(self) -> None:
        user = {"login": "szpaked", "is_admin": 0}
        with patch.object(web_site_presence.settings, "bot_auth_allowed_logins", "szpaked"):
            self.assertTrue(web_site_presence._can_manage_bot_account(user))
            self.assertFalse(web_site_presence._is_admin_user(user))

    def test_admin_settings_context_hides_bot_account(self) -> None:
        users = [
            {
                "id": 1,
                "login": "szpaked",
                "display_name": "szpaked",
                "is_admin": 1,
                "created_at": "2026-04-09 10:00:00",
                "updated_at": "2026-04-09 10:00:00",
            },
            {
                "id": 2,
                "login": "quuuizbot",
                "display_name": "quuuizbot",
                "is_admin": 1,
                "created_at": "2026-04-09 10:01:00",
                "updated_at": "2026-04-09 10:01:00",
            },
            {
                "id": 3,
                "login": "viewer",
                "display_name": "viewer",
                "is_admin": 0,
                "created_at": "2026-04-09 10:02:00",
                "updated_at": "2026-04-09 10:02:00",
            },
        ]

        with patch.object(web_site_presence, "list_web_users", return_value=users):
            with patch.object(web_site_presence, "get_user_auto_bet_settings", return_value={"dota2_enabled": 0, "cs2_enabled": 0, "active_prediction_id": "", "active_game_key": ""}):
                with patch.object(web_site_presence.auto_bet_runtime, "get_gsi_debug_state", return_value={}):
                    with patch.object(web_site_presence.settings, "twitch_bot_user_login", "quuuizbot"):
                        context = web_site_presence._build_admin_settings_context(users[0])

        self.assertEqual([item["login"] for item in context["admin_users"]], ["szpaked"])
        self.assertEqual([item["login"] for item in context["admin_candidates"]], ["viewer"])

    def test_admin_settings_context_hides_legacy_dota_special_ranges(self) -> None:
        current_user = {"id": 1, "login": "szpaked", "display_name": "szpaked", "is_admin": 1}
        users = [
            {
                "id": 1,
                "login": "szpaked",
                "display_name": "szpaked",
                "is_admin": 1,
                "created_at": "2026-04-09 10:00:00",
                "updated_at": "2026-04-09 10:00:00",
            }
        ]

        with patch.object(web_site_presence, "list_web_users", return_value=users):
            with patch.object(web_site_presence, "get_user_auto_bet_settings", return_value={"dota2_enabled": 0, "cs2_enabled": 0, "active_prediction_id": "", "active_game_key": ""}):
                with patch.object(web_site_presence.auto_bet_runtime, "get_gsi_debug_state", return_value={}):
                    with patch.object(web_site_presence.settings, "twitch_bot_user_login", "quuuizbot"):
                        context = web_site_presence._build_admin_settings_context(current_user)

        dota_ranges = context["global_settings"]["custom_market_ranges"]["dota2"]
        self.assertEqual(set(dota_ranges.keys()), {"kills", "deaths", "assists", "duration"})

    def test_admin_settings_context_includes_autobet_debug_channels(self) -> None:
        current_user = {"id": 1, "login": "szpaked", "display_name": "szpaked", "is_admin": 1}
        users = [
            {
                "id": 1,
                "login": "szpaked",
                "display_name": "szpaked",
                "is_admin": 1,
                "created_at": "2026-04-09 10:00:00",
                "updated_at": "2026-04-09 10:00:00",
            }
        ]
        auto_settings = {
            "dota2_enabled": 1,
            "cs2_enabled": 0,
            "active_prediction_id": "",
            "active_game_key": "",
            "gsi_match_id": "8764534875",
            "gsi_game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "gsi_game_time": 119,
            "gsi_hero_name": "Dawnbreaker",
            "gsi_kills": 0,
            "gsi_deaths": 0,
            "gsi_assists": 0,
        }
        dota_debug = {
            "updated_at": 200.0,
            "match_id": "8764534875",
            "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
            "game_time": 119,
            "hero_name": "Dawnbreaker",
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "game_mode": "2",
            "lobby_type": "",
        }

        with patch.object(web_site_presence, "time") as time_mock:
            time_mock.time.return_value = 201.0
            with patch.object(web_site_presence, "list_web_users", return_value=users):
                with patch.object(web_site_presence, "get_user_auto_bet_settings", return_value=auto_settings):
                    with patch.object(
                        web_site_presence.auto_bet_runtime,
                        "get_gsi_debug_state",
                        side_effect=lambda user_id, game_key: dota_debug if game_key == "dota2" else {},
                    ):
                        with patch.object(web_site_presence.settings, "twitch_bot_user_login", "quuuizbot"):
                            context = web_site_presence._build_admin_settings_context(current_user)

        debug_channels = context["autobet_debug_channels"]
        self.assertEqual(len(debug_channels), 1)
        self.assertEqual(debug_channels[0]["login"], "szpaked")
        self.assertTrue(debug_channels[0]["gsi"]["dota2"]["connected"])
        self.assertEqual(debug_channels[0]["gsi"]["dota2"]["mode_label"], "2 / —")
        self.assertTrue(debug_channels[0]["gsi"]["dota2"]["opening_allowed"])

    def test_admin_debug_does_not_leak_cs2_shared_state_into_dota_card(self) -> None:
        current_user = {"id": 1, "login": "szpaked", "display_name": "szpaked", "is_admin": 1}
        users = [
            {
                "id": 1,
                "login": "szpaked",
                "display_name": "szpaked",
                "is_admin": 1,
                "created_at": "2026-04-09 10:00:00",
                "updated_at": "2026-04-09 10:00:00",
            }
        ]
        auto_settings = {
            "dota2_enabled": 1,
            "cs2_enabled": 1,
            "active_prediction_id": "",
            "active_game_key": "",
            "gsi_match_id": "76561198803233589-de_inferno",
            "gsi_game_state": "CS2 competitive live",
            "gsi_game_time": 1,
            "gsi_hero_name": "de_inferno",
            "gsi_kills": 1,
            "gsi_deaths": 0,
            "gsi_assists": 0,
        }
        cs2_debug = {
            "updated_at": 200.0,
            "match_id": "76561198803233589-de_inferno",
            "phase": "live",
            "mode": "competitive",
            "round": 1,
            "map_name": "de_inferno",
            "kills": 1,
            "deaths": 0,
            "assists": 0,
            "player_team": "CT",
        }

        with patch.object(web_site_presence, "time") as time_mock:
            time_mock.time.return_value = 201.0
            with patch.object(web_site_presence, "list_web_users", return_value=users):
                with patch.object(web_site_presence, "get_user_auto_bet_settings", return_value=auto_settings):
                    with patch.object(
                        web_site_presence.auto_bet_runtime,
                        "get_gsi_debug_state",
                        side_effect=lambda user_id, game_key: cs2_debug if game_key == "cs2" else {},
                    ):
                        with patch.object(web_site_presence.settings, "twitch_bot_user_login", "quuuizbot"):
                            context = web_site_presence._build_admin_settings_context(current_user)

        debug_channel = context["autobet_debug_channels"][0]
        self.assertEqual(debug_channel["gsi"]["dota2"]["match_id"], "")
        self.assertEqual(debug_channel["gsi"]["dota2"]["subject_label"], "—")
        self.assertEqual(debug_channel["gsi"]["cs2"]["match_id"], "76561198803233589-de_inferno")
        self.assertEqual(debug_channel["gsi"]["cs2"]["subject_label"], "de_inferno")


class RecentAutoBetResultTests(unittest.TestCase):
    def test_recent_result_is_returned_within_visibility_window(self) -> None:
        history_row = {
            "prediction_id": "prediction-1",
            "title": "Матч Dota 2: победа?",
            "outcome_title": "Победа",
            "status": "RESOLVED",
            "created_at": _db_timestamp(12),
        }
        with patch.object(web_site_presence, "list_user_auto_bet_history", return_value=[history_row]):
            payload = web_site_presence._build_recent_autobet_result_payload(1)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["prediction_id"], "prediction-1")
        self.assertEqual(payload["status"], "RESOLVED")

    def test_recent_result_expires_after_visibility_window(self) -> None:
        history_row = {
            "prediction_id": "prediction-1",
            "title": "Матч Dota 2: победа?",
            "outcome_title": "Победа",
            "status": "RESOLVED",
            "created_at": _db_timestamp(25),
        }
        with patch.object(web_site_presence, "list_user_auto_bet_history", return_value=[history_row]):
            payload = web_site_presence._build_recent_autobet_result_payload(1)

        self.assertIsNone(payload)


class PublicAutoBetOverlayPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_overlay_payload_includes_active_prediction_and_recent_result(self) -> None:
        user = {"id": 1, "login": "szpaked", "display_name": "szpaked"}
        active_prediction = {"id": "prediction-1", "status": "ACTIVE"}
        recent_result = {"prediction_id": "prediction-0", "status": "RESOLVED"}

        with patch.object(web_site_presence, "get_user_auto_bet_settings", return_value={"active_prediction_id": "prediction-1"}):
            with patch.object(
                web_site_presence,
                "_get_cached_active_auto_bet_prediction",
                AsyncMock(return_value=active_prediction),
            ) as active_mock:
                with patch.object(
                    web_site_presence,
                    "_build_recent_autobet_result_payload",
                    return_value=recent_result,
                ):
                    payload = await web_site_presence._build_public_autobet_overlay_payload(user, "slug-123")

        self.assertEqual(payload["channel_name"], "szpaked")
        self.assertEqual(payload["owner_display_name"], "szpaked")
        self.assertEqual(payload["overlay_slug"], "slug-123")
        self.assertEqual(payload["active_prediction"], active_prediction)
        self.assertEqual(payload["recent_result"], recent_result)
        active_mock.assert_awaited_once()

    async def test_active_prediction_cache_uses_runtime_state(self) -> None:
        user = {"id": 1, "login": "szpaked", "display_name": "szpaked"}
        auto_settings = {"active_prediction_id": "prediction-1"}
        prediction_payload = {"id": "prediction-1", "status": "ACTIVE"}
        store = InMemoryRuntimeStateStore(namespace='test-web')

        with patch.object(web_site_presence, "runtime_state", store):
            with patch.object(
                web_site_presence,
                "_build_active_auto_bet_prediction",
                AsyncMock(return_value=prediction_payload),
            ) as build_mock:
                first = await web_site_presence._get_cached_active_auto_bet_prediction(
                    user,
                    auto_settings,
                    "prediction-1",
                )
                second = await web_site_presence._get_cached_active_auto_bet_prediction(
                    user,
                    auto_settings,
                    "prediction-1",
                )

        self.assertEqual(first, prediction_payload)
        self.assertEqual(second, prediction_payload)
        build_mock.assert_awaited_once()


class AutoBetPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_uses_gsi_only_without_steam_or_opendota_blocks(self) -> None:
        user = {"id": 1, "login": "szpaked", "display_name": "szpaked", "twitch_user_id": "123", "overlay_slug": "slug-1"}
        settings_row = {
            "user_id": 1,
            "gsi_token": "token-1",
            "active_prediction_id": "",
            "gsi_last_seen_at": 0,
            "gsi_match_id": "",
            "gsi_game_state": "",
            "gsi_game_time": 0,
            "gsi_hero_id": 0,
            "gsi_hero_name": "",
            "gsi_kills": 0,
            "gsi_deaths": 0,
            "gsi_assists": 0,
        }

        with patch.object(web_site_presence.auto_bet_runtime, "payload", return_value={"games": []}):
            with patch.object(web_site_presence, "ensure_user_auto_bet_gsi_token", return_value=settings_row):
                with patch.object(web_site_presence, "_get_cached_active_auto_bet_prediction", AsyncMock(return_value=None)):
                    with patch.object(web_site_presence, "list_user_auto_bet_history", return_value=[]):
                        payload = await web_site_presence._build_auto_bet_payload(user)

        self.assertIn("gsi", payload)
        self.assertNotIn("steam", payload)
        self.assertNotIn("opendota", payload)


class StatsContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_context_handles_utc_timestamps_without_500(self) -> None:
        users = [
            {
                "id": 1,
                "login": "szpaked",
                "display_name": "szpaked",
                "twitch_user_id": "123",
                "bot_enabled": 1,
                "questions_file": "",
                "turbo_mode": 0,
                "quiet_mode": 0,
                "overlay_slug": "slug-1",
                "created_at": "2026-04-09 10:00:00",
                "updated_at": "2026-04-09 10:00:00",
            },
            {
                "id": 2,
                "login": "viewer",
                "display_name": "viewer",
                "twitch_user_id": "",
                "bot_enabled": 1,
                "questions_file": "",
                "turbo_mode": 0,
                "quiet_mode": 0,
                "overlay_slug": "slug-2",
                "created_at": "",
                "updated_at": "",
            },
        ]

        with patch.object(web_site_presence, "list_web_users", return_value=users):
            with patch.object(web_site_presence.twitch_api, "get_live_streams", AsyncMock(return_value={})):
                with patch.object(web_site_presence.twitch_listener, "is_channel_connected", return_value=False):
                    with patch.object(web_site_presence, "list_user_bot_commands", return_value=[]):
                        with patch.object(web_site_presence, "list_user_timers", return_value=[]):
                            with patch.object(web_site_presence, "count_user_action_logs", return_value=0):
                                context = await web_site_presence._build_stats_context()

        self.assertEqual(context["stats_cards"][0]["label"], "Кастомных команд")
        self.assertEqual(len(context["recent_channels"]), 2)
        systems_status = context["systems_status"]
        self.assertIn("summary", systems_status)
        self.assertIn("fleet", systems_status)
        self.assertGreaterEqual(len(systems_status["layers"]), 3)
        self.assertEqual(systems_status["fleet"]["active_channels"], 2)
class QuizUploadRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_route_returns_json_error_for_unexpected_failures(self) -> None:
        upload = UploadFile(filename="quiz.json", file=BytesIO(b"[]"))
        user = {"id": 4, "login": "gorchh1ca", "twitch_user_id": "1233761197"}

        with patch.object(web_site_presence, "require_channel_user", AsyncMock(return_value=user)):
            with patch.object(web_site_presence, "add_user_question_config", side_effect=RuntimeError("boom")):
                response = await web_site_presence.api_app_dashboard_questions_upload(object(), questions_file=upload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.body.decode("utf-8"), '{"ok":false,"error":"Не удалось загрузить конфиг вопросов. Попробуй ещё раз."}')


class StandardQuestionPresetAdminTests(unittest.TestCase):
    def test_admin_settings_context_includes_standard_question_presets(self) -> None:
        current_user = {"id": 1, "login": "admin", "display_name": "admin", "is_admin": 1}

        with patch.object(web_site_presence, "list_web_users", return_value=[]):
            with patch.object(
                web_site_presence,
                "_list_standard_question_presets",
                return_value=[{"file_name": "questions.json", "name": "Стандартная база", "question_count": 2000, "is_builtin": True, "linked_user_count": 3}],
            ):
                context = web_site_presence._build_admin_settings_context(current_user)

        self.assertEqual(
            context["standard_question_presets"],
            [{"file_name": "questions.json", "name": "Стандартная база", "question_count": 2000, "is_builtin": True, "linked_user_count": 3}],
        )


class StandardQuestionPresetDistributionTests(unittest.IsolatedAsyncioTestCase):
    async def test_distribution_skips_existing_and_limit_users(self) -> None:
        request = object()
        admin_user = {"id": 1, "login": "admin", "display_name": "admin", "is_admin": 1}
        all_users = [
            {"id": 2, "login": "alpha"},
            {"id": 3, "login": "beta"},
            {"id": 4, "login": "gamma"},
        ]
        presets = [
            {
                "file_name": "questions.json",
                "name": "Стандартная база",
                "question_count": 2000,
            }
        ]

        def fake_configs(user_id: int):
            if user_id == 2:
                return [{"name": "Стандартная база"}]
            if user_id == 3:
                return [{"name": "A"}, {"name": "B"}, {"name": "C"}]
            return []

        with patch.object(web_site_presence, "require_admin_user", return_value=admin_user):
            with patch.object(web_site_presence, "_list_standard_question_presets", return_value=presets):
                with patch.object(web_site_presence, "list_web_users", return_value=all_users):
                    with patch.object(web_site_presence, "get_user_question_configs", side_effect=fake_configs):
                        with patch.object(web_site_presence, "add_user_question_config") as add_mock:
                            with patch.object(web_site_presence, "_log_user_action"):
                                response = await web_site_presence.api_app_settings_question_presets_distribute(
                                    request,
                                    {"file_name": "questions.json"},
                                )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        # Shared presets no longer collide with personal configs that only share the
        # same title. We skip only the exact same preset source.
        self.assertEqual(payload["added"], 3)
        self.assertEqual(payload["skipped_existing"], 0)
        self.assertEqual(payload["skipped_limit"], 0)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(add_mock.call_count, 3)


class QuizSeasonRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_quiz_season_start_returns_updated_quiz_state(self) -> None:
        request = object()
        user = {"id": 4, "login": "owner", "display_name": "owner", "twitch_user_id": "123"}
        user_game = Mock()
        user_game.config.scope_id = "user:123"
        user_game.get_public_state.return_value = {"season": {"title": "Неделя знаний"}}

        with patch.object(web_site_presence, "require_channel_user", AsyncMock(return_value=user)):
            with patch.object(web_site_presence, "_get_user_game", return_value=user_game):
                with patch.object(
                    web_site_presence.quiz_db,
                    "create_quiz_season",
                    return_value={"id": 7, "title": "Неделя знаний", "ends_at": "2026-04-16 18:00:00"},
                ):
                    with patch.object(web_site_presence, "_log_user_action") as log_mock:
                        response = await web_site_presence.api_app_quiz_season_start(
                            request,
                            {"title": "Неделя знаний", "ends_at": "2026-04-16T18:00:00+00:00"},
                        )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Сезон запущен.")
        self.assertEqual(payload["quiz"]["season"]["title"], "Неделя знаний")
        log_mock.assert_called_once()

    async def test_quiz_season_finish_returns_error_without_active_season(self) -> None:
        request = object()
        user = {"id": 4, "login": "owner", "display_name": "owner", "twitch_user_id": "123"}
        user_game = Mock()
        user_game.config.scope_id = "user:123"

        with patch.object(web_site_presence, "require_channel_user", AsyncMock(return_value=user)):
            with patch.object(web_site_presence, "_get_user_game", return_value=user_game):
                with patch.object(web_site_presence.quiz_db, "finish_quiz_season", return_value=None):
                    response = await web_site_presence.api_app_quiz_season_finish(request)

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Активный сезон не найден.")
