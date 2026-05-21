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
from .runtime_state import runtime_state
from .twitch_api import twitch_api
from .web_db import (
    get_web_user_by_twitch_id,
    increment_user_timer_line_counts,
    list_web_users,
    set_web_user_bot_enabled,
    set_web_user_bot_enabled_by_twitch_id,
)


logger = logging.getLogger(__name__)


class TwitchChatListener:
    BASE_WS_URL = 'wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30'
    DEFAULT_KEEPALIVE_TIMEOUT_SECONDS = 30

    def __init__(self) -> None:
        self.session_id: Optional[str] = None
        self._ws_url = self.BASE_WS_URL
        self._keepalive_timeout_seconds = self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
        self._subscribed_broadcaster_ids: set[str] = set()
        self._subscribed_redemption_reward_keys: set[tuple[str, str]] = set()
        self._redemption_tasks: dict[tuple[int, str], asyncio.Task] = {}
        self._owner_cache: dict[str, tuple[Optional[dict[str, Any]], float]] = {}
        self._owner_cache_ttl = 5.0
        self._chat_event_dedupe_ttl = 15.0

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

                if message_type == 'revocation':
                    await self._handle_revocation(payload.get('payload', {}).get('subscription') or {})
                    continue

                if message_type != 'notification':
                    continue

                sub_type = payload['payload']['subscription']['type']
                event = payload['payload']['event']
                if sub_type == 'channel.chat.message':
                    await self._handle_chat_event(event, delivery_id=str(meta.get('message_id') or ''))
                elif sub_type == 'channel.channel_points_custom_reward_redemption.add':
                    await self._handle_points_redemption_event(event)

    def _reset_chat_session(self) -> None:
        self._ws_url = self.BASE_WS_URL
        self.session_id = None
        self._keepalive_timeout_seconds = self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
        self._subscribed_broadcaster_ids.clear()

    def _remember_chat_event(self, event: dict[str, Any], delivery_id: str = '') -> bool:
        event_id = str(event.get('message_id') or '').strip()
        if not event_id:
            event_id = str(delivery_id or '').strip()
        if not event_id:
            return False
        broadcaster_id = str(event.get('broadcaster_user_id') or '').strip() or '__global__'
        return runtime_state.mark_seen(
            f'chat-event:{broadcaster_id}:{event_id}',
            ttl_seconds=self._chat_event_dedupe_ttl,
        )

    async def _handle_chat_event(self, event: dict[str, Any], delivery_id: str = '') -> None:
        if self._remember_chat_event(event, delivery_id):
            return
        username = (event.get('chatter_user_login') or '').lower()
        broadcaster_id = (event.get('broadcaster_user_id') or '').strip()
        broadcaster_login = (event.get('broadcaster_user_login') or '').strip()
        text = (event.get('message', {}) or {}).get('text', '').strip()
        if not username or not text or not broadcaster_id:
            return

        owner = self._get_owner(broadcaster_id)
        if not owner or not bool(owner.get('bot_enabled', 1)):
            return
        increment_user_timer_line_counts(int(owner['id']))
        await giveaway_runtime.handle_chat_message(owner, event, text)

        bot_is_moderator = await self._bot_is_allowed_to_operate(owner, broadcaster_id)

        game = runtime.get_game_by_broadcaster(
            broadcaster_id,
            channel_name=broadcaster_login,
            questions_path=owner.get('questions_file'),
            answer_cooldown_seconds=owner.get('answer_cooldown_seconds'),
            turbo_mode=bool(owner.get('turbo_mode', 0)),
            passive_mode=bool(owner.get('quiz_passive_mode', 0)),
            quiet_mode=bool(owner.get('quiet_mode', 0)),
            chat_questions_enabled=bool(owner.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(owner.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(owner.get('chat_winners_enabled', 0)),
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

    async def handle_chat_event(self, event: dict[str, Any], delivery_id: str = '') -> None:
        await self._handle_chat_event(event, delivery_id=delivery_id)

    async def _handle_points_redemption_event(self, event: dict[str, Any]) -> None:
        broadcaster_id = str(event.get('broadcaster_user_id') or '').strip()
        if not broadcaster_id:
            return
        owner = self._get_owner(broadcaster_id)
        if not owner:
            return
        await giveaway_runtime.handle_points_redemption(owner, event)

    async def _subscribe_all_channels(self) -> None:
        broadcaster_ids: set[str] = set()
        for user in list_web_users(active_only=True):
            twitch_user_id = (user.get('twitch_user_id') or '').strip()
            if twitch_user_id:
                broadcaster_ids.add(twitch_user_id)
                self._owner_cache[twitch_user_id] = (user, time.time())
                runtime.get_game_by_broadcaster(
                    twitch_user_id,
                    channel_name=user.get('login') or twitch_user_id,
                    questions_path=user.get('questions_file'),
                    answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
                    turbo_mode=bool(user.get('turbo_mode', 0)),
                    passive_mode=bool(user.get('quiz_passive_mode', 0)),
                    quiet_mode=bool(user.get('quiet_mode', 0)),
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

            owner = self._get_owner(broadcaster_id)
            if owner:
                state = giveaway_runtime.get_state(int(owner['id']))
                if state.running and state.giveaway_type == 'points' and state.points_reward_id:
                    try:
                        await self.ensure_points_redemption_subscription(owner, state.points_reward_id)
                    except httpx.HTTPStatusError as exc:
                        logger.warning(
                            'Skipping points redemption subscription for broadcaster %s reward=%s status=%s body=%s',
                            broadcaster_id,
                            state.points_reward_id,
                            exc.response.status_code,
                            exc.response.text,
                        )
                    except httpx.HTTPError as exc:
                        logger.warning(
                            'Skipping points redemption subscription for broadcaster %s reward=%s error=%s',
                            broadcaster_id,
                            state.points_reward_id,
                            exc,
                        )

        logger.info(
            'EventSub chat subscriptions ready subscribed=%s skipped=%s session_id=%s',
            subscribed_count,
            skipped_count,
            self.session_id,
        )

    async def ensure_channel_subscription(self, broadcaster_id: str) -> None:
        if not self.session_id or not broadcaster_id:
            return
        owner = self._get_owner(broadcaster_id)
        if not owner or not bool(owner.get('bot_enabled', 1)):
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

    async def ensure_points_redemption_subscription(self, owner: dict[str, Any], reward_id: str) -> bool:
        if not owner or not reward_id:
            return False
        broadcaster_id = str(owner.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            return False
        owner_id = int(owner['id'])
        task_key = (owner_id, str(reward_id))
        existing_task = self._redemption_tasks.get(task_key)
        if existing_task and not existing_task.done():
            return True

        ready: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._run_points_redemption_listener(dict(owner), str(reward_id), ready))
        self._redemption_tasks[task_key] = task
        try:
            return await asyncio.wait_for(ready, timeout=10)
        except Exception:
            task.cancel()
            self._redemption_tasks.pop(task_key, None)
            raise

    def cancel_points_redemption_subscription(self, owner_id: int, reward_id: str) -> None:
        task_key = (int(owner_id), str(reward_id))
        task = self._redemption_tasks.pop(task_key, None)
        if task:
            task.cancel()

    def is_points_redemption_subscription_active(self, owner_id: int, reward_id: str) -> bool:
        task = self._redemption_tasks.get((int(owner_id), str(reward_id)))
        return bool(task and not task.done())

    async def _run_points_redemption_listener(
        self,
        owner: dict[str, Any],
        reward_id: str,
        ready: asyncio.Future[bool],
    ) -> None:
        broadcaster_id = str(owner.get('twitch_user_id') or '').strip()
        owner_id = int(owner['id'])
        key = (broadcaster_id, str(reward_id))
        ws_url = self.BASE_WS_URL
        keepalive_timeout_seconds = self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
        while True:
            try:
                async with websockets.connect(ws_url, max_size=2_000_000) as ws:
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=keepalive_timeout_seconds + 5)
                        except asyncio.TimeoutError:
                            logger.warning(
                                'Giveaway redemption listener timed out owner=%s reward=%s after %s seconds without messages; reconnecting',
                                owner_id,
                                reward_id,
                                keepalive_timeout_seconds,
                            )
                            ws_url = self.BASE_WS_URL
                            self._subscribed_redemption_reward_keys.discard(key)
                            break

                        payload = json.loads(raw)
                        meta = payload.get('metadata', {})
                        message_type = meta.get('message_type')

                        if message_type == 'session_welcome':
                            session = payload['payload']['session']
                            keepalive_timeout_seconds = int(
                                session.get('keepalive_timeout_seconds') or self.DEFAULT_KEEPALIVE_TIMEOUT_SECONDS
                            )
                            ws_url = self.BASE_WS_URL
                            session_id = session['id']
                            await twitch_api.create_user_subscription(
                                owner,
                                session_id,
                                'channel.channel_points_custom_reward_redemption.add',
                                condition={
                                    'broadcaster_user_id': broadcaster_id,
                                    'reward_id': str(reward_id),
                                },
                                version='1',
                            )
                            self._subscribed_redemption_reward_keys.add(key)
                            if not ready.done():
                                ready.set_result(True)
                            logger.info(
                                'EventSub subscribed for giveaway reward redemptions broadcaster=%s reward=%s',
                                broadcaster_id,
                                reward_id,
                            )
                            continue

                        if message_type == 'session_reconnect':
                            ws_url = payload['payload']['session']['reconnect_url']
                            self._subscribed_redemption_reward_keys.discard(key)
                            break

                        if message_type == 'revocation':
                            subscription = payload.get('payload', {}).get('subscription') or {}
                            logger.warning(
                                'Twitch revoked giveaway redemption subscription for broadcaster %s reward=%s with status=%s',
                                broadcaster_id,
                                reward_id,
                                subscription.get('status'),
                            )
                            self._subscribed_redemption_reward_keys.discard(key)
                            if not ready.done():
                                ready.set_result(False)
                            return

                        if message_type != 'notification':
                            continue

                        sub_type = payload['payload']['subscription']['type']
                        if sub_type == 'channel.channel_points_custom_reward_redemption.add':
                            await self._handle_points_redemption_event(payload['payload']['event'])
            except asyncio.CancelledError:
                self._subscribed_redemption_reward_keys.discard(key)
                raise
            except Exception as exc:
                self._subscribed_redemption_reward_keys.discard(key)
                ws_url = self.BASE_WS_URL
                if not ready.done():
                    ready.set_exception(exc)
                    return
                logger.warning(
                    'Giveaway redemption listener crashed owner=%s reward=%s error=%s',
                    owner_id,
                    reward_id,
                    exc,
                )
                await asyncio.sleep(5)

    async def deactivate_channel(self, broadcaster_id: str) -> None:
        self._subscribed_broadcaster_ids.discard(broadcaster_id)
        self._subscribed_redemption_reward_keys = {
            key for key in self._subscribed_redemption_reward_keys if key[0] != broadcaster_id
        }
        owner = self._get_owner(broadcaster_id)
        if owner:
            owner['bot_enabled'] = 0
            self._cancel_redemption_tasks_for_owner(int(owner['id']))
            self._owner_cache[broadcaster_id] = (owner, time.time())
        await twitch_api.delete_chat_message_subscriptions_for_broadcaster(broadcaster_id)

    async def resubscribe_enabled_channels(self) -> None:
        if not self.session_id:
            return
        self._subscribed_broadcaster_ids.clear()
        await self._subscribe_all_channels()

    def remember_owner(self, user: dict[str, Any]) -> None:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            return
        self._owner_cache[broadcaster_id] = (dict(user), time.time())

    def is_channel_connected(self, broadcaster_id: str) -> bool:
        owner = self._get_owner(broadcaster_id)
        return bool(
            self.session_id
            and owner
            and bool(owner.get('bot_enabled', 1))
            and broadcaster_id in self._subscribed_broadcaster_ids
        )

    async def _bot_is_allowed_to_operate(self, owner: dict[str, Any], broadcaster_id: str) -> bool:
        if not owner or not owner.get('access_token'):
            return False
        try:
            is_allowed = await twitch_api.is_bot_moderator_for_user(owner, broadcaster_id)
            self._owner_cache[broadcaster_id] = (owner, time.time())
            return is_allowed
        except httpx.HTTPStatusError:
            return False
        except Exception:
            return False

    async def _handle_revocation(self, subscription: dict[str, Any]) -> None:
        condition = subscription.get('condition') or {}
        broadcaster_id = str(condition.get('broadcaster_user_id') or '').strip()
        if not broadcaster_id:
            return
        sub_type = str(subscription.get('type') or '').strip()
        if sub_type == 'channel.channel_points_custom_reward_redemption.add':
            reward_id = str(condition.get('reward_id') or '').strip()
            if reward_id:
                self._subscribed_redemption_reward_keys.discard((broadcaster_id, reward_id))
            logger.warning(
                'Twitch revoked giveaway redemption subscription for broadcaster %s reward=%s with status=%s',
                broadcaster_id,
                reward_id,
                subscription.get('status'),
            )
            return
        self._subscribed_broadcaster_ids.discard(broadcaster_id)
        self._subscribed_redemption_reward_keys = {
            key for key in self._subscribed_redemption_reward_keys if key[0] != broadcaster_id
        }
        owner = self._get_owner(broadcaster_id)
        if owner and owner.get('id'):
            set_web_user_bot_enabled(int(owner['id']), False)
            owner['bot_enabled'] = 0
            self._owner_cache[broadcaster_id] = (owner, time.time())
        else:
            set_web_user_bot_enabled_by_twitch_id(broadcaster_id, False)
        logger.warning(
            'Twitch revoked chat subscription for broadcaster %s with status=%s',
            broadcaster_id,
            subscription.get('status'),
        )

    def _cancel_redemption_tasks_for_owner(self, owner_id: int) -> None:
        for key, task in list(self._redemption_tasks.items()):
            if key[0] != owner_id:
                continue
            task.cancel()
            self._redemption_tasks.pop(key, None)

    def _get_owner(self, broadcaster_id: str) -> Optional[dict[str, Any]]:
        cached = self._owner_cache.get(broadcaster_id)
        now = time.time()
        if cached and now - cached[1] < self._owner_cache_ttl:
            return cached[0]
        owner = get_web_user_by_twitch_id(broadcaster_id)
        self._owner_cache[broadcaster_id] = (owner, now)
        return owner


twitch_listener = TwitchChatListener()
