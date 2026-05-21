import os
import threading
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / '.env'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_host: str = Field(default='127.0.0.1', alias='APP_HOST')
    app_port: int = Field(default=8000, alias='APP_PORT')
    app_name: str = Field(default='Twitch Guess Game MVP', alias='APP_NAME')
    debug: bool = Field(default=False, alias='DEBUG')
    app_public_base_url: str = Field(default='http://127.0.0.1:8000', alias='APP_PUBLIC_BASE_URL')
    session_secret: str = Field(default='change-me-session-secret', alias='SESSION_SECRET')
    answer_cooldown_seconds: float = Field(default=2.5, alias='ANSWER_COOLDOWN_SECONDS')

    twitch_client_id: str = Field(default='', alias='TWITCH_CLIENT_ID')
    twitch_client_secret: str = Field(default='', alias='TWITCH_CLIENT_SECRET')
    twitch_redirect_uri: str = Field(default='http://127.0.0.1:8000/auth/twitch/callback', alias='TWITCH_REDIRECT_URI')
    twitch_eventsub_secret: str = Field(default='change-me-twitch-eventsub-secret', alias='TWITCH_EVENTSUB_SECRET')
    twitch_bot_user_access_token: str = Field(default='', alias='TWITCH_BOT_USER_ACCESS_TOKEN')
    twitch_bot_user_refresh_token: str = Field(default='', alias='TWITCH_BOT_USER_REFRESH_TOKEN')
    twitch_broadcaster_id: str = Field(default='', alias='TWITCH_BROADCASTER_ID')
    twitch_bot_user_id: str = Field(default='', alias='TWITCH_BOT_USER_ID')
    twitch_bot_user_login: str = Field(default='', alias='TWITCH_BOT_USER_LOGIN')
    bot_auth_allowed_logins: str = Field(default='', alias='BOT_AUTH_ALLOWED_LOGINS')
    chatbot_badge_mode: bool = Field(default=False, alias='CHATBOT_BADGE_MODE')
    chatbot_chatters_list_mode: bool = Field(default=False, alias='CHATBOT_CHATTERS_LIST_MODE')
    twitch_channel_name: str = Field(default='', alias='TWITCH_CHANNEL_NAME')
    twitch_require_follower_only: bool = Field(default=False, alias='TWITCH_REQUIRE_FOLLOWER_ONLY')
    follower_cache_ttl: int = Field(default=300, alias='FOLLOWER_CACHE_TTL')
    moderator_cache_ttl: int = Field(default=5, alias='MODERATOR_CACHE_TTL')
    runtime_state_backend: str = Field(default='memory', alias='RUNTIME_STATE_BACKEND')
    runtime_state_namespace: str = Field(default='twitch_guess_game', alias='RUNTIME_STATE_NAMESPACE')
    runtime_state_redis_url: str = Field(default='', alias='RUNTIME_STATE_REDIS_URL')
    job_dispatcher_backend: str = Field(default='inline', alias='JOB_DISPATCHER_BACKEND')
    job_dispatcher_namespace: str = Field(default='twitch_guess_game', alias='JOB_DISPATCHER_NAMESPACE')
    autobet_require_stream_online: bool = Field(default=True, alias='AUTOBET_REQUIRE_STREAM_ONLINE')
    autobet_dota_kills_min: int = Field(default=5, alias='AUTOBET_DOTA_KILLS_MIN')
    autobet_dota_kills_max: int = Field(default=11, alias='AUTOBET_DOTA_KILLS_MAX')
    autobet_dota_deaths_min: int = Field(default=2, alias='AUTOBET_DOTA_DEATHS_MIN')
    autobet_dota_deaths_max: int = Field(default=8, alias='AUTOBET_DOTA_DEATHS_MAX')
    autobet_dota_assists_min: int = Field(default=7, alias='AUTOBET_DOTA_ASSISTS_MIN')
    autobet_dota_assists_max: int = Field(default=19, alias='AUTOBET_DOTA_ASSISTS_MAX')
    autobet_dota_duration_min: int = Field(default=29, alias='AUTOBET_DOTA_DURATION_MIN')
    autobet_dota_duration_max: int = Field(default=44, alias='AUTOBET_DOTA_DURATION_MAX')
    autobet_dota_pudge_flesh_heap_min: int = Field(default=7, alias='AUTOBET_DOTA_PUDGE_FLESH_HEAP_MIN')
    autobet_dota_pudge_flesh_heap_max: int = Field(default=19, alias='AUTOBET_DOTA_PUDGE_FLESH_HEAP_MAX')
    autobet_dota_legion_duel_min: int = Field(default=19, alias='AUTOBET_DOTA_LEGION_DUEL_MIN')
    autobet_dota_legion_duel_max: int = Field(default=79, alias='AUTOBET_DOTA_LEGION_DUEL_MAX')
    autobet_cs2_kills_min: int = Field(default=11, alias='AUTOBET_CS2_KILLS_MIN')
    autobet_cs2_kills_max: int = Field(default=23, alias='AUTOBET_CS2_KILLS_MAX')
    autobet_cs2_deaths_min: int = Field(default=9, alias='AUTOBET_CS2_DEATHS_MIN')
    autobet_cs2_deaths_max: int = Field(default=21, alias='AUTOBET_CS2_DEATHS_MAX')
    autobet_cs2_assists_min: int = Field(default=3, alias='AUTOBET_CS2_ASSISTS_MIN')
    autobet_cs2_assists_max: int = Field(default=11, alias='AUTOBET_CS2_ASSISTS_MAX')

    game_round_duration_seconds: int = Field(default=120, alias='GAME_ROUND_DURATION_SECONDS')
    game_reveal_interval_seconds: int = Field(default=30, alias='GAME_REVEAL_INTERVAL_SECONDS')
    game_base_score: int = Field(default=100, alias='GAME_BASE_SCORE')
    game_letter_penalty: int = Field(default=10, alias='GAME_LETTER_PENALTY')
    game_time_step_penalty: int = Field(default=5, alias='GAME_TIME_STEP_PENALTY')
    game_auto_next_delay_seconds: int = Field(default=8, alias='GAME_AUTO_NEXT_DELAY_SECONDS')

    db_path: str = Field(default=str(BASE_DIR / 'game.db'), alias='DB_PATH')
    questions_path: str = Field(default='', alias='QUESTIONS_PATH')
    questions_category: str = Field(default='', alias='QUESTIONS_CATEGORY')
    questions_path_main: str = Field(default='', alias='QUESTIONS_PATH_MAIN')
    questions_path_dota: str = Field(default='', alias='QUESTIONS_PATH_DOTA')
    user_questions_dir: str = Field(default=str(BASE_DIR / 'storage' / 'user_questions'), alias='USER_QUESTIONS_DIR')


settings = Settings()
_ENV_WRITE_LOCK = threading.Lock()


def persist_settings_env(updates: dict[str, str]) -> None:
    normalized_updates = {str(key): str(value) for key, value in updates.items()}
    with _ENV_WRITE_LOCK:
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding='utf-8').splitlines()
        else:
            lines = []

        updated_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in line:
                updated_lines.append(line)
                continue
            key, _, _ = line.partition('=')
            normalized_key = key.strip()
            if normalized_key in normalized_updates:
                updated_lines.append(f'{normalized_key}={normalized_updates[normalized_key]}')
                seen.add(normalized_key)
            else:
                updated_lines.append(line)

        for key, value in normalized_updates.items():
            if key not in seen:
                updated_lines.append(f'{key}={value}')

        tmp_file = ENV_FILE.with_name(f'{ENV_FILE.name}.tmp')
        payload = '\n'.join(updated_lines).rstrip() + '\n'
        try:
            tmp_file.write_text(payload, encoding='utf-8')
            os.replace(tmp_file, ENV_FILE)
        finally:
            if tmp_file.exists():
                tmp_file.unlink(missing_ok=True)


def apply_runtime_settings(updates: dict[str, str]) -> None:
    attribute_map = {
        'TWITCH_BOT_USER_ACCESS_TOKEN': 'twitch_bot_user_access_token',
        'TWITCH_BOT_USER_REFRESH_TOKEN': 'twitch_bot_user_refresh_token',
        'TWITCH_BOT_USER_ID': 'twitch_bot_user_id',
        'TWITCH_BOT_USER_LOGIN': 'twitch_bot_user_login',
        'CHATBOT_BADGE_MODE': 'chatbot_badge_mode',
        'CHATBOT_CHATTERS_LIST_MODE': 'chatbot_chatters_list_mode',
        'AUTOBET_REQUIRE_STREAM_ONLINE': 'autobet_require_stream_online',
        'AUTOBET_DOTA_KILLS_MIN': 'autobet_dota_kills_min',
        'AUTOBET_DOTA_KILLS_MAX': 'autobet_dota_kills_max',
        'AUTOBET_DOTA_DEATHS_MIN': 'autobet_dota_deaths_min',
        'AUTOBET_DOTA_DEATHS_MAX': 'autobet_dota_deaths_max',
        'AUTOBET_DOTA_ASSISTS_MIN': 'autobet_dota_assists_min',
        'AUTOBET_DOTA_ASSISTS_MAX': 'autobet_dota_assists_max',
        'AUTOBET_DOTA_DURATION_MIN': 'autobet_dota_duration_min',
        'AUTOBET_DOTA_DURATION_MAX': 'autobet_dota_duration_max',
        'AUTOBET_DOTA_PUDGE_FLESH_HEAP_MIN': 'autobet_dota_pudge_flesh_heap_min',
        'AUTOBET_DOTA_PUDGE_FLESH_HEAP_MAX': 'autobet_dota_pudge_flesh_heap_max',
        'AUTOBET_DOTA_LEGION_DUEL_MIN': 'autobet_dota_legion_duel_min',
        'AUTOBET_DOTA_LEGION_DUEL_MAX': 'autobet_dota_legion_duel_max',
        'AUTOBET_CS2_KILLS_MIN': 'autobet_cs2_kills_min',
        'AUTOBET_CS2_KILLS_MAX': 'autobet_cs2_kills_max',
        'AUTOBET_CS2_DEATHS_MIN': 'autobet_cs2_deaths_min',
        'AUTOBET_CS2_DEATHS_MAX': 'autobet_cs2_deaths_max',
        'AUTOBET_CS2_ASSISTS_MIN': 'autobet_cs2_assists_min',
        'AUTOBET_CS2_ASSISTS_MAX': 'autobet_cs2_assists_max',
    }
    for env_key, value in updates.items():
        attribute = attribute_map.get(env_key)
        if attribute:
            current_value = getattr(settings, attribute, '')
            if isinstance(current_value, bool):
                setattr(settings, attribute, str(value).strip().lower() in {'1', 'true', 'yes', 'on'})
            elif isinstance(current_value, int):
                try:
                    setattr(settings, attribute, int(str(value).strip()))
                except (TypeError, ValueError):
                    continue
            else:
                setattr(settings, attribute, str(value))
