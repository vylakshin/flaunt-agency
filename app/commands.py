from typing import Optional

import json
import time
from typing import Any

from .game import GameManager, game
from .web_db import get_user_bot_command_by_name, list_user_bot_commands


BUILTIN_COMMANDS: list[dict[str, str]] = [
    {'name': '!start', 'title': 'Старт раунда', 'description': 'Начать новый раунд.'},
    {'name': '!skip', 'title': 'Пропустить вопрос', 'description': 'Пропустить текущий вопрос.'},
    {'name': '!refresh', 'title': 'Новый раунд и сброс', 'description': 'Перезапустить раунд и сбросить состояние.'},
    {'name': '!stop', 'title': 'Остановить игру', 'description': 'Остановить игру и сбросить очки.'},
    {'name': '!pause', 'title': 'Пауза', 'description': 'Поставить игру на паузу.'},
    {'name': '!resume', 'title': 'Продолжить', 'description': 'Снять игру с паузы.'},
    {'name': '!answer', 'title': 'Показать ответ', 'description': 'Показать правильный ответ.'},
    {'name': '!top', 'title': 'Топ игроков', 'description': 'Отправить топ игроков в чат.'},
    {'name': '!resetpoints', 'title': 'Сбросить очки', 'description': 'Сбросить очки игроков.'},
    {'name': '!reload', 'title': 'Перечитать вопросы', 'description': 'Перезагрузить активный файл вопросов.'},
    {'name': '!ping', 'title': 'Проверить бота', 'description': 'Проверить, что бот отвечает.'},
]

MOD_COMMANDS = {item['name'] for item in BUILTIN_COMMANDS}
_CUSTOM_COMMAND_COOLDOWNS: dict[tuple[int, str], float] = {}
CUSTOM_COMMAND_ROLES = {'streamer', 'moderator', 'editor', 'subscriber', 'non_subscriber', 'vip'}


def _normalize_command_name(value: str) -> str:
    command = value.strip().split()[0].lower() if value.strip() else ''
    if command and not command.startswith('!'):
        command = f'!{command}'
    return command


def _first_bang_command(value: str) -> str:
    first = value.strip().split()[0].lower() if value.strip() else ''
    if not first.startswith('!'):
        return ''
    return _normalize_command_name(first)


def _parse_string_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []

    items: list[str] = []
    for item in parsed:
        text = str(item or '').strip()
        if text and text not in items:
            items.append(text)
    return items


def _parse_aliases(value: Any) -> list[str]:
    aliases: list[str] = []
    for item in _parse_string_list(value):
        alias = _normalize_command_name(item)
        if len(alias) > 1 and alias not in aliases:
            aliases.append(alias)
    return aliases


def _parse_keywords(value: Any) -> list[str]:
    keywords: list[str] = []
    for item in _parse_string_list(value):
        keyword = item.strip().lower().lstrip('!')
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def get_user_commands(user_id: int) -> list[dict[str, Any]]:
    rows = list_user_bot_commands(user_id)
    rows_by_name = {str(row.get('name') or '').lower(): row for row in rows}
    commands: list[dict[str, Any]] = []

    for builtin in BUILTIN_COMMANDS:
        stored = rows_by_name.get(builtin['name'])
        commands.append(
            {
                'id': int(stored['id']) if stored else None,
                'name': builtin['name'],
                'title': builtin['title'],
                'description': builtin['description'],
                'response_text': '',
                'enabled': bool(stored.get('enabled')) if stored else True,
                'cooldown_seconds': float(stored.get('cooldown_seconds') or 0) if stored else 0,
                'allowed_roles': [],
                'aliases': [],
                'keywords': [],
                'is_builtin': True,
                'can_delete': False,
            }
        )

    for row in rows:
        name = str(row.get('name') or '').lower()
        if bool(row.get('is_builtin')) or name in MOD_COMMANDS:
            continue
        commands.append(
            {
                'id': int(row['id']),
                'name': name,
                'title': name,
                'description': str(row.get('response_text') or ''),
                'response_text': str(row.get('response_text') or ''),
                'enabled': bool(row.get('enabled')),
                'cooldown_seconds': float(row.get('cooldown_seconds') or 0),
                'allowed_roles': _parse_allowed_roles(row.get('allowed_roles')),
                'aliases': _parse_aliases(row.get('aliases')),
                'keywords': _parse_keywords(row.get('keywords')),
                'is_builtin': False,
                'can_delete': True,
            }
        )
    return commands


def _parse_allowed_roles(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [role for role in parsed if isinstance(role, str) and role in CUSTOM_COMMAND_ROLES]


def _event_badge_names(event: dict) -> set[str]:
    badges = event.get('badges') or []
    if isinstance(badges, dict):
        return {str(name).lower() for name, enabled in badges.items() if enabled}
    if isinstance(badges, list):
        return {str(item.get('set_id') or '').lower() for item in badges if isinstance(item, dict)}
    return set()


def _event_has_custom_role(event: dict, owner: dict, role: str) -> bool:
    badges = _event_badge_names(event)
    chatter_id = str(event.get('chatter_user_id') or event.get('user_id') or '')
    broadcaster_id = str(event.get('broadcaster_user_id') or owner.get('twitch_user_id') or '')
    is_streamer = bool(chatter_id and broadcaster_id and chatter_id == broadcaster_id) or bool(event.get('chatter_is_broadcaster')) or 'broadcaster' in badges
    is_moderator = bool(event.get('chatter_is_moderator')) or 'moderator' in badges or is_streamer
    is_editor = bool(event.get('chatter_is_editor')) or 'editor' in badges
    is_subscriber = bool(event.get('chatter_is_subscriber')) or 'subscriber' in badges or 'founder' in badges
    is_vip = bool(event.get('chatter_is_vip')) or 'vip' in badges

    if role == 'streamer':
        return is_streamer
    if role == 'moderator':
        return is_moderator
    if role == 'editor':
        return is_editor
    if role == 'subscriber':
        return is_subscriber
    if role == 'non_subscriber':
        return not is_subscriber
    if role == 'vip':
        return is_vip
    return False


def _custom_command_matches_text(row: dict[str, Any], text: str) -> bool:
    bang_command = _first_bang_command(text)
    name = str(row.get('name') or '').lower()
    if bang_command and (bang_command == name or bang_command in _parse_aliases(row.get('aliases'))):
        return True

    text_lower = str(text or '').strip().lower()
    return any(keyword in text_lower for keyword in _parse_keywords(row.get('keywords')))


def _custom_command_for_text(owner: Optional[dict], text: str) -> Optional[dict[str, Any]]:
    if not owner:
        return None
    for row in list_user_bot_commands(int(owner['id'])):
        name = str(row.get('name') or '').lower()
        if bool(row.get('is_builtin')) or name in MOD_COMMANDS or not bool(row.get('enabled')):
            continue
        if _custom_command_matches_text(row, text):
            return row
    return None


def can_use_named_command(event: dict, owner: Optional[dict], text: str) -> bool:
    cmd = _first_bang_command(text)
    if cmd in MOD_COMMANDS:
        if not owner:
            return can_use_commands(event)
        return can_use_commands(event, owner.get('command_access', 'moderators'))

    if not owner:
        return False

    stored = _custom_command_for_text(owner, text)
    if not stored:
        return False
    allowed_roles = _parse_allowed_roles(stored.get('allowed_roles'))
    if not allowed_roles:
        return True
    return any(_event_has_custom_role(event, owner, role) for role in allowed_roles)


def is_supported_command(text: str, owner: Optional[dict] = None) -> bool:
    cmd = _first_bang_command(text)
    if cmd in MOD_COMMANDS:
        if not owner:
            return True
        stored = get_user_bot_command_by_name(int(owner['id']), cmd)
        return bool(stored.get('enabled')) if stored else True
    if not owner:
        return False
    return _custom_command_for_text(owner, text) is not None


def can_use_commands(event: dict, access_level: str = 'moderators') -> bool:
    normalized_access = (access_level or 'moderators').strip().lower()
    if normalized_access == 'everyone':
        return True
    if normalized_access == 'owner':
        return str(event.get('chatter_user_id') or '') == str(event.get('broadcaster_user_id') or '')

    badges = event.get('badges') or []
    if isinstance(badges, dict):
        return bool(badges.get('moderator') or badges.get('broadcaster'))
    if isinstance(badges, list):
        badge_sets = {str(item.get('set_id') or '').lower() for item in badges if isinstance(item, dict)}
        if 'moderator' in badge_sets or 'broadcaster' in badge_sets:
            return True
    if str(event.get('chatter_user_id') or '') == str(event.get('broadcaster_user_id') or ''):
        return True
    if bool(event.get('chatter_is_moderator')) or bool(event.get('chatter_is_broadcaster')):
        return True
    return False


def _custom_command_response(owner: Optional[dict], stored: Optional[dict[str, Any]]) -> Optional[str]:
    if not owner or not stored:
        return None
    if not stored or bool(stored.get('is_builtin')) or not bool(stored.get('enabled')):
        return None

    cooldown = max(0.0, float(stored.get('cooldown_seconds') or 0))
    cmd = str(stored.get('name') or '').lower()
    key = (int(owner['id']), cmd)
    now = time.monotonic()
    if cooldown > 0 and now - _CUSTOM_COMMAND_COOLDOWNS.get(key, 0) < cooldown:
        return None
    _CUSTOM_COMMAND_COOLDOWNS[key] = now
    return str(stored.get('response_text') or '').strip() or None


async def handle_command(text: str, game_instance: Optional[GameManager] = None, owner: Optional[dict] = None) -> Optional[str]:
    game_instance = game_instance or game
    parts = text.strip().split()
    if not parts:
        return None
    cmd = _first_bang_command(parts[0])
    if cmd not in MOD_COMMANDS:
        return _custom_command_response(owner, _custom_command_for_text(owner, text))
    if owner:
        stored = get_user_bot_command_by_name(int(owner['id']), cmd)
        if stored and not bool(stored.get('enabled')):
            return None
    if cmd == '!start':
        return await game_instance.start_round()
    if cmd == '!skip':
        return await game_instance.skip_round()
    if cmd == '!refresh':
        return await game_instance.refresh_round()
    if cmd == '!stop':
        return await game_instance.stop_game()
    if cmd == '!pause':
        return await game_instance.pause()
    if cmd == '!resume':
        return await game_instance.resume()
    if cmd == '!answer':
        return await game_instance.reveal_answer()
    if cmd == '!top':
        return await game_instance.get_top_text()
    if cmd == '!resetpoints':
        return await game_instance.reset_points()
    if cmd == '!reload':
        count = await game_instance.reload_questions()
        return f'Загадки перезагружены: {count}'
    if cmd == '!ping':
        return 'Бот в сети.'
    return None
