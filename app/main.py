import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import init_db
from .auto_bets import auto_bet_runtime
from .game import game, runtime
from .job_dispatcher import job_dispatcher
from .service_metrics import service_metrics
from .timers import timer_runtime
from .twitch_chat_eventsub import twitch_listener as eventsub_listener
from .twitch_chat_webhook import twitch_webhook_listener
from .twitch_api import twitch_api
from .web_db import init_web_db
from .web_db import get_web_user_by_overlay_slug
from .web_site_presence import router as web_router


BASE_DIR = Path(__file__).resolve().parent.parent
OVERLAY_DIR = BASE_DIR / 'overlay'
SITE_STATIC_DIR = BASE_DIR / 'site_static'
FRONTEND_DIST_DIR = BASE_DIR / 'frontend' / 'dist'
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / 'assets'


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.debug:
        logging.basicConfig(level=logging.INFO)
    service_metrics.increment('app.starts')
    init_db()
    init_web_db()
    await twitch_api.resolve_missing_ids()
    try:
        await twitch_webhook_listener.sync_enabled_channels()
    except Exception as exc:
        logging.getLogger(__name__).warning('Unable to sync Twitch webhook chat subscriptions on startup: %s', exc)
    twitch_task = asyncio.create_task(eventsub_listener.run_forever())
    ticker_task = asyncio.create_task(_run_runtime_ticker())
    yield
    twitch_task.cancel()
    ticker_task.cancel()
    await twitch_api.close()


async def _run_runtime_ticker() -> None:
    try:
        while True:
            await asyncio.sleep(1)
            service_metrics.heartbeat('runtime_ticker')
            service_metrics.increment('runtime_ticker.loops')
            for job_name, handler in (
                ('runtime.tick', runtime.tick),
                ('timers.tick', timer_runtime.tick),
                ('autobet.tick', auto_bet_runtime.tick),
            ):
                started_at = asyncio.get_running_loop().time()
                try:
                    await job_dispatcher.dispatch(job_name, handler)
                except Exception as exc:
                    service_metrics.increment(f'{job_name}.failures')
                    service_metrics.record_error(job_name, str(exc))
                    service_metrics.record_check(job_name, 'down')
                    raise
                else:
                    duration_seconds = asyncio.get_running_loop().time() - started_at
                    service_metrics.increment(f'{job_name}.success')
                    service_metrics.observe_duration(job_name, duration_seconds)
                    check_state = 'warn' if duration_seconds >= 1.5 else 'up'
                    service_metrics.record_check(job_name, check_state)
            service_metrics.record_check('runtime_ticker', 'up')
    except asyncio.CancelledError:
        return


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=not settings.debug,
    same_site='lax',
)
app.add_middleware(GZipMiddleware, minimum_size=500)

_CANONICAL_BASE = urlsplit(settings.app_public_base_url.rstrip('/'))
_CANONICAL_HOST = _CANONICAL_BASE.netloc
_CANONICAL_SCHEME = _CANONICAL_BASE.scheme or 'https'


@app.middleware('http')
async def add_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith('/overlay/static/') or path.startswith('/site/static/'):
        response.headers.setdefault('Cache-Control', 'public, max-age=86400, immutable')
    elif (
        path.startswith('/api/')
        or path.startswith('/auth/')
        or path.startswith('/dashboard')
        or path.startswith('/quiz')
        or path.startswith('/stats')
        or path.startswith('/timers')
        or path.startswith('/autobet')
        or path.startswith('/admin')
        or path.startswith('/commands')
        or path.startswith('/giveaways')
        or path == '/'
    ):
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


@app.middleware('http')
async def redirect_to_canonical_host(request, call_next):
    if request.url.path == '/healthz':
        return await call_next(request)
    if _CANONICAL_HOST:
        forwarded_host = request.headers.get('x-forwarded-host')
        current_host = (forwarded_host or request.headers.get('host') or '').strip()
        forwarded_proto = request.headers.get('x-forwarded-proto')
        current_scheme = (forwarded_proto or request.url.scheme or '').strip()
        if current_host and (
            current_host.lower() != _CANONICAL_HOST.lower()
            or (current_scheme and current_scheme.lower() != _CANONICAL_SCHEME.lower())
        ):
            target = f'{settings.app_public_base_url.rstrip("/")}{request.url.path}'
            if request.url.query:
                target = f'{target}?{request.url.query}'
            return RedirectResponse(target, status_code=307)
    return await call_next(request)


app.mount('/overlay/static', StaticFiles(directory=OVERLAY_DIR), name='overlay-static')
if SITE_STATIC_DIR.exists():
    app.mount('/site/static', StaticFiles(directory=SITE_STATIC_DIR), name='site-static')
if FRONTEND_ASSETS_DIR.exists():
    app.mount('/app-static/assets', StaticFiles(directory=FRONTEND_ASSETS_DIR), name='app-static-assets')
app.include_router(web_router)


@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}


@app.post('/auth/twitch/eventsub/chat')
async def twitch_eventsub_chat_callback(request: Request):
    body = await request.body()
    message_id = str(request.headers.get('Twitch-Eventsub-Message-Id') or '')
    timestamp = str(request.headers.get('Twitch-Eventsub-Message-Timestamp') or '')
    signature = str(request.headers.get('Twitch-Eventsub-Message-Signature') or '')
    message_type = str(request.headers.get('Twitch-Eventsub-Message-Type') or '')

    if not twitch_webhook_listener.is_valid_signature(
        message_id=message_id,
        timestamp=timestamp,
        body=body,
        signature=signature,
    ):
        return Response(status_code=403)
    if not twitch_webhook_listener.is_fresh_message(timestamp):
        return Response(status_code=403)

    try:
        payload = json.loads(body.decode('utf-8') or '{}')
    except ValueError:
        return Response(status_code=400)

    if message_type == 'webhook_callback_verification':
        return PlainTextResponse(str(payload.get('challenge') or ''))
    if message_type == 'notification':
        await twitch_webhook_listener.handle_notification(payload, delivery_id=message_id)
        return Response(status_code=204)
    if message_type == 'revocation':
        await twitch_webhook_listener.handle_revocation(payload.get('subscription') or {})
        return Response(status_code=204)
    return Response(status_code=204)


@app.get('/overlay')
async def overlay_page():
    return FileResponse(OVERLAY_DIR / 'index.html')


@app.get('/api/state')
async def api_state():
    return game.get_public_state()


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await game.register_client(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        game.unregister_client(websocket)


@app.websocket('/ws/u/{overlay_slug}')
async def websocket_user_overlay(websocket: WebSocket, overlay_slug: str):
    user = get_web_user_by_overlay_slug(overlay_slug)
    if not user:
        await websocket.close(code=4404)
        return
    await websocket.accept()
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
    await user_game.register_client(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        user_game.unregister_client(websocket)
