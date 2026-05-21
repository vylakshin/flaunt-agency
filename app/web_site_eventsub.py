import json
import logging
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR, settings
from .game import runtime
from .twitch_api import twitch_api
from .twitch_chat_eventsub import twitch_listener
from .web_db import (
    add_user_question_config,
    delete_user_question_config,
    get_question_config_by_id,
    get_template_questions,
    get_user_question_configs,
    get_user_questions_preview_from_path,
    get_web_user_by_id,
    get_web_user_by_overlay_slug,
    set_web_user_bot_enabled,
    set_active_user_questions_config,
    update_web_user_tokens,
    update_web_user_settings,
    upsert_web_user,
)


templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))
router = APIRouter()
logger = logging.getLogger(__name__)

OVERLAY_THEME_OPTIONS = [
    {
        'value': 'classic',
        'label': 'Классический',
        'description': 'Текущий дизайн overlay с темной стеклянной карточкой.',
    },
    {
        'value': 'neo',
        'label': 'Новый',
        'description': 'Контрастный дизайн с более яркой подачей и переработанной композицией.',
    },
]

COMMAND_ACCESS_OPTIONS = [
    {'value': 'owner', 'label': 'Только я'},
    {'value': 'moderators', 'label': 'Я и модераторы'},
    {'value': 'everyone', 'label': 'Все пользователи'},
]


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


def build_overlay_url(slug: str) -> str:
    return f'{settings.app_public_base_url.rstrip("/")}/u/{slug}/overlay'


def _subscription_setup_warning(bot_login: str) -> str:
    return (
        f'Чат пока не удалось подключить автоматически. Убедись, что бот получил /mod {bot_login}, '
        'затем отвяжи приложение в Twitch Connections, войди заново через Twitch и нажми повторную активацию.'
    )


def _bot_not_moderator_text(bot_login: str) -> str:
    return f'Бот не подключен к чату. Выдай ему модератора командой /mod {bot_login} и затем нажми повторную активацию.'


def _subscription_warning(bot_login: str) -> str:
    return (
        f'Чат еще не подключен. Выдай боту модератора командой /mod {bot_login} '
        'и затем открой кабинет еще раз или нажми повторную активацию.'
    )


async def _activate_chat_for_user(user: dict) -> str:
    set_web_user_bot_enabled(int(user['id']), True)
    user['bot_enabled'] = 1
    try:
        await twitch_listener.ensure_channel_subscription(user['twitch_user_id'])
    except httpx.HTTPStatusError as exc:
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
    return ''


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


async def _check_bot_moderator(user: dict) -> bool:
    if not user or not bool(user.get('bot_enabled', 1)):
        return False
    if not user.get('access_token'):
        return False
    try:
        is_moderator = await twitch_api.is_bot_moderator_for_user(user, user['twitch_user_id'])
        if user.get('id') and user.get('access_token'):
            update_web_user_tokens(
                int(user['id']),
                str(user.get('access_token') or ''),
                str(user.get('refresh_token') or ''),
            )
        return is_moderator
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 401, 403} and user.get('id'):
            set_web_user_bot_enabled(int(user['id']), False)
            user['bot_enabled'] = 0
        return False
    except Exception:
        return False


def _apply_user_game_settings(user: dict) -> None:
    runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=user.get('questions_file') or settings.questions_path_main,
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        quiet_mode=False,
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )


@router.get('/', response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse('/dashboard', status_code=302)
    return templates.TemplateResponse(
        'home.html',
        {
            'request': request,
            'title': settings.app_name,
            'bot_login': settings.twitch_bot_user_login or 'your_bot',
        },
    )


@router.get('/auth/twitch/login')
async def twitch_login(request: Request):
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse('/dashboard', status_code=302)

    if not settings.twitch_client_id or not settings.twitch_redirect_uri:
        raise HTTPException(status_code=500, detail='Не настроены TWITCH_CLIENT_ID/TWITCH_REDIRECT_URI.')

    state = secrets.token_urlsafe(24)
    request.session['oauth_state'] = state
    query = urlencode(
        {
            'client_id': settings.twitch_client_id,
            'redirect_uri': settings.twitch_redirect_uri,
            'response_type': 'code',
            'scope': 'user:read:email channel:bot moderation:read',
            'state': state,
        }
    )
    return RedirectResponse(f'https://id.twitch.tv/oauth2/authorize?{query}', status_code=302)


@router.get('/auth/twitch/callback')
async def twitch_callback(request: Request, code: str = '', state: str = ''):
    expected_state = request.session.get('oauth_state')
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail='Неверный OAuth state.')
    if not code:
        raise HTTPException(status_code=400, detail='Twitch не вернул code.')

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
        access_token=token_data['access_token'],
        refresh_token=token_data.get('refresh_token') or '',
    )
    _apply_user_game_settings(user)
    request.session['user_id'] = user['id']
    request.session.pop('oauth_state', None)

    warning = await _activate_chat_for_user(user)
    return _redirect_dashboard(warning=warning)


@router.post('/logout')
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse('/', status_code=302)


@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request):
    user = require_user(request)
    configs = get_user_question_configs(user['id'])
    active_config_id = None
    for config in configs:
        config['is_active'] = config['file_path'] == (user.get('questions_file') or '')
        config['file_name'] = Path(config['file_path']).name
        if config['is_active']:
            active_config_id = config['id']

    bot_is_moderator = False
    if user.get('access_token'):
        try:
            bot_is_moderator = await twitch_api.is_bot_moderator_in_channel(
                user['access_token'],
                user['twitch_user_id'],
            )
        except Exception:
            bot_is_moderator = False

    chat_connected = twitch_listener.is_channel_connected(user['twitch_user_id']) and bot_is_moderator
    active_preview = get_user_questions_preview_from_path(user.get('questions_file') or '', limit=5)

    return templates.TemplateResponse(
        'dashboard.html',
        {
            'request': request,
            'title': 'Кабинет',
            'user': user,
            'chat_connected': chat_connected,
            'bot_is_moderator': bot_is_moderator,
            'chat_status_text': '' if chat_connected else _bot_not_moderator_text(
                settings.twitch_bot_user_login or 'your_bot'
            ),
            'bot_status_online_label': 'Бот модератор',
            'bot_status_offline_label': 'Бот не модератор',
            'overlay_url': build_overlay_url(user['overlay_slug']),
            'bot_login': settings.twitch_bot_user_login or 'your_bot',
            'chat_activate_button_text': 'Повторно активировать чат',
            'template_json': json.dumps(get_template_questions(), ensure_ascii=False, indent=2),
            'saved': request.query_params.get('saved') == '1',
            'error': request.query_params.get('error') or '',
            'warning': request.query_params.get('warning') or '',
            'configs': configs,
            'active_config_id': active_config_id,
            'active_preview': active_preview,
            'using_standard_config': not bool(user.get('questions_file')),
            'custom_limit_reached': len(configs) >= 3,
            'command_access_options': COMMAND_ACCESS_OPTIONS,
            'overlay_theme_options': OVERLAY_THEME_OPTIONS,
        },
    )


@router.post('/dashboard/settings')
async def update_dashboard_settings(
    request: Request,
    answer_cooldown_seconds: float = Form(...),
    command_access: str = Form(...),
    overlay_theme: str = Form('classic'),
    chat_questions_enabled: Optional[str] = Form(None),
    chat_correct_answers_enabled: Optional[str] = Form(None),
    chat_winners_enabled: Optional[str] = Form(None),
):
    user = require_user(request)
    normalized_command_access = (command_access or '').strip().lower()
    valid_access_values = {item['value'] for item in COMMAND_ACCESS_OPTIONS}
    if normalized_command_access not in valid_access_values:
        return _redirect_dashboard(error='Некорректный уровень доступа к командам.')
    normalized_overlay_theme = (overlay_theme or '').strip().lower()
    valid_overlay_themes = {item['value'] for item in OVERLAY_THEME_OPTIONS}
    if normalized_overlay_theme not in valid_overlay_themes:
        return _redirect_dashboard(error='Некорректный стиль overlay.')
    if answer_cooldown_seconds < 0 or answer_cooldown_seconds > 30:
        return _redirect_dashboard(error='Кулдаун ответа должен быть в диапазоне от 0 до 30 секунд.')

    normalized_chat_questions_enabled = (
        bool(user.get('chat_questions_enabled', 0))
        if chat_questions_enabled is None
        else chat_questions_enabled == '1'
    )
    normalized_chat_correct_answers_enabled = (
        bool(user.get('chat_correct_answers_enabled', 0))
        if chat_correct_answers_enabled is None
        else chat_correct_answers_enabled == '1'
    )
    normalized_chat_winners_enabled = (
        bool(user.get('chat_winners_enabled', 0))
        if chat_winners_enabled is None
        else chat_winners_enabled == '1'
    )

    update_web_user_settings(
        user['id'],
        answer_cooldown_seconds=round(float(answer_cooldown_seconds), 2),
        command_access=normalized_command_access,
        overlay_theme=normalized_overlay_theme,
        quiet_mode=False,
        chat_questions_enabled=normalized_chat_questions_enabled,
        chat_correct_answers_enabled=normalized_chat_correct_answers_enabled,
        chat_winners_enabled=normalized_chat_winners_enabled,
    )
    updated_user = get_web_user_by_id(user['id'])
    if updated_user:
        _apply_user_game_settings(updated_user)
    return _redirect_dashboard(saved=True)


@router.post('/dashboard/chat/activate')
async def activate_chat(request: Request):
    user = require_user(request)
    warning = await _activate_chat_for_user(user)
    return _redirect_dashboard(saved=True, warning=warning)


@router.post('/dashboard/questions/select')
async def select_questions_config(
    request: Request,
    selected_source: str = Form(''),
    source_type: str = Form(''),
    config_id: str = Form(''),
):
    user = require_user(request)
    try:
        if selected_source:
            selected_id = None if selected_source == 'standard' else int(selected_source)
        else:
            selected_id = None if source_type == 'standard' else int(config_id)
        selected_path = set_active_user_questions_config(user['id'], selected_id)
        runtime.get_game_by_broadcaster(
            user['twitch_user_id'],
            channel_name=user['login'],
            questions_path=selected_path or settings.questions_path_main,
            answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
            quiet_mode=False,
            chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
        )
    except (ValueError, TypeError) as exc:
        return _redirect_dashboard(error=str(exc))
    return _redirect_dashboard()


@router.get('/dashboard/questions/template')
async def download_template():
    payload = json.dumps(get_template_questions(), ensure_ascii=False, indent=2)
    headers = {'Content-Disposition': 'attachment; filename="questions-template.json"'}
    return Response(content=payload, media_type='application/json; charset=utf-8', headers=headers)


@router.post('/dashboard/questions/upload')
async def upload_questions(
    request: Request,
    config_name: str = Form(''),
    questions_file: UploadFile = File(...),
):
    user = require_user(request)
    try:
        raw = await questions_file.read()
        config = add_user_question_config(
            user['id'],
            config_name,
            questions_file.filename or 'questions.json',
            raw,
        )
        set_active_user_questions_config(user['id'], config['id'])
        runtime.get_game_by_broadcaster(
            user['twitch_user_id'],
            channel_name=user['login'],
            questions_path=config['file_path'],
            answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
            quiet_mode=False,
            chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
        )
    except ValueError as exc:
        return _redirect_dashboard(error=str(exc))
    return _redirect_dashboard(saved=True)


@router.post('/dashboard/questions/template-text')
async def save_questions_from_text(
    request: Request,
    config_name: str = Form(''),
    template_json: str = Form(...),
):
    user = require_user(request)
    try:
        config = add_user_question_config(
            user['id'],
            config_name,
            'questions-template.json',
            template_json.encode('utf-8'),
        )
        set_active_user_questions_config(user['id'], config['id'])
        runtime.get_game_by_broadcaster(
            user['twitch_user_id'],
            channel_name=user['login'],
            questions_path=config['file_path'],
            answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
            quiet_mode=False,
            chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
        )
    except ValueError as exc:
        return _redirect_dashboard(error=str(exc))
    return _redirect_dashboard(saved=True)


@router.post('/dashboard/questions/delete')
async def delete_questions_config(
    request: Request,
    config_id: int = Form(...),
):
    user = require_user(request)
    try:
        config = get_question_config_by_id(user['id'], config_id)
        if not config:
            raise ValueError('Конфиг не найден.')
        delete_user_question_config(user['id'], config_id)
        fallback_path = get_web_user_by_id(user['id']).get('questions_file') or settings.questions_path_main
        runtime.get_game_by_broadcaster(
            user['twitch_user_id'],
            channel_name=user['login'],
            questions_path=fallback_path,
            answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
            quiet_mode=False,
            chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
            chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
            chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
        )
    except ValueError as exc:
        return _redirect_dashboard(error=str(exc))
    return _redirect_dashboard(saved=True)


@router.get('/u/{overlay_slug}/overlay', response_class=HTMLResponse)
async def user_overlay_page(request: Request, overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=user.get('questions_file') or settings.questions_path_main,
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        quiet_mode=False,
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )
    return templates.TemplateResponse(
        'overlay_page.html',
        {
            'request': request,
            'title': f'Overlay {user["display_name"]}',
            'overlay_slug': overlay_slug,
            'overlay_theme': user.get('overlay_theme') or 'classic',
            'overlay_state_url': f'/api/u/{overlay_slug}/state',
            'overlay_ws_url': f'/ws/u/{overlay_slug}',
        },
    )


@router.get('/api/u/{overlay_slug}/state')
async def user_overlay_state(overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        raise HTTPException(status_code=404, detail='Overlay не найден.')
    user_game = runtime.get_game_by_broadcaster(
        user['twitch_user_id'],
        channel_name=user['login'],
        questions_path=user.get('questions_file') or settings.questions_path_main,
        answer_cooldown_seconds=user.get('answer_cooldown_seconds'),
        quiet_mode=False,
        chat_questions_enabled=bool(user.get('chat_questions_enabled', 0)),
        chat_correct_answers_enabled=bool(user.get('chat_correct_answers_enabled', 0)),
        chat_winners_enabled=bool(user.get('chat_winners_enabled', 0)),
    )
    state = user_game.get_public_state()
    state['channel_name'] = user['login']
    state['owner_display_name'] = user['display_name']
    state['overlay_slug'] = overlay_slug
    return state
