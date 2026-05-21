import hashlib
import hmac
import logging
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from .config import settings
from .twitch_api import twitch_api
from .twitch_chat_eventsub import twitch_listener
from .web_db import list_web_users


logger = logging.getLogger(__name__)


class TwitchWebhookChatListener:
    CALLBACK_PATH = '/auth/twitch/eventsub/chat'
    MAX_MESSAGE_AGE = timedelta(minutes=10)

    def __init__(self) -> None:
        self._subscribed_broadcaster_ids: set[str] = set()

    def is_enabled(self) -> bool:
        return bool(
            settings.chatbot_chatters_list_mode
            and str(settings.twitch_bot_user_id or '').strip()
            and str(settings.twitch_eventsub_secret or '').strip()
        )

    def callback_url(self) -> str:
        base_url = settings.app_public_base_url.rstrip('/')
        return f'{base_url}{self.CALLBACK_PATH}'

    def is_configured_for_webhooks(self) -> bool:
        parsed = urlsplit(self.callback_url())
        return bool(parsed.scheme == 'https' and parsed.netloc)

    def is_valid_signature(self, *, message_id: str, timestamp: str, body: bytes, signature: str) -> bool:
        secret = str(settings.twitch_eventsub_secret or '').encode('utf-8')
        if not secret or not message_id or not timestamp or not signature:
            return False
        expected = 'sha256=' + hmac.new(secret, message_id.encode('utf-8') + timestamp.encode('utf-8') + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def is_fresh_message(self, timestamp: str) -> bool:
        raw_timestamp = str(timestamp or '').strip()
        if not raw_timestamp:
            return False
        normalized_timestamp = raw_timestamp.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized_timestamp)
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.astimezone(UTC)
        age = datetime.now(UTC) - parsed
        return timedelta(0) <= age <= self.MAX_MESSAGE_AGE

    async def sync_enabled_channels(self) -> None:
        if not self.is_enabled():
            return
        if not self.is_configured_for_webhooks():
            logger.warning('Chat Bots webhook mode is enabled, but APP_PUBLIC_BASE_URL is not a public https URL')
            return
        for user in list_web_users(active_only=True):
            if not bool(user.get('bot_enabled', 1)):
                continue
            broadcaster_id = str(user.get('twitch_user_id') or '').strip()
            if broadcaster_id:
                await self.ensure_channel_subscription(broadcaster_id)

    async def resubscribe_enabled_channels(self) -> None:
        self._subscribed_broadcaster_ids.clear()
        await self.sync_enabled_channels()

    async def ensure_channel_subscription(self, broadcaster_id: str) -> None:
        normalized_broadcaster_id = str(broadcaster_id or '').strip()
        if not normalized_broadcaster_id or not self.is_enabled():
            return
        if not self.is_configured_for_webhooks():
            return
        if normalized_broadcaster_id in self._subscribed_broadcaster_ids:
            return
        await twitch_api.create_webhook_subscription(
            self.callback_url(),
            str(settings.twitch_eventsub_secret or '').strip(),
            'channel.chat.message',
            normalized_broadcaster_id,
            user_id=str(settings.twitch_bot_user_id or '').strip(),
        )
        self._subscribed_broadcaster_ids.add(normalized_broadcaster_id)

    async def deactivate_channel(self, broadcaster_id: str) -> None:
        normalized_broadcaster_id = str(broadcaster_id or '').strip()
        if not normalized_broadcaster_id:
            return
        self._subscribed_broadcaster_ids.discard(normalized_broadcaster_id)
        if not self.is_enabled():
            return
        await twitch_api.delete_webhook_chat_message_subscriptions_for_broadcaster(
            normalized_broadcaster_id,
            callback_url=self.callback_url(),
        )

    async def handle_notification(self, payload: dict[str, Any], *, delivery_id: str = '') -> None:
        subscription = payload.get('subscription') or {}
        event = payload.get('event') or {}
        if str(subscription.get('type') or '') != 'channel.chat.message':
            return
        await twitch_listener.handle_chat_event(event, delivery_id=delivery_id)

    async def handle_revocation(self, subscription: dict[str, Any]) -> None:
        condition = subscription.get('condition') or {}
        broadcaster_id = str(condition.get('broadcaster_user_id') or '').strip()
        if broadcaster_id:
            self._subscribed_broadcaster_ids.discard(broadcaster_id)
        logger.warning(
            'Twitch revoked webhook chat subscription for broadcaster %s with status=%s',
            broadcaster_id,
            subscription.get('status'),
        )


twitch_webhook_listener = TwitchWebhookChatListener()
