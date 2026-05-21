import asyncio
import json
import logging
import time
from typing import Any, Optional

import httpx
import websockets

from .commands import can_use_named_command, handle_command, is_supported_command
from .game import runtime
from .giveaways import giveaway_runtime
from .twitch_api import twitch_api
from .web_db import get_web_user_by_twitch_id, increment_user_timer_line_counts, list_web_users


logger = logging.getLogger(__name__)


class TwitchChatListener:
    BASE_WS_URL = 'wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30'
    DEFAULT_KEEPALIVE_TIMEOUT_SECONDS = 30

    def __init__(self) -> None:
        self.session_id: Optional[str] = None
        self._ws_url = self.BASE_WS_URL
        self._keepalive_timeout_seconds = self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
        self._subscribed_broadcaster_ids: set[str] = set()
        self._owner_cache: dict[str, tuple[Optional[dict[str, Any]], float]] = {}
        self._owner_cache_ttl = 5.0

    async def run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                self._reset_chat_session()
                logger.exception('Twitch listener crashed: %s', exc)
                await asyncio.sleep(5)

    async def _connect_and_listen(self) -> None:
        ws_url = self._ws_url
        async with websockets.connect(ws_url, max_size=2_000_000) as ws:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self._keepalive_timeout_seconds + 5)
                except asyncio.TimeoutError:
                    logger.warning(
                        'EventSub chat listener timed out after %s seconds without messages; reconnecting',
                        self._keepalive_timeout_seconds,
                    )
                    self._reset_chat_session()
                    return

                payload = json.loads(raw)
                meta = payload.get('metadata', {})
                message_type = meta.get('message_type')

                if message_type == 'session_welcome':
                    session = payload['payload']['session']
                    self.session_id = session['id']
                    self._keepalive_timeout_seconds = int(
                        session.get('keepalive_timeout_seconds') or self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
                    )
                    self._ws_url = self.BASE_WS_URL
                    self._subscribed_broadcaster_ids.clear()
                    await self._subscribe_all_channels()
                    logger.info('EventSub subscribed for channel.chat.message')
                    continue

                if message_type == 'session_reconnect':
                    reconnect_url = payload['payload']['session']['reconnect_url']
                    self._ws_url = reconnect_url
                    self.session_id = None
                    self._subscribed_broadcaster_ids.clear()
                    logger.info('Reconnect requested by Twitch')
                    return

                if message_type != 'notification':
                    continue

                sub_type = payload['payload']['subscription']['type']
                event = payload['payload']['event']
                if sub_type == 'channel.chat.message':
                    await self._handle_chat_event(event)

    def _reset_chat_session(self) -> None:
        self._ws_url = self.BASE_WS_URL
        self.session_id = None
        self._keepalive_timeout_seconds = self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
        self._subscribed_broadcaster_ids.clear()

    async def _handle_chat_event(self, event: dict[str, Any]) -> None:
        username = (event.get('chatter_user_login') or '').lower()
        broadcaster_id = (event.get('broadcaster_user_id') or '').strip()
        broadcaster_login = (event.get('broadcaster_user_login') or '').strip()
        text = (event.get('message', {}) or {}).get('text', '').strip()
        if not username or not text or not broadcaster_id:
            return

        bot_is_moderator = await self._bot_is_allowed_to_operate(broadcaster_id)
        owner = self._get_owner(broadcaster_id)
        if owner:
            increment_user_timer_line_counts(int(owner['id']))
            await giveaway_runtime.handle_chat_message(owner, event, text)

        game = runtime.get_game_by_broadcaster(
            broadcaster_id,
            channel_name=broadcaster_login,
            questions_path=(owner or {}).get('questions_file'),
            answer_cooldown_seconds=(owner or {}).get('answer_cooldown_seconds'),
            passive_mode=bool((owner or {}).get('quiz_passive_mode', 0)),
            quiet_mode=False,
            chat_questions_enabled=bool((owner or {}).get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool((owner or {}).get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool((owner or {}).get('chat_winners_enabled', 0)),
        )

        if is_supported_command(text, owner):
            if not bot_is_moderator:
                await twitch_api.send_chat_message(
                    'Бот не модератор на этом канале. Выдай /mod и потом повтори команду.',
                    broadcaster_id=broadcaster_id,
                )
                return
            if not can_use_named_command(event, owner, text):
                return
            response = await handle_command(text, game, owner)
            if response:
                await twitch_api.send_chat_message(response, broadcaster_id=broadcaster_id)
            return

        if not bot_is_moderator:
            return
        won, response = await game.handle_guess(username, text)
        if won and response:
            await twitch_api.send_chat_message(response, broadcaster_id=broadcaster_id)

    async def _subscribe_all_channels(self) -> None:
        broadcaster_ids: set[str] = set()
        for user in list_web_users():
            twitch_user_id = (user.get('twitch_user_id') or '').strip()
            if twitch_user_id:
                broadcaster_ids.add(twitch_user_id)
                self._owner_cache[twitch_user_id] = (user, time.time())
                runtime.get_game_by_broadcaster(
                    twitch_user_id,
                    channel_name=user.get('login') or twitch_user_id,
                    questions_path=user.get('questions_file'),
                    answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
                    passive_mode=bool(user.get('quiz_passive_mode', 0)),
                    quiet_mode=False,
                    chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
                    chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
                    chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
                )

        subscribed_count = 0
        skipped_count = 0
        for broadcaster_id in broadcaster_ids:
            try:
                await twitch_api.create_subscription(
                    self.session_id,
                    'channel.chat.message',
                    broadcaster_id=broadcaster_id,
                    version='1',
                )
                self._subscribed_broadcaster_ids.add(broadcaster_id)
                subscribed_count += 1
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {400, 403}:
                    skipped_count += 1
                    logger.warning(
                        'Skipping chat subscription for broadcaster %s until the bot has the required permissions or grants',
                        broadcaster_id,
                    )
                    continue
                raise

        logger.info(
            'EventSub chat subscriptions ready subscribed=%s skipped=%s session_id=%s',
            subscribed_count,
            skipped_count,
            self.session_id,
        )

    async def ensure_channel_subscription(self, broadcaster_id: str) -> None:
        if not self.session_id or not broadcaster_id:
            return
        if broadcaster_id in self._subscribed_broadcaster_ids:
            return
        await twitch_api.create_subscription(
            self.session_id,
            'channel.chat.message',
            broadcaster_id=broadcaster_id,
            version='1',
        )
        self._subscribed_broadcaster_ids.add(broadcaster_id)

    def is_channel_connected(self, broadcaster_id: str) -> bool:
        return bool(self.session_id and broadcaster_id in self._subscribed_broadcaster_ids)

    async def _bot_is_allowed_to_operate(self, broadcaster_id: str) -> bool:
        owner = self._get_owner(broadcaster_id)
        if not owner or not owner.get('access_token'):
            return False
        try:
            return await twitch_api.is_bot_moderator_in_channel(
                owner['access_token'],
                broadcaster_id,
                use_cache=False,
            )
        except Exception:
            return False

    def _get_owner(self, broadcaster_id: str) -> Optional[dict[str, Any]]:
        cached = self._owner_cache.get(broadcaster_id)
        now = time.time()
        if cached and now - cached[1] < self._owner_cache_ttl:
            return cached[0]
        owner = get_web_user_by_twitch_id(broadcaster_id)
        self._owner_cache[broadcaster_id] = (owner, now)
        return owner


twitch_listener = TwitchChatListener()
