import hashlib
import hmac
import unittest
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import patch

from app.twitch_chat_webhook import TwitchWebhookChatListener


class TwitchWebhookChatListenerTests(unittest.IsolatedAsyncioTestCase):
    def test_signature_validation_accepts_correct_hmac(self) -> None:
        listener = TwitchWebhookChatListener()
        body = b'{"subscription":{"type":"channel.chat.message"}}'
        signature = 'sha256=' + hmac.new(
            b'secret-value',
            b'abc2026-04-09T01:10:00Z' + body,
            hashlib.sha256,
        ).hexdigest()
        with patch('app.twitch_chat_webhook.settings.twitch_eventsub_secret', 'secret-value'):
            is_valid = listener.is_valid_signature(
                message_id='abc',
                timestamp='2026-04-09T01:10:00Z',
                body=body,
                signature=signature,
            )

        self.assertTrue(is_valid)

    async def test_handle_notification_forwards_chat_event(self) -> None:
        listener = TwitchWebhookChatListener()
        payload = {
            'subscription': {'type': 'channel.chat.message'},
            'event': {'message': {'text': '!ping'}},
        }
        with patch('app.twitch_chat_webhook.twitch_listener.handle_chat_event', AsyncMock()) as handle_mock:
            await listener.handle_notification(payload, delivery_id='delivery-1')

        handle_mock.assert_awaited_once_with(payload['event'], delivery_id='delivery-1')

    def test_fresh_message_rejects_stale_timestamp(self) -> None:
        listener = TwitchWebhookChatListener()
        stale_timestamp = (datetime.now(UTC) - timedelta(minutes=11)).isoformat().replace('+00:00', 'Z')

        self.assertFalse(listener.is_fresh_message(stale_timestamp))

    async def test_ensure_channel_subscription_uses_webhook_subscription_when_enabled(self) -> None:
        listener = TwitchWebhookChatListener()
        with patch('app.twitch_chat_webhook.settings.chatbot_chatters_list_mode', True):
            with patch('app.twitch_chat_webhook.settings.twitch_bot_user_id', '123'):
                with patch('app.twitch_chat_webhook.settings.twitch_eventsub_secret', 'secret-value'):
                    with patch('app.twitch_chat_webhook.settings.app_public_base_url', 'https://flaunt.agency'):
                        with patch('app.twitch_chat_webhook.twitch_api.create_webhook_subscription', AsyncMock()) as create_mock:
                            await listener.ensure_channel_subscription('456')

        create_mock.assert_awaited_once()
