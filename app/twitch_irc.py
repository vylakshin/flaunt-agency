import asyncio
import logging
import ssl
from typing import Any, Optional

from .commands import can_use_commands, can_use_named_command, handle_command, is_supported_command
from .config import settings
from .game import game
from .twitch_api import twitch_api
from .web_db import get_web_user_by_login


logger = logging.getLogger(__name__)


class TwitchIRCListener:
    HOST = 'irc.chat.twitch.tv'
    PORT = 6697

    def __init__(self) -> None:
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._joined_channel = ''

    async def run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                self._connected = False
                logger.exception('IRC listener crashed: %s', exc)
                await asyncio.sleep(max(1, settings.irc_reconnect_delay_seconds))

    async def _connect_and_listen(self) -> None:
        if not settings.irc_bot_login or not settings.irc_bot_oauth or not settings.irc_target_channel:
            logger.error('IRC mode requires BOT_LOGIN, BOT_OAUTH, TARGET_CHANNEL')
            self._connected = False
            await asyncio.sleep(max(1, settings.irc_reconnect_delay_seconds))
            return

        ssl_context = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(self.HOST, self.PORT, ssl=ssl_context)
        self._reader = reader
        self._writer = writer

        await self._send_raw(f'PASS {settings.irc_bot_oauth}')
        await self._send_raw(f'NICK {settings.irc_bot_login}')
        await self._send_raw('CAP REQ :twitch.tv/tags')
        await self._send_raw('CAP REQ :twitch.tv/commands')
        await self._send_raw(f'JOIN #{settings.irc_target_channel}')
        self._connected = True
        self._joined_channel = settings.irc_target_channel.strip().lower()
        logger.info('IRC connected as %s in #%s', settings.irc_bot_login, settings.irc_target_channel)

        while True:
            raw = await reader.readline()
            if not raw:
                break
            line = raw.decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            if line.startswith('PING'):
                await self._send_raw(line.replace('PING', 'PONG', 1))
                continue
            await self._handle_line(line)

        await self._close_writer()
        await asyncio.sleep(max(1, settings.irc_reconnect_delay_seconds))

    async def _handle_line(self, line: str) -> None:
        tags: dict[str, str] = {}
        rest = line
        if line.startswith('@'):
            tag_part, rest = line.split(' ', 1)
            tags = self._parse_tags(tag_part[1:])

        if settings.debug:
            logger.info('IRC line: %s', line)

        if ' PRIVMSG ' not in rest:
            return

        prefix, trailing = rest.split(' PRIVMSG ', 1)
        username = self._parse_username(prefix)
        if not username or ' :' not in trailing:
            return
        _, text = trailing.split(' :', 1)
        text = text.strip()
        if not text:
            return

        event = self._build_event_from_tags(tags)
        await self._handle_chat_message(username, text, event)

    async def _handle_chat_message(self, username: str, text: str, event: dict[str, Any]) -> None:
        owner = get_web_user_by_login(settings.irc_target_channel)
        if is_supported_command(text, owner):
            is_broadcaster = username.lower() == settings.irc_target_channel.lower()
            if not can_use_named_command(event, owner, text):
                logger.warning('IRC command denied: user=%s text=%s badges=%s', username, text, event.get('badges'))
                return
            logger.info('IRC command accepted: user=%s text=%s', username, text)
            response = await handle_command(text, owner=owner)
            if response:
                await self.send_chat_message(response)
            return

        if settings.twitch_require_follower_only:
            is_broadcaster = username.lower() == settings.irc_target_channel.lower()
            if not (is_broadcaster or can_use_commands(event)):
                user_id = event.get('user_id') or ''
                if not settings.twitch_client_id or not settings.twitch_client_secret:
                    logger.warning('Follower-only enabled but missing Twitch app credentials')
                    return
                if not settings.twitch_broadcaster_id:
                    logger.warning('Follower-only enabled but missing broadcaster id')
                    return
                try:
                    is_follower = await twitch_api.is_user_follower(settings.twitch_broadcaster_id, user_id)
                except Exception as exc:
                    logger.warning('Follower check failed: %s', exc)
                    return
                if not is_follower:
                    return

        won, response = await game.handle_guess(username, text)
        if won and response:
            await self.send_chat_message(response)

    async def send_chat_message(self, message: str) -> None:
        if not self._writer:
            return
        safe = message[:500]
        await self._send_raw(f'PRIVMSG #{settings.irc_target_channel} :{safe}')

    async def _send_raw(self, line: str) -> None:
        if not self._writer:
            return
        self._writer.write((line + '\r\n').encode('utf-8'))
        await self._writer.drain()

    async def _close_writer(self) -> None:
        self._connected = False
        self._joined_channel = ''
        if not self._writer:
            return
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass
        self._writer = None
        self._reader = None

    @staticmethod
    def _parse_tags(raw: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in raw.split(';'):
            if '=' not in item:
                continue
            key, value = item.split('=', 1)
            out[key] = value
        return out

    @staticmethod
    def _parse_username(prefix: str) -> str:
        if prefix.startswith(':'):
            prefix = prefix[1:]
        if '!' in prefix:
            return prefix.split('!', 1)[0].lower()
        return prefix.lower()

    @staticmethod
    def _build_event_from_tags(tags: dict[str, str]) -> dict[str, Any]:
        badges: dict[str, bool] = {}
        raw_badges = tags.get('badges') or ''
        if raw_badges:
            for badge in raw_badges.split(','):
                if not badge:
                    continue
                name = badge.split('/', 1)[0]
                if name:
                    badges[name] = True
        if tags.get('mod') == '1':
            badges['moderator'] = True
        user_id = tags.get('user-id') or ''
        return {'badges': badges, 'user_id': user_id}

    def is_channel_connected(self, broadcaster_id: str = '') -> bool:
        return self._connected and bool(self._joined_channel)

    async def ensure_channel_subscription(self, broadcaster_id: str) -> None:
        return


twitch_irc_listener = TwitchIRCListener()
