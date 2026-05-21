import unittest
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from app.twitch_api import TwitchAPI


class SendChatMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_chat_message_uses_app_token_when_badge_mode_enabled(self) -> None:
        api = TwitchAPI()
        with patch("app.twitch_api.settings.chatbot_badge_mode", True):
            with patch("app.twitch_api.settings.twitch_bot_user_id", "123"):
                with patch("app.twitch_api.settings.twitch_broadcaster_id", "456"):
                    with patch.object(api, "_send_chat_message_via_app_token", AsyncMock()) as app_mock:
                        with patch.object(api, "_send_chat_message_via_user_token", AsyncMock()) as user_mock:
                            await api.send_chat_message("hello")

        app_mock.assert_awaited_once()
        user_mock.assert_not_awaited()

    async def test_send_chat_message_falls_back_to_user_token_when_app_token_send_fails(self) -> None:
        api = TwitchAPI()
        with patch("app.twitch_api.settings.chatbot_badge_mode", True):
            with patch("app.twitch_api.settings.twitch_bot_user_id", "123"):
                with patch("app.twitch_api.settings.twitch_broadcaster_id", "456"):
                    with patch("app.twitch_api.settings.twitch_bot_user_access_token", "token"):
                        with patch.object(api, "_send_chat_message_via_app_token", AsyncMock(side_effect=RuntimeError("boom"))) as app_mock:
                            with patch.object(api, "_send_chat_message_via_user_token", AsyncMock()) as user_mock:
                                await api.send_chat_message("hello")

        app_mock.assert_awaited_once()
        user_mock.assert_awaited_once()

    async def test_send_chat_message_uses_user_token_when_badge_mode_disabled(self) -> None:
        api = TwitchAPI()
        with patch("app.twitch_api.settings.chatbot_badge_mode", False):
            with patch("app.twitch_api.settings.twitch_bot_user_id", "123"):
                with patch("app.twitch_api.settings.twitch_broadcaster_id", "456"):
                    with patch("app.twitch_api.settings.twitch_bot_user_access_token", "token"):
                        with patch.object(api, "_send_chat_message_via_app_token", AsyncMock()) as app_mock:
                            with patch.object(api, "_send_chat_message_via_user_token", AsyncMock()) as user_mock:
                                await api.send_chat_message("hello")

        app_mock.assert_not_awaited()
        user_mock.assert_awaited_once()


class LiveStreamsCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_live_streams_returns_stale_cache_on_fetch_error(self) -> None:
        api = TwitchAPI()
        good_response = Mock()
        good_response.raise_for_status.return_value = None
        good_response.json.return_value = {
            "data": [
                {
                    "user_id": "123",
                    "title": "Live",
                }
            ]
        }
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[good_response, RuntimeError("dns boom")])

        with patch.object(api, "get_app_access_token", AsyncMock(return_value="token")):
            with patch.object(api, "_get_client", return_value=client):
                first = await api.get_live_streams(["123"])

                cached_stream, _ = api._live_streams_cache["123"]
                api._live_streams_cache["123"] = (cached_stream, 0.0)

                with patch("app.twitch_api.time.time", return_value=50.0):
                    second = await api.get_live_streams(["123"])

        self.assertEqual(first["123"]["title"], "Live")
        self.assertEqual(second["123"]["title"], "Live")

    async def test_get_live_streams_uses_fresh_cache_without_http_call(self) -> None:
        api = TwitchAPI()
        api._live_streams_cache["123"] = ({"user_id": "123", "title": "Cached"}, 10_000.0)

        with patch("app.twitch_api.time.time", return_value=10_010.0):
            with patch.object(api, "get_app_access_token", AsyncMock()) as token_mock:
                with patch.object(api, "_get_client") as client_mock:
                    streams = await api.get_live_streams(["123"])

        self.assertEqual(streams["123"]["title"], "Cached")
        token_mock.assert_not_awaited()
        client_mock.assert_not_called()
