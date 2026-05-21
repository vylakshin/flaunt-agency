import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from app.auto_bets import AutoBetRuntime
from app.runtime_state import InMemoryRuntimeStateStore


class AutoBetRuntimeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_dota_gsi_payload_opens_prediction_for_live_match(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "map": {
                "matchid": "debug-dota-501",
                "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
                "game_mode": "22",
                "lobby_type": "7",
                "clock_time": 75,
            },
            "hero": {"id": 14, "name": "npc_dota_hero_pudge"},
            "player": {"kills": 1, "deaths": 0, "assists": 2},
        }

        with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
            with patch.object(runtime, "_stream_online_gate_passed", AsyncMock(return_value=True)):
                with patch.object(runtime, "_open_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                    result = await runtime.handle_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["opened"])
        open_mock.assert_awaited_once()

    async def test_handle_dota_gsi_payload_opens_for_live_match_with_unrecognized_mode(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "map": {
                "matchid": "debug-dota-503",
                "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
                "game_mode": "2",
                "lobby_type": "",
                "clock_time": 90,
            },
            "hero": {"id": 135, "name": "npc_dota_hero_dawnbreaker"},
            "player": {"kills": 0, "deaths": 0, "assists": 0},
        }

        with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
            with patch.object(runtime, "_stream_online_gate_passed", AsyncMock(return_value=True)):
                with patch.object(runtime, "_open_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                    result = await runtime.handle_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["opened"])
        open_mock.assert_awaited_once()

    async def test_handle_dota_gsi_payload_opens_when_all_ten_heroes_are_picked(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "map": {
                "matchid": "debug-dota-504",
                "game_state": "DOTA_GAMERULES_STATE_PRE_GAME",
                "game_mode": "22",
                "lobby_type": "7",
                "clock_time": 0,
            },
            "hero": {"id": 135, "name": "npc_dota_hero_dawnbreaker"},
            "player": {"kills": 0, "deaths": 0, "assists": 0},
            "allplayers": {
                str(index): {
                    "accountid": str(1000 + index),
                    "hero_id": index + 1,
                    "hero": {"id": index + 1, "name": f"npc_dota_hero_{index + 1}"},
                }
                for index in range(10)
            },
        }

        with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
            with patch.object(runtime, "_stream_online_gate_passed", AsyncMock(return_value=True)):
                with patch.object(runtime, "_open_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                    result = await runtime.handle_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["opened"])
        open_mock.assert_awaited_once()

    async def test_handle_dota_gsi_payload_opens_when_match_time_is_running_even_if_state_is_weird(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "map": {
                "matchid": "debug-dota-505",
                "game_state": "DOTA_GAMERULES_STATE_UNKNOWN",
                "game_mode": "22",
                "lobby_type": "7",
                "clock_time": 86,
            },
            "hero": {"id": 135, "name": "npc_dota_hero_dawnbreaker"},
            "player": {"kills": 0, "deaths": 0, "assists": 0},
        }

        with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
            with patch.object(runtime, "_stream_online_gate_passed", AsyncMock(return_value=True)):
                with patch.object(runtime, "_open_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                    result = await runtime.handle_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["opened"])
        open_mock.assert_awaited_once()

    async def test_debug_open_dota_gsi_prediction_opens_when_game_enabled(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}

        with patch("app.auto_bets.get_user_auto_bet_settings", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
            with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value={"dota2_enabled": 1, "active_prediction_id": ""}):
                with patch.object(runtime, "_open_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                    result = await runtime.debug_open_dota_gsi_prediction(user, match_id="debug-dota-777")

        self.assertTrue(result["opened"])
        self.assertEqual(result["match_id"], "debug-dota-777")
        open_mock.assert_awaited_once()

    async def test_handle_dota_gsi_payload_resolves_active_prediction_after_match(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "map": {
                "matchid": "debug-dota-502",
                "game_state": "DOTA_GAMERULES_STATE_POST_GAME",
                "game_mode": "22",
                "lobby_type": "7",
                "clock_time": 2440,
                "winner": "radiant",
            },
            "hero": {"id": 74, "name": "npc_dota_hero_invoker"},
            "player": {"kills": 14, "deaths": 3, "assists": 11, "team_name": "radiant"},
        }

        with patch(
            "app.auto_bets.set_user_auto_bet_gsi_state",
            return_value={
                "dota2_enabled": 1,
                "active_prediction_id": "prediction-1",
                "active_game_key": "dota2",
                "last_opened_stream_signature": "dota-gsi:debug-dota-502:kills_over:12",
            },
        ):
            with patch.object(runtime, "_resolve_dota_gsi_prediction", AsyncMock()) as resolve_mock:
                result = await runtime.handle_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertFalse(result["opened"])
        resolve_mock.assert_awaited_once()

    async def test_handle_cs2_gsi_payload_opens_prediction_for_live_match(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "provider": {"steamid": "76561198803233589"},
            "map": {
                "matchid": "debug-cs2-501",
                "name": "de_mirage",
                "mode": "premier",
                "phase": "live",
                "round": 7,
                "team_ct": {"score": 3},
                "team_t": {"score": 4},
            },
            "player_id": {"steamid": "76561198803233589"},
            "player_match_stats": {"kills": 8, "deaths": 5, "assists": 2},
            "player_state": {"team": "CT"},
        }

        with patch("app.auto_bets.get_user_auto_bet_settings", return_value={"gsi_kills": 0, "gsi_deaths": 0, "gsi_assists": 0}):
            with patch(
                "app.auto_bets.set_user_auto_bet_gsi_state",
                return_value={"cs2_enabled": 1, "active_prediction_id": "", "active_game_key": ""},
            ):
                with patch.object(runtime, "_stream_online_gate_passed", AsyncMock(return_value=True)):
                    with patch.object(runtime, "_open_cs2_gsi_prediction", AsyncMock(return_value=True)) as open_mock:
                        result = await runtime.handle_cs2_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertTrue(result["opened"])
        self.assertTrue(result["gsi"]["stats_reliable"])
        open_mock.assert_awaited_once()

    async def test_handle_cs2_gsi_payload_resolves_active_prediction_after_match(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        payload = {
            "provider": {"steamid": "76561198803233589"},
            "map": {
                "matchid": "debug-cs2-502",
                "name": "de_mirage",
                "mode": "premier",
                "phase": "matchover",
                "round": 24,
                "team_ct": {"score": 13},
                "team_t": {"score": 10},
            },
            "player_id": {"steamid": "76561198803233589"},
            "player_match_stats": {"kills": 18, "deaths": 11, "assists": 6},
            "player_state": {"team": "CT"},
        }

        with patch("app.auto_bets.get_user_auto_bet_settings", return_value={"gsi_kills": 8, "gsi_deaths": 5, "gsi_assists": 2}):
            with patch(
                "app.auto_bets.set_user_auto_bet_gsi_state",
                return_value={"cs2_enabled": 1, "active_prediction_id": "prediction-1", "active_game_key": "cs2"},
            ):
                with patch.object(runtime, "_resolve_cs2_gsi_prediction", AsyncMock()) as resolve_mock:
                    result = await runtime.handle_cs2_gsi_payload(user, payload)

        self.assertTrue(result["ok"])
        self.assertFalse(result["opened"])
        resolve_mock.assert_awaited_once()

    async def test_resolve_dota_gsi_allows_compatible_match_id_drift(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        settings = {
            "active_prediction_id": "prediction-1",
            "active_game_key": "dota2",
            "win_outcome_id": "win-1",
            "loss_outcome_id": "loss-1",
            "last_opened_stream_signature": "dota-gsi:steam-de_mirage:kills_over:12",
        }
        state = {
            "match_id": "steam-de_mirage-premier",
            "game_state": "DOTA_GAMERULES_STATE_POST_GAME",
            "kills": 20,
            "deaths": 2,
            "assists": 9,
        }

        with patch("app.auto_bets.twitch_api.end_prediction_for_user", AsyncMock(return_value={"id": "prediction-1"})):
            with patch("app.auto_bets.clear_user_auto_bet_prediction", return_value={"active_prediction_id": ""}) as clear_mock:
                await runtime._resolve_dota_gsi_prediction(user, settings, state)

        clear_mock.assert_called_once()

    async def test_tick_retries_resolve_from_cached_gsi(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        settings = {
            "active_prediction_id": "prediction-1",
            "active_game_key": "cs2",
            "last_opened_stream_signature": "cs2-gsi:debug-cs2-777:win:0",
        }
        runtime._set_gsi_debug_state(
            1,
            "cs2",
            {
                "match_id": "debug-cs2-777",
                "phase": "matchover",
                "player_team": "CT",
                "ct_score": 13,
                "t_score": 10,
                "kills": 18,
                "deaths": 11,
                "assists": 6,
                "updated_at": __import__("time").time(),
            },
        )

        with patch("app.auto_bets.list_auto_bet_enabled_users", return_value=[user]):
            with patch("app.auto_bets.get_user_auto_bet_settings", return_value=settings):
                with patch.object(runtime, "_sync_active_prediction", AsyncMock()):
                    with patch.object(runtime, "_resolve_cs2_gsi_prediction", AsyncMock()) as resolve_mock:
                        await runtime.tick()

        resolve_mock.assert_awaited()

    async def test_debug_close_cs2_gsi_prediction_resolves_current_match(self) -> None:
        runtime = AutoBetRuntime()
        user = {"id": 1}
        initial_settings = {
            "active_prediction_id": "prediction-1",
            "active_game_key": "cs2",
            "last_opened_stream_signature": "cs2-gsi:debug-cs2-777:win:0",
        }
        cleared_settings = {"active_prediction_id": ""}

        with patch("app.auto_bets.get_user_auto_bet_settings", side_effect=[initial_settings, cleared_settings]):
            with patch("app.auto_bets.set_user_auto_bet_gsi_state", return_value=initial_settings):
                with patch.object(runtime, "_resolve_cs2_gsi_prediction", AsyncMock()) as resolve_mock:
                    result = await runtime.debug_close_cs2_gsi_prediction(user)

        self.assertTrue(result["resolved"])
        self.assertEqual(result["match_id"], "debug-cs2-777")
        resolve_mock.assert_awaited_once()

    async def test_opendota_status_cache_is_shared_across_runtime_instances(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test-autobet')
        request_urls: list[str] = []

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self):
                return self._payload

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                request_urls.append(url)
                if url.endswith('/recentMatches'):
                    return FakeResponse([{'match_id': 1}])
                return FakeResponse({'profile': {'personaname': 'Tester', 'profileurl': 'https://example.com'}})

        with patch('app.auto_bets.runtime_state', new=store):
            with patch('app.auto_bets.httpx.AsyncClient', return_value=FakeAsyncClient()):
                first_runtime = AutoBetRuntime()
                second_runtime = AutoBetRuntime()

                first_status = await first_runtime.opendota_status('123')
                second_status = await second_runtime.opendota_status('123')

        self.assertTrue(first_status['ok'])
        self.assertTrue(second_status['ok'])
        self.assertEqual(len(request_urls), 2)

    async def test_opendota_live_cache_returns_stale_matches_on_fetch_error(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test-autobet')

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return [{'match_id': 777}]

        class SuccessAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                return FakeResponse()

        class FailingAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                raise RuntimeError('boom')

        with patch('app.auto_bets.runtime_state', new=store):
            first_runtime = AutoBetRuntime()
            second_runtime = AutoBetRuntime()

            with patch('app.auto_bets.httpx.AsyncClient', return_value=SuccessAsyncClient()):
                first_matches = await first_runtime._get_opendota_live_matches(100.0)

            with patch('app.auto_bets.httpx.AsyncClient', return_value=FailingAsyncClient()):
                second_matches = await second_runtime._get_opendota_live_matches(131.0)

        self.assertEqual(first_matches, [{'match_id': 777}])
        self.assertEqual(second_matches, [{'match_id': 777}])

    async def test_opendota_429_enables_cooldown_and_reuses_stale_live_cache(self) -> None:
        store = InMemoryRuntimeStateStore(namespace='test-autobet')
        request_count = 0

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self):
                return [{'match_id': 888}]

        class SuccessAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                nonlocal request_count
                request_count += 1
                return FakeResponse()

        class RateLimitedAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                nonlocal request_count
                request_count += 1
                raise RuntimeError('429 Too Many Requests')

        class UnexpectedCallAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url: str):
                raise AssertionError('OpenDota should stay on cooldown and avoid a new live fetch')

        with patch('app.auto_bets.runtime_state', new=store):
            first_runtime = AutoBetRuntime()
            second_runtime = AutoBetRuntime()
            third_runtime = AutoBetRuntime()

            with patch('app.auto_bets.httpx.AsyncClient', return_value=SuccessAsyncClient()):
                first_matches = await first_runtime._get_opendota_live_matches(100.0)

            with patch('app.auto_bets.httpx.AsyncClient', return_value=RateLimitedAsyncClient()):
                second_matches = await second_runtime._get_opendota_live_matches(131.0)

            with patch('app.auto_bets.httpx.AsyncClient', return_value=UnexpectedCallAsyncClient()):
                third_matches = await third_runtime._get_opendota_live_matches(140.0)

        throttle_state = store.get('opendota:cooldown')
        self.assertEqual(first_matches, [{'match_id': 888}])
        self.assertEqual(second_matches, [{'match_id': 888}])
        self.assertEqual(third_matches, [{'match_id': 888}])
        self.assertIsInstance(throttle_state, dict)
        self.assertEqual(request_count, 2)
