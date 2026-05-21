import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import db as quiz_db
from .commands import CUSTOM_COMMAND_ROLES, MOD_COMMANDS, get_user_commands
from .auto_bets import auto_bet_runtime
from .config import BASE_DIR, apply_runtime_settings, persist_settings_env, settings
from .game import runtime
from .giveaways import giveaway_runtime
from .runtime_state import runtime_state
from .service_metrics import service_metrics
from .twitch_api import twitch_api
from .twitch_chat_eventsub import twitch_listener
from .twitch_chat_webhook import twitch_webhook_listener
from .web_db import (
    APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE,
    add_standard_question_preset,
    add_user_question_config,
    BUILTIN_STANDARD_QUESTION_PRESET_FILES,
    build_standard_question_preset_ref,
    count_user_action_logs,
    get_app_setting,
    get_standard_question_presets,
    get_standard_question_preset_title,
    get_standard_question_preset_link_counts,
    create_user_timer,
    delete_user_question_config,
    delete_user_timer,
    get_question_config_by_id,
    get_template_questions,
    get_user_question_configs,
    get_user_questions_preview_from_path,
    get_user_timer_by_id,
    get_web_user_by_id,
    get_web_user_by_overlay_slug,
    list_user_action_logs,
    list_user_timers,
    list_user_bot_commands,
    list_web_users,
    delete_user_bot_command,
    ensure_user_auto_bet_gsi_token,
    get_auto_bet_user_by_gsi_token,
    get_user_auto_bet_settings,
    get_user_bot_command_by_name,
    log_user_action,
    remove_standard_question_preset,
    revoke_standard_question_preset_access,
    list_user_auto_bet_history,
    set_active_user_questions_config,
    set_app_settings,
    set_user_timer_enabled,
    set_web_user_admin,
    set_web_user_bot_enabled,
    update_web_user_profile_image_url,
    update_user_timer,
    upsert_user_bot_command,
    update_web_user_settings,
    upsert_web_user,
)


templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))
router = APIRouter()
logger = logging.getLogger(__name__)

OVERLAY_THEME_OPTIONS = [
    {'value': 'classic', 'label': 'Классический', 'description': 'Текущий дизайн overlay с темной стеклянной карточкой.'},
    {'value': 'neo', 'label': 'Новый', 'description': 'Контрастный дизайн с более яркой подачей и переработанной композицией.'},
]

COMMAND_ACCESS_OPTIONS = [
    {'value': 'owner', 'label': 'Только я'},
    {'value': 'moderators', 'label': 'Я и модераторы'},
    {'value': 'everyone', 'label': 'Все пользователи'},
]

GSI_INSTALL_SESSION_TTL_SECONDS = 10 * 60
GSI_INSTALL_SESSIONS: dict[str, dict[str, Any]] = {}
ACTIVE_AUTOBET_PREDICTION_CACHE_TTL_SECONDS = 1.0
ACTIVE_AUTOBET_PREDICTION_CACHE_STALE_SECONDS = 15.0
RECENT_AUTOBET_RESULT_VISIBLE_SECONDS = 20.0


def _normalize_login(value: str) -> str:
    return str(value or '').strip().lower()


def _bot_auth_allowed_logins() -> set[str]:
    return {
        item.strip().lower()
        for item in str(settings.bot_auth_allowed_logins or '').split(',')
        if item.strip()
    }


def _can_manage_bot_account(user: Optional[dict]) -> bool:
    if not user:
        return False
    allowed_logins = _bot_auth_allowed_logins()
    if not allowed_logins:
        return False
    return _normalize_login(user.get('login')) in allowed_logins


def _is_admin_user(user: Optional[dict]) -> bool:
    if not user:
        return False
    return bool(user.get('is_admin', 0))


def _session_user_id(request: Request) -> Optional[int]:
    user_id = request.session.get('user_id')
    return int(user_id) if user_id is not None else None


def get_current_user(request: Request) -> Optional[dict]:
    user_id = _session_user_id(request)
    if user_id is None:
        return None
    return get_web_user_by_id(user_id)


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail='Требуется авторизация через Twitch.')
    return user


def require_admin_user(request: Request) -> dict:
    user = require_user(request)
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail='Доступ разрешён только администраторам.')
    return user


def _channel_context_payload(user: dict, role: str, *, is_active: bool = False) -> dict[str, Any]:
    return {
        'id': int(user['id']),
        'login': user.get('login') or '',
        'display_name': user.get('display_name') or user.get('login') or '',
        'profile_image_url': user.get('profile_image_url') or '',
        'role': role,
        'is_active': is_active,
    }


async def _ensure_profile_image_url(user: dict) -> dict:
    if user.get('profile_image_url') or not user.get('twitch_user_id'):
        return user
    try:
        twitch_user = await twitch_api.get_user_by_id(str(user.get('twitch_user_id') or ''))
    except Exception as exc:
        logger.warning('Failed to refresh Twitch avatar for user %s: %s', user.get('id'), exc)
        return user
    profile_image_url = twitch_user.get('profile_image_url') if twitch_user else ''
    if not profile_image_url:
        return user
    update_web_user_profile_image_url(int(user['id']), profile_image_url)
    next_user = dict(user)
    next_user['profile_image_url'] = profile_image_url
    return next_user


async def _can_manage_channel(current_user: dict, owner_user: Optional[dict]) -> bool:
    if not current_user or not owner_user:
        return False
    if int(current_user['id']) == int(owner_user['id']):
        return True
    try:
        return await twitch_api.is_user_moderator_for_user(
            owner_user,
            str(current_user.get('twitch_user_id') or ''),
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            'Channel access check failed actor=%s owner=%s status=%s body=%s',
            current_user.get('login'),
            owner_user.get('login'),
            exc.response.status_code,
            exc.response.text,
        )
    except Exception as exc:
        logger.warning(
            'Channel access check failed actor=%s owner=%s error=%s',
            current_user.get('login'),
            owner_user.get('login') if owner_user else '',
            exc,
        )
    return False


async def _list_accessible_channels(current_user: dict, active_owner_id: Optional[int] = None) -> list[dict[str, Any]]:
    current_user = await _ensure_profile_image_url(current_user)
    channels = [
        _channel_context_payload(
            current_user,
            'owner',
            is_active=int(active_owner_id or current_user['id']) == int(current_user['id']),
        )
    ]
    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    for owner_user in list_web_users(active_only=False):
        if int(owner_user['id']) == int(current_user['id']):
            continue
        if _normalize_login(owner_user.get('login')) in bot_logins:
            continue
        if await _can_manage_channel(current_user, owner_user):
            owner_user = await _ensure_profile_image_url(owner_user)
            channels.append(
                _channel_context_payload(
                    owner_user,
                    'moderator',
                    is_active=int(active_owner_id or current_user['id']) == int(owner_user['id']),
                )
            )
    channels.sort(key=lambda item: (item['role'] != 'owner', item['display_name'].lower()))
    return channels


async def get_active_channel_user(request: Request, current_user: Optional[dict] = None) -> dict:
    current_user = current_user or require_user(request)
    active_owner_id = request.session.get('active_channel_user_id')
    owner_user = get_web_user_by_id(int(active_owner_id)) if active_owner_id is not None else current_user
    if not owner_user or not await _can_manage_channel(current_user, owner_user):
        request.session['active_channel_user_id'] = current_user['id']
        return current_user
    request.session['active_channel_user_id'] = owner_user['id']
    return owner_user


async def require_channel_user(request: Request) -> dict:
    return await get_active_channel_user(request, require_user(request))


async def require_giveaway_owner_user(request: Request) -> dict:
    return require_user(request)


async def _build_session_payload(request: Request, current_user: dict) -> dict[str, Any]:
    current_user = await _ensure_profile_image_url(current_user)
    active_user = await get_active_channel_user(request, current_user)
    active_user = await _ensure_profile_image_url(active_user)
    channels = await _list_accessible_channels(current_user, int(active_user['id']))
    return {
        'user': {
            'id': int(current_user['id']),
            'twitch_user_id': current_user.get('twitch_user_id') or '',
            'login': current_user.get('login') or '',
            'display_name': current_user.get('display_name') or current_user.get('login') or '',
            'profile_image_url': current_user.get('profile_image_url') or '',
        },
        'active_channel': _channel_context_payload(
            active_user,
            'owner' if int(active_user['id']) == int(current_user['id']) else 'moderator',
            is_active=True,
        ),
        'channels': channels,
        'is_admin': _is_admin_user(current_user),
        'routes': {
            'dashboard': '/dashboard',
            'stats': '/stats',
            'settings': '/settings',
            'timers': '/timers',
            'admin': '/admin',
            'commands': '/commands',
            'giveaways': '/giveaways',
            'autobet': '/autobet',
            'quiz': '/quiz',
        },
    }


def build_overlay_url(slug: str) -> str:
    return f'{settings.app_public_base_url.rstrip("/")}/u/{slug}/overlay'


def build_autobet_overlay_url(slug: str) -> str:
    return f'{settings.app_public_base_url.rstrip("/")}/u/{slug}/autobet-overlay'


def _overlay_asset_version(filename: str) -> str:
    asset_path = BASE_DIR / 'overlay' / filename
    if not asset_path.exists():
        return str(int(time.time()))
    return str(int(asset_path.stat().st_mtime))


def build_site_css_url() -> str:
    css_path = BASE_DIR / 'site_static' / 'site.css'
    if not css_path.exists():
        return '/site/static/site.css'
    version = int(css_path.stat().st_mtime)
    return f'/site/static/site.css?v={version}'


def _frontend_dist_index_path() -> Path:
    return BASE_DIR / 'frontend' / 'dist' / 'index.html'


def _frontend_spa_response() -> FileResponse:
    index_path = _frontend_dist_index_path()
    if not index_path.exists():
        raise HTTPException(status_code=503, detail='React build not found. Run npm run build in frontend.')
    return FileResponse(index_path)


def _subscription_setup_warning(bot_login: str) -> str:
    return (
        f'Чат пока не удалось подключить автоматически. Убедись, что бот получил /mod {bot_login}, '
        'затем отвяжи приложение в Twitch Connections, войди заново через Twitch и нажми повторную активацию.'
    )


def _bot_not_moderator_text(bot_login: str) -> str:
    return f'Бот не подключен к чату. Выдай ему модератора командой /mod {bot_login} и затем нажми повторную активацию.'


def _bot_token_invalid_text() -> str:
    return (
        'Бот имеет модератора, но Twitch отклонил подключение EventSub. '
        'Обычно это означает, что у бота истек или стал недействительным TWITCH_BOT_USER_ACCESS_TOKEN.'
    )


def _subscription_warning(bot_login: str) -> str:
    return (
        f'Чат еще не подключен. Выдай боту модератора командой /mod {bot_login} '
        'и затем открой кабинет еще раз или нажми повторную активацию.'
    )


async def _activate_chat_for_user(user: dict) -> str:
    set_web_user_bot_enabled(int(user['id']), True)
    user['bot_enabled'] = 1
    twitch_listener.remember_owner(user)
    try:
        await twitch_listener.ensure_channel_subscription(user['twitch_user_id'])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            return (
                'Не удалось подключить чат: Twitch отклонил токен бота. '
                'Обнови TWITCH_BOT_USER_ACCESS_TOKEN и затем нажми повторную активацию.'
            )
        if exc.response.status_code == 403:
            return _subscription_warning(settings.twitch_bot_user_login or 'your_bot')
        if exc.response.status_code == 400:
            return _subscription_setup_warning(settings.twitch_bot_user_login or 'your_bot')
        logger.warning(
            'Unexpected Twitch subscription error for broadcaster %s: status=%s body=%s',
            user.get('twitch_user_id'),
            exc.response.status_code,
            exc.response.text,
        )
        return 'Не удалось автоматически активировать чат. Попробуй еще раз через пару секунд.'
    except Exception as exc:
        logger.exception('Failed to activate chat for broadcaster %s: %s', user.get('twitch_user_id'), exc)
        return 'Не удалось автоматически активировать чат. Попробуй еще раз через пару секунд.'
    try:
        await twitch_webhook_listener.ensure_channel_subscription(user['twitch_user_id'])
    except Exception as exc:
        logger.warning(
            'Primary chat activation succeeded, but Chat Bots webhook subscription failed for broadcaster %s: %s',
            user.get('twitch_user_id'),
            exc,
        )
    return ''


async def _deactivate_chat_for_user(user: dict) -> str:
    set_web_user_bot_enabled(int(user['id']), False)
    user['bot_enabled'] = 0
    twitch_listener.remember_owner(user)
    await twitch_listener.deactivate_channel(user['twitch_user_id'])
    try:
        await twitch_webhook_listener.deactivate_channel(user['twitch_user_id'])
    except Exception as exc:
        logger.warning(
            'Failed to deactivate Chat Bots webhook subscription for broadcaster %s: %s',
            user.get('twitch_user_id'),
            exc,
        )
    try:
        remove_warning = await twitch_api.remove_bot_as_moderator_for_user(user)
    except Exception as exc:
        logger.exception('Failed to remove bot moderator for user %s: %s', user.get('id'), exc)
        remove_warning = 'Не удалось снять модератора с бота. Попробуй еще раз через пару секунд.'
    if remove_warning:
        return f'Бот отключен от чата, но модератор не снят: {remove_warning}'
    return 'Бот отключен от чата и снят с модераторов.'


def _redirect_dashboard(saved: bool = False, error: str = '', warning: str = '') -> RedirectResponse:
    params: dict[str, str] = {}
    if saved:
        params['saved'] = '1'
    if error:
        params['error'] = error
    if warning:
        params['warning'] = warning
    suffix = '' if not params else '?' + urlencode(params)
    return RedirectResponse(f'/dashboard{suffix}', status_code=302)


def _json_result(*, ok: bool = True, error: str = '', **payload: Any) -> JSONResponse:
    body: dict[str, Any] = {'ok': ok}
    if error:
        body['error'] = error
    body.update(payload)
    return JSONResponse(body, status_code=200 if ok else 400)


def _bot_login_scope() -> str:
    return 'user:read:chat user:write:chat user:bot'


def _owner_login_scope() -> str:
    return 'user:read:email channel:bot moderation:read channel:manage:moderators channel:manage:redemptions channel:read:redemptions channel:manage:predictions channel:read:predictions'


async def _check_bot_moderator(user: dict) -> bool:
    if not user or not bool(user.get('bot_enabled', 1)):
        return False
    if not user.get('access_token'):
        return False
    try:
        return await twitch_api.is_bot_moderator_for_user(
            user,
            user['twitch_user_id'],
            use_cache=False,
        )
    except httpx.HTTPStatusError:
        return False
    except Exception:
        return False


async def _heal_chat_subscription_if_needed(user: dict, bot_is_moderator: bool) -> str:
    if not user or not bool(user.get('bot_enabled', 1)):
        return ''
    if not bot_is_moderator:
        return ''
    if twitch_listener.is_channel_connected(user['twitch_user_id']):
        return ''
    return await _activate_chat_for_user(user)


def _apply_user_game_settings(user: dict) -> None:
    _get_user_game(user)


def _get_user_game(user: dict):
    selected_path = user.get('questions_file') or ''
    return runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=selected_path,
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        turbo_mode=bool(user.get('turbo_mode', 0)),
        passive_mode=bool(user.get('quiz_passive_mode', 0)),
        quiet_mode=bool(user.get('quiet_mode', 0)),
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )


def _parse_db_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or '').strip()
    if not text:
        return None
    normalized = text.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except ValueError:
        pass
    try:
        return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_db_timestamp(value: Any) -> str:
    parsed = _parse_db_timestamp(value)
    if not parsed:
        return 'Неизвестно'
    return parsed.strftime('%d.%m.%Y %H:%M')


def _format_seconds_brief(value: Any) -> str:
    try:
        seconds = max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        seconds = 0
    if seconds < 60:
        return f'{seconds}с'
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f'{minutes}м {remainder}с'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}ч {minutes}м'


def _find_recent_error(recent_errors: list[dict[str, Any]], key: str, *, within_seconds: int) -> Optional[dict[str, Any]]:
    normalized_key = str(key or '').strip()
    if not normalized_key:
        return None
    for item in recent_errors:
        if str(item.get('key') or '').strip() != normalized_key:
            continue
        try:
            age_seconds = float(item.get('age_seconds') or 0.0)
        except (TypeError, ValueError):
            age_seconds = 0.0
        if age_seconds <= float(within_seconds):
            return item
    return None


def _status_from_age(age_seconds: float, *, warn_after: float = 5.0, error_after: float = 15.0) -> str:
    if age_seconds <= warn_after:
        return 'healthy'
    if age_seconds <= error_after:
        return 'warning'
    return 'error'


def _status_from_timing(last_ms: float, count: int, *, warn_ms: float = 900.0, error_ms: float = 2500.0) -> str:
    if count <= 0:
        return 'healthy'
    if last_ms >= error_ms:
        return 'error'
    if last_ms >= warn_ms:
        return 'warning'
    return 'healthy'


def _status_label(status: str) -> str:
    if status == 'healthy':
        return 'Работает'
    if status == 'warning':
        return 'Нужен контроль'
    return 'Сбой'


def _worst_status(*statuses: str) -> str:
    if any(status == 'error' for status in statuses):
        return 'error'
    if any(status == 'warning' for status in statuses):
        return 'warning'
    return 'healthy'


def _check_history(snapshot: dict[str, Any], key: str) -> list[str]:
    history = (snapshot.get('check_history') or {}).get(key) or []
    return [str(item) for item in history if str(item) in {'up', 'warn', 'down'}]


def _counter_value(snapshot: dict[str, Any], key: str) -> int:
    return int((snapshot.get('counters') or {}).get(key) or 0)


def _timing_value(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    return (snapshot.get('timings') or {}).get(key) or {}


def _build_systems_status_payload(
    *,
    total_channels: int,
    active_channels: int,
    live_channels: int,
    chat_connected_channels: int,
) -> dict[str, Any]:
    snapshot = service_metrics.snapshot()
    heartbeats = snapshot.get('heartbeats') or {}
    recent_errors = list(snapshot.get('recent_errors') or [])
    eventsub_stats = twitch_listener.connection_stats()

    ticker_age = float((heartbeats.get('runtime_ticker') or {}).get('age_seconds') or 999999.0)
    ticker_status = _status_from_age(ticker_age)

    runtime_timing = _timing_value(snapshot, 'runtime.tick')
    timers_timing = _timing_value(snapshot, 'timers.tick')
    autobet_timing = _timing_value(snapshot, 'autobet.tick')
    twitch_streams_timing = _timing_value(snapshot, 'twitch.get_live_streams')

    runtime_status = _worst_status(ticker_status, _status_from_timing(float(runtime_timing.get('last_ms') or 0.0), int(runtime_timing.get('count') or 0)))
    timers_status = _status_from_timing(float(timers_timing.get('last_ms') or 0.0), int(timers_timing.get('count') or 0))
    autobet_status = _status_from_timing(float(autobet_timing.get('last_ms') or 0.0), int(autobet_timing.get('count') or 0))

    twitch_streams_error = _find_recent_error(recent_errors, 'twitch.get_live_streams', within_seconds=300)
    twitch_streams_stale = bool(twitch_streams_error) and 'stale cache' in str(twitch_streams_error.get('message') or '').lower()
    twitch_streams_status = 'warning' if twitch_streams_stale else ('warning' if twitch_streams_error else _status_from_timing(float(twitch_streams_timing.get('last_ms') or 0.0), int(twitch_streams_timing.get('count') or 0)))

    chat_failures = _counter_value(snapshot, 'chat.send.user_token.failures')
    chat_skipped = _counter_value(snapshot, 'chat.send.skipped_no_user_token')
    chat_fallbacks = _counter_value(snapshot, 'chat.send.app_token.fallbacks')
    chat_status = 'error' if chat_failures > 40 else ('warning' if chat_failures > 5 or chat_fallbacks > 25 or chat_skipped > 10 else 'healthy')

    eventsub_status = 'error' if not eventsub_stats.get('session_active') else ('warning' if chat_connected_channels < max(1, active_channels // 2) and active_channels else 'healthy')

    opendota_failures = _counter_value(snapshot, 'opendota.status.failures') + _counter_value(snapshot, 'opendota.live.failures')
    opendota_status = 'error' if opendota_failures > 20 else ('warning' if opendota_failures > 0 or _counter_value(snapshot, 'opendota.cooldowns') > 0 else 'healthy')

    layers = [
        {
            'id': 'core',
            'title': 'Ядро Flaunt',
            'tagline': 'Фоновый цикл, который крутит викторину, таймеры и автоставку каждую секунду.',
            'status': runtime_status,
            'components': [
                {
                    'id': 'runtime_ticker',
                    'label': 'Runtime ticker',
                    'role': 'Главный 1 Hz цикл',
                    'status': ticker_status,
                    'status_label': f'Heartbeat {_format_seconds_brief(ticker_age)} назад',
                    'detail': 'Держит в живом состоянии quiz runtime, timers и autobet.',
                    'metrics': [
                        {'label': 'Циклов', 'value': str(_counter_value(snapshot, 'runtime_ticker.loops'))},
                        {'label': 'Uptime процесса', 'value': _format_seconds_brief(snapshot.get('uptime_seconds') or 0)},
                    ],
                    'history': _check_history(snapshot, 'runtime_ticker'),
                },
                {
                    'id': 'runtime.tick',
                    'label': 'Quiz runtime',
                    'role': 'Викторина и overlay state',
                    'status': _status_from_timing(float(runtime_timing.get('last_ms') or 0.0), int(runtime_timing.get('count') or 0)),
                    'status_label': _status_label(_status_from_timing(float(runtime_timing.get('last_ms') or 0.0), int(runtime_timing.get('count') or 0))),
                    'detail': f'Средний тик {float(runtime_timing.get("avg_ms") or 0.0):.1f} ms, последний {float(runtime_timing.get("last_ms") or 0.0):.1f} ms.',
                    'metrics': [
                        {'label': 'Успешных тиков', 'value': str(_counter_value(snapshot, 'runtime.tick.success'))},
                        {'label': 'Сбоев', 'value': str(_counter_value(snapshot, 'runtime.tick.failures'))},
                    ],
                    'history': _check_history(snapshot, 'runtime.tick'),
                },
                {
                    'id': 'timers.tick',
                    'label': 'Timers runtime',
                    'role': 'Автосообщения и команды по расписанию',
                    'status': timers_status,
                    'status_label': _status_label(timers_status),
                    'detail': f'Средний тик {float(timers_timing.get("avg_ms") or 0.0):.1f} ms, пик {float(timers_timing.get("max_ms") or 0.0):.1f} ms.',
                    'metrics': [
                        {'label': 'Успешных тиков', 'value': str(_counter_value(snapshot, 'timers.tick.success'))},
                        {'label': 'Сбоев', 'value': str(_counter_value(snapshot, 'timers.tick.failures'))},
                    ],
                    'history': _check_history(snapshot, 'timers.tick'),
                },
                {
                    'id': 'autobet.tick',
                    'label': 'AutoBet runtime',
                    'role': 'Открытие и закрытие ставок по GSI',
                    'status': autobet_status,
                    'status_label': _status_label(autobet_status),
                    'detail': f'Средний тик {float(autobet_timing.get("avg_ms") or 0.0):.1f} ms, последний {float(autobet_timing.get("last_ms") or 0.0):.1f} ms.',
                    'metrics': [
                        {'label': 'Успешных тиков', 'value': str(_counter_value(snapshot, 'autobet.tick.success'))},
                        {'label': 'Сбоев', 'value': str(_counter_value(snapshot, 'autobet.tick.failures'))},
                    ],
                    'history': _check_history(snapshot, 'autobet.tick'),
                },
            ],
        },
        {
            'id': 'twitch',
            'title': 'Twitch слой',
            'tagline': 'Подключение к чату, Helix API и исходящие сообщения бота.',
            'status': _worst_status(eventsub_status, twitch_streams_status, chat_status),
            'components': [
                {
                    'id': 'eventsub',
                    'label': 'EventSub WebSocket',
                    'role': 'Входящий чат и redemption события',
                    'status': eventsub_status,
                    'status_label': 'Сессия активна' if eventsub_stats.get('session_active') else 'Сессия не поднята',
                    'detail': f'Подписано каналов: {int(eventsub_stats.get("subscribed_channels") or 0)}. В базе чат активен у {chat_connected_channels} из {active_channels} каналов.',
                    'metrics': [
                        {'label': 'Подписок EventSub', 'value': str(int(eventsub_stats.get('subscribed_channels') or 0))},
                        {'label': 'Чат подключён', 'value': f'{chat_connected_channels}/{active_channels}'},
                    ],
                    'history': [],
                },
                {
                    'id': 'twitch.get_live_streams',
                    'label': 'Helix Live Streams',
                    'role': 'Статус эфира для дашборда и автоставки',
                    'status': twitch_streams_status,
                    'status_label': 'Из кэша' if twitch_streams_stale else _status_label(twitch_streams_status),
                    'detail': (
                        f'Временный сбой {_format_seconds_brief(twitch_streams_error.get("age_seconds") or 0)} назад, работаем по кэшу.'
                        if twitch_streams_stale
                        else (
                            f'Последняя ошибка {_format_seconds_brief(twitch_streams_error.get("age_seconds") or 0)} назад.'
                            if twitch_streams_error
                            else f'Вызовов: {_counter_value(snapshot, "twitch.get_live_streams.calls")}, cache hit: {_counter_value(snapshot, "twitch.get_live_streams.cache_hits")}.'
                        )
                    ),
                    'metrics': [
                        {'label': 'Вызовов API', 'value': str(_counter_value(snapshot, 'twitch.get_live_streams.calls'))},
                        {'label': 'Последний ответ', 'value': f'{float(twitch_streams_timing.get("last_ms") or 0.0):.0f} ms'},
                    ],
                    'history': _check_history(snapshot, 'twitch.get_live_streams') if _check_history(snapshot, 'twitch.get_live_streams') else [],
                },
                {
                    'id': 'chat.send',
                    'label': 'Исходящий чат',
                    'role': 'Ответы бота, викторина, таймеры, розыгрыши',
                    'status': chat_status,
                    'status_label': _status_label(chat_status),
                    'detail': 'App token → user token fallback, если бейдж-путь не сработал.',
                    'metrics': [
                        {'label': 'Попыток отправки', 'value': str(_counter_value(snapshot, 'chat.send.attempts'))},
                        {'label': 'Fallback', 'value': str(chat_fallbacks)},
                        {'label': 'Ошибок user token', 'value': str(chat_failures)},
                    ],
                    'history': [],
                },
            ],
        },
        {
            'id': 'integrations',
            'title': 'Интеграции',
            'tagline': 'Внешние API и игровые источники данных.',
            'status': opendota_status,
            'components': [
                {
                    'id': 'opendota',
                    'label': 'OpenDota API',
                    'role': 'Dota 2 матчи и live-статус для автоставки',
                    'status': opendota_status,
                    'status_label': _status_label(opendota_status),
                    'detail': 'Используется, когда GSI не дал надёжный финальный результат.',
                    'metrics': [
                        {'label': 'Успешных status', 'value': str(_counter_value(snapshot, 'opendota.status.success'))},
                        {'label': 'Ошибок', 'value': str(opendota_failures)},
                        {'label': 'Cooldown', 'value': str(_counter_value(snapshot, 'opendota.cooldowns'))},
                    ],
                    'history': [],
                },
                {
                    'id': 'gsi',
                    'label': 'Game State Integration',
                    'role': 'Dota 2 и CS2 события от клиента игры',
                    'status': 'healthy',
                    'status_label': 'Приём активен',
                    'detail': 'Эндпоинты /api/dota/gsi/{token} и /api/cs2/gsi/{token} на стороне Flaunt.',
                    'metrics': [
                        {'label': 'Протокол', 'value': 'HTTP POST'},
                        {'label': 'Игры', 'value': 'Dota 2, CS2'},
                    ],
                    'history': [],
                },
            ],
        },
        {
            'id': 'delivery',
            'title': 'Доставка интерфейсов',
            'tagline': 'Кабинет стримера и OBS overlay для зрителей.',
            'status': 'healthy',
            'components': [
                {
                    'id': 'cabinet',
                    'label': 'Кабинет Flaunt',
                    'role': 'React SPA /app/*',
                    'status': 'healthy',
                    'status_label': 'Раздаётся приложением',
                    'detail': 'Статика из frontend/dist через FastAPI.',
                    'metrics': [
                        {'label': 'Стартов приложения', 'value': str(_counter_value(snapshot, 'app.starts'))},
                    ],
                    'history': [],
                },
                {
                    'id': 'overlay',
                    'label': 'Quiz overlay',
                    'role': 'Browser Source для OBS',
                    'status': 'healthy',
                    'status_label': 'Jinja + overlay/app.js',
                    'detail': 'Отдельный слой викторины, не зависит от SPA-сборки.',
                    'metrics': [
                        {'label': 'Маршрут', 'value': '/overlay/{slug}'},
                    ],
                    'history': [],
                },
            ],
        },
    ]

    layer_statuses = [str(layer.get('status') or 'healthy') for layer in layers]
    global_status = _worst_status(*layer_statuses)
    if recent_errors and global_status == 'healthy':
        global_status = 'warning'
    if len(recent_errors) > 8:
        global_status = 'error'

    global_label = (
        'Все системы работают'
        if global_status == 'healthy'
        else ('Частичная деградация' if global_status == 'warning' else 'Есть критические сбои')
    )

    return {
        'summary': {
            'status': global_status,
            'label': global_label,
            'uptime_label': _format_seconds_brief(snapshot.get('uptime_seconds') or 0),
            'updated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        },
        'fleet': {
            'total_channels': total_channels,
            'active_channels': active_channels,
            'live_channels': live_channels,
            'chat_connected_channels': chat_connected_channels,
        },
        'layers': layers,
        'incidents': [
            {
                'key': str(item.get('key') or ''),
                'message': str(item.get('message') or ''),
                'age_label': _format_seconds_brief(item.get('age_seconds') or 0),
            }
            for item in recent_errors[:8]
        ],
    }


def _build_service_metrics_payload() -> dict[str, Any]:
    snapshot = service_metrics.snapshot()
    heartbeats = snapshot.get('heartbeats') or {}
    ticker_heartbeat = heartbeats.get('runtime_ticker') or {}
    ticker_age = float(ticker_heartbeat.get('age_seconds') or 999999.0)
    recent_errors = list(snapshot.get('recent_errors') or [])
    recent_error_count = len(recent_errors)
    twitch_streams_recent_error = _find_recent_error(recent_errors, 'twitch.get_live_streams', within_seconds=300)
    twitch_streams_error_message = str((twitch_streams_recent_error or {}).get('message') or '').lower()
    twitch_streams_using_stale_cache = bool(twitch_streams_recent_error) and 'using stale cache' in twitch_streams_error_message

    if ticker_age <= 5:
        health_status = 'healthy'
        health_label = 'Стабильно'
    elif ticker_age <= 15:
        health_status = 'warning'
        health_label = 'Нужен контроль'
    else:
        health_status = 'error'
        health_label = 'Тикер отстал'

    counters = snapshot.get('counters') or {}
    timings = snapshot.get('timings') or {}
    overview_cards = [
        {
            'label': 'Uptime',
            'value': _format_seconds_brief(snapshot.get('uptime_seconds') or 0),
            'description': 'Сколько приложение живёт после последнего рестарта.',
            'tone': 'default',
        },
        {
            'label': 'Отправок в чат',
            'value': int(counters.get('chat.send.attempts') or 0),
            'description': f'Успешно через app/user token: {int(counters.get("chat.send.app_token.success") or 0) + int(counters.get("chat.send.user_token.success") or 0)}.',
            'tone': 'default',
        },
        {
            'label': 'Fallback на user token',
            'value': int(counters.get('chat.send.app_token.fallbacks') or 0),
            'description': 'Сколько раз бейдж-путь не сработал и бот откатился на user token.',
            'tone': 'warning' if int(counters.get('chat.send.app_token.fallbacks') or 0) else 'success',
        },
        {
            'label': 'Свежие ошибки',
            'value': recent_error_count,
            'description': 'Последние ошибки интеграций и фоновых тиков.',
            'tone': 'error' if recent_error_count else 'success',
        },
    ]
    pipelines = [
        {
            'label': 'Runtime ticker',
            'status': health_status,
            'status_label': health_label,
            'detail': f'Последний heartbeat { _format_seconds_brief(ticker_age) } назад.',
        },
        {
            'label': 'Twitch streams API',
            'status': 'healthy' if twitch_streams_using_stale_cache or not twitch_streams_recent_error else 'warning',
            'status_label': 'Из кэша' if twitch_streams_using_stale_cache else ('С ошибками' if twitch_streams_recent_error else 'Ок'),
            'detail': (
                f'Временный сетевой сбой {_format_seconds_brief(twitch_streams_recent_error.get("age_seconds") or 0)} назад. Работаем по последнему удачному статусу.'
                if twitch_streams_using_stale_cache
                else (
                    f'Последняя ошибка {_format_seconds_brief(twitch_streams_recent_error.get("age_seconds") or 0)} назад.'
                    if twitch_streams_recent_error
                    else f'Вызовов: {int(counters.get("twitch.get_live_streams.calls") or 0)}.'
                )
            ),
        },
    ]
    operation_rows = [
        {
            'label': label,
            'avg_ms': float((timings.get(key) or {}).get('avg_ms') or 0.0),
            'last_ms': float((timings.get(key) or {}).get('last_ms') or 0.0),
            'max_ms': float((timings.get(key) or {}).get('max_ms') or 0.0),
            'count': int((timings.get(key) or {}).get('count') or 0),
        }
        for key, label in (
            ('runtime.tick', 'Quiz runtime tick'),
            ('timers.tick', 'Timers tick'),
            ('autobet.tick', 'AutoBet tick'),
            ('twitch.get_live_streams', 'Twitch live streams'),
        )
    ]
    counter_rows = [
        {'label': label, 'value': int(counters.get(key) or 0)}
        for key, label in (
            ('runtime_ticker.loops', 'Циклы тикера'),
            ('runtime.tick.success', 'Успешных runtime tick'),
            ('timers.tick.success', 'Успешных timers tick'),
            ('autobet.tick.success', 'Успешных auto-bet tick'),
            ('chat.send.user_token.failures', 'Ошибок chat user-token'),
            ('chat.send.skipped_no_user_token', 'Пропусков без user token'),
        )
    ]
    return {
        'updated_at': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        'uptime_seconds': int(snapshot.get('uptime_seconds') or 0),
        'uptime_label': _format_seconds_brief(snapshot.get('uptime_seconds') or 0),
        'health': {
            'status': health_status,
            'label': health_label,
        },
        'overview_cards': overview_cards,
        'pipelines': pipelines,
        'operations': operation_rows,
        'counters': counter_rows,
        'recent_errors': [
            {
                'key': str(item.get('key') or ''),
                'message': str(item.get('message') or ''),
                'age_label': _format_seconds_brief(item.get('age_seconds') or 0),
            }
            for item in recent_errors
        ],
    }


def _format_action_log(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': int(row.get('id') or 0),
        'action': row.get('action') or '',
        'title': row.get('title') or '',
        'detail': row.get('detail') or '',
        'actor_login': row.get('actor_login') or '',
        'actor_display_name': row.get('actor_display_name') or row.get('actor_login') or '',
        'created_at': row.get('created_at') or '',
        'created_at_formatted': _format_db_timestamp(row.get('created_at')),
    }


def _log_user_action(
    request: Request,
    user: dict,
    *,
    action: str,
    title: str,
    detail: str = '',
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    actor = get_current_user(request) or user
    try:
        log_user_action(
            int(user['id']),
            action=action,
            title=title,
            detail=detail,
            actor_user_id=int(actor['id']) if actor and actor.get('id') is not None else None,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning('Failed to write action log user=%s action=%s error=%s', user.get('id'), action, exc)


def _format_timer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': int(row['id']),
        'name': str(row.get('name') or ''),
        'enabled': bool(row.get('enabled')),
        'offline_enabled': bool(row.get('offline_enabled')),
        'online_enabled': bool(row.get('online_enabled')),
        'offline_interval_minutes': int(row.get('offline_interval_minutes') or 60),
        'online_interval_minutes': int(row.get('online_interval_minutes') or 10),
        'minimum_lines': int(row.get('minimum_lines') or 0),
        'commands': list(row.get('commands') or []),
        'messages': list(row.get('messages') or []),
        'line_count': int(row.get('line_count') or 0),
        'created_at': str(row.get('created_at') or ''),
    }


def _build_timers_payload(user: dict) -> dict[str, Any]:
    commands = [
        {
            'name': command['name'],
            'label': command['name'],
            'response_text': command.get('response_text') or '',
        }
        for command in get_user_commands(int(user['id']))
        if not bool(command.get('is_builtin')) and bool(command.get('enabled')) and str(command.get('response_text') or '').strip()
    ]
    return {
        'title': 'Таймеры',
        'user': {
            'id': int(user['id']),
            'twitch_user_id': user.get('twitch_user_id') or '',
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        'timers': [_format_timer(row) for row in list_user_timers(int(user['id']))],
        'commands': commands,
    }


def _timer_payload_list(value: Any, *, max_items: int = 20, command_names: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or '').strip()
        if not text:
            continue
        if command_names:
            text = text.lower()
            if not text.startswith('!'):
                text = f'!{text}'
        if text not in result:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def _json_list_len(value: Any) -> int:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


async def _build_stats_context() -> dict[str, Any]:
    all_users = list_web_users(active_only=False)
    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    filtered_users = [
        user
        for user in all_users
        if _normalize_login(user.get('login')) not in bot_logins
    ]
    active_users = [user for user in filtered_users if bool(user.get('bot_enabled', 1))]
    service_metrics.set_gauge('channels.total', len(filtered_users))
    service_metrics.set_gauge('channels.active', len(active_users))
    broadcaster_ids = [str(user.get('twitch_user_id') or '').strip() for user in active_users if user.get('twitch_user_id')]
    live_streams: dict[str, dict[str, Any]] = {}

    if broadcaster_ids:
        try:
            live_streams = await twitch_api.get_live_streams(broadcaster_ids)
        except Exception as exc:
            logger.warning('Failed to fetch live streams for stats page: %s', exc)
    service_metrics.set_gauge('channels.live', len(live_streams))

    now = datetime.now(timezone.utc)
    min_sort_datetime = datetime.min.replace(tzinfo=timezone.utc)
    connected_chat_count = 0
    recent_connected_7d = 0
    turbo_enabled_count = 0
    quiet_mode_count = 0
    custom_configs_count = 0
    custom_commands_count = 0
    enabled_custom_commands_count = 0
    builtin_command_overrides_count = 0
    disabled_builtin_commands_count = 0
    command_aliases_count = 0
    command_keywords_count = 0
    timers_count = 0
    enabled_timers_count = 0
    timer_messages_count = 0
    timer_command_links_count = 0
    action_logs_count = 0
    channels_with_custom_commands = 0
    channels_with_timers = 0
    recent_channels: list[dict[str, Any]] = []

    for user in active_users:
        user_id = int(user['id'])
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        created_at = user.get('created_at')
        parsed_created_at = _parse_db_timestamp(created_at)
        is_live = broadcaster_id in live_streams
        chat_connected = twitch_listener.is_channel_connected(broadcaster_id) if broadcaster_id else False
        user_commands = list_user_bot_commands(user_id)
        user_timers = list_user_timers(user_id)
        user_action_logs_count = count_user_action_logs(user_id)
        user_custom_commands = [command for command in user_commands if not bool(command.get('is_builtin', 0))]
        user_builtin_overrides = [command for command in user_commands if bool(command.get('is_builtin', 0))]
        user_enabled_custom_commands = [command for command in user_custom_commands if bool(command.get('enabled', 1))]
        user_disabled_builtin_commands = [command for command in user_builtin_overrides if not bool(command.get('enabled', 1))]
        user_enabled_timers = [timer for timer in user_timers if bool(timer.get('enabled', 1))]
        user_aliases_count = sum(_json_list_len(command.get('aliases')) for command in user_custom_commands)
        user_keywords_count = sum(_json_list_len(command.get('keywords')) for command in user_custom_commands)
        user_timer_messages_count = sum(len(timer.get('messages') or []) for timer in user_timers)
        user_timer_command_links_count = sum(len(timer.get('commands') or []) for timer in user_timers)

        if chat_connected:
            connected_chat_count += 1
        if bool(user.get('turbo_mode', 0)):
            turbo_enabled_count += 1
        if bool(user.get('quiet_mode', 0)):
            quiet_mode_count += 1
        if user.get('questions_file'):
            custom_configs_count += 1
        if parsed_created_at and now - parsed_created_at <= timedelta(days=7):
            recent_connected_7d += 1
        if user_custom_commands:
            channels_with_custom_commands += 1
        if user_timers:
            channels_with_timers += 1

        custom_commands_count += len(user_custom_commands)
        enabled_custom_commands_count += len(user_enabled_custom_commands)
        builtin_command_overrides_count += len(user_builtin_overrides)
        disabled_builtin_commands_count += len(user_disabled_builtin_commands)
        command_aliases_count += user_aliases_count
        command_keywords_count += user_keywords_count
        timers_count += len(user_timers)
        enabled_timers_count += len(user_enabled_timers)
        timer_messages_count += user_timer_messages_count
        timer_command_links_count += user_timer_command_links_count
        action_logs_count += user_action_logs_count

        stream = live_streams.get(broadcaster_id) or {}
        recent_channels.append(
            {
                'display_name': user.get('display_name') or user.get('login') or 'Канал',
                'login': user.get('login') or '',
                'connected_at': _format_db_timestamp(created_at),
                'updated_at': _format_db_timestamp(user.get('updated_at')),
                '_created_at_sort': parsed_created_at or min_sort_datetime,
                'overlay_url': build_overlay_url(user['overlay_slug']),
                'is_live': is_live,
                'chat_connected': chat_connected,
                'turbo_mode': bool(user.get('turbo_mode', 0)),
                'quiet_mode': bool(user.get('quiet_mode', 0)),
                'uses_custom_config': bool(user.get('questions_file')),
                'custom_command_count': len(user_custom_commands),
                'enabled_custom_command_count': len(user_enabled_custom_commands),
                'timer_count': len(user_timers),
                'enabled_timer_count': len(user_enabled_timers),
                'action_log_count': user_action_logs_count,
                'command_alias_count': user_aliases_count,
                'command_keyword_count': user_keywords_count,
                'stream_title': stream.get('title') or '',
                'stream_category': stream.get('game_name') or '',
                'viewer_count': int(stream.get('viewer_count') or 0),
            }
        )

    recent_channels.sort(key=lambda item: item['_created_at_sort'], reverse=True)

    return {
        'stats_cards': [
            {
                'value': custom_commands_count,
                'label': 'Кастомных команд',
                'description': f'Активных: {enabled_custom_commands_count}. Каналов с кастомными командами: {channels_with_custom_commands}.',
            },
            {
                'value': timers_count,
                'label': 'Таймеров',
                'description': f'Включено: {enabled_timers_count}. Каналов с таймерами: {channels_with_timers}.',
            },
            {
                'value': connected_chat_count,
                'label': 'Чатов подключено',
                'description': 'Каналы, где EventSub сейчас активен и бот видит чат.',
            },
            {
                'value': action_logs_count,
                'label': 'Действий в логах',
                'description': 'Все действия по каналам: команды, таймеры, викторина, конфиги и бот.',
            },
        ],
        'stats_highlights': [
            {
                'label': 'Активных каналов с ботом',
                'value': len(active_users),
            },
            {
                'label': 'Всего каналов в базе',
                'value': len(filtered_users),
            },
            {
                'label': 'Сейчас в эфире',
                'value': len(live_streams),
            },
            {
                'label': 'Новых за 7 дней',
                'value': recent_connected_7d,
            },
            {
                'label': 'С кастомными вопросами',
                'value': custom_configs_count,
            },
            {
                'label': 'С турбо-режимом',
                'value': turbo_enabled_count,
            },
            {
                'label': 'В тихом режиме',
                'value': quiet_mode_count,
            },
            {
                'label': 'Отключённых стандартных команд',
                'value': disabled_builtin_commands_count,
            },
            {
                'label': 'Override стандартных команд',
                'value': builtin_command_overrides_count,
            },
            {
                'label': 'Alias у команд',
                'value': command_aliases_count,
            },
            {
                'label': 'Кейвордов у команд',
                'value': command_keywords_count,
            },
            {
                'label': 'Сообщений в таймерах',
                'value': timer_messages_count,
            },
            {
                'label': 'Команд в таймерах',
                'value': timer_command_links_count,
            },
        ],
        'recent_channels': recent_channels[:12],
        'stats_updated_at': now.strftime('%d.%m.%Y %H:%M'),
        'service_metrics': _build_service_metrics_payload(),
        'systems_status': _build_systems_status_payload(
            total_channels=len(filtered_users),
            active_channels=len(active_users),
            live_channels=len(live_streams),
            chat_connected_channels=connected_chat_count,
        ),
    }


def _build_admin_settings_context(current_user: dict) -> dict[str, Any]:
    all_users = list_web_users(active_only=False)
    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    admin_users = [
        user
        for user in all_users
        if _is_admin_user(user) and _normalize_login(user.get('login')) not in bot_logins
    ]
    service_metrics.set_gauge('admin.users', len(admin_users))
    admin_users.sort(key=lambda item: _normalize_login(item.get('login')))

    admin_ids = {int(user['id']) for user in admin_users}
    candidate_users = [
        user
        for user in all_users
        if int(user['id']) not in admin_ids and _normalize_login(user.get('login')) not in bot_logins
    ]
    candidate_users.sort(
        key=lambda item: _parse_db_timestamp(item.get('created_at')) or datetime.min,
        reverse=True,
    )

    for item in admin_users + candidate_users:
        item['created_at_formatted'] = _format_db_timestamp(item.get('created_at'))
        item['updated_at_formatted'] = _format_db_timestamp(item.get('updated_at'))

    return {
        'admin_users': admin_users,
        'admin_candidates': candidate_users[:25],
        'standard_question_presets': _list_standard_question_presets(),
        'autobet_debug_channels': _build_admin_autobet_debug_channels(
            [
                user
                for user in all_users
                if _normalize_login(user.get('login')) not in bot_logins
            ]
        ),
        'settings_updated_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
        'current_user_is_admin': _is_admin_user(current_user),
        'service_metrics': _build_service_metrics_payload(),
        'global_settings': {
            'autobet_require_stream_online': bool(settings.autobet_require_stream_online),
            'quiz_passive_debug_allow_offline': bool(get_app_setting(APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE, False)),
            'custom_market_ranges': _build_autobet_range_settings_payload(),
        },
    }


def _humanize_question_preset_name(file_name: str) -> str:
    stem = Path(file_name).stem.replace('_', ' ').replace('-', ' ').strip()
    lower_name = file_name.lower()
    if lower_name == 'questions.json':
        return 'Стандартная база'
    if lower_name == 'questions_dota2.json':
        return 'Dota 2 база'
    return ' '.join(part.capitalize() for part in stem.split()) or file_name


def _friendly_question_category_name(value: str) -> str:
    normalized = str(value or '').strip()
    lowered = normalized.lower()
    if 'послов' in lowered:
        return 'Пословицы'
    if 'актер' in lowered or 'актёр' in lowered:
        return 'Актеры'
    if 'фильм' in lowered or 'кино' in lowered:
        return 'Фильмы'
    if 'слов' in lowered:
        return 'Слова'
    if 'дота' in lowered:
        return 'Dota 2'
    return normalized[:1].upper() + normalized[1:] if normalized else ''


def _infer_question_preset_name(file_name: str, payload: list[dict[str, Any]]) -> str:
    fallback_name = _humanize_question_preset_name(file_name)
    categories: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        category = _friendly_question_category_name(str(item.get('category') or '').strip())
        if not category or category in categories:
            continue
        categories.append(category)
        if len(categories) >= 4:
            break
    if 2 <= len(categories) <= 4:
        return ' / '.join(categories)
    return fallback_name


def _list_standard_question_presets() -> list[dict[str, Any]]:
    link_counts = get_standard_question_preset_link_counts()
    preferred_order: dict[str, int] = {}
    presets: list[dict[str, Any]] = []
    for row in get_standard_question_presets():
        file_name = str(row.get('slug') or '').strip()
        try:
            payload = json.loads(str(row.get('content_json') or '[]'))
        except json.JSONDecodeError:
            payload = []
        if not file_name or not isinstance(payload, list) or not payload:
            continue
        presets.append(
            {
                'preset_id': f'pack-{int(row.get("id") or 0)}',
                'file_name': file_name,
                'name': str(row.get('name') or '').strip() or get_standard_question_preset_title(file_name) or _infer_question_preset_name(file_name, payload),
                'question_count': int(row.get('question_count') or len(payload)),
                'is_builtin': bool(row.get('is_builtin')),
                'linked_user_count': int(link_counts.get(file_name, 0)),
                '_sort_key': (preferred_order.get(file_name.lower(), 99), file_name.lower()),
            }
        )
    presets.sort(key=lambda item: item['_sort_key'])
    for item in presets:
        item.pop('_sort_key', None)
    return presets


def _build_admin_autobet_debug_channels(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = time.time()
    channels: list[dict[str, Any]] = []
    for user in users:
        user_id = int(user['id'])
        auto_settings = get_user_auto_bet_settings(user_id)
        dota_debug = auto_bet_runtime.get_gsi_debug_state(user_id, 'dota2')
        cs2_debug = auto_bet_runtime.get_gsi_debug_state(user_id, 'cs2')
        channels.append(
            {
                'id': user_id,
                'login': user.get('login') or '',
                'display_name': user.get('display_name') or user.get('login') or 'Канал',
                'dota2_enabled': bool(auto_settings.get('dota2_enabled')),
                'cs2_enabled': bool(auto_settings.get('cs2_enabled')),
                'active_prediction_id': str(auto_settings.get('active_prediction_id') or ''),
                'active_game_key': str(auto_settings.get('active_game_key') or ''),
                'gsi': {
                    'dota2': _build_admin_gsi_debug_game_payload(
                        'dota2',
                        auto_settings,
                        dota_debug,
                        now=now,
                    ),
                    'cs2': _build_admin_gsi_debug_game_payload(
                        'cs2',
                        auto_settings,
                        cs2_debug,
                        now=now,
                    ),
                },
            }
        )
    channels.sort(key=lambda item: item['display_name'].lower())
    return channels


def _admin_gsi_fallback_state(game_key: str, settings_row: dict[str, Any]) -> dict[str, Any]:
    shared_game_state = str(settings_row.get('gsi_game_state') or '').strip()
    if game_key == 'dota2':
        if not shared_game_state or shared_game_state.upper().startswith('CS2 '):
            return {}
        return {
            'match_id': str(settings_row.get('gsi_match_id') or '').strip(),
            'game_state': shared_game_state,
            'game_time': int(settings_row.get('gsi_game_time') or 0),
            'hero_name': str(settings_row.get('gsi_hero_name') or '').strip(),
            'kills': int(settings_row.get('gsi_kills') or 0),
            'deaths': int(settings_row.get('gsi_deaths') or 0),
            'assists': int(settings_row.get('gsi_assists') or 0),
        }
    if not shared_game_state.upper().startswith('CS2 '):
        return {}
    return {
        'match_id': str(settings_row.get('gsi_match_id') or '').strip(),
        'phase': shared_game_state,
        'round': int(settings_row.get('gsi_game_time') or 0),
        'map_name': str(settings_row.get('gsi_hero_name') or '').strip(),
        'kills': int(settings_row.get('gsi_kills') or 0),
        'deaths': int(settings_row.get('gsi_deaths') or 0),
        'assists': int(settings_row.get('gsi_assists') or 0),
    }


def _build_admin_gsi_debug_game_payload(
    game_key: str,
    settings_row: dict[str, Any],
    debug_state: dict[str, Any],
    *,
    now: float,
) -> dict[str, Any]:
    effective_state = {
        **_admin_gsi_fallback_state(game_key, settings_row),
        **(debug_state or {}),
    }
    updated_at = 0.0
    try:
        updated_at = float(effective_state.get('updated_at') or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    seconds_since_last_seen = int(max(0.0, now - updated_at)) if updated_at else 0
    connected = bool(updated_at and seconds_since_last_seen < 30)
    match_id = str(effective_state.get('match_id') or '').strip()
    game_state = str(effective_state.get('game_state') or '').strip()
    active_prediction_id = str(settings_row.get('active_prediction_id') or '').strip()
    active_game_key = str(settings_row.get('active_game_key') or '').strip()
    last_signature = str(settings_row.get('last_opened_stream_signature') or '').strip()
    last_error = str(settings_row.get('last_error') or '').strip()

    if game_key == 'dota2':
        mode_details = f"{str(effective_state.get('game_mode') or '').strip() or '—'} / {str(effective_state.get('lobby_type') or '').strip() or '—'}"
        duplicate_match_guard = bool(match_id) and last_signature.startswith(f'dota-gsi:{match_id}:')
        opening_allowed = (
            bool(settings_row.get('dota2_enabled'))
            and bool(match_id)
            and not (active_prediction_id and active_game_key == 'dota2')
            and not duplicate_match_guard
            and not last_error
            and auto_bet_runtime._gsi_ready_for_prediction_open(effective_state)
            and auto_bet_runtime._gsi_match_mode_is_allowed(effective_state)
        )
        if not bool(settings_row.get('dota2_enabled')):
            block_reason = 'Dota автоставка выключена'
        elif active_prediction_id and active_game_key == 'dota2':
            block_reason = 'Уже есть активная Dota ставка'
        elif duplicate_match_guard:
            block_reason = 'На этот match id ставка уже открывалась'
        elif last_error:
            block_reason = last_error
        elif not match_id:
            block_reason = 'Нет match id'
        elif not auto_bet_runtime._gsi_ready_for_prediction_open(effective_state):
            block_reason = 'Матч ещё не дошёл до стадии открытия ставки'
        elif not auto_bet_runtime._gsi_match_mode_is_allowed(effective_state):
            block_reason = 'Режим матча отфильтрован'
        else:
            block_reason = ''
        return {
            'connected': connected,
            'seconds_since_last_seen': seconds_since_last_seen,
            'last_seen_label': _format_seconds_brief(seconds_since_last_seen) if updated_at else 'никогда',
            'match_id': match_id,
            'game_state': game_state or '—',
            'game_time': int(effective_state.get('game_time') or 0),
            'subject_label': str(effective_state.get('hero_name') or '').strip() or '—',
            'score_line': f"{int(effective_state.get('kills') or 0)}/{int(effective_state.get('deaths') or 0)}/{int(effective_state.get('assists') or 0)}",
            'mode_label': mode_details,
            'extra_label': '',
            'opening_allowed': opening_allowed,
            'block_reason': block_reason,
            'last_error': last_error,
        }

    phase = str(effective_state.get('phase') or '').strip()
    mode = str(effective_state.get('mode') or '').strip()
    duplicate_match_guard = bool(match_id) and last_signature.startswith(f'cs2-gsi:{match_id}:')
    opening_allowed = (
        bool(settings_row.get('cs2_enabled'))
        and bool(match_id)
        and not (active_prediction_id and active_game_key == 'cs2')
        and not duplicate_match_guard
        and not last_error
        and auto_bet_runtime._cs2_mode_is_allowed(effective_state)
        and auto_bet_runtime._cs2_match_is_live(effective_state)
    )
    if not bool(settings_row.get('cs2_enabled')):
        block_reason = 'CS2 автоставка выключена'
    elif active_prediction_id and active_game_key == 'cs2':
        block_reason = 'Уже есть активная CS2 ставка'
    elif duplicate_match_guard:
        block_reason = 'На этот match id ставка уже открывалась'
    elif last_error:
        block_reason = last_error
    elif not match_id:
        block_reason = 'Нет match id'
    elif not auto_bet_runtime._cs2_match_is_live(effective_state):
        block_reason = 'Матч ещё не в live phase'
    elif not auto_bet_runtime._cs2_mode_is_allowed(effective_state):
        block_reason = 'Режим матча отфильтрован'
    else:
        block_reason = ''
    return {
        'connected': connected,
        'seconds_since_last_seen': seconds_since_last_seen,
        'last_seen_label': _format_seconds_brief(seconds_since_last_seen) if updated_at else 'никогда',
        'match_id': match_id,
        'game_state': phase or '—',
        'game_time': int(effective_state.get('round') or 0),
        'subject_label': str(effective_state.get('map_name') or '').strip() or '—',
        'score_line': f"{int(effective_state.get('kills') or 0)}/{int(effective_state.get('deaths') or 0)}/{int(effective_state.get('assists') or 0)}",
        'mode_label': mode or '—',
        'extra_label': str(effective_state.get('player_team') or '').strip().upper() or '',
        'opening_allowed': opening_allowed,
        'block_reason': block_reason,
        'last_error': last_error,
    }


def _build_autobet_range_settings_payload() -> dict[str, Any]:
    return {
        'dota2': {
            'kills': {'min': int(settings.autobet_dota_kills_min), 'max': int(settings.autobet_dota_kills_max)},
            'deaths': {'min': int(settings.autobet_dota_deaths_min), 'max': int(settings.autobet_dota_deaths_max)},
            'assists': {'min': int(settings.autobet_dota_assists_min), 'max': int(settings.autobet_dota_assists_max)},
            'duration': {'min': int(settings.autobet_dota_duration_min), 'max': int(settings.autobet_dota_duration_max)},
        },
        'cs2': {
            'kills': {'min': int(settings.autobet_cs2_kills_min), 'max': int(settings.autobet_cs2_kills_max)},
            'deaths': {'min': int(settings.autobet_cs2_deaths_min), 'max': int(settings.autobet_cs2_deaths_max)},
            'assists': {'min': int(settings.autobet_cs2_assists_min), 'max': int(settings.autobet_cs2_assists_max)},
        },
    }


def _normalize_autobet_range(value: Any, default: int, *, minimum: int = 0, maximum: int = 999) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(parsed, maximum))


@router.get('/', response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse('/dashboard', status_code=302)
    return _frontend_spa_response()


@router.get('/auth/twitch/login')
async def twitch_login(request: Request):
    current_user = get_current_user(request)
    force_reauth = str(request.query_params.get('force') or '').strip().lower() in {'1', 'true', 'yes'}
    return_to = str(request.query_params.get('return_to') or '').strip()
    if return_to.startswith('/') and not return_to.startswith('//'):
        request.session['post_login_redirect'] = return_to
    if current_user and not force_reauth:
        redirect_to = request.session.pop('post_login_redirect', None) or '/dashboard'
        return RedirectResponse(str(redirect_to), status_code=302)

    if not settings.twitch_client_id or not settings.twitch_redirect_uri:
        raise HTTPException(status_code=500, detail='Не настроены TWITCH_CLIENT_ID/TWITCH_REDIRECT_URI.')

    state = secrets.token_urlsafe(24)
    request.session['oauth_state'] = state
    if force_reauth:
        request.session['oauth_force_reauth'] = True
    query_params = {
        'client_id': settings.twitch_client_id,
        'redirect_uri': settings.twitch_redirect_uri,
        'response_type': 'code',
        'scope': _owner_login_scope(),
        'state': state,
    }
    if force_reauth:
        query_params['force_verify'] = 'true'
    query = urlencode(query_params)
    return RedirectResponse(f'https://id.twitch.tv/oauth2/authorize?{query}', status_code=302)


@router.get('/auth/twitch/bot/login')
async def twitch_bot_login(request: Request):
    user = require_user(request)
    if not _can_manage_bot_account(user):
        return _redirect_dashboard(error='У тебя нет доступа к авторизации бот-аккаунта.')
    if not settings.twitch_client_id or not settings.twitch_redirect_uri:
        raise HTTPException(status_code=500, detail='Не настроены TWITCH_CLIENT_ID/TWITCH_REDIRECT_URI.')

    state = secrets.token_urlsafe(24)
    request.session['bot_oauth_state'] = state
    request.session['bot_oauth_owner_id'] = user['id']
    query = urlencode(
        {
            'client_id': settings.twitch_client_id,
            'redirect_uri': settings.twitch_redirect_uri,
            'response_type': 'code',
            'scope': _bot_login_scope(),
            'state': state,
            'force_verify': 'true',
        }
    )
    return RedirectResponse(f'https://id.twitch.tv/oauth2/authorize?{query}', status_code=302)


@router.get('/auth/twitch/callback')
async def twitch_callback(request: Request, code: str = '', state: str = ''):
    bot_expected_state = request.session.get('bot_oauth_state')
    if bot_expected_state and state == bot_expected_state:
        owner_id = request.session.get('bot_oauth_owner_id')
        current_user = get_current_user(request)
        if not current_user or not owner_id or int(owner_id) != int(current_user['id']) or not _can_manage_bot_account(current_user):
            request.session.pop('bot_oauth_state', None)
            request.session.pop('bot_oauth_owner_id', None)
            return _redirect_dashboard(error='Недостаточно прав для завершения авторизации бот-аккаунта.')
        if not code:
            request.session.pop('bot_oauth_state', None)
            request.session.pop('bot_oauth_owner_id', None)
            return _redirect_dashboard(error='Twitch не вернул код авторизации для бот-аккаунта.')
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token_resp = await client.post(
                    'https://id.twitch.tv/oauth2/token',
                    params={
                        'client_id': settings.twitch_client_id,
                        'client_secret': settings.twitch_client_secret,
                        'code': code,
                        'grant_type': 'authorization_code',
                        'redirect_uri': settings.twitch_redirect_uri,
                    },
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()

                user_resp = await client.get(
                    'https://api.twitch.tv/helix/users',
                    headers={
                        'Authorization': f"Bearer {token_data['access_token']}",
                        'Client-Id': settings.twitch_client_id,
                    },
                )
                user_resp.raise_for_status()
                users = user_resp.json().get('data') or []
                if not users:
                    return _redirect_dashboard(error='Не удалось получить профиль бот-аккаунта Twitch.')
                bot_user = users[0]
        except httpx.HTTPStatusError as exc:
            request.session.pop('bot_oauth_state', None)
            request.session.pop('bot_oauth_owner_id', None)
            logger.warning(
                'Bot OAuth exchange failed: status=%s body=%s',
                exc.response.status_code,
                exc.response.text,
            )
            return _redirect_dashboard(error='Не удалось авторизовать бот-аккаунт. Попробуй еще раз.')
        except httpx.HTTPError as exc:
            request.session.pop('bot_oauth_state', None)
            request.session.pop('bot_oauth_owner_id', None)
            logger.exception('Bot OAuth request failed: %s', exc)
            return _redirect_dashboard(error='Twitch временно недоступен. Попробуй еще раз.')

        expected_login = str(settings.twitch_bot_user_login or '').strip().lower()
        actual_login = str(bot_user.get('login') or '').strip().lower()
        if expected_login and expected_login != actual_login:
            request.session.pop('bot_oauth_state', None)
            request.session.pop('bot_oauth_owner_id', None)
            return _redirect_dashboard(
                error=f'Авторизован не тот аккаунт. Ожидался бот @{expected_login}, а получен @{actual_login}.'
            )

        updates = {
            'TWITCH_BOT_USER_ACCESS_TOKEN': str(token_data.get('access_token') or ''),
            'TWITCH_BOT_USER_REFRESH_TOKEN': str(token_data.get('refresh_token') or ''),
            'TWITCH_BOT_USER_ID': str(bot_user.get('id') or ''),
            'TWITCH_BOT_USER_LOGIN': str(bot_user.get('login') or ''),
        }
        persist_settings_env(updates)
        apply_runtime_settings(updates)
        await twitch_api.resolve_missing_ids()
        await twitch_listener.resubscribe_enabled_channels()
        try:
            await twitch_webhook_listener.resubscribe_enabled_channels()
        except Exception as exc:
            logger.warning('Unable to refresh Chat Bots webhook subscriptions after bot auth: %s', exc)
        request.session.pop('bot_oauth_state', None)
        request.session.pop('bot_oauth_owner_id', None)
        return _redirect_dashboard(saved=True, warning='Бот-аккаунт авторизован. Если чат был отключен из-за токена, он подключится автоматически.')

    expected_state = request.session.get('oauth_state')
    if not expected_state or state != expected_state:
        request.session.pop('oauth_state', None)
        return RedirectResponse(
            '/?warning=' + urlencode({'message': 'Сессия входа устарела. Запусти авторизацию через Twitch еще раз.'}).split('=', 1)[1],
            status_code=302,
        )
    if not code:
        request.session.pop('oauth_state', None)
        return RedirectResponse(
            '/?error=' + urlencode({'message': 'Twitch не вернул код авторизации. Попробуй войти еще раз.'}).split('=', 1)[1],
            status_code=302,
        )

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_resp = await client.post(
                'https://id.twitch.tv/oauth2/token',
                params={
                    'client_id': settings.twitch_client_id,
                    'client_secret': settings.twitch_client_secret,
                    'code': code,
                    'grant_type': 'authorization_code',
                    'redirect_uri': settings.twitch_redirect_uri,
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            user_resp = await client.get(
                'https://api.twitch.tv/helix/users',
                headers={
                    'Authorization': f"Bearer {token_data['access_token']}",
                    'Client-Id': settings.twitch_client_id,
                },
            )
            user_resp.raise_for_status()
            users = user_resp.json().get('data') or []
            if not users:
                raise HTTPException(status_code=400, detail='Не удалось получить профиль Twitch.')
            twitch_user = users[0]
    except httpx.HTTPStatusError as exc:
        request.session.pop('oauth_state', None)
        logger.warning(
            'Twitch OAuth exchange failed: status=%s body=%s',
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(status_code=400, detail='Не удалось завершить авторизацию Twitch. Попробуй войти еще раз.')
    except httpx.HTTPError as exc:
        request.session.pop('oauth_state', None)
        logger.exception('Twitch OAuth request failed: %s', exc)
        raise HTTPException(status_code=502, detail='Twitch временно недоступен. Попробуй еще раз.')

    user = upsert_web_user(
        twitch_user_id=twitch_user['id'],
        login=twitch_user['login'],
        display_name=twitch_user['display_name'],
        profile_image_url=twitch_user.get('profile_image_url') or '',
        access_token=token_data['access_token'],
        refresh_token=token_data.get('refresh_token') or '',
    )
    twitch_listener.remember_owner(user)
    _apply_user_game_settings(user)
    request.session['user_id'] = user['id']
    request.session['active_channel_user_id'] = user['id']
    request.session.pop('oauth_state', None)
    request.session.pop('oauth_force_reauth', None)
    _log_user_action(request, user, action='auth.login', title='Вход на сайт', detail='Пользователь авторизовался через Twitch.')

    warning = await _activate_chat_for_user(user)
    redirect_to = request.session.pop('post_login_redirect', None)
    if isinstance(redirect_to, str) and redirect_to.startswith('/') and not redirect_to.startswith('//'):
        return RedirectResponse(redirect_to, status_code=302)
    return _redirect_dashboard(warning=warning)


@router.post('/logout')
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/', status_code=302)


async def _build_dashboard_page_context(request: Request, user: dict) -> dict[str, Any]:
    actor_user = get_current_user(request) or user
    configs = get_user_question_configs(user['id'])
    custom_configs_count = sum(1 for config in configs if not bool(config.get('is_standard')))
    active_config_id = None
    for config in configs:
        config['is_active'] = config['file_path'] == (user.get('questions_file') or '')
        config['file_name'] = Path(config['file_path']).name
        config['kind_label'] = 'Общий пакет' if bool(config.get('is_standard')) else 'Личный пакет'
        if config['is_active']:
            active_config_id = config['id']

    bot_is_moderator = await _check_bot_moderator(user)
    user = get_web_user_by_id(user['id']) or user
    current_user_is_admin = _is_admin_user(actor_user)
    bot_enabled = bool(user.get('bot_enabled', 1))
    auto_heal_warning = await _heal_chat_subscription_if_needed(user, bot_is_moderator)
    chat_connected = bot_enabled and twitch_listener.is_channel_connected(user['twitch_user_id']) and bot_is_moderator
    active_preview = get_user_questions_preview_from_path(user.get('questions_file') or '', limit=5)
    quiz_state = _get_user_game(user).get_public_state()

    if not bot_enabled:
        chat_status_text = 'Бот отключен в кабинете. Нажми «Подключить бота», чтобы вернуть его в чат.'
        chat_activate_button_text = 'Подключить бота'
        bot_status_offline_label = 'Бот отключен'
    elif chat_connected:
        chat_status_text = ''
        chat_activate_button_text = 'Повторно активировать чат'
        bot_status_offline_label = 'Бот не модератор'
    elif bot_is_moderator:
        chat_status_text = _bot_token_invalid_text()
        chat_activate_button_text = 'Повторно активировать чат'
        bot_status_offline_label = 'EventSub не подключен'
    else:
        chat_status_text = _bot_not_moderator_text(settings.twitch_bot_user_login or 'your_bot')
        chat_activate_button_text = 'Повторно активировать чат'
        bot_status_offline_label = 'Бот не модератор'

    return {
        'title': 'Кабинет',
        'user': user,
        'bot_enabled': bot_enabled,
        'chat_connected': chat_connected,
        'bot_is_moderator': bot_is_moderator,
        'chat_status_text': chat_status_text,
        'bot_status_online_label': 'Бот модератор',
        'bot_status_offline_label': bot_status_offline_label,
        'overlay_url': build_overlay_url(user['overlay_slug']),
        'bot_login': settings.twitch_bot_user_login or 'your_bot',
        'bot_token_configured': bool(settings.twitch_bot_user_access_token),
        'can_manage_bot_account': int(actor_user['id']) == int(user['id']) and _can_manage_bot_account(actor_user),
        'current_user_is_admin': current_user_is_admin,
        'chat_activate_button_text': chat_activate_button_text,
        'warning': request.query_params.get('warning') or auto_heal_warning,
        'configs': configs,
        'active_config_id': active_config_id,
        'active_preview': active_preview,
        'quiz_state': quiz_state,
        'action_logs': [_format_action_log(row) for row in list_user_action_logs(int(user['id']), limit=30)],
        'using_standard_config': False,
        'custom_limit_reached': custom_configs_count >= 3,
        'chat_outcomes_enabled': bool(user.get('chat_correct_answers_enabled', 0) or user.get('chat_winners_enabled', 0)),
        'command_access_options': COMMAND_ACCESS_OPTIONS,
        'overlay_theme_options': OVERLAY_THEME_OPTIONS,
    }


def _apply_dashboard_settings_update(
    user: dict,
    *,
    answer_cooldown_seconds: float,
    command_access: str,
    overlay_theme: str,
    turbo_mode: bool,
    quiz_passive_mode: bool,
    quiet_mode: bool,
    chat_questions_enabled: bool,
    chat_outcomes_enabled: bool,
) -> str:
    normalized_command_access = (command_access or '').strip().lower()
    valid_access_values = {item['value'] for item in COMMAND_ACCESS_OPTIONS}
    if normalized_command_access not in valid_access_values:
        return 'Некорректный уровень доступа к командам.'

    normalized_overlay_theme = (overlay_theme or '').strip().lower()
    valid_overlay_themes = {item['value'] for item in OVERLAY_THEME_OPTIONS}
    if normalized_overlay_theme not in valid_overlay_themes:
        return 'Некорректный стиль overlay.'

    if answer_cooldown_seconds < 0 or answer_cooldown_seconds > 30:
        return 'Кулдаун ответа должен быть в диапазоне от 0 до 30 секунд.'

    normalized_turbo_mode = bool(turbo_mode)
    normalized_quiz_passive_mode = bool(quiz_passive_mode)
    normalized_quiet_mode = bool(quiet_mode)
    normalized_chat_questions_enabled = bool(chat_questions_enabled)
    normalized_chat_outcomes_enabled = bool(chat_outcomes_enabled)

    if normalized_quiet_mode:
        normalized_chat_questions_enabled = False
        normalized_chat_outcomes_enabled = False
    elif normalized_chat_questions_enabled or normalized_chat_outcomes_enabled:
        normalized_quiet_mode = False
    else:
        normalized_quiet_mode = True

    update_web_user_settings(
        user['id'],
        answer_cooldown_seconds=round(float(answer_cooldown_seconds), 2),
        command_access=normalized_command_access,
        overlay_theme=normalized_overlay_theme,
        turbo_mode=normalized_turbo_mode,
        quiz_passive_mode=normalized_quiz_passive_mode,
        quiet_mode=normalized_quiet_mode,
        chat_questions_enabled=normalized_chat_questions_enabled,
        chat_correct_answers_enabled=normalized_chat_outcomes_enabled,
        chat_winners_enabled=normalized_chat_outcomes_enabled,
    )
    updated_user = get_web_user_by_id(user['id'])
    if updated_user:
        twitch_listener.remember_owner(updated_user)
        _apply_user_game_settings(updated_user)
    return ''


def _activate_question_source_for_user(user: dict, selected_id: Optional[int]) -> Optional[str]:
    selected_path = set_active_user_questions_config(user['id'], selected_id)
    runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=selected_path or '',
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        turbo_mode=bool(user.get('turbo_mode', 0)),
        passive_mode=bool(user.get('quiz_passive_mode', 0)),
        quiet_mode=bool(user.get('quiet_mode', 0)),
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )
    return selected_path


@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request):
    require_user(request)
    return _frontend_spa_response()


@router.get('/quiz', response_class=HTMLResponse)
async def quiz_page(request: Request):
    require_user(request)
    return _frontend_spa_response()


@router.get('/stats', response_class=HTMLResponse)
async def stats_page(request: Request):
    require_admin_user(request)
    return _frontend_spa_response()


@router.get('/timers', response_class=HTMLResponse)
async def timers_page(request: Request):
    require_user(request)
    return _frontend_spa_response()


@router.get('/admin', response_class=HTMLResponse)
async def admin_page(request: Request):
    require_admin_user(request)
    return _frontend_spa_response()


@router.get('/commands', response_class=HTMLResponse)
async def commands_page(request: Request):
    require_user(request)
    return _frontend_spa_response()


@router.get('/giveaways', response_class=HTMLResponse)
async def giveaways_page(request: Request):
    await require_giveaway_owner_user(request)
    return _frontend_spa_response()


@router.get('/autobet', response_class=HTMLResponse)
async def autobet_page(request: Request):
    require_user(request)
    return _frontend_spa_response()


@router.get('/api/app/session')
async def api_app_session(request: Request):
    user = require_user(request)
    fresh_user = get_web_user_by_id(user['id']) or user
    return await _build_session_payload(request, fresh_user)


@router.post('/api/app/session/channel')
async def api_app_session_channel(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    current_user = require_user(request)
    try:
        owner_id = int(payload.get('owner_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный канал.')

    owner_user = get_web_user_by_id(owner_id)
    if not owner_user:
        return _json_result(ok=False, error='Канал не найден.')
    if not await _can_manage_channel(current_user, owner_user):
        return _json_result(ok=False, error='У тебя нет доступа к настройкам этого канала.')

    request.session['active_channel_user_id'] = owner_id
    return await _build_session_payload(request, current_user)


@router.get('/api/app/dashboard')
async def api_app_dashboard(request: Request):
    user = await require_channel_user(request)
    context = await _build_dashboard_page_context(request, user)
    return {
        'title': context['title'],
        'user': {
            'id': int(context['user']['id']),
            'twitch_user_id': context['user'].get('twitch_user_id') or '',
            'login': context['user'].get('login') or '',
            'display_name': context['user'].get('display_name') or '',
        },
        'status': {
            'chat_connected': bool(context['chat_connected']),
            'bot_is_moderator': bool(context['bot_is_moderator']),
            'chat_status_text': context['chat_status_text'],
            'bot_status_online_label': context['bot_status_online_label'],
            'bot_status_offline_label': context['bot_status_offline_label'],
        },
        'overlay_url': context['overlay_url'],
        'bot_login': context['bot_login'],
        'bot_token_configured': bool(context['bot_token_configured']),
        'can_manage_bot_account': bool(context['can_manage_bot_account']),
        'is_admin': bool(context['current_user_is_admin']),
        'settings': {
            'answer_cooldown_seconds': context['user'].get('answer_cooldown_seconds'),
            'command_access': context['user'].get('command_access') or 'moderators',
            'overlay_theme': context['user'].get('overlay_theme') or 'classic',
            'turbo_mode': bool(context['user'].get('turbo_mode', 0)),
            'quiz_passive_mode': bool(context['user'].get('quiz_passive_mode', 0)),
            'quiet_mode': bool(context['user'].get('quiet_mode', 0)),
            'chat_questions_enabled': bool(context['user'].get('chat_questions_enabled', 0)),
            'chat_outcomes_enabled': bool(context['chat_outcomes_enabled']),
        },
        'quiz': {
            'is_active': bool(context['quiz_state'].get('is_active')),
            'paused': bool(context['quiz_state'].get('paused')),
            'passive_mode': bool(context['quiz_state'].get('passive_mode')),
            'passive_waiting_for_live': bool(context['quiz_state'].get('passive_waiting_for_live')),
            'passive_result_seconds_left': int(context['quiz_state'].get('passive_result_seconds_left') or 0),
            'auto_rounds_stopped': bool(context['quiz_state'].get('auto_rounds_stopped')),
            'next_round_in': int(context['quiz_state'].get('next_round_in') or 0),
            'seconds_left': int(context['quiz_state'].get('seconds_left') or 0),
            'last_no_winner': bool(context['quiz_state'].get('last_no_winner')),
            'category': context['quiz_state'].get('category') or '',
            'hint': context['quiz_state'].get('hint') or '',
            'masked_answer': context['quiz_state'].get('masked_answer') or '',
            'top_players': context['quiz_state'].get('top_players') or [],
            'season': context['quiz_state'].get('season'),
            'season_history': context['quiz_state'].get('season_history') or [],
        },
        'configs': [
            {
                'id': int(config['id']),
                'name': config.get('name') or '',
                'file_name': config.get('file_name') or '',
                'kind_label': config.get('kind_label') or '',
                'is_active': bool(config.get('is_active')),
                'is_standard': bool(config.get('is_standard')),
            }
            for config in context['configs']
          ],
          'active_preview': context['active_preview'],
          'action_logs': context['action_logs'],
          'using_standard_config': bool(context['using_standard_config']),
          'limits': {
            'custom_configs_max': 3,
            'custom_limit_reached': bool(context['custom_limit_reached']),
        },
        'options': {
            'command_access': COMMAND_ACCESS_OPTIONS,
            'overlay_theme': OVERLAY_THEME_OPTIONS,
        },
    }


@router.post('/api/app/quiz/start')
async def api_app_quiz_start(request: Request):
    user = await require_channel_user(request)
    user_game = _get_user_game(user)
    message = await user_game.start_round()
    _log_user_action(request, user, action='quiz.start', title='Викторина включена', detail=message)
    return _json_result(saved=True, message=message, quiz=user_game.get_public_state())


@router.post('/api/app/quiz/stop')
async def api_app_quiz_stop(request: Request):
    user = await require_channel_user(request)
    user_game = _get_user_game(user)
    message = await user_game.stop_game()
    _log_user_action(request, user, action='quiz.stop', title='Викторина отключена', detail=message)
    return _json_result(saved=True, message=message, quiz=user_game.get_public_state())


@router.post('/api/app/quiz/season/start')
async def api_app_quiz_season_start(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_channel_user(request)
    user_game = _get_user_game(user)
    ends_at = _parse_iso_datetime(payload.get('ends_at'))
    if not ends_at:
        return _json_result(ok=False, error='Укажи дату и время окончания сезона.')

    starts_at = _parse_iso_datetime(payload.get('starts_at')) or datetime.now(timezone.utc)
    title = str(payload.get('title') or '').strip() or _default_quiz_season_title(ends_at)
    try:
        season = quiz_db.create_quiz_season(
            user_game.config.scope_id,
            title,
            starts_at=starts_at,
            ends_at=ends_at,
        )
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))

    detail = f'Сезон «{season.get("title") or title}» активен до {season.get("ends_at")}.'
    _log_user_action(request, user, action='quiz.season.start', title='Сезон викторины запущен', detail=detail)
    return _json_result(saved=True, message='Сезон запущен.', quiz=user_game.get_public_state())


@router.post('/api/app/quiz/season/finish')
async def api_app_quiz_season_finish(request: Request, payload: Optional[dict[str, Any]] = Body(None)):
    user = await require_channel_user(request)
    user_game = _get_user_game(user)
    season_id = None
    if isinstance(payload, dict) and payload.get('season_id') not in {None, ''}:
        try:
            season_id = int(payload.get('season_id'))
        except (TypeError, ValueError):
            return _json_result(ok=False, error='Некорректный сезон.')

    season = quiz_db.finish_quiz_season(user_game.config.scope_id, season_id)
    if not season:
        return _json_result(ok=False, error='Активный сезон не найден.')

    detail = f'Сезон «{season.get("title") or season.get("id")}» завершён.'
    _log_user_action(request, user, action='quiz.season.finish', title='Сезон викторины завершён', detail=detail)
    return _json_result(saved=True, message='Сезон завершён.', quiz=user_game.get_public_state())


@router.get('/api/app/timers')
async def api_app_timers(request: Request):
    user = await require_channel_user(request)
    return _build_timers_payload(user)


async def _build_auto_bet_payload(user: dict) -> dict[str, Any]:
    state = auto_bet_runtime.payload(user)
    auto_settings = ensure_user_auto_bet_gsi_token(int(user['id']))
    active_prediction_id = str(auto_settings.get('active_prediction_id') or '').strip()
    gsi_token = str(auto_settings.get('gsi_token') or '').strip()
    gsi_endpoint_url = f'{settings.app_public_base_url.rstrip("/")}/api/dota/gsi/{gsi_token}'
    return {
        'title': 'Автоставка',
        'user': {
            'id': int(user['id']),
            'twitch_user_id': user.get('twitch_user_id') or '',
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        'settings': auto_settings,
        'games': state['games'],
        'active_prediction': await _get_cached_active_auto_bet_prediction(user, auto_settings, active_prediction_id),
        'history': list_user_auto_bet_history(int(user['id']), limit=5),
        'gsi': _build_gsi_payload(user, auto_settings, gsi_endpoint_url),
        'obs_overlay_url': build_autobet_overlay_url(str(user.get('overlay_slug') or '')),
        'limits': {
            'prediction_window_min_seconds': 30,
            'prediction_window_max_seconds': 1800,
        },
        'oauth_reauth_url': '/auth/twitch/login?force=1',
        'detection_note': 'Dota 2 и CS2 можно подключить одной установкой. После этого игра сама сообщает о матче, а бот открывает и закрывает ставки автоматически.',
    }


def _build_game_gsi_status(user: dict[str, Any], game_key: str, settings_row: dict[str, Any], now: float) -> dict[str, Any]:
    user_id = int(user['id'])
    debug_state = auto_bet_runtime.get_gsi_debug_state(user_id, game_key)
    try:
        debug_seen_at = float(debug_state.get('updated_at') or 0)
    except (TypeError, ValueError):
        debug_seen_at = 0.0
    connected = bool(debug_seen_at and now - debug_seen_at < 30)
    if game_key == 'dota2':
        phase = str(debug_state.get('game_state') or settings_row.get('gsi_game_state') or '')
        finished = auto_bet_runtime._gsi_match_is_finished(debug_state) if debug_state else False
        live = auto_bet_runtime._gsi_ready_for_prediction_open(debug_state) if debug_state else False
    else:
        phase = str(debug_state.get('phase') or settings_row.get('gsi_game_state') or '')
        finished = auto_bet_runtime._cs2_match_is_finished(debug_state) if debug_state else False
        live = auto_bet_runtime._cs2_match_is_live(debug_state) if debug_state else False
    return {
        'connected': connected,
        'last_seen_at': debug_seen_at,
        'seconds_since_last_seen': int(now - debug_seen_at) if debug_seen_at else 0,
        'match_id': str(debug_state.get('match_id') or settings_row.get('gsi_match_id') or ''),
        'phase': phase,
        'is_live': live,
        'is_finished': finished,
        'kills': int(debug_state.get('kills') or settings_row.get('gsi_kills') or 0),
        'deaths': int(debug_state.get('deaths') or settings_row.get('gsi_deaths') or 0),
        'assists': int(debug_state.get('assists') or settings_row.get('gsi_assists') or 0),
    }


def _build_gsi_payload(user: dict[str, Any], settings_row: dict[str, Any], endpoint_url: str) -> dict[str, Any]:
    last_seen_at = float(settings_row.get('gsi_last_seen_at') or 0)
    now = time.time()
    token = str(settings_row.get('gsi_token') or '')
    cs2_endpoint_url = endpoint_url.replace('/api/dota/gsi/', '/api/cs2/gsi/')
    install_script_url = endpoint_url.replace('/api/dota/gsi/', '/install/gsi/') + '.ps1'
    short_install_url = endpoint_url.replace('/api/dota/gsi/', '/install/')
    generic_install_url = f'{settings.app_public_base_url.rstrip("/")}/install'
    return {
        'token': token,
        'endpoint_url': endpoint_url,
        'cs2_endpoint_url': cs2_endpoint_url,
        'install_script_url': install_script_url,
        'short_install_url': short_install_url,
        'install_command': f'powershell -NoExit -Command "iwr -UseBasicParsing \'{install_script_url}\' | iex"',
        'pairing_install_command': f'powershell -NoExit -c "irm {generic_install_url} | iex"',
        'config_filename': 'gamestate_integration_flaunt_autobet.cfg',
        'config_text': _build_gsi_config(endpoint_url, token),
        'cs2_config_filename': 'gamestate_integration_flaunt_autobet.cfg',
        'cs2_config_text': _build_cs2_gsi_config(cs2_endpoint_url, token),
        'connected': bool(last_seen_at and now - last_seen_at < 30),
        'last_seen_at': last_seen_at,
        'seconds_since_last_seen': int(now - last_seen_at) if last_seen_at else 0,
        'match_id': settings_row.get('gsi_match_id') or '',
        'game_state': settings_row.get('gsi_game_state') or '',
        'game_time': int(settings_row.get('gsi_game_time') or 0),
        'hero_id': int(settings_row.get('gsi_hero_id') or 0),
        'hero_name': settings_row.get('gsi_hero_name') or '',
        'kills': int(settings_row.get('gsi_kills') or 0),
        'deaths': int(settings_row.get('gsi_deaths') or 0),
        'assists': int(settings_row.get('gsi_assists') or 0),
        'dota2': _build_game_gsi_status(user, 'dota2', settings_row, now),
        'cs2': _build_game_gsi_status(user, 'cs2', settings_row, now),
    }


def _normalize_gsi_install_code(value: str) -> str:
    normalized = str(value or '').strip()
    allowed = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-')
    if not normalized or len(normalized) > 80 or any(char not in allowed for char in normalized):
        return ''
    return normalized


def _prune_gsi_install_sessions(now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    expired_codes = [
        code
        for code, session in GSI_INSTALL_SESSIONS.items()
        if float(session.get('expires_at') or 0) <= now
    ]
    for code in expired_codes:
        GSI_INSTALL_SESSIONS.pop(code, None)


def _build_gsi_config(endpoint_url: str, token: str) -> str:
    return f'''"Flaunt AutoBet Dota 2"
{{
  "uri" "{endpoint_url}"
  "timeout" "5.0"
  "buffer" "0.1"
  "throttle" "0.5"
  "heartbeat" "5.0"
  "auth"
  {{
    "token" "{token}"
  }}
  "data"
  {{
    "provider" "1"
    "map" "1"
    "player" "1"
    "hero" "1"
    "allplayers" "1"
    "abilities" "1"
    "items" "1"
  }}
}}
'''


def _build_cs2_gsi_config(endpoint_url: str, token: str) -> str:
    return f'''"Flaunt AutoBet CS2"
{{
  "uri" "{endpoint_url}"
  "timeout" "5.0"
  "buffer" "0.1"
  "throttle" "0.2"
  "heartbeat" "1.0"
  "auth"
  {{
    "token" "{token}"
  }}
  "data"
  {{
    "provider" "1"
    "map" "1"
    "round" "1"
    "player_id" "1"
    "player_state" "1"
    "player_match_stats" "1"
    "allplayers_id" "1"
    "allplayers_state" "1"
    "allplayers_match_stats" "1"
  }}
}}
'''


def _build_gsi_install_script(endpoint_url: str, token: str) -> str:
    cs2_endpoint_url = endpoint_url.replace('/api/dota/gsi/', '/api/cs2/gsi/')
    config_text = _build_gsi_config(endpoint_url, token).replace("'@", "' + \"@\" + '")
    cs2_config_text = _build_cs2_gsi_config(cs2_endpoint_url, token).replace("'@", "' + \"@\" + '")
    return f'''$ErrorActionPreference = 'Stop'
try {{
$cfgName = 'gamestate_integration_flaunt_autobet.cfg'
$cfgText = @'
{config_text}'@
$cs2CfgName = 'gamestate_integration_flaunt_autobet.cfg'
$cs2CfgText = @'
{cs2_config_text}'@

function Add-Candidate([System.Collections.Generic.List[string]] $list, [string] $path) {{
  if ([string]::IsNullOrWhiteSpace($path)) {{ return }}
  if (-not $list.Contains($path)) {{ [void]$list.Add($path) }}
}}

function Ensure-DotaLaunchOption([System.Collections.Generic.List[string]] $steamPaths) {{
  $updatedFiles = New-Object 'System.Collections.Generic.List[string]'
  foreach ($steamPath in @($steamPaths)) {{
    $userdataDir = Join-Path $steamPath 'userdata'
    if (-not (Test-Path $userdataDir)) {{ continue }}
    $localConfigs = Get-ChildItem -Path $userdataDir -Filter 'localconfig.vdf' -Recurse -ErrorAction SilentlyContinue
    foreach ($localConfig in @($localConfigs)) {{
      $content = Get-Content -Path $localConfig.FullName -Raw -ErrorAction SilentlyContinue
      if ([string]::IsNullOrWhiteSpace($content) -or $content -notmatch '"570"') {{ continue }}
      if ($content -match '(?s)"570"\\s*\\{{.*?-gamestateintegration') {{
        [void]$updatedFiles.Add($localConfig.FullName)
        continue
      }}

      $updated = $content
      $appMatch = [regex]::Match($updated, '(?s)("570"\\s*\\{{)(.*?)(\\r?\\n\\s*\\}})')
      if ($appMatch.Success) {{
        $appPrefix = $appMatch.Groups[1].Value
        $appBody = $appMatch.Groups[2].Value
        $appSuffix = $appMatch.Groups[3].Value
        if ($appBody -match '"LaunchOptions"\\s+"([^"]*)"') {{
          $appBody = [regex]::Replace(
            $appBody,
            '("LaunchOptions"\\s+")([^"]*)(")',
            {{
              param($match)
              $options = $match.Groups[2].Value.Trim()
              if ($options -notmatch '(^|\\s)-gamestateintegration(\\s|$)') {{
                $options = ($options + ' -gamestateintegration').Trim()
              }}
              return $match.Groups[1].Value + $options + $match.Groups[3].Value
            }},
            1
          )
        }} else {{
          $appBody = $appBody + "`r`n`t`t`t`t`t`t`t`t`"LaunchOptions`" `"-gamestateintegration`""
        }}
        $updated = $updated.Substring(0, $appMatch.Index) + $appPrefix + $appBody + $appSuffix + $updated.Substring($appMatch.Index + $appMatch.Length)
      }}

      if ($updated -ne $content) {{
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($localConfig.FullName, $updated, $utf8NoBom)
        [void]$updatedFiles.Add($localConfig.FullName)
      }}
    }}
  }}
  return $updatedFiles
}}

$candidates = New-Object 'System.Collections.Generic.List[string]'
$cs2Candidates = New-Object 'System.Collections.Generic.List[string]'
$steamPaths = New-Object 'System.Collections.Generic.List[string]'

try {{
  $steamReg = Get-ItemProperty -Path 'HKCU:\\Software\\Valve\\Steam' -ErrorAction Stop
  Add-Candidate $steamPaths $steamReg.SteamPath
}} catch {{}}

Add-Candidate $steamPaths (Join-Path ${{env:ProgramFiles(x86)}} 'Steam')
Add-Candidate $steamPaths (Join-Path $env:ProgramFiles 'Steam')

foreach ($steamPath in @($steamPaths)) {{
  Add-Candidate $candidates (Join-Path $steamPath 'steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration')
  Add-Candidate $cs2Candidates (Join-Path $steamPath 'steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\cfg')
  $libraryFile = Join-Path $steamPath 'steamapps\\libraryfolders.vdf'
  if (Test-Path $libraryFile) {{
    $content = Get-Content $libraryFile -Raw
    foreach ($match in [regex]::Matches($content, '"path"\\s+"([^"]+)"')) {{
      $libraryPath = $match.Groups[1].Value -replace '\\\\', '\\'
      Add-Candidate $candidates (Join-Path $libraryPath 'steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration')
      Add-Candidate $cs2Candidates (Join-Path $libraryPath 'steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\cfg')
    }}
  }}
}}

$targetDir = $null
foreach ($candidate in $candidates) {{
  $dotaCfg = Split-Path $candidate -Parent
  if (Test-Path $dotaCfg) {{
    $targetDir = $candidate
    break
  }}
}}

if (-not $targetDir) {{
  $targetDir = Join-Path ${{env:ProgramFiles(x86)}} 'Steam\\steamapps\\common\\dota 2 beta\\game\\dota\\cfg\\gamestate_integration'
}}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
$targetFile = Join-Path $targetDir $cfgName
Set-Content -Path $targetFile -Value $cfgText -Encoding ASCII
$launchOptionFiles = Ensure-DotaLaunchOption $steamPaths

$cs2TargetDir = $null
foreach ($candidate in $cs2Candidates) {{
  if (Test-Path $candidate) {{
    $cs2TargetDir = $candidate
    break
  }}
}}
if (-not $cs2TargetDir) {{
  $cs2TargetDir = Join-Path ${{env:ProgramFiles(x86)}} 'Steam\\steamapps\\common\\Counter-Strike Global Offensive\\game\\csgo\\cfg'
}}
$cs2Installed = $false
if (Test-Path (Split-Path $cs2TargetDir -Parent)) {{
  New-Item -ItemType Directory -Force -Path $cs2TargetDir | Out-Null
  $cs2TargetFile = Join-Path $cs2TargetDir $cs2CfgName
  Set-Content -Path $cs2TargetFile -Value $cs2CfgText -Encoding ASCII
  $cs2Installed = $true
}}

Write-Host ''
Write-Host 'Flaunt AutoBet game connection installed:' -ForegroundColor Green
Write-Host $targetFile
if ($cs2Installed) {{
  Write-Host $cs2TargetFile
}} else {{
  Write-Host 'CS2 was not found. Dota 2 was configured only.' -ForegroundColor Yellow
}}
if ($launchOptionFiles.Count -gt 0) {{
  Write-Host 'Dota 2 launch option is ready: -gamestateintegration'
}} else {{
  Write-Host 'Could not update Steam launch options automatically.' -ForegroundColor Yellow
  Write-Host 'Add this manually in Steam -> Dota 2 -> Properties -> Launch Options: -gamestateintegration'
}}
Write-Host ''
Write-Host 'Restart Dota 2, then open /autobet and wait until the game is shown as connected.'
Write-Host ''
Write-Host 'This window will close in 10 seconds.'
Start-Sleep -Seconds 10
}} catch {{
  Write-Host ''
  Write-Host 'Flaunt AutoBet game connection install failed:' -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host ''
  Read-Host 'Press Enter to close'
}}
'''


def _build_gsi_pairing_install_script() -> str:
    base_url = settings.app_public_base_url.rstrip('/')
    return f'''$ErrorActionPreference = 'Stop'
try {{
$baseUrl = '{base_url}'
$code = [Guid]::NewGuid().ToString('N')
$authUrl = "$baseUrl/install/gsi/authorize?code=$code"
$statusUrl = "$baseUrl/install/gsi/session/$code"

Write-Host 'Opening Flaunt AutoBet authentication...' -ForegroundColor Cyan
Write-Host $authUrl
cmd /c start "" $authUrl
Write-Host ''
Write-Host 'Waiting for authentication with Flaunt...'

for ($i = 0; $i -lt 180; $i++) {{
  Start-Sleep -Seconds 2
  try {{
    $pollUrl = "$statusUrl?ts=$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
    $session = Invoke-RestMethod -UseBasicParsing -Headers @{{ 'Cache-Control' = 'no-cache'; 'Pragma' = 'no-cache' }} -Uri $pollUrl
  }} catch {{
    if (($i % 15) -eq 0) {{
      Write-Host 'Waiting for Flaunt authentication...'
      Write-Host "If the browser did not open, open this link manually:"
      Write-Host $authUrl
    }}
    continue
  }}

  $status = [string]$session.status
  $authorized = [string]$session.authorized
  $installScriptUrl = [string]$session.install_script_url
  if ($status -eq 'ready' -or $authorized -eq 'True' -or -not [string]::IsNullOrWhiteSpace($installScriptUrl)) {{
    Write-Host 'Authentication confirmed. Installing the game connection...' -ForegroundColor Green
    (Invoke-WebRequest -UseBasicParsing -Headers @{{ 'Cache-Control' = 'no-cache'; 'Pragma' = 'no-cache' }} -Uri $installScriptUrl).Content | Invoke-Expression
    exit
  }}

  if ($status -eq 'expired') {{
    throw 'Authentication session expired. Run the install command again.'
  }}

  if (($i % 15) -eq 0) {{
    Write-Host 'Have not authenticated with Flaunt yet...'
    Write-Host "Current status: $status"
  }}
}}

throw 'Timed out waiting for Flaunt authentication. Run the install command again.'
}} catch {{
  Write-Host ''
  Write-Host 'Flaunt AutoBet game connection install failed:' -ForegroundColor Red
  Write-Host $_.Exception.Message
  Write-Host ''
  Read-Host 'Press Enter to close'
}}
'''


def _parse_twitch_datetime(value: Any) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_quiz_season_title(ends_at: datetime) -> str:
    local_end = ends_at.astimezone()
    return f'Сезон до {local_end.strftime("%d.%m %H:%M")}'


def _json_clone(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False))


async def _get_cached_active_auto_bet_prediction(
    user: dict[str, Any],
    settings: dict[str, Any],
    active_prediction_id: str,
    *,
    cache_ttl_seconds: float = ACTIVE_AUTOBET_PREDICTION_CACHE_TTL_SECONDS,
    stale_ttl_seconds: float = ACTIVE_AUTOBET_PREDICTION_CACHE_STALE_SECONDS,
) -> Optional[dict[str, Any]]:
    cache_key = f'autobet-active-prediction:{int(user["id"])}:{str(active_prediction_id or "").strip() or "__current__"}'
    now = time.time()
    cached_entry = runtime_state.get(cache_key)
    cached_payload = None
    cached_at = 0.0
    if isinstance(cached_entry, dict):
        cached_payload = _json_clone(cached_entry.get('payload'))
        try:
            cached_at = float(cached_entry.get('cached_at') or 0.0)
        except (TypeError, ValueError):
            cached_at = 0.0
    if cached_payload is not None and now - cached_at < cache_ttl_seconds:
        return cached_payload

    prediction_payload = await _build_active_auto_bet_prediction(user, settings, active_prediction_id)
    if prediction_payload and str(prediction_payload.get('sync_error') or '').strip():
        if cached_payload is not None and now - cached_at < stale_ttl_seconds:
            return cached_payload
        return prediction_payload

    runtime_state.set(
        cache_key,
        {
            'cached_at': now,
            'payload': _json_clone(prediction_payload),
        },
        ttl_seconds=stale_ttl_seconds,
    )
    return _json_clone(prediction_payload)


async def _build_active_auto_bet_prediction(user: dict, settings: dict[str, Any], active_prediction_id: str) -> Optional[dict[str, Any]]:
    payload: dict[str, Any] = {
        'id': active_prediction_id,
        'game_key': settings.get('active_game_key') or '',
        'game_name': settings.get('active_game_name') or ('Twitch' if not active_prediction_id else ''),
        'title': settings.get('active_prediction_title') or '',
        'win_outcome_id': settings.get('win_outcome_id') or '',
        'loss_outcome_id': settings.get('loss_outcome_id') or '',
        'win_outcome_title': settings.get('win_outcome_title') or ('Победа' if active_prediction_id else ''),
        'loss_outcome_title': settings.get('loss_outcome_title') or ('Поражение' if active_prediction_id else ''),
        'status': '',
        'created_at': '',
        'locks_at': '',
        'closes_at': '',
        'seconds_remaining': 0,
        'total_users': 0,
        'total_channel_points': 0,
        'outcomes': [],
        'winning_outcome_id': '',
        'winning_outcome_title': '',
        'sync_error': '',
    }
    prediction = None
    try:
        if active_prediction_id:
            prediction = await twitch_api.get_prediction_for_user(user, prediction_id=active_prediction_id)
            prediction_status = str((prediction or {}).get('status') or '').strip().upper()
            if not prediction or prediction_status in {'RESOLVED', 'CANCELED'}:
                current_prediction = await twitch_api.get_current_prediction_for_user(user)
                if current_prediction:
                    prediction = current_prediction
        else:
            prediction = await twitch_api.get_current_prediction_for_user(user)
    except RuntimeError as exc:
        if active_prediction_id:
            payload['sync_error'] = str(exc)
            return payload
        return None
    except Exception as exc:
        logger.exception(
            'Failed to build active auto-bet prediction user=%s prediction_id=%s error=%s',
            user.get('id'),
            active_prediction_id,
            exc,
        )
        if active_prediction_id:
            payload['sync_error'] = 'Не удалось обновить ставку из Twitch.'
            return payload
        return None
    if not prediction:
        return None

    payload['id'] = prediction.get('id') or payload['id']

    now_utc = datetime.now(timezone.utc)
    locks_at = _parse_twitch_datetime(prediction.get('locks_at'))
    if locks_at:
        payload['closes_at'] = locks_at.isoformat()
        payload['seconds_remaining'] = max(0, int((locks_at - now_utc).total_seconds()))
    else:
        created_at = _parse_twitch_datetime(prediction.get('created_at'))
        prediction_window_seconds = 0
        try:
            prediction_window_seconds = int(
                prediction.get('prediction_window')
                or prediction.get('prediction_window_seconds')
                or settings.get('prediction_window_seconds')
                or 0
            )
        except (TypeError, ValueError):
            prediction_window_seconds = int(settings.get('prediction_window_seconds') or 0)
        if created_at and prediction_window_seconds > 0:
            closes_at = created_at + timedelta(seconds=prediction_window_seconds)
            payload['closes_at'] = closes_at.isoformat()
            payload['seconds_remaining'] = max(
                0,
                int((closes_at - now_utc).total_seconds()),
            )
    payload['status'] = prediction.get('status') or ''
    payload['created_at'] = prediction.get('created_at') or ''
    payload['locks_at'] = prediction.get('locks_at') or ''
    payload['title'] = prediction.get('title') or payload['title']
    payload['winning_outcome_id'] = prediction.get('winning_outcome_id') or ''

    normalized_outcomes: list[dict[str, Any]] = []
    for index, outcome in enumerate(prediction.get('outcomes') or []):
        if not isinstance(outcome, dict):
            continue
        top_predictors = outcome.get('top_predictors') or []
        top_predictor = top_predictors[0] if top_predictors and isinstance(top_predictors[0], dict) else {}
        normalized_outcome = {
            'id': outcome.get('id') or '',
            'title': outcome.get('title') or ('Победа' if index == 0 else 'Поражение'),
            'users': int(outcome.get('users') or 0),
            'channel_points': int(outcome.get('channel_points') or 0),
            'color': 'blue' if index == 0 else 'pink',
            'top_predictor_login': top_predictor.get('user_login') or '',
            'top_predictor_display_name': top_predictor.get('user_name') or '',
            'top_predictor_points': int(top_predictor.get('channel_points_used') or 0),
        }
        normalized_outcomes.append(normalized_outcome)

    payload['outcomes'] = normalized_outcomes
    if normalized_outcomes:
        if not payload['win_outcome_id']:
            payload['win_outcome_id'] = normalized_outcomes[0].get('id') or ''
        if not payload['win_outcome_title']:
            payload['win_outcome_title'] = normalized_outcomes[0].get('title') or 'Победа'
    if len(normalized_outcomes) > 1:
        if not payload['loss_outcome_id']:
            payload['loss_outcome_id'] = normalized_outcomes[1].get('id') or ''
        if not payload['loss_outcome_title']:
            payload['loss_outcome_title'] = normalized_outcomes[1].get('title') or 'Поражение'
    if payload['winning_outcome_id']:
        for normalized_outcome in normalized_outcomes:
            if str(normalized_outcome.get('id') or '') == str(payload['winning_outcome_id']):
                payload['winning_outcome_title'] = normalized_outcome.get('title') or ''
                break
    payload['total_users'] = sum(int(outcome.get('users') or 0) for outcome in normalized_outcomes)
    payload['total_channel_points'] = sum(int(outcome.get('channel_points') or 0) for outcome in normalized_outcomes)
    return payload


def _build_recent_autobet_result_payload(user_id: int) -> Optional[dict[str, Any]]:
    history = list_user_auto_bet_history(int(user_id), limit=1)
    if not history:
        return None
    latest = dict(history[0])
    resolved_at = _parse_db_timestamp(latest.get('created_at'))
    if resolved_at:
        age_seconds = (datetime.now(timezone.utc) - resolved_at).total_seconds()
        if age_seconds > RECENT_AUTOBET_RESULT_VISIBLE_SECONDS:
            return None
    return {
        'prediction_id': str(latest.get('prediction_id') or ''),
        'title': str(latest.get('title') or ''),
        'outcome_title': str(latest.get('outcome_title') or ''),
        'status': str(latest.get('status') or ''),
        'resolved_at': resolved_at.isoformat() if resolved_at else '',
    }


async def _build_public_autobet_overlay_payload(user: dict, overlay_slug: str) -> dict[str, Any]:
    auto_settings = get_user_auto_bet_settings(int(user['id']))
    active_prediction_id = str(auto_settings.get('active_prediction_id') or '').strip()
    active_prediction = await _get_cached_active_auto_bet_prediction(user, auto_settings, active_prediction_id)
    return {
        'channel_name': user.get('login') or '',
        'owner_display_name': user.get('display_name') or user.get('login') or '',
        'overlay_slug': overlay_slug,
        'fetched_at': time.time(),
        'active_prediction': active_prediction,
        'recent_result': _build_recent_autobet_result_payload(int(user['id'])),
    }


@router.get('/api/app/autobet')
async def api_app_autobet(request: Request):
    user = await require_channel_user(request)
    return await _build_auto_bet_payload(user)


async def _handle_dota_gsi_payload(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = get_auto_bet_user_by_gsi_token(token)
    if not user:
        raise HTTPException(status_code=404, detail='Unknown GSI token')
    body_token = str(((payload.get('auth') or {}) if isinstance(payload.get('auth'), dict) else {}).get('token') or '').strip()
    if body_token and not secrets.compare_digest(body_token, str(user.get('gsi_token') or '')):
        raise HTTPException(status_code=403, detail='Invalid GSI auth token')
    try:
        result = await auto_bet_runtime.handle_gsi_payload(user, payload)
    except Exception as exc:
        logger.exception('Dota GSI processing failed user=%s error=%s', user.get('id'), exc)
        return {'ok': False, 'error': 'Не удалось обработать сигнал Dota 2.'}
    return result


async def _handle_cs2_gsi_payload(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = get_auto_bet_user_by_gsi_token(token)
    if not user:
        raise HTTPException(status_code=404, detail='Unknown GSI token')
    body_token = str(((payload.get('auth') or {}) if isinstance(payload.get('auth'), dict) else {}).get('token') or '').strip()
    if body_token and not secrets.compare_digest(body_token, str(user.get('gsi_token') or '')):
        raise HTTPException(status_code=403, detail='Invalid GSI auth token')
    try:
        return await auto_bet_runtime.handle_cs2_gsi_payload(user, payload)
    except Exception as exc:
        logger.exception('CS2 GSI processing failed user=%s error=%s', user.get('id'), exc)
        return {'ok': False, 'error': 'Не удалось обработать сигнал CS2.'}


@router.post('/api/dota/gsi/{token}')
async def api_dota_gsi(token: str, payload: dict[str, Any] = Body(...)):
    return await _handle_dota_gsi_payload(token, payload)


@router.post('/api/dota/gsi/{token}/')
async def api_dota_gsi_slash(token: str, payload: dict[str, Any] = Body(...)):
    return await _handle_dota_gsi_payload(token, payload)


@router.post('/api/cs2/gsi/{token}')
async def api_cs2_gsi(token: str, payload: dict[str, Any] = Body(...)):
    return await _handle_cs2_gsi_payload(token, payload)


@router.post('/api/cs2/gsi/{token}/')
async def api_cs2_gsi_slash(token: str, payload: dict[str, Any] = Body(...)):
    return await _handle_cs2_gsi_payload(token, payload)


@router.get('/install')
async def install_dota_gsi_pairing():
    return Response(content=_build_gsi_pairing_install_script(), media_type='text/plain; charset=utf-8')


@router.get('/install/gsi/authorize', response_class=HTMLResponse)
async def authorize_dota_gsi_install(request: Request, code: str = ''):
    normalized_code = _normalize_gsi_install_code(code)
    if not normalized_code:
        raise HTTPException(status_code=400, detail='Invalid install code')

    current_user = get_current_user(request)
    if not current_user:
        return_to = '/install/gsi/authorize?' + urlencode({'code': normalized_code})
        return RedirectResponse('/auth/twitch/login?' + urlencode({'return_to': return_to}), status_code=302)

    owner_user = await get_active_channel_user(request, current_user)
    settings_row = ensure_user_auto_bet_gsi_token(int(owner_user['id']))
    token = str(settings_row.get('gsi_token') or '').strip()
    now = time.time()
    _prune_gsi_install_sessions(now)
    GSI_INSTALL_SESSIONS[normalized_code] = {
        'token': token,
        'user_id': int(owner_user['id']),
        'login': owner_user.get('login') or owner_user.get('display_name') or '',
        'created_at': now,
        'expires_at': now + GSI_INSTALL_SESSION_TTL_SECONDS,
    }
    _log_user_action(
        request,
        owner_user,
        action='autobet.gsi.authorize',
        title='Подключение игры подтверждено',
        detail='Разовая установка для игры подтверждена через браузер.',
    )
    login = escape(str(owner_user.get('display_name') or owner_user.get('login') or 'канал'))
    install_script_url = f'{settings.app_public_base_url.rstrip("/")}/install/gsi/{token}.ps1'
    install_command = f'powershell -NoExit -Command "iwr -UseBasicParsing \'{install_script_url}\' | iex"'
    escaped_install_command = escape(install_command)
    escaped_install_script_url = escape(install_script_url)
    return HTMLResponse(
        f'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flaunt AutoBet</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f8fb; color: #111827; }}
    main {{ width: min(520px, calc(100vw - 32px)); border: 1px solid #e5e7eb; border-radius: 12px; background: white; padding: 28px; box-shadow: 0 16px 50px rgba(15, 23, 42, .08); }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    p {{ margin: 0; color: #4b5563; line-height: 1.55; }}
    .ok {{ display: inline-flex; align-items: center; gap: 8px; margin-bottom: 18px; color: #047857; font-weight: 700; }}
    .hint {{ margin-top: 18px; font-size: 14px; color: #6b7280; }}
    .actions {{ display: grid; gap: 12px; margin-top: 20px; }}
    .button {{ display: inline-flex; align-items: center; justify-content: center; min-height: 42px; border: 1px solid #111827; border-radius: 8px; background: #111827; color: white; text-decoration: none; font-weight: 600; padding: 0 16px; }}
    .button.secondary {{ background: white; color: #111827; }}
    .command {{ margin-top: 14px; padding: 12px 14px; background: #111827; color: #f9fafb; border-radius: 8px; font-size: 13px; line-height: 1.5; overflow-x: auto; }}
  </style>
</head>
<body>
  <main>
    <div class="ok">✓ Авторизация подтверждена</div>
    <h1>Flaunt AutoBet</h1>
    <p>Подключение привязано к каналу {login}. Если окно PowerShell не продолжило установку само, просто запусти команду ниже.</p>
    <div class="actions">
      <button class="button" type="button" onclick="navigator.clipboard.writeText(document.getElementById('install-command').innerText)">Скопировать команду</button>
      <a class="button secondary" href="{escaped_install_script_url}">Открыть файл установки</a>
    </div>
    <pre id="install-command" class="command">{escaped_install_command}</pre>
    <p class="hint">После запуска команды PowerShell продолжит установку, положит файлы для Dota 2 и CS2 и выведет результат в консоль.</p>
  </main>
</body>
</html>''',
        status_code=200,
    )


@router.get('/install/gsi/session/{code}')
async def dota_gsi_install_session(code: str):
    normalized_code = _normalize_gsi_install_code(code)
    if not normalized_code:
        raise HTTPException(status_code=400, detail='Invalid install code')
    now = time.time()
    _prune_gsi_install_sessions(now)
    session = GSI_INSTALL_SESSIONS.get(normalized_code)
    if not session:
        return {'status': 'pending'}
    if float(session.get('expires_at') or 0) <= now:
        GSI_INSTALL_SESSIONS.pop(normalized_code, None)
        return {'status': 'expired', 'authorized': False, 'install_script_url': ''}
    token = str(session.get('token') or '').strip()
    if not token:
        return {'status': 'pending', 'authorized': False, 'install_script_url': ''}
    return {
        'status': 'ready',
        'authorized': True,
        'install_script_url': f'{settings.app_public_base_url.rstrip("/")}/install/gsi/{token}.ps1',
        'login': session.get('login') or '',
    }


@router.get('/install/gsi/{token}.ps1')
async def install_dota_gsi(token: str):
    user = get_auto_bet_user_by_gsi_token(token)
    if not user:
        raise HTTPException(status_code=404, detail='Unknown GSI token')
    normalized_token = str(token or '').strip()
    endpoint_url = f'{settings.app_public_base_url.rstrip("/")}/api/dota/gsi/{normalized_token}'
    script = _build_gsi_install_script(endpoint_url, normalized_token)
    return Response(content=script, media_type='text/plain; charset=utf-8')


@router.get('/install/{token}')
async def install_dota_gsi_short(token: str):
    return await install_dota_gsi(token)


@router.post('/api/app/autobet/settings')
async def api_app_autobet_settings(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_channel_user(request)
    try:
        prediction_window_seconds = int(payload.get('prediction_window_seconds') or 120)
    except (TypeError, ValueError):
        prediction_window_seconds = 120
    try:
        auto_bet_runtime.update_settings(
            int(user['id']),
            dota2_enabled=bool(payload.get('dota2_enabled')),
            dota2_custom_questions_enabled=bool(payload.get('dota2_custom_questions_enabled')),
            dota2_custom_kills_enabled=bool(payload.get('dota2_custom_kills_enabled', True)),
            dota2_custom_deaths_enabled=bool(payload.get('dota2_custom_deaths_enabled', True)),
            dota2_custom_assists_enabled=bool(payload.get('dota2_custom_assists_enabled', True)),
            dota2_custom_duration_enabled=bool(payload.get('dota2_custom_duration_enabled', True)),
            dota2_custom_items_enabled=bool(payload.get('dota2_custom_items_enabled', False)),
            dota2_custom_hero_special_enabled=bool(payload.get('dota2_custom_hero_special_enabled', False)),
            cs2_enabled=bool(payload.get('cs2_enabled')),
            cs2_custom_questions_enabled=bool(payload.get('cs2_custom_questions_enabled')),
            cs2_custom_win_enabled=bool(payload.get('cs2_custom_win_enabled', True)),
            cs2_custom_kills_enabled=bool(payload.get('cs2_custom_kills_enabled', True)),
            cs2_custom_deaths_enabled=bool(payload.get('cs2_custom_deaths_enabled', True)),
            cs2_custom_assists_enabled=bool(payload.get('cs2_custom_assists_enabled', True)),
            prediction_window_seconds=prediction_window_seconds,
            prediction_title_template=str(payload.get('prediction_title_template') or ''),
        )
        _log_user_action(
            request,
            user,
            action='autobet.settings',
            title='Автоставка настроена',
            detail='Настройки Dota 2/CS2 обновлены.',
        )
        return await _build_auto_bet_payload(user)
    except Exception as exc:
        logger.exception('Failed to save auto-bet settings user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось сохранить автоставку. Попробуй ещё раз.')


@router.post('/api/app/autobet/resolve')
async def api_app_autobet_resolve(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_channel_user(request)
    result = str(payload.get('result') or '').strip().lower()
    try:
        await auto_bet_runtime.resolve_prediction(user, result)
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception('Failed to resolve auto-bet user=%s result=%s error=%s', user.get('id'), result, exc)
        return _json_result(ok=False, error='Не удалось закрыть ставку. Попробуй ещё раз.')
    title_by_result = {
        'win': 'Автоставка закрыта победой',
        'loss': 'Автоставка закрыта поражением',
        'cancel': 'Автоставка отменена',
    }
    try:
        _log_user_action(
            request,
            user,
            action='autobet.resolve',
            title=title_by_result.get(result, 'Автоставка закрыта'),
            detail='Prediction обновлён в Twitch.',
        )
        return await _build_auto_bet_payload(user)
    except Exception as exc:
        logger.exception('Failed to refresh auto-bet payload after resolve user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Ставка обновилась, но страницу не удалось обновить автоматически.')


@router.post('/api/app/autobet/manual')
async def api_app_autobet_manual(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_channel_user(request)
    try:
        prediction_window_seconds = int(payload.get('prediction_window_seconds') or 120)
    except (TypeError, ValueError):
        prediction_window_seconds = 120
    try:
        await auto_bet_runtime.open_manual_prediction(
            user,
            game_key=str(payload.get('game_key') or 'dota2'),
            title=str(payload.get('title') or ''),
            first_outcome_title=str(payload.get('first_outcome_title') or ''),
            second_outcome_title=str(payload.get('second_outcome_title') or ''),
            prediction_window_seconds=prediction_window_seconds,
        )
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception('Failed to open manual auto-bet prediction user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось открыть ставку. Попробуй ещё раз.')
    try:
        _log_user_action(
            request,
            user,
            action='autobet.manual',
            title='Автоставка открыта вручную',
            detail='Prediction создан в Twitch.',
        )
        return await _build_auto_bet_payload(user)
    except Exception as exc:
        logger.exception('Failed to refresh payload after manual auto-bet open user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Ставка создана, но не удалось обновить страницу автоматически.')


@router.post('/api/app/autobet/debug/dota/open')
async def api_app_autobet_debug_dota_open(request: Request, payload: dict[str, Any] = Body(...)):
    require_admin_user(request)
    user = await require_channel_user(request)
    try:
        result = await auto_bet_runtime.debug_open_dota_gsi_prediction(
            user,
            match_id=str(payload.get('match_id') or '').strip(),
            hero_id=int(payload.get('hero_id') or 14),
            hero_name=str(payload.get('hero_name') or 'Pudge'),
            kills=int(payload.get('kills') or 1),
            deaths=int(payload.get('deaths') or 0),
            assists=int(payload.get('assists') or 2),
            game_mode=str(payload.get('game_mode') or '22'),
            lobby_type=str(payload.get('lobby_type') or '7'),
            game_time=int(payload.get('game_time') or 75),
        )
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception('Failed to run Dota auto-bet debug open user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось выполнить debug-открытие Dota ставки.')
    _log_user_action(
        request,
        user,
        action='autobet.debug.dota.open',
        title='Debug Dota ставка открыта',
        detail=f'Debug-матч {result.get("match_id") or ""} отправлен в автоставку.',
    )
    return _json_result(**result)


@router.post('/api/app/autobet/debug/cs2/open')
async def api_app_autobet_debug_cs2_open(request: Request, payload: dict[str, Any] = Body(...)):
    require_admin_user(request)
    user = await require_channel_user(request)
    try:
        result = await auto_bet_runtime.debug_open_cs2_gsi_prediction(
            user,
            match_id=str(payload.get('match_id') or '').strip(),
            map_name=str(payload.get('map_name') or 'de_mirage'),
            mode=str(payload.get('mode') or 'premier'),
            round_number=int(payload.get('round') or 7),
            player_team=str(payload.get('player_team') or 'CT'),
            kills=int(payload.get('kills') or 8),
            deaths=int(payload.get('deaths') or 5),
            assists=int(payload.get('assists') or 2),
            ct_score=int(payload.get('ct_score') or 3),
            t_score=int(payload.get('t_score') or 4),
        )
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception('Failed to run CS2 auto-bet debug open user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось выполнить debug-открытие CS2 ставки.')
    _log_user_action(
        request,
        user,
        action='autobet.debug.cs2.open',
        title='Debug CS2 ставка открыта',
        detail=f'Debug-матч {result.get("match_id") or ""} отправлен в автоставку.',
    )
    return _json_result(**result)


@router.post('/api/app/autobet/debug/cs2/close')
async def api_app_autobet_debug_cs2_close(request: Request, payload: dict[str, Any] = Body(...)):
    require_admin_user(request)
    user = await require_channel_user(request)
    try:
        result = await auto_bet_runtime.debug_close_cs2_gsi_prediction(
            user,
            match_id=str(payload.get('match_id') or '').strip(),
            map_name=str(payload.get('map_name') or 'de_mirage'),
            mode=str(payload.get('mode') or 'premier'),
            round_number=int(payload.get('round') or 24),
            player_team=str(payload.get('player_team') or 'CT'),
            kills=int(payload.get('kills') or 18),
            deaths=int(payload.get('deaths') or 11),
            assists=int(payload.get('assists') or 6),
            ct_score=int(payload.get('ct_score') or 13),
            t_score=int(payload.get('t_score') or 10),
        )
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception as exc:
        logger.exception('Failed to run CS2 auto-bet debug close user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось выполнить debug-закрытие CS2 ставки.')
    _log_user_action(
        request,
        user,
        action='autobet.debug.cs2.close',
        title='Debug CS2 ставка закрыта',
        detail=f'Debug-матч {result.get("match_id") or ""} отправлен на закрытие.',
    )
    return _json_result(**result)


def _build_giveaway_payload(user: dict) -> dict[str, Any]:
    state = giveaway_runtime.payload(user)
    reward_id = str(state.get('points_reward_id') or '').strip()
    state['points_subscription_ready'] = (
        twitch_listener.is_points_redemption_subscription_active(int(user['id']), reward_id)
        if reward_id
        else False
    )
    return {
        'title': 'Розыгрыши',
        'user': {
            'id': int(user['id']),
            'twitch_user_id': user.get('twitch_user_id') or '',
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        'state': state,
    }


async def _random_org_integer(min_value: int, max_value: int) -> int:
    if max_value < min_value:
        raise ValueError('Invalid random range')
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            'https://www.random.org/integers/',
            params={
                'num': 1,
                'min': int(min_value),
                'max': int(max_value),
                'col': 1,
                'base': 10,
                'format': 'plain',
                'rnd': 'new',
            },
        )
    response.raise_for_status()
    return int(response.text.strip().splitlines()[0])


@router.get('/api/app/giveaways')
async def api_app_giveaways(request: Request):
    user = await require_giveaway_owner_user(request)
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/settings')
async def api_app_giveaways_settings(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_giveaway_owner_user(request)
    giveaway_runtime.update_settings(
        int(user['id']),
        giveaway_type=payload.get('giveaway_type') or 'active',
        keyword=payload.get('keyword') or '',
        chat_announcements=bool(payload.get('chat_announcements')),
        points_reward_title=payload.get('points_reward_title') or '',
        points_reward_cost=payload.get('points_reward_cost') or 100,
        points_allow_multiple_entries=bool(payload.get('points_allow_multiple_entries')),
        multipliers=payload.get('multipliers') if isinstance(payload.get('multipliers'), dict) else {},
    )
    _log_user_action(request, user, action='giveaway.settings', title='Розыгрыш настроен', detail='Настройки розыгрыша обновлены.')
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/toggle')
async def api_app_giveaways_toggle(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_giveaway_owner_user(request)
    owner_id = int(user['id'])
    running = bool(payload.get('running'))
    giveaway_state = giveaway_runtime.get_state(owner_id)
    if running and giveaway_state.giveaway_type == 'points':
        giveaway_runtime.set_running(owner_id, True)
        try:
            reward = await twitch_api.ensure_giveaway_points_reward_for_user(
                user,
                title=giveaway_state.points_reward_title,
                cost=giveaway_state.points_reward_cost,
            )
            giveaway_runtime.set_points_reward(owner_id, reward)
            subscribed = await twitch_listener.ensure_points_redemption_subscription(user, str(reward.get('id') or ''))
            if not subscribed:
                giveaway_runtime.set_running(owner_id, False)
                return _json_result(ok=False, error='EventSub сейчас не подключен. Сначала подключи бота к чату на дашборде, потом запусти розыгрыш за баллы.')
        except RuntimeError as exc:
            giveaway_runtime.set_running(owner_id, False)
            return _json_result(ok=False, error=str(exc))
        except httpx.HTTPStatusError as exc:
            giveaway_runtime.set_running(owner_id, False)
            try:
                scope_detail = await twitch_api._redemption_scope_error(user, 'подключить награду за баллы')
            except Exception:
                scope_detail = 'Не удалось проверить scopes токена.'
            detail = twitch_api._response_error_detail(exc.response)
            logger.warning(
                'Failed to prepare points giveaway reward user=%s status=%s body=%s',
                user.get('id'),
                exc.response.status_code,
                exc.response.text,
            )
            return _json_result(ok=False, error=f'Twitch не разрешил подключить награду за баллы. Код {exc.response.status_code}: {detail}. {scope_detail}')
        except httpx.HTTPError as exc:
            giveaway_runtime.set_running(owner_id, False)
            logger.warning('Failed to prepare points giveaway reward user=%s error=%s', user.get('id'), exc)
            return _json_result(ok=False, error='Twitch временно недоступен. Не удалось подключить награду за баллы.')
    else:
        giveaway_runtime.set_running(owner_id, running)
    _log_user_action(request, user, action='giveaway.toggle', title='Розыгрыш запущен' if running else 'Розыгрыш остановлен', detail='Сбор участников включён.' if running else 'Сбор участников остановлен.')
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/reward/toggle')
async def api_app_giveaways_reward_toggle(request: Request):
    user = await require_giveaway_owner_user(request)
    owner_id = int(user['id'])
    giveaway_state = giveaway_runtime.get_state(owner_id)
    reward_id = str(giveaway_state.points_reward_id or '').strip()

    if reward_id:
        try:
            await twitch_api.delete_custom_reward_for_user(user, reward_id)
        except RuntimeError as exc:
            return _json_result(ok=False, error=str(exc))
        except httpx.HTTPStatusError as exc:
            detail = twitch_api._response_error_detail(exc.response)
            logger.warning(
                'Failed to delete giveaway reward user=%s reward=%s status=%s body=%s',
                user.get('id'),
                reward_id,
                exc.response.status_code,
                exc.response.text,
            )
            return _json_result(ok=False, error=f'Twitch не удалил награду за баллы. Код {exc.response.status_code}: {detail}.')
        twitch_listener.cancel_points_redemption_subscription(owner_id, reward_id)
        giveaway_runtime.clear_points_reward(owner_id)
        _log_user_action(request, user, action='giveaway.reward.delete', title='Награда розыгрыша удалена', detail=f'Удалена награда за баллы: {giveaway_state.points_reward_title}.')
        return _build_giveaway_payload(user)

    try:
        reward = await twitch_api.ensure_giveaway_points_reward_for_user(
            user,
            title=giveaway_state.points_reward_title,
            cost=giveaway_state.points_reward_cost,
        )
    except RuntimeError as exc:
        return _json_result(ok=False, error=str(exc))
    except httpx.HTTPStatusError as exc:
        try:
            scope_detail = await twitch_api._redemption_scope_error(user, 'создать награду за баллы')
        except Exception:
            scope_detail = 'Не удалось проверить scopes токена.'
        detail = twitch_api._response_error_detail(exc.response)
        logger.warning(
            'Failed to create giveaway reward user=%s status=%s body=%s',
            user.get('id'),
            exc.response.status_code,
            exc.response.text,
        )
        return _json_result(ok=False, error=f'Twitch не создал награду за баллы. Код {exc.response.status_code}: {detail}. {scope_detail}')
    except httpx.HTTPError as exc:
        logger.warning('Failed to create giveaway reward user=%s error=%s', user.get('id'), exc)
        return _json_result(ok=False, error='Twitch временно недоступен. Не удалось создать награду за баллы.')

    giveaway_runtime.set_points_reward(owner_id, reward)
    try:
        await twitch_listener.ensure_points_redemption_subscription(user, str(reward.get('id') or ''))
    except Exception as exc:
        logger.warning('Failed to subscribe newly created giveaway reward user=%s reward=%s error=%s', user.get('id'), reward.get('id'), exc)
    _log_user_action(request, user, action='giveaway.reward.create', title='Награда розыгрыша создана', detail=f'Создана награда за баллы: {reward.get("title") or giveaway_state.points_reward_title}.')
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/wheel/spin')
async def api_app_giveaways_wheel_spin(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_giveaway_owner_user(request)
    owner_id = int(user['id'])
    mode = 'elimination' if str(payload.get('mode') or '').strip() == 'elimination' else 'normal'
    total_tickets = giveaway_runtime.wheel_total_tickets(owner_id, mode)
    if total_tickets <= 0:
        return _json_result(ok=False, error='В колесе пока нет участников.')
    try:
        ticket = await _random_org_integer(1, total_tickets)
    except Exception as exc:
        logger.warning('RANDOM.ORG did not return giveaway wheel result user=%s total=%s error=%s', user.get('id'), total_tickets, exc)
        return _json_result(ok=False, error='RANDOM.ORG не ответил. Попробуй крутить колесо ещё раз.')
    participant = giveaway_runtime.wheel_spin(owner_id, mode, ticket, 'RANDOM.ORG')
    if participant is None:
        return _json_result(ok=False, error='В колесе пока нет участников.')
    state = giveaway_runtime.get_state(owner_id)
    result_title = 'Лот выбывает' if mode == 'elimination' and state.winner_login != participant.login else 'Победитель выбран'
    _log_user_action(
        request,
        user,
        action='giveaway.wheel.spin',
        title=result_title,
        detail=f'Колесо RANDOM.ORG выбрало @{participant.login}.',
    )
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/roll')
async def api_app_giveaways_roll(request: Request):
    user = await require_giveaway_owner_user(request)
    winner = giveaway_runtime.roll(int(user['id']))
    if winner is None:
        return _json_result(ok=False, error='В розыгрыше пока нет участников.')
    giveaway_state = giveaway_runtime.get_state(int(user['id']))
    broadcaster_id = str(user.get('twitch_user_id') or '').strip()
    if giveaway_state.chat_announcements and broadcaster_id:
        try:
            await twitch_api.send_chat_message(f'Победитель в розыгрыше - @{winner.login}', broadcaster_id=broadcaster_id)
        except Exception as exc:
            logger.warning('Failed to announce giveaway winner user=%s winner=%s error=%s', user.get('id'), winner.login, exc)
    _log_user_action(request, user, action='giveaway.roll', title='Победитель выбран', detail=f'Победитель: @{winner.login}.')
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/participants/remove')
async def api_app_giveaways_remove_participant(request: Request, payload: dict[str, Any] = Body(...)):
    user = await require_giveaway_owner_user(request)
    login = str(payload.get('login') or '').strip().lower()
    if not login:
        raise HTTPException(status_code=400, detail='Не передан логин участника.')
    removed = giveaway_runtime.remove_participant(int(user['id']), login)
    _log_user_action(
        request,
        user,
        action='giveaway.participant.remove',
        title='Участник удалён из розыгрыша',
        detail=f'@{login} удалён из списка участников до очистки розыгрыша.' if removed else f'@{login} добавлен в исключения до очистки розыгрыша.',
    )
    return _build_giveaway_payload(user)


@router.post('/api/app/giveaways/clear')
async def api_app_giveaways_clear(request: Request):
    user = await require_giveaway_owner_user(request)
    giveaway_runtime.clear(int(user['id']))
    _log_user_action(request, user, action='giveaway.clear', title='Розыгрыш очищен', detail='Список участников и победитель очищены.')
    return _build_giveaway_payload(user)


@router.post('/api/app/timers')
async def api_app_timers_create(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    name = str(payload.get('name') or '').strip()
    if not name:
        return _json_result(ok=False, error='Укажи название таймера.')

    messages = _timer_payload_list(payload.get('messages'), max_items=5)
    commands = _timer_payload_list(payload.get('commands'), max_items=20, command_names=True)
    if not messages and not commands:
        return _json_result(ok=False, error='Добавь хотя бы одно сообщение или команду.')

    try:
        timer = create_user_timer(
            int(user['id']),
            name=name,
            enabled=bool(payload.get('enabled', True)),
            offline_enabled=bool(payload.get('offline_enabled', True)),
            online_enabled=bool(payload.get('online_enabled', True)),
            offline_interval_minutes=int(payload.get('offline_interval_minutes') or 60),
            online_interval_minutes=int(payload.get('online_interval_minutes') or 10),
            minimum_lines=int(payload.get('minimum_lines') or 0),
            commands=commands,
            messages=messages,
        )
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Проверь интервалы и минимум строк.')

    _log_user_action(request, user, action='timer.create', title='Таймер добавлен', detail=f'Добавлен таймер «{timer["name"]}».')
    return _json_result(saved=True, timers=_build_timers_payload(user)['timers'])


@router.post('/api/app/timers/update')
async def api_app_timers_update(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        timer_id = int(payload.get('timer_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный таймер.')

    existing = get_user_timer_by_id(int(user['id']), timer_id)
    if not existing:
        return _json_result(ok=False, error='Таймер не найден.')

    name = str(payload.get('name') or '').strip()
    if not name:
        return _json_result(ok=False, error='Укажи название таймера.')

    messages = _timer_payload_list(payload.get('messages'), max_items=5)
    commands = _timer_payload_list(payload.get('commands'), max_items=20, command_names=True)
    if not messages and not commands:
        return _json_result(ok=False, error='Добавь хотя бы одно сообщение или команду.')

    try:
        timer = update_user_timer(
            int(user['id']),
            timer_id,
            name=name,
            enabled=bool(payload.get('enabled', True)),
            offline_enabled=bool(payload.get('offline_enabled', True)),
            online_enabled=bool(payload.get('online_enabled', True)),
            offline_interval_minutes=int(payload.get('offline_interval_minutes') or 60),
            online_interval_minutes=int(payload.get('online_interval_minutes') or 10),
            minimum_lines=int(payload.get('minimum_lines') or 0),
            commands=commands,
            messages=messages,
        )
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Проверь интервалы и минимум строк.')

    _log_user_action(request, user, action='timer.update', title='Таймер обновлён', detail=f'Изменён таймер «{timer["name"] if timer else name}».')
    return _json_result(saved=True, timers=_build_timers_payload(user)['timers'])


@router.post('/api/app/timers/toggle')
async def api_app_timers_toggle(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        timer_id = int(payload.get('timer_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный таймер.')

    timer = get_user_timer_by_id(int(user['id']), timer_id)
    if not timer:
        return _json_result(ok=False, error='Таймер не найден.')

    enabled = bool(payload.get('enabled'))
    updated_timer = set_user_timer_enabled(int(user['id']), timer_id, enabled)
    _log_user_action(
        request,
        user,
        action='timer.toggle',
        title='Таймер обновлён',
        detail=f'Таймер «{timer["name"]}» теперь {"включён" if enabled else "отключён"}.',
    )
    return _json_result(saved=True, timer=_format_timer(updated_timer) if updated_timer else None, timers=_build_timers_payload(user)['timers'])


@router.post('/api/app/timers/delete')
async def api_app_timers_delete(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        timer_id = int(payload.get('timer_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный таймер.')

    timer = get_user_timer_by_id(int(user['id']), timer_id)
    if not timer:
        return _json_result(ok=False, error='Таймер не найден.')

    delete_user_timer(int(user['id']), timer_id)
    _log_user_action(request, user, action='timer.delete', title='Таймер удалён', detail=f'Удалён таймер «{timer["name"]}».')
    return _json_result(saved=True, timers=_build_timers_payload(user)['timers'])


@router.post('/api/app/dashboard/settings')
async def api_app_dashboard_settings(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    previous = {
        'answer_cooldown_seconds': float(user.get('answer_cooldown_seconds') or 2.5),
        'command_access': str(user.get('command_access') or 'moderators'),
        'overlay_theme': str(user.get('overlay_theme') or 'classic'),
        'turbo_mode': bool(user.get('turbo_mode', 0)),
        'quiz_passive_mode': bool(user.get('quiz_passive_mode', 0)),
        'quiet_mode': bool(user.get('quiet_mode', 0)),
        'chat_questions_enabled': bool(user.get('chat_questions_enabled', 0)),
        'chat_outcomes_enabled': bool(user.get('chat_correct_answers_enabled', 0) or user.get('chat_winners_enabled', 0)),
    }
    next_values = {
        'answer_cooldown_seconds': float(payload.get('answer_cooldown_seconds', user.get('answer_cooldown_seconds') or 2.5)),
        'command_access': str(payload.get('command_access') or user.get('command_access') or 'moderators'),
        'overlay_theme': str(payload.get('overlay_theme') or user.get('overlay_theme') or 'classic'),
        'turbo_mode': bool(payload.get('turbo_mode', False)),
        'quiz_passive_mode': bool(payload.get('quiz_passive_mode', False)),
        'quiet_mode': bool(payload.get('quiet_mode', False)),
        'chat_questions_enabled': bool(payload.get('chat_questions_enabled', False)),
        'chat_outcomes_enabled': bool(payload.get('chat_outcomes_enabled', False)),
    }
    error = _apply_dashboard_settings_update(
        user,
        answer_cooldown_seconds=next_values['answer_cooldown_seconds'],
        command_access=next_values['command_access'],
        overlay_theme=next_values['overlay_theme'],
        turbo_mode=next_values['turbo_mode'],
        quiz_passive_mode=next_values['quiz_passive_mode'],
        quiet_mode=next_values['quiet_mode'],
        chat_questions_enabled=next_values['chat_questions_enabled'],
        chat_outcomes_enabled=next_values['chat_outcomes_enabled'],
    )
    if error:
        return _json_result(ok=False, error=error)
    labels = {
        'answer_cooldown_seconds': 'КД ответа',
        'command_access': 'Доступ к командам',
        'overlay_theme': 'Дизайн overlay',
        'turbo_mode': 'Турбо режим',
        'quiz_passive_mode': 'Пассивный режим викторины',
        'quiet_mode': 'Тихий режим',
        'chat_questions_enabled': 'Дублирование вопросов',
        'chat_outcomes_enabled': 'Показ ответа',
    }
    changes = []
    for key, label in labels.items():
        if previous[key] != next_values[key]:
            before = 'включено' if previous[key] is True else 'выключено' if previous[key] is False else str(previous[key])
            after = 'включено' if next_values[key] is True else 'выключено' if next_values[key] is False else str(next_values[key])
            changes.append(f'{label}: {before} → {after}')
    _log_user_action(
        request,
        user,
        action='settings.update',
        title='Настройки викторины обновлены',
        detail='; '.join(changes) if changes else 'Настройки отправлены без изменений.',
    )
    return _json_result(saved=True)


@router.post('/api/app/dashboard/chat/activate')
async def api_app_dashboard_chat_activate(request: Request):
    user = await require_channel_user(request)
    warning = await _activate_chat_for_user(user)
    _log_user_action(request, user, action='bot.connect', title='Бот подключён', detail='Бот подключён к Twitch-чату.')
    return _json_result(saved=True, warning=warning)


@router.post('/api/app/dashboard/chat/moderator')
async def api_app_dashboard_chat_moderator(request: Request):
    user = await require_channel_user(request)
    try:
        warning = await twitch_api.add_bot_as_moderator_for_user(user)
    except Exception as exc:
        logger.exception('Failed to add bot as moderator for user %s: %s', user.get('id'), exc)
        return _json_result(ok=False, error='Не удалось сделать бота модератором. Попробуй еще раз через пару секунд.')
    bot_is_moderator = await _check_bot_moderator(user)
    if warning and not bot_is_moderator:
        return _json_result(ok=False, error=warning)
    if warning and bot_is_moderator:
        warning = ''
    activate_warning = await _activate_chat_for_user(user)
    _log_user_action(request, user, action='bot.moderator.add', title='Бот стал модератором', detail=f'Бот @{settings.twitch_bot_user_login or "bot"} добавлен в модераторы канала.')
    return _json_result(saved=True, warning=activate_warning or warning)


@router.post('/api/app/dashboard/chat/deactivate')
async def api_app_dashboard_chat_deactivate(request: Request):
    user = await require_channel_user(request)
    warning = await _deactivate_chat_for_user(user)
    _log_user_action(request, user, action='bot.disconnect', title='Бот отключён', detail='Бот отключён от чата, модератор снят при наличии доступа Twitch.')
    return _json_result(saved=True, warning=warning)


@router.post('/api/app/dashboard/questions/select')
async def api_app_dashboard_questions_select(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    selected_source = str(payload.get('selected_source') or '').strip()
    try:
        selected_id = None if selected_source in {'', 'standard'} else int(selected_source)
        _activate_question_source_for_user(user, selected_id)
    except (ValueError, TypeError) as exc:
        return _json_result(ok=False, error=str(exc))
    source_label = 'стандартная база' if selected_id is None else f'конфиг #{selected_id}'
    _log_user_action(request, user, action='quiz.config.select', title='Конфиг вопросов выбран', detail=f'Активирован источник вопросов: {source_label}.')
    return _json_result(saved=True)


@router.post('/api/app/dashboard/questions/delete')
async def api_app_dashboard_questions_delete(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        config_id = int(payload.get('config_id'))
        config = get_question_config_by_id(user['id'], config_id)
        if not config:
            raise ValueError('Конфиг не найден.')
        delete_user_question_config(user['id'], config_id)
        fallback_path = (get_web_user_by_id(user['id']) or user).get('questions_file') or ''
        runtime.get_game_by_broadcaster(
            user['twitch_user_id'],
            channel_name=user['login'],
            questions_path=fallback_path,
            answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
            turbo_mode=bool(user.get('turbo_mode', 0)),
            passive_mode=bool(user.get('quiz_passive_mode', 0)),
            quiet_mode=bool(user.get('quiet_mode', 0)),
            chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
        )
    except (ValueError, TypeError) as exc:
        return _json_result(ok=False, error=str(exc))
    _log_user_action(request, user, action='quiz.config.delete', title='Конфиг вопросов удалён', detail=f'Удалён конфиг: {config.get("name") or config_id}.')
    return _json_result(saved=True)


@router.post('/api/app/dashboard/questions/upload')
async def api_app_dashboard_questions_upload(
    request: Request,
    config_name: str = Form(''),
    questions_file: UploadFile = File(...),
):
    user = await require_channel_user(request)
    try:
        raw = await questions_file.read()
        config = add_user_question_config(user['id'], config_name, questions_file.filename or 'questions.json', raw)
        _activate_question_source_for_user(user, int(config['id']))
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception:
        logger.exception(
            'Failed to upload questions config user_id=%s filename=%s',
            user.get('id'),
            questions_file.filename,
        )
        return _json_result(ok=False, error='Не удалось загрузить конфиг вопросов. Попробуй ещё раз.')
    _log_user_action(request, user, action='quiz.config.upload', title='Конфиг вопросов добавлен', detail=f'Загружен конфиг: {config.get("name") or config_name or questions_file.filename}.')
    return _json_result(saved=True)


@router.get('/api/app/stats')
async def api_app_stats(request: Request):
    user = require_admin_user(request)
    stats_context = await _build_stats_context()
    return {
        'title': 'Статистика',
        'user': {
            'id': int(user['id']),
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        **stats_context,
    }


@router.get('/api/app/settings')
async def api_app_settings(request: Request):
    user = require_admin_user(request)
    settings_context = _build_admin_settings_context(user)
    return {
        'title': 'Настройки',
        'user': {
            'id': int(user['id']),
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        **settings_context,
    }


@router.post('/api/app/settings/global')
async def api_app_settings_global(request: Request, payload: dict[str, Any] = Body(...)):
    user = require_admin_user(request)
    current_ranges = _build_autobet_range_settings_payload()
    dota_ranges = payload.get('dota2_ranges') if isinstance(payload.get('dota2_ranges'), dict) else {}
    cs2_ranges = payload.get('cs2_ranges') if isinstance(payload.get('cs2_ranges'), dict) else {}
    updates = {
        'AUTOBET_REQUIRE_STREAM_ONLINE': 'true' if bool(payload.get('autobet_require_stream_online', True)) else 'false',
        'AUTOBET_DOTA_KILLS_MIN': str(_normalize_autobet_range(((dota_ranges.get('kills') or {}) if isinstance(dota_ranges.get('kills'), dict) else {}).get('min'), current_ranges['dota2']['kills']['min'])),
        'AUTOBET_DOTA_KILLS_MAX': str(_normalize_autobet_range(((dota_ranges.get('kills') or {}) if isinstance(dota_ranges.get('kills'), dict) else {}).get('max'), current_ranges['dota2']['kills']['max'])),
        'AUTOBET_DOTA_DEATHS_MIN': str(_normalize_autobet_range(((dota_ranges.get('deaths') or {}) if isinstance(dota_ranges.get('deaths'), dict) else {}).get('min'), current_ranges['dota2']['deaths']['min'])),
        'AUTOBET_DOTA_DEATHS_MAX': str(_normalize_autobet_range(((dota_ranges.get('deaths') or {}) if isinstance(dota_ranges.get('deaths'), dict) else {}).get('max'), current_ranges['dota2']['deaths']['max'])),
        'AUTOBET_DOTA_ASSISTS_MIN': str(_normalize_autobet_range(((dota_ranges.get('assists') or {}) if isinstance(dota_ranges.get('assists'), dict) else {}).get('min'), current_ranges['dota2']['assists']['min'])),
        'AUTOBET_DOTA_ASSISTS_MAX': str(_normalize_autobet_range(((dota_ranges.get('assists') or {}) if isinstance(dota_ranges.get('assists'), dict) else {}).get('max'), current_ranges['dota2']['assists']['max'])),
        'AUTOBET_DOTA_DURATION_MIN': str(_normalize_autobet_range(((dota_ranges.get('duration') or {}) if isinstance(dota_ranges.get('duration'), dict) else {}).get('min'), current_ranges['dota2']['duration']['min'], minimum=1, maximum=240)),
        'AUTOBET_DOTA_DURATION_MAX': str(_normalize_autobet_range(((dota_ranges.get('duration') or {}) if isinstance(dota_ranges.get('duration'), dict) else {}).get('max'), current_ranges['dota2']['duration']['max'], minimum=1, maximum=240)),
        'AUTOBET_CS2_KILLS_MIN': str(_normalize_autobet_range(((cs2_ranges.get('kills') or {}) if isinstance(cs2_ranges.get('kills'), dict) else {}).get('min'), current_ranges['cs2']['kills']['min'])),
        'AUTOBET_CS2_KILLS_MAX': str(_normalize_autobet_range(((cs2_ranges.get('kills') or {}) if isinstance(cs2_ranges.get('kills'), dict) else {}).get('max'), current_ranges['cs2']['kills']['max'])),
        'AUTOBET_CS2_DEATHS_MIN': str(_normalize_autobet_range(((cs2_ranges.get('deaths') or {}) if isinstance(cs2_ranges.get('deaths'), dict) else {}).get('min'), current_ranges['cs2']['deaths']['min'])),
        'AUTOBET_CS2_DEATHS_MAX': str(_normalize_autobet_range(((cs2_ranges.get('deaths') or {}) if isinstance(cs2_ranges.get('deaths'), dict) else {}).get('max'), current_ranges['cs2']['deaths']['max'])),
        'AUTOBET_CS2_ASSISTS_MIN': str(_normalize_autobet_range(((cs2_ranges.get('assists') or {}) if isinstance(cs2_ranges.get('assists'), dict) else {}).get('min'), current_ranges['cs2']['assists']['min'])),
        'AUTOBET_CS2_ASSISTS_MAX': str(_normalize_autobet_range(((cs2_ranges.get('assists') or {}) if isinstance(cs2_ranges.get('assists'), dict) else {}).get('max'), current_ranges['cs2']['assists']['max'])),
    }
    persist_settings_env(updates)
    apply_runtime_settings(updates)
    set_app_settings(
        {
            APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE: bool(payload.get('quiz_passive_debug_allow_offline', False)),
        }
    )
    _log_user_action(
        request,
        user,
        action='admin.global_settings',
        title='Глобальные настройки обновлены',
        detail='Обновлены правила автоставок, debug-режим пассивной викторины и диапазоны кастомных вопросов.',
    )
    return _json_result(
        saved=True,
        global_settings={
            'autobet_require_stream_online': bool(settings.autobet_require_stream_online),
            'quiz_passive_debug_allow_offline': bool(get_app_setting(APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE, False)),
            'custom_market_ranges': _build_autobet_range_settings_payload(),
        },
    )


@router.post('/api/app/settings/question-presets/upload')
async def api_app_settings_question_presets_upload(
    request: Request,
    config_name: str = Form(''),
    questions_file: UploadFile = File(...),
):
    admin_user = require_admin_user(request)
    try:
        raw = await questions_file.read()
        preset = add_standard_question_preset(config_name, questions_file.filename or 'questions.json', raw)
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))
    except Exception:
        logger.exception(
            'Failed to upload standard questions preset admin_user_id=%s filename=%s',
            admin_user.get('id'),
            questions_file.filename,
        )
        return _json_result(ok=False, error='Не удалось загрузить стандартный конфиг.')

    _log_user_action(
        request,
        admin_user,
        action='admin.quiz.presets.upload',
        title='Стандартный конфиг загружен',
        detail=f'Загружен пресет {preset.get("file_name")}.',
    )
    return _json_result(saved=True, file_name=preset.get('file_name'))


@router.post('/api/app/settings/question-presets/distribute')
async def api_app_settings_question_presets_distribute(request: Request, payload: dict[str, Any] = Body(...)):
    admin_user = require_admin_user(request)
    selected_file_name = str(payload.get('file_name') or '').strip()
    presets = _list_standard_question_presets()
    selected_preset = next((item for item in presets if item['file_name'] == selected_file_name), None)
    if not selected_preset:
        return _json_result(ok=False, error='Стандартный конфиг не найден.')

    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    target_users = [
        user
        for user in list_web_users(active_only=False)
        if _normalize_login(user.get('login')) not in bot_logins
    ]

    added = 0
    skipped_existing = 0
    skipped_limit = 0
    failed = 0
    for target_user in target_users:
        user_configs = get_user_question_configs(int(target_user['id']))
        existing_sources = {(config.get('source_file_name') or '').strip().lower() for config in user_configs}
        if selected_preset['file_name'].strip().lower() in existing_sources:
            skipped_existing += 1
            continue
        try:
            add_user_question_config(
                int(target_user['id']),
                f'{selected_preset["name"]} (общий)',
                selected_preset['file_name'],
                b'[]',
                is_standard=True,
                source_file_name=selected_preset['file_name'],
                file_path_override=build_standard_question_preset_ref(selected_preset['file_name']),
            )
            added += 1
        except ValueError:
            skipped_limit += 1
        except Exception:
            failed += 1
            logger.exception(
                'Failed to distribute standard questions preset file=%s to user_id=%s',
                selected_preset['file_name'],
                target_user.get('id'),
            )

    detail = (
        f'Пресет: {selected_preset["name"]}. '
        f'Добавлено: {added}. '
        f'Уже был: {skipped_existing}. '
        f'Пропущено по лимиту: {skipped_limit}.'
    )
    if failed:
        detail += f' Ошибок: {failed}.'

    _log_user_action(
        request,
        admin_user,
        action='admin.quiz.presets.distribute',
        title='Стандартный конфиг раздан каналам',
        detail=detail,
    )
    return _json_result(
        saved=True,
        added=added,
        skipped_existing=skipped_existing,
        skipped_limit=skipped_limit,
        failed=failed,
        message=detail,
    )


@router.post('/api/app/settings/question-presets/delete')
async def api_app_settings_question_presets_delete(request: Request, payload: dict[str, Any] = Body(...)):
    admin_user = require_admin_user(request)
    selected_file_name = str(payload.get('file_name') or '').strip()
    if not selected_file_name:
        return _json_result(ok=False, error='Стандартный конфиг не найден.')
    try:
        result = remove_standard_question_preset(selected_file_name)
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))

    detail = f'Пресет {selected_file_name} удалён полностью. Отвязано у каналов: {result["deleted_links"]}.'
    _log_user_action(
        request,
        admin_user,
        action='admin.quiz.presets.delete',
        title='Стандартный конфиг удалён',
        detail=detail,
    )
    return _json_result(saved=True, deleted_links=result['deleted_links'], message=detail)


@router.post('/api/app/settings/question-presets/revoke')
async def api_app_settings_question_presets_revoke(request: Request, payload: dict[str, Any] = Body(...)):
    admin_user = require_admin_user(request)
    selected_file_name = str(payload.get('file_name') or '').strip()
    if not selected_file_name:
        return _json_result(ok=False, error='Стандартный конфиг не найден.')
    try:
        result = revoke_standard_question_preset_access(selected_file_name)
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))

    detail = f'Общий доступ к пресету {selected_file_name} отключён. Убрано у каналов: {result["deleted_links"]}.'
    _log_user_action(
        request,
        admin_user,
        action='admin.quiz.presets.revoke',
        title='Общий доступ к конфигу отключён',
        detail=detail,
    )
    return _json_result(saved=True, deleted_links=result['deleted_links'], message=detail)


def _normalize_custom_command_name(value: Any) -> str:
    command = str(value or '').strip().lower()
    if not command:
        raise ValueError('Укажи команду.')
    command = command.split()[0]
    if not command.startswith('!'):
        command = f'!{command}'
    if len(command) < 2:
        raise ValueError('Укажи команду после !.')
    if any(ch.isspace() for ch in command):
        raise ValueError('Команда не должна содержать пробелы.')
    return command


def _normalize_custom_command_roles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    roles: list[str] = []
    for item in value:
        role = str(item or '').strip().lower()
        if role in CUSTOM_COMMAND_ROLES and role not in roles:
            roles.append(role)
    return roles


def _normalize_custom_command_aliases(value: Any, command: str) -> list[str]:
    if not isinstance(value, list):
        return []
    aliases: list[str] = []
    for item in value:
        raw = str(item or '').strip()
        if not raw:
            continue
        alias = _normalize_custom_command_name(raw)
        if alias == command:
            continue
        if alias in MOD_COMMANDS:
            raise ValueError('Alias не может совпадать со стандартной командой.')
        if alias not in aliases:
            aliases.append(alias)
    return aliases[:20]


def _normalize_custom_command_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    keywords: list[str] = []
    for item in value:
        keyword = str(item or '').strip().lower().lstrip('!')
        if not keyword:
            continue
        if len(keyword) > 80:
            raise ValueError('Кейворд должен быть не длиннее 80 символов.')
        if keyword not in keywords:
            keywords.append(keyword)
    return keywords[:20]


def _stored_custom_command_roles(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return _normalize_custom_command_roles(parsed)


def _stored_custom_command_aliases(value: Any, command: str) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return _normalize_custom_command_aliases(parsed, command)


def _stored_custom_command_keywords(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return _normalize_custom_command_keywords(parsed)


@router.get('/api/app/commands')
async def api_app_commands(request: Request):
    user = await require_channel_user(request)
    return {
        'title': 'Команды',
        'user': {
            'id': int(user['id']),
            'login': user.get('login') or '',
            'display_name': user.get('display_name') or '',
        },
        'commands': get_user_commands(int(user['id'])),
    }


@router.post('/api/app/commands')
async def api_app_commands_create(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        command = _normalize_custom_command_name(payload.get('name'))
        if command in MOD_COMMANDS:
            return _json_result(ok=False, error='Стандартную команду нельзя создать повторно.')
        response_text = str(payload.get('response_text') or '').strip()
        if not response_text:
            return _json_result(ok=False, error='Укажи текст ответа.')
        if len(response_text) > 500:
            return _json_result(ok=False, error='Текст ответа должен быть не длиннее 500 символов.')
        existing = get_user_bot_command_by_name(int(user['id']), command)
        if existing:
            return _json_result(ok=False, error='Такая команда уже есть.')
        cooldown_seconds = max(0.0, float(payload.get('cooldown_seconds') or 0))
        allowed_roles = _normalize_custom_command_roles(payload.get('allowed_roles'))
        aliases = _normalize_custom_command_aliases(payload.get('aliases'), command)
        keywords = _normalize_custom_command_keywords(payload.get('keywords'))
    except (TypeError, ValueError) as exc:
        return _json_result(ok=False, error=str(exc))

    upsert_user_bot_command(
        int(user['id']),
        name=command,
        response_text=response_text,
        enabled=bool(payload.get('enabled', True)),
        cooldown_seconds=cooldown_seconds,
        allowed_roles=allowed_roles,
        aliases=aliases,
        keywords=keywords,
        is_builtin=False,
    )
    _log_user_action(request, user, action='command.create', title='Команда добавлена', detail=f'Добавлена команда {command}.')
    return _json_result(saved=True, commands=get_user_commands(int(user['id'])))


@router.post('/api/app/commands/update')
async def api_app_commands_update(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        command = _normalize_custom_command_name(payload.get('name'))
        existing = get_user_bot_command_by_name(int(user['id']), command)
        if not existing:
            return _json_result(ok=False, error='Команда не найдена.')
        if bool(existing.get('is_builtin')) or command in MOD_COMMANDS:
            return _json_result(ok=False, error='Стандартные команды можно только отключить.')
        response_text = str(payload.get('response_text') or '').strip()
        if not response_text:
            return _json_result(ok=False, error='Укажи текст ответа.')
        if len(response_text) > 500:
            return _json_result(ok=False, error='Текст ответа должен быть не длиннее 500 символов.')
        cooldown_seconds = max(0.0, float(payload.get('cooldown_seconds') or 0))
        allowed_roles = _normalize_custom_command_roles(payload.get('allowed_roles'))
        aliases = _normalize_custom_command_aliases(payload.get('aliases'), command)
        keywords = _normalize_custom_command_keywords(payload.get('keywords'))
    except (TypeError, ValueError) as exc:
        return _json_result(ok=False, error=str(exc))

    upsert_user_bot_command(
        int(user['id']),
        name=command,
        response_text=response_text,
        enabled=bool(payload.get('enabled', True)),
        cooldown_seconds=cooldown_seconds,
        allowed_roles=allowed_roles,
        aliases=aliases,
        keywords=keywords,
        is_builtin=False,
    )
    _log_user_action(request, user, action='command.update', title='Команда обновлена', detail=f'Изменена команда {command}.')
    return _json_result(saved=True, commands=get_user_commands(int(user['id'])))


@router.post('/api/app/commands/toggle')
async def api_app_commands_toggle(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        command = _normalize_custom_command_name(payload.get('name'))
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))

    existing = get_user_bot_command_by_name(int(user['id']), command)
    if command in MOD_COMMANDS:
        upsert_user_bot_command(
            int(user['id']),
            name=command,
            response_text='',
            enabled=bool(payload.get('enabled')),
            cooldown_seconds=float(existing.get('cooldown_seconds') or 0) if existing else 0,
            allowed_roles=[],
            aliases=[],
            keywords=[],
            is_builtin=True,
        )
    elif existing and not bool(existing.get('is_builtin')):
        upsert_user_bot_command(
            int(user['id']),
            name=command,
            response_text=str(existing.get('response_text') or ''),
            enabled=bool(payload.get('enabled')),
            cooldown_seconds=float(existing.get('cooldown_seconds') or 0),
            allowed_roles=_stored_custom_command_roles(existing.get('allowed_roles')),
            aliases=_stored_custom_command_aliases(existing.get('aliases'), command),
            keywords=_stored_custom_command_keywords(existing.get('keywords')),
            is_builtin=False,
        )
    else:
        return _json_result(ok=False, error='Команда не найдена.')
    enabled = bool(payload.get('enabled'))
    _log_user_action(
        request,
        user,
        action='command.enable' if enabled else 'command.disable',
        title='Команда включена' if enabled else 'Команда отключена',
        detail=f'{command} теперь {"включена" if enabled else "отключена"}.',
    )
    return _json_result(saved=True, commands=get_user_commands(int(user['id'])))


@router.post('/api/app/commands/toggle-all')
async def api_app_commands_toggle_all(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    enabled = bool(payload.get('enabled'))
    group = str(payload.get('group') or 'builtin').strip().lower()
    user_id = int(user['id'])

    for command in get_user_commands(user_id):
        name = str(command.get('name') or '').strip().lower()
        if not name:
            continue
        is_builtin = bool(command.get('is_builtin'))
        if group == 'builtin' and not is_builtin:
            continue
        if group == 'custom' and is_builtin:
            continue
        upsert_user_bot_command(
            user_id,
            name=name,
            response_text=str(command.get('response_text') or ''),
            enabled=enabled,
            cooldown_seconds=float(command.get('cooldown_seconds') or 0),
            allowed_roles=list(command.get('allowed_roles') or []),
            aliases=list(command.get('aliases') or []),
            keywords=list(command.get('keywords') or []),
            is_builtin=is_builtin,
        )

    group_label = 'Команды викторины' if group == 'builtin' else 'Кастомные команды' if group == 'custom' else 'Все команды'
    _log_user_action(
        request,
        user,
        action='command.group.enable' if enabled else 'command.group.disable',
        title=f'{group_label} включены' if enabled else f'{group_label} отключены',
        detail=f'{group_label} включены группой.' if enabled else f'{group_label} отключены группой.',
    )
    return _json_result(saved=True, commands=get_user_commands(user_id))


@router.post('/api/app/commands/delete')
async def api_app_commands_delete(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    user = await require_channel_user(request)
    try:
        command = _normalize_custom_command_name(payload.get('name'))
    except ValueError as exc:
        return _json_result(ok=False, error=str(exc))

    existing = get_user_bot_command_by_name(int(user['id']), command)
    if not existing:
        return _json_result(ok=False, error='Команда не найдена.')
    if bool(existing.get('is_builtin')) or command in MOD_COMMANDS:
        return _json_result(ok=False, error='Стандартные команды можно только отключить.')

    delete_user_bot_command(int(user['id']), int(existing['id']))
    _log_user_action(request, user, action='command.delete', title='Команда удалена', detail=f'Удалена команда {command}.')
    return _json_result(saved=True, commands=get_user_commands(int(user['id'])))


@router.post('/api/app/settings/admins/grant')
async def api_app_settings_admins_grant(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    current_user = require_admin_user(request)
    try:
        user_id = int(payload.get('user_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный пользователь.')

    target_user = get_web_user_by_id(user_id)
    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    if not target_user:
        return _json_result(ok=False, error='Пользователь не найден.')
    if _normalize_login(target_user.get('login')) in bot_logins:
        return _json_result(ok=False, error='Бот-аккаунт нельзя назначить администратором.')
    if _is_admin_user(target_user):
        return _json_result(ok=False, error='Этот пользователь уже администратор.')

    set_web_user_admin(user_id, True)
    if int(current_user['id']) == int(user_id):
        current_user['is_admin'] = 1
    _log_user_action(request, current_user, action='admin.grant', title='Админка выдана', detail=f'Пользователь @{target_user.get("login") or user_id} получил админку.')
    _log_user_action(request, target_user, action='admin.grant.received', title='Админка получена', detail=f'Доступ выдал @{current_user.get("login") or current_user.get("id")}.')
    return _json_result(saved=True)


@router.post('/api/app/settings/admins/revoke')
async def api_app_settings_admins_revoke(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    current_user = require_admin_user(request)
    try:
        user_id = int(payload.get('user_id'))
    except (TypeError, ValueError):
        return _json_result(ok=False, error='Некорректный пользователь.')

    if int(current_user['id']) == user_id:
        return _json_result(ok=False, error='Нельзя забрать админку у самого себя.')

    target_user = get_web_user_by_id(user_id)
    bot_logins = {
        'quuuizbot',
        _normalize_login(settings.twitch_bot_user_login),
    }
    if not target_user:
        return _json_result(ok=False, error='Пользователь не найден.')
    if _normalize_login(target_user.get('login')) in bot_logins:
        return _json_result(ok=False, error='Бот-аккаунт нельзя менять через админ-панель.')
    if not _is_admin_user(target_user):
        return _json_result(ok=False, error='У этого пользователя уже нет админки.')

    set_web_user_admin(user_id, False)
    _log_user_action(request, current_user, action='admin.revoke', title='Админка забрана', detail=f'У пользователя @{target_user.get("login") or user_id} забрали админку.')
    _log_user_action(request, target_user, action='admin.revoke.received', title='Админка снята', detail=f'Доступ забрал @{current_user.get("login") or current_user.get("id")}.')
    return _json_result(saved=True)


@router.get('/dashboard/questions/template')
async def download_template():
    payload = json.dumps(get_template_questions(), ensure_ascii=False, indent=2)
    headers = {'Content-Disposition': 'attachment; filename="questions-template.json"'}
    return Response(content=payload, media_type='application/json; charset=utf-8', headers=headers)


@router.get('/u/{overlay_slug}/overlay', response_class=HTMLResponse)
async def user_overlay_page(request: Request, overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    preview_theme = (request.query_params.get('preview_theme') or '').strip().lower()
    preview_theme_values = {item['value'] for item in OVERLAY_THEME_OPTIONS}
    overlay_theme = preview_theme if preview_theme in preview_theme_values else (user.get('overlay_theme') or 'classic')
    overlay_preview = request.query_params.get('preview') == '1'
    runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=user.get('questions_file') or '',
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        turbo_mode=bool(user.get('turbo_mode', 0)),
        passive_mode=bool(user.get('quiz_passive_mode', 0)),
        quiet_mode=bool(user.get('quiet_mode', 0)),
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )
    return templates.TemplateResponse(
        'overlay_page.html',
        {
            'request': request,
            'title': f'Overlay {user["display_name"]}',
            'site_css_url': build_site_css_url(),
            'overlay_slug': overlay_slug,
            'overlay_theme': overlay_theme,
            'overlay_preview': overlay_preview,
            'overlay_state_url': f'/api/u/{overlay_slug}/state',
            'overlay_ws_url': f'/ws/u/{overlay_slug}',
            'asset_version': _overlay_asset_version('app.js'),
        },
    )


@router.get('/u/{overlay_slug}/autobet-overlay', response_class=HTMLResponse)
async def user_autobet_overlay_page(request: Request, overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    response = templates.TemplateResponse(
        'autobet_overlay.html',
        {
            'request': request,
            'title': f'OBS ставки {user["display_name"]}',
            'overlay_slug': overlay_slug,
            'autobet_state_url': f'/api/u/{overlay_slug}/autobet-overlay',
            'asset_version': _overlay_asset_version('autobet-overlay.js'),
        },
    )
    response.headers.setdefault('Cache-Control', 'no-store')
    return response


@router.get('/api/u/{overlay_slug}/state')
async def user_overlay_state(overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    user_game = runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=user.get('questions_file') or '',
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        turbo_mode=bool(user.get('turbo_mode', 0)),
        passive_mode=bool(user.get('quiz_passive_mode', 0)),
        quiet_mode=bool(user.get('quiet_mode', 0)),
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )
    state = user_game.get_public_state()
    state['channel_name'] = user['login']
    state['owner_display_name'] = user['display_name']
    state['overlay_slug'] = overlay_slug
    return state


@router.get('/api/u/{overlay_slug}/autobet-overlay')
async def user_autobet_overlay_state(overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    return await _build_public_autobet_overlay_payload(user, overlay_slug)
