import logging
import time
from typing import Any

from .twitch_api import twitch_api
from .web_db import list_user_bot_commands, list_user_timers, list_web_users, mark_user_timer_sent


logger = logging.getLogger(__name__)


class TimerRuntime:
    def __init__(self) -> None:
        self._next_tick_at = 0.0
        self._live_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})

    async def tick(self) -> None:
        now = time.time()
        if now < self._next_tick_at:
            return
        self._next_tick_at = now + 10

        users = list_web_users(active_only=True)
        if not users:
            return

        live_streams = await self._get_live_streams(users, now)
        for user in users:
            try:
                await self._process_user_timers(user, live_streams, now)
            except Exception as exc:
                logger.warning('Failed to process timers for user=%s: %s', user.get('id'), exc)

    async def _get_live_streams(self, users: list[dict[str, Any]], now: float) -> dict[str, dict[str, Any]]:
        cached_at, cached_streams = self._live_cache
        if now - cached_at < 45:
            return cached_streams

        broadcaster_ids = [str(user.get('twitch_user_id') or '') for user in users if str(user.get('twitch_user_id') or '').strip()]
        try:
            streams = await twitch_api.get_live_streams(broadcaster_ids)
        except Exception as exc:
            logger.warning('Failed to fetch live streams for timers: %s', exc)
            streams = cached_streams
        self._live_cache = (now, streams)
        return streams

    async def _process_user_timers(self, user: dict[str, Any], live_streams: dict[str, dict[str, Any]], now: float) -> None:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            return

        is_online = broadcaster_id in live_streams
        commands_by_name = {
            str(command.get('name') or '').lower(): command
            for command in list_user_bot_commands(int(user['id']))
            if not bool(command.get('is_builtin')) and bool(command.get('enabled')) and str(command.get('response_text') or '').strip()
        }

        for timer in list_user_timers(int(user['id'])):
            if not bool(timer.get('enabled')):
                continue
            if is_online and not bool(timer.get('online_enabled')):
                continue
            if not is_online and not bool(timer.get('offline_enabled')):
                continue

            interval_minutes = int(timer.get('online_interval_minutes') if is_online else timer.get('offline_interval_minutes') or 1)
            if now - float(timer.get('last_sent_at') or 0) < max(1, interval_minutes) * 60:
                continue
            if float(timer.get('last_sent_at') or 0) > 0 and int(timer.get('line_count') or 0) < max(0, int(timer.get('minimum_lines') or 0)):
                continue

            items = self._build_timer_items(timer, commands_by_name)
            if not items:
                continue

            index = int(timer.get('next_item_index') or 0) % len(items)
            message = items[index].strip()
            if not message:
                continue

            await twitch_api.send_chat_message(message, broadcaster_id=broadcaster_id)
            mark_user_timer_sent(int(timer['id']), next_item_index=(index + 1) % len(items), sent_at=now)

    @staticmethod
    def _build_timer_items(timer: dict[str, Any], commands_by_name: dict[str, dict[str, Any]]) -> list[str]:
        items: list[str] = []
        for command_name in timer.get('commands') or []:
            command = commands_by_name.get(str(command_name or '').lower())
            if command and str(command.get('response_text') or '').strip():
                items.append(str(command.get('response_text') or '').strip())
        items.extend(str(message or '').strip() for message in timer.get('messages') or [] if str(message or '').strip())
        return items


timer_runtime = TimerRuntime()
