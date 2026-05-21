import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .config import BASE_DIR, settings
from .db import get_conn


def _resolve_user_questions_dir() -> Path:
    configured = Path(settings.user_questions_dir)
    legacy_dir = BASE_DIR / 'data' / 'user_questions'
    if configured == legacy_dir:
        return BASE_DIR / 'storage' / 'user_questions'
    return configured


USER_QUESTIONS_DIR = _resolve_user_questions_dir()
STANDARD_QUESTION_PRESETS_DIR = BASE_DIR / 'storage' / 'admin_question_presets'
MAX_USER_CONFIGS = 3
BUILTIN_STANDARD_QUESTION_PRESET_FILES: set[str] = set()
DB_QUESTION_PRESET_PREFIX = 'db-preset://'
DB_USER_QUESTION_CONFIG_PREFIX = 'db-user-config://'
APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE = 'quiz_passive_debug_allow_offline'
APP_SETTINGS_DEFAULTS: dict[str, Any] = {
    APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE: False,
}


def _json_string_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or '[]'))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item or '').strip()]


def _ensure_question_preset_storage() -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS question_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                content_json TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_by_user_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES web_users(id) ON DELETE SET NULL
            )
            '''
        )


def _ensure_app_settings_storage() -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL DEFAULT 'null',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )


def build_standard_question_preset_ref(slug: str) -> str:
    normalized_slug = Path(str(slug or '').strip()).name
    if not normalized_slug:
        raise ValueError('Стандартный конфиг не найден.')
    return f'{DB_QUESTION_PRESET_PREFIX}{normalized_slug}'


def is_standard_question_preset_ref(value: str) -> bool:
    return str(value or '').strip().lower().startswith(DB_QUESTION_PRESET_PREFIX)


def _standard_question_preset_slug_from_ref(value: str) -> str:
    raw = str(value or '').strip()
    if not is_standard_question_preset_ref(raw):
        return ''
    return Path(raw[len(DB_QUESTION_PRESET_PREFIX):]).name


def build_user_question_config_ref(config_id: int) -> str:
    try:
        normalized_id = int(config_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Конфиг не найден.') from exc
    if normalized_id <= 0:
        raise ValueError('Конфиг не найден.')
    return f'{DB_USER_QUESTION_CONFIG_PREFIX}{normalized_id}'


def is_user_question_config_ref(value: str) -> bool:
    return str(value or '').strip().lower().startswith(DB_USER_QUESTION_CONFIG_PREFIX)


def _user_question_config_id_from_ref(value: str) -> Optional[int]:
    raw = str(value or '').strip()
    if not is_user_question_config_ref(raw):
        return None
    try:
        return int(raw[len(DB_USER_QUESTION_CONFIG_PREFIX):])
    except (TypeError, ValueError):
        return None


def init_web_db() -> None:
    with sqlite3.connect(settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS web_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twitch_user_id TEXT NOT NULL UNIQUE,
                login TEXT NOT NULL,
                display_name TEXT NOT NULL,
                profile_image_url TEXT NOT NULL DEFAULT '',
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                overlay_slug TEXT NOT NULL UNIQUE,
                questions_file TEXT,
                answer_cooldown_seconds REAL NOT NULL DEFAULT 2.5,
                command_access TEXT NOT NULL DEFAULT 'moderators',
                overlay_theme TEXT NOT NULL DEFAULT 'classic',
                bot_enabled INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                turbo_mode INTEGER NOT NULL DEFAULT 0,
                quiz_passive_mode INTEGER NOT NULL DEFAULT 0,
                quiet_mode INTEGER NOT NULL DEFAULT 1,
                chat_questions_enabled INTEGER NOT NULL DEFAULT 0,
                chat_correct_answers_enabled INTEGER NOT NULL DEFAULT 0,
                chat_winners_enabled INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_question_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_json TEXT NOT NULL DEFAULT '[]',
                is_standard INTEGER NOT NULL DEFAULT 0,
                source_file_name TEXT NOT NULL DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS question_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                content_json TEXT NOT NULL,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_by_user_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(created_by_user_id) REFERENCES web_users(id) ON DELETE SET NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL DEFAULT 'null',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_bot_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                response_text TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                cooldown_seconds REAL NOT NULL DEFAULT 5,
                allowed_roles TEXT NOT NULL DEFAULT '[]',
                aliases TEXT NOT NULL DEFAULT '[]',
                keywords TEXT NOT NULL DEFAULT '[]',
                is_builtin INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, name),
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                actor_user_id INTEGER,
                action TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE,
                FOREIGN KEY(actor_user_id) REFERENCES web_users(id) ON DELETE SET NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                offline_enabled INTEGER NOT NULL DEFAULT 1,
                online_enabled INTEGER NOT NULL DEFAULT 1,
                offline_interval_minutes INTEGER NOT NULL DEFAULT 60,
                online_interval_minutes INTEGER NOT NULL DEFAULT 10,
                minimum_lines INTEGER NOT NULL DEFAULT 10,
                commands TEXT NOT NULL DEFAULT '[]',
                messages TEXT NOT NULL DEFAULT '[]',
                next_item_index INTEGER NOT NULL DEFAULT 0,
                line_count INTEGER NOT NULL DEFAULT 0,
                last_sent_at REAL NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_auto_bet_settings (
                user_id INTEGER PRIMARY KEY,
                dota2_enabled INTEGER NOT NULL DEFAULT 0,
                dota2_custom_questions_enabled INTEGER NOT NULL DEFAULT 0,
                dota2_custom_kills_enabled INTEGER NOT NULL DEFAULT 1,
                dota2_custom_deaths_enabled INTEGER NOT NULL DEFAULT 1,
                dota2_custom_assists_enabled INTEGER NOT NULL DEFAULT 1,
                dota2_custom_duration_enabled INTEGER NOT NULL DEFAULT 1,
                dota2_custom_items_enabled INTEGER NOT NULL DEFAULT 1,
                dota2_custom_hero_special_enabled INTEGER NOT NULL DEFAULT 1,
                cs2_enabled INTEGER NOT NULL DEFAULT 0,
                cs2_custom_questions_enabled INTEGER NOT NULL DEFAULT 0,
                cs2_custom_win_enabled INTEGER NOT NULL DEFAULT 1,
                cs2_custom_kills_enabled INTEGER NOT NULL DEFAULT 1,
                cs2_custom_deaths_enabled INTEGER NOT NULL DEFAULT 1,
                cs2_custom_assists_enabled INTEGER NOT NULL DEFAULT 1,
                prediction_window_seconds INTEGER NOT NULL DEFAULT 120,
                prediction_title_template TEXT NOT NULL DEFAULT 'Матч {game}: победа?',
                steam_id64 TEXT NOT NULL DEFAULT '',
                dota_account_id TEXT NOT NULL DEFAULT '',
                steam_linked_at REAL NOT NULL DEFAULT 0,
                gsi_token TEXT NOT NULL DEFAULT '',
                gsi_last_seen_at REAL NOT NULL DEFAULT 0,
                gsi_match_id TEXT NOT NULL DEFAULT '',
                gsi_game_state TEXT NOT NULL DEFAULT '',
                gsi_game_time INTEGER NOT NULL DEFAULT 0,
                gsi_hero_id INTEGER NOT NULL DEFAULT 0,
                gsi_hero_name TEXT NOT NULL DEFAULT '',
                gsi_kills INTEGER NOT NULL DEFAULT 0,
                gsi_deaths INTEGER NOT NULL DEFAULT 0,
                gsi_assists INTEGER NOT NULL DEFAULT 0,
                active_prediction_id TEXT NOT NULL DEFAULT '',
                active_game_key TEXT NOT NULL DEFAULT '',
                active_game_name TEXT NOT NULL DEFAULT '',
                active_prediction_title TEXT NOT NULL DEFAULT '',
                win_outcome_id TEXT NOT NULL DEFAULT '',
                loss_outcome_id TEXT NOT NULL DEFAULT '',
                win_outcome_title TEXT NOT NULL DEFAULT 'Победа',
                loss_outcome_title TEXT NOT NULL DEFAULT 'Поражение',
                last_opened_stream_signature TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                last_error_at REAL NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_auto_bet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prediction_id TEXT NOT NULL DEFAULT '',
                game_key TEXT NOT NULL DEFAULT '',
                game_name TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                outcome_title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                total_channel_points INTEGER NOT NULL DEFAULT 0,
                total_users INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
            '''
        )
        conn.commit()

    _migrate_web_user_settings()
    _migrate_legacy_question_files()
    _migrate_question_presets()
    _migrate_question_source_refs()
    _migrate_user_question_configs_to_db()


def _migrate_web_user_settings() -> None:
    with get_conn() as conn:
        columns = {
            row['name']
            for row in conn.execute("PRAGMA table_info(web_users)").fetchall()
        }
        if 'answer_cooldown_seconds' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN answer_cooldown_seconds REAL NOT NULL DEFAULT 2.5"
            )
        if 'command_access' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN command_access TEXT NOT NULL DEFAULT 'moderators'"
            )
        if 'overlay_theme' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN overlay_theme TEXT NOT NULL DEFAULT 'classic'"
            )
        if 'bot_enabled' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN bot_enabled INTEGER NOT NULL DEFAULT 1"
            )
        if 'is_admin' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )
        if 'turbo_mode' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN turbo_mode INTEGER NOT NULL DEFAULT 0"
            )
        if 'quiz_passive_mode' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN quiz_passive_mode INTEGER NOT NULL DEFAULT 0"
            )
        if 'quiet_mode' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN quiet_mode INTEGER NOT NULL DEFAULT 1"
            )
        if 'chat_questions_enabled' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN chat_questions_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if 'chat_correct_answers_enabled' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN chat_correct_answers_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if 'chat_winners_enabled' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN chat_winners_enabled INTEGER NOT NULL DEFAULT 0"
            )
        if 'profile_image_url' not in columns:
            conn.execute(
                "ALTER TABLE web_users ADD COLUMN profile_image_url TEXT NOT NULL DEFAULT ''"
            )

        question_config_columns = {
            row['name']
            for row in conn.execute("PRAGMA table_info(user_question_configs)").fetchall()
        }
        if question_config_columns and 'content_json' not in question_config_columns:
            conn.execute(
                "ALTER TABLE user_question_configs ADD COLUMN content_json TEXT NOT NULL DEFAULT '[]'"
            )
        if question_config_columns and 'is_standard' not in question_config_columns:
            conn.execute(
                "ALTER TABLE user_question_configs ADD COLUMN is_standard INTEGER NOT NULL DEFAULT 0"
            )
        if question_config_columns and 'source_file_name' not in question_config_columns:
            conn.execute(
                "ALTER TABLE user_question_configs ADD COLUMN source_file_name TEXT NOT NULL DEFAULT ''"
            )

        command_columns = {
            row['name']
            for row in conn.execute("PRAGMA table_info(user_bot_commands)").fetchall()
        }
        if command_columns and 'allowed_roles' not in command_columns:
            conn.execute(
                "ALTER TABLE user_bot_commands ADD COLUMN allowed_roles TEXT NOT NULL DEFAULT '[]'"
            )
        if command_columns and 'aliases' not in command_columns:
            conn.execute(
                "ALTER TABLE user_bot_commands ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]'"
            )
        if command_columns and 'keywords' not in command_columns:
            conn.execute(
                "ALTER TABLE user_bot_commands ADD COLUMN keywords TEXT NOT NULL DEFAULT '[]'"
            )

        auto_bet_columns = {
            row['name']
            for row in conn.execute("PRAGMA table_info(user_auto_bet_settings)").fetchall()
        }
        if auto_bet_columns and 'steam_id64' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN steam_id64 TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'dota_account_id' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN dota_account_id TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'steam_linked_at' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN steam_linked_at REAL NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'dota2_custom_questions_enabled' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN dota2_custom_questions_enabled INTEGER NOT NULL DEFAULT 0"
            )
        for custom_column in (
            'dota2_custom_kills_enabled',
            'dota2_custom_deaths_enabled',
            'dota2_custom_assists_enabled',
            'dota2_custom_duration_enabled',
            'dota2_custom_items_enabled',
            'dota2_custom_hero_special_enabled',
        ):
            if auto_bet_columns and custom_column not in auto_bet_columns:
                conn.execute(
                    f"ALTER TABLE user_auto_bet_settings ADD COLUMN {custom_column} INTEGER NOT NULL DEFAULT 1"
                )
        if auto_bet_columns and 'cs2_custom_questions_enabled' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN cs2_custom_questions_enabled INTEGER NOT NULL DEFAULT 0"
            )
        for custom_column in (
            'cs2_custom_win_enabled',
            'cs2_custom_kills_enabled',
            'cs2_custom_deaths_enabled',
            'cs2_custom_assists_enabled',
        ):
            if auto_bet_columns and custom_column not in auto_bet_columns:
                conn.execute(
                    f"ALTER TABLE user_auto_bet_settings ADD COLUMN {custom_column} INTEGER NOT NULL DEFAULT 1"
                )
        if auto_bet_columns and 'win_outcome_title' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN win_outcome_title TEXT NOT NULL DEFAULT 'Победа'"
            )
        if auto_bet_columns and 'loss_outcome_title' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN loss_outcome_title TEXT NOT NULL DEFAULT 'Поражение'"
            )
        if auto_bet_columns and 'gsi_token' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_token TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'gsi_last_seen_at' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_last_seen_at REAL NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'gsi_match_id' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_match_id TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'gsi_game_state' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_game_state TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'gsi_game_time' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_game_time INTEGER NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'gsi_hero_id' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_hero_id INTEGER NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'gsi_hero_name' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_hero_name TEXT NOT NULL DEFAULT ''"
            )
        if auto_bet_columns and 'gsi_kills' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_kills INTEGER NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'gsi_deaths' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_deaths INTEGER NOT NULL DEFAULT 0"
            )
        if auto_bet_columns and 'gsi_assists' not in auto_bet_columns:
            conn.execute(
                "ALTER TABLE user_auto_bet_settings ADD COLUMN gsi_assists INTEGER NOT NULL DEFAULT 0"
            )


def _migrate_legacy_question_files() -> None:
    with get_conn() as conn:
        users = conn.execute(
            'SELECT id, questions_file FROM web_users WHERE COALESCE(questions_file, "") != ""'
        ).fetchall()
        for user in users:
            if is_standard_question_preset_ref(str(user['questions_file'] or '')) or is_user_question_config_ref(str(user['questions_file'] or '')):
                continue
            existing = conn.execute(
                'SELECT id FROM user_question_configs WHERE user_id = ? AND file_path = ?',
                (user['id'], user['questions_file']),
            ).fetchone()
            if existing:
                continue
            count_row = conn.execute(
                'SELECT COUNT(*) AS cnt FROM user_question_configs WHERE user_id = ?',
                (user['id'],),
            ).fetchone()
            if int(count_row['cnt']) >= MAX_USER_CONFIGS:
                continue
            payload = '[]'
            legacy_path = Path(str(user['questions_file'] or '').strip())
            if legacy_path.exists():
                try:
                    payload = json.dumps(
                        _decode_questions_payload_from_text(legacy_path.read_text(encoding='utf-8')),
                        ensure_ascii=False,
                        indent=2,
                    )
                except OSError:
                    payload = '[]'
            conn.execute(
                'INSERT INTO user_question_configs(user_id, name, file_path, content_json) VALUES (?, ?, ?, ?)',
                (user['id'], f'Кастомный конфиг {int(count_row["cnt"]) + 1}', user['questions_file'], payload),
            )


def _user_from_row(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return dict(row) if row else None


def _config_from_row(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return dict(row) if row else None


def _generate_overlay_slug(login: str) -> str:
    normalized = ''.join(ch.lower() for ch in login if ch.isalnum()) or 'channel'
    return f'{normalized}-{secrets.token_hex(4)}'


def upsert_web_user(
    *,
    twitch_user_id: str,
    login: str,
    display_name: str,
    access_token: str,
    profile_image_url: str = '',
    refresh_token: str = '',
) -> dict[str, Any]:
    existing = get_web_user_by_twitch_id(twitch_user_id)
    overlay_slug = existing['overlay_slug'] if existing else _generate_overlay_slug(login)
    questions_file = existing['questions_file'] if existing else ''
    answer_cooldown_seconds = (
        existing['answer_cooldown_seconds'] if existing and existing.get('answer_cooldown_seconds') is not None else settings.answer_cooldown_seconds
    )
    command_access = (
        existing['command_access'] if existing and existing.get('command_access') else 'moderators'
    )
    overlay_theme = (
        existing['overlay_theme'] if existing and existing.get('overlay_theme') else 'classic'
    )
    bot_enabled = 1 if not existing else int(existing.get('bot_enabled', 1))
    is_admin = 0 if not existing else int(existing.get('is_admin', 0))
    turbo_mode = 0 if not existing else int(existing.get('turbo_mode', 0))
    quiz_passive_mode = 0 if not existing else int(existing.get('quiz_passive_mode', 0))
    quiet_mode = 1 if not existing else int(existing.get('quiet_mode', 1))
    chat_questions_enabled = 0 if not existing else int(existing.get('chat_questions_enabled', 0))
    chat_correct_answers_enabled = 0 if not existing else int(existing.get('chat_correct_answers_enabled', 0))
    chat_winners_enabled = 0 if not existing else int(existing.get('chat_winners_enabled', 0))

    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO web_users (
                twitch_user_id, login, display_name, profile_image_url, access_token, refresh_token, overlay_slug, questions_file,
                answer_cooldown_seconds, command_access, overlay_theme, bot_enabled, is_admin, turbo_mode, quiz_passive_mode, quiet_mode, chat_questions_enabled,
                chat_correct_answers_enabled, chat_winners_enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(twitch_user_id) DO UPDATE SET
                login = excluded.login,
                display_name = excluded.display_name,
                profile_image_url = CASE
                    WHEN excluded.profile_image_url != '' THEN excluded.profile_image_url
                    ELSE web_users.profile_image_url
                END,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                bot_enabled = 1,
                is_admin = CASE WHEN excluded.is_admin = 1 THEN 1 ELSE web_users.is_admin END,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (
                twitch_user_id,
                login,
                display_name,
                profile_image_url,
                access_token,
                refresh_token,
                overlay_slug,
                questions_file,
                answer_cooldown_seconds,
                command_access,
                overlay_theme,
                bot_enabled,
                is_admin,
                turbo_mode,
                quiz_passive_mode,
                quiet_mode,
                chat_questions_enabled,
                chat_correct_answers_enabled,
                chat_winners_enabled,
            ),
        )
        row = conn.execute('SELECT * FROM web_users WHERE twitch_user_id = ?', (twitch_user_id,)).fetchone()
    return dict(row)


def update_web_user_settings(
    user_id: int,
    *,
    answer_cooldown_seconds: float,
    command_access: str,
    overlay_theme: str,
    turbo_mode: bool,
    quiz_passive_mode: bool,
    quiet_mode: bool,
    chat_questions_enabled: bool,
    chat_correct_answers_enabled: bool,
    chat_winners_enabled: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET answer_cooldown_seconds = ?, command_access = ?, overlay_theme = ?, turbo_mode = ?, quiz_passive_mode = ?, quiet_mode = ?,
                chat_questions_enabled = ?, chat_correct_answers_enabled = ?, chat_winners_enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (
                answer_cooldown_seconds,
                command_access,
                overlay_theme,
                1 if turbo_mode else 0,
                1 if quiz_passive_mode else 0,
                1 if quiet_mode else 0,
                1 if chat_questions_enabled else 0,
                1 if chat_correct_answers_enabled else 0,
                1 if chat_winners_enabled else 0,
                user_id,
            ),
        )


def get_web_user_by_twitch_id(twitch_user_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM web_users WHERE twitch_user_id = ?', (twitch_user_id,)).fetchone()
    return _user_from_row(row)


def get_web_user_by_id(user_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM web_users WHERE id = ?', (user_id,)).fetchone()
    return _user_from_row(row)


def get_web_user_by_login(login: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM web_users WHERE lower(login) = lower(?)', (login,)).fetchone()
    return _user_from_row(row)


def get_web_user_by_overlay_slug(slug: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM web_users WHERE overlay_slug = ?', (slug,)).fetchone()
    return _user_from_row(row)


def list_web_users(*, active_only: bool = False) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                'SELECT * FROM web_users WHERE bot_enabled = 1 ORDER BY created_at ASC'
            ).fetchall()
        else:
            rows = conn.execute('SELECT * FROM web_users ORDER BY created_at ASC').fetchall()
    return [dict(row) for row in rows]


def update_web_user_tokens(user_id: int, access_token: str, refresh_token: str = '') -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET access_token = ?, refresh_token = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (access_token, refresh_token, user_id),
        )


def update_web_user_profile_image_url(user_id: int, profile_image_url: str) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET profile_image_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (profile_image_url, user_id),
        )


def set_web_user_bot_enabled(user_id: int, enabled: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET bot_enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (1 if enabled else 0, user_id),
        )


def set_web_user_bot_enabled_by_twitch_id(twitch_user_id: str, enabled: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET bot_enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE twitch_user_id = ?
            ''',
            (1 if enabled else 0, twitch_user_id),
        )


def set_web_user_admin(user_id: int, is_admin: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE web_users
            SET is_admin = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (1 if is_admin else 0, user_id),
        )


def list_user_bot_commands(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, user_id, name, response_text, enabled, cooldown_seconds, allowed_roles, aliases, keywords, is_builtin, created_at, updated_at
            FROM user_bot_commands
            WHERE user_id = ?
            ORDER BY is_builtin DESC, name ASC
            ''',
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_user_bot_command_by_name(user_id: int, name: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT id, user_id, name, response_text, enabled, cooldown_seconds, allowed_roles, aliases, keywords, is_builtin, created_at, updated_at
            FROM user_bot_commands
            WHERE user_id = ? AND name = ?
            ''',
            (user_id, name),
        ).fetchone()
    return dict(row) if row else None


def get_user_bot_command_by_id(user_id: int, command_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT id, user_id, name, response_text, enabled, cooldown_seconds, allowed_roles, aliases, keywords, is_builtin, created_at, updated_at
            FROM user_bot_commands
            WHERE user_id = ? AND id = ?
            ''',
            (user_id, command_id),
        ).fetchone()
    return dict(row) if row else None


def upsert_user_bot_command(
    user_id: int,
    *,
    name: str,
    response_text: str = '',
    enabled: bool = True,
    cooldown_seconds: float = 5,
    allowed_roles: Optional[list[str]] = None,
    aliases: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    is_builtin: bool = False,
) -> dict[str, Any]:
    normalized_name = name.strip().lower()
    if not normalized_name.startswith('!'):
        normalized_name = f'!{normalized_name}'

    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_bot_commands(user_id, name, response_text, enabled, cooldown_seconds, allowed_roles, aliases, keywords, is_builtin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET
                response_text = excluded.response_text,
                enabled = excluded.enabled,
                cooldown_seconds = excluded.cooldown_seconds,
                allowed_roles = excluded.allowed_roles,
                aliases = excluded.aliases,
                keywords = excluded.keywords,
                is_builtin = excluded.is_builtin,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (
                user_id,
                normalized_name,
                response_text.strip(),
                1 if enabled else 0,
                max(0.0, float(cooldown_seconds)),
                json.dumps(allowed_roles or [], ensure_ascii=False),
                json.dumps(aliases or [], ensure_ascii=False),
                json.dumps(keywords or [], ensure_ascii=False),
                1 if is_builtin else 0,
            ),
        )
        row = conn.execute(
            '''
            SELECT id, user_id, name, response_text, enabled, cooldown_seconds, allowed_roles, aliases, keywords, is_builtin, created_at, updated_at
            FROM user_bot_commands
            WHERE user_id = ? AND name = ?
            ''',
            (user_id, normalized_name),
        ).fetchone()
    return dict(row)


def set_user_bot_command_enabled(user_id: int, command_id: int, enabled: bool) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_bot_commands
            SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND id = ?
            ''',
            (1 if enabled else 0, user_id, command_id),
        )
    return get_user_bot_command_by_id(user_id, command_id)


def delete_user_bot_command(user_id: int, command_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            'DELETE FROM user_bot_commands WHERE user_id = ? AND id = ? AND is_builtin = 0',
            (user_id, command_id),
        )


def _timer_from_row(row: sqlite3.Row | dict[str, Any] | None) -> Optional[dict[str, Any]]:
    if not row:
        return None
    data = dict(row)
    data['commands'] = _json_string_list(data.get('commands'))
    data['messages'] = _json_string_list(data.get('messages'))
    return data


def list_user_timers(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT *
            FROM user_timers
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            ''',
            (user_id,),
        ).fetchall()
    return [timer for row in rows if (timer := _timer_from_row(row)) is not None]


def get_user_timer_by_id(user_id: int, timer_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM user_timers WHERE user_id = ? AND id = ?',
            (user_id, timer_id),
        ).fetchone()
    return _timer_from_row(row)


def create_user_timer(
    user_id: int,
    *,
    name: str,
    enabled: bool,
    offline_enabled: bool,
    online_enabled: bool,
    offline_interval_minutes: int,
    online_interval_minutes: int,
    minimum_lines: int,
    commands: Optional[list[str]] = None,
    messages: Optional[list[str]] = None,
) -> dict[str, Any]:
    normalized_commands = [item.strip().lower() for item in commands or [] if item.strip()]
    normalized_commands = [item if item.startswith('!') else f'!{item}' for item in normalized_commands]
    normalized_messages = [item.strip() for item in messages or [] if item.strip()][:5]
    with get_conn() as conn:
        cursor = conn.execute(
            '''
            INSERT INTO user_timers(
                user_id, name, enabled, offline_enabled, online_enabled,
                offline_interval_minutes, online_interval_minutes, minimum_lines,
                commands, messages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                user_id,
                name.strip(),
                1 if enabled else 0,
                1 if offline_enabled else 0,
                1 if online_enabled else 0,
                max(1, int(offline_interval_minutes)),
                max(1, int(online_interval_minutes)),
                max(0, int(minimum_lines)),
                json.dumps(normalized_commands, ensure_ascii=False),
                json.dumps(normalized_messages, ensure_ascii=False),
            ),
        )
        row = conn.execute('SELECT * FROM user_timers WHERE id = ?', (cursor.lastrowid,)).fetchone()
    timer = _timer_from_row(row)
    if timer is None:
        raise RuntimeError('Timer was not created.')
    return timer


def update_user_timer(
    user_id: int,
    timer_id: int,
    *,
    name: str,
    enabled: bool,
    offline_enabled: bool,
    online_enabled: bool,
    offline_interval_minutes: int,
    online_interval_minutes: int,
    minimum_lines: int,
    commands: Optional[list[str]] = None,
    messages: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    normalized_commands = [item.strip().lower() for item in commands or [] if item.strip()]
    normalized_commands = [item if item.startswith('!') else f'!{item}' for item in normalized_commands]
    normalized_messages = [item.strip() for item in messages or [] if item.strip()][:5]
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_timers
            SET name = ?, enabled = ?, offline_enabled = ?, online_enabled = ?,
                offline_interval_minutes = ?, online_interval_minutes = ?, minimum_lines = ?,
                commands = ?, messages = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND id = ?
            ''',
            (
                name.strip(),
                1 if enabled else 0,
                1 if offline_enabled else 0,
                1 if online_enabled else 0,
                max(1, int(offline_interval_minutes)),
                max(1, int(online_interval_minutes)),
                max(0, int(minimum_lines)),
                json.dumps(normalized_commands, ensure_ascii=False),
                json.dumps(normalized_messages, ensure_ascii=False),
                user_id,
                timer_id,
            ),
        )
    return get_user_timer_by_id(user_id, timer_id)


def set_user_timer_enabled(user_id: int, timer_id: int, enabled: bool) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_timers
            SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND id = ?
            ''',
            (1 if enabled else 0, user_id, timer_id),
        )
    return get_user_timer_by_id(user_id, timer_id)


def delete_user_timer(user_id: int, timer_id: int) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM user_timers WHERE user_id = ? AND id = ?', (user_id, timer_id))


def increment_user_timer_line_counts(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_timers
            SET line_count = line_count + 1
            WHERE user_id = ? AND enabled = 1
            ''',
            (user_id,),
        )


def mark_user_timer_sent(timer_id: int, *, next_item_index: int, sent_at: float) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_timers
            SET next_item_index = ?, line_count = 0, last_sent_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (max(0, int(next_item_index)), float(sent_at), timer_id),
        )


def _auto_bet_from_row(row: sqlite3.Row | dict[str, Any] | None, user_id: int) -> dict[str, Any]:
    if row:
        data = dict(row)
    else:
        data = {
            'user_id': user_id,
            'dota2_enabled': 0,
            'dota2_custom_questions_enabled': 0,
            'dota2_custom_kills_enabled': 1,
            'dota2_custom_deaths_enabled': 1,
            'dota2_custom_assists_enabled': 1,
            'dota2_custom_duration_enabled': 1,
            'dota2_custom_items_enabled': 1,
            'dota2_custom_hero_special_enabled': 1,
            'cs2_enabled': 0,
            'cs2_custom_questions_enabled': 0,
            'cs2_custom_win_enabled': 1,
            'cs2_custom_kills_enabled': 1,
            'cs2_custom_deaths_enabled': 1,
            'cs2_custom_assists_enabled': 1,
            'prediction_window_seconds': 120,
            'prediction_title_template': 'Матч {game}: победа?',
            'steam_id64': '',
            'dota_account_id': '',
            'steam_linked_at': 0,
            'gsi_token': '',
            'gsi_last_seen_at': 0,
            'gsi_match_id': '',
            'gsi_game_state': '',
            'gsi_game_time': 0,
            'gsi_hero_id': 0,
            'gsi_hero_name': '',
            'gsi_kills': 0,
            'gsi_deaths': 0,
            'gsi_assists': 0,
            'active_prediction_id': '',
            'active_game_key': '',
            'active_game_name': '',
            'active_prediction_title': '',
            'win_outcome_id': '',
            'loss_outcome_id': '',
            'win_outcome_title': 'Победа',
            'loss_outcome_title': 'Поражение',
            'last_opened_stream_signature': '',
            'last_error': '',
            'last_error_at': 0,
            'created_at': '',
            'updated_at': '',
        }
    data['dota2_enabled'] = bool(data.get('dota2_enabled', 0))
    data['dota2_custom_questions_enabled'] = bool(data.get('dota2_custom_questions_enabled', 0))
    data['dota2_custom_kills_enabled'] = bool(data.get('dota2_custom_kills_enabled', 1))
    data['dota2_custom_deaths_enabled'] = bool(data.get('dota2_custom_deaths_enabled', 1))
    data['dota2_custom_assists_enabled'] = bool(data.get('dota2_custom_assists_enabled', 1))
    data['dota2_custom_duration_enabled'] = bool(data.get('dota2_custom_duration_enabled', 1))
    data['dota2_custom_items_enabled'] = bool(data.get('dota2_custom_items_enabled', 1))
    data['dota2_custom_hero_special_enabled'] = bool(data.get('dota2_custom_hero_special_enabled', 1))
    data['cs2_enabled'] = bool(data.get('cs2_enabled', 0))
    data['cs2_custom_questions_enabled'] = bool(data.get('cs2_custom_questions_enabled', 0))
    data['cs2_custom_win_enabled'] = bool(data.get('cs2_custom_win_enabled', 1))
    data['cs2_custom_kills_enabled'] = bool(data.get('cs2_custom_kills_enabled', 1))
    data['cs2_custom_deaths_enabled'] = bool(data.get('cs2_custom_deaths_enabled', 1))
    data['cs2_custom_assists_enabled'] = bool(data.get('cs2_custom_assists_enabled', 1))
    data['prediction_window_seconds'] = int(data.get('prediction_window_seconds') or 120)
    data['last_error_at'] = float(data.get('last_error_at') or 0)
    data['steam_linked_at'] = float(data.get('steam_linked_at') or 0)
    data['gsi_last_seen_at'] = float(data.get('gsi_last_seen_at') or 0)
    data['gsi_game_time'] = int(data.get('gsi_game_time') or 0)
    data['gsi_hero_id'] = int(data.get('gsi_hero_id') or 0)
    data['gsi_kills'] = int(data.get('gsi_kills') or 0)
    data['gsi_deaths'] = int(data.get('gsi_deaths') or 0)
    data['gsi_assists'] = int(data.get('gsi_assists') or 0)
    return data


def get_user_auto_bet_settings(user_id: int) -> dict[str, Any]:
    _migrate_web_user_settings()
    with get_conn() as conn:
        row = conn.execute(
            'SELECT * FROM user_auto_bet_settings WHERE user_id = ?',
            (int(user_id),),
        ).fetchone()
    return _auto_bet_from_row(row, int(user_id))


def ensure_user_auto_bet_gsi_token(user_id: int) -> dict[str, Any]:
    _migrate_web_user_settings()
    settings_row = get_user_auto_bet_settings(int(user_id))
    if str(settings_row.get('gsi_token') or '').strip():
        return settings_row
    token = secrets.token_urlsafe(24)
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(user_id, gsi_token)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                gsi_token = CASE
                    WHEN COALESCE(user_auto_bet_settings.gsi_token, '') = '' THEN excluded.gsi_token
                    ELSE user_auto_bet_settings.gsi_token
                END,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (int(user_id), token),
        )
    return get_user_auto_bet_settings(int(user_id))


def get_auto_bet_user_by_gsi_token(token: str) -> Optional[dict[str, Any]]:
    _migrate_web_user_settings()
    normalized_token = str(token or '').strip()
    if not normalized_token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT users.*, settings.dota2_enabled, settings.cs2_enabled,
                   settings.dota2_custom_questions_enabled,
                   settings.dota2_custom_kills_enabled, settings.dota2_custom_deaths_enabled,
                   settings.dota2_custom_assists_enabled, settings.dota2_custom_duration_enabled,
                   settings.dota2_custom_items_enabled, settings.dota2_custom_hero_special_enabled,
                   settings.cs2_custom_questions_enabled, settings.cs2_custom_win_enabled,
                   settings.cs2_custom_kills_enabled, settings.cs2_custom_deaths_enabled,
                   settings.cs2_custom_assists_enabled,
                   settings.prediction_window_seconds, settings.prediction_title_template,
                   settings.steam_id64, settings.dota_account_id, settings.steam_linked_at,
                   settings.gsi_token, settings.gsi_last_seen_at, settings.gsi_match_id,
                   settings.gsi_game_state, settings.gsi_game_time, settings.gsi_hero_id,
                   settings.gsi_hero_name, settings.gsi_kills, settings.gsi_deaths, settings.gsi_assists,
                   settings.active_prediction_id, settings.active_game_key, settings.active_game_name,
                   settings.active_prediction_title, settings.win_outcome_id, settings.loss_outcome_id,
                   settings.win_outcome_title, settings.loss_outcome_title,
                   settings.last_opened_stream_signature, settings.last_error, settings.last_error_at
            FROM user_auto_bet_settings AS settings
            JOIN web_users AS users ON users.id = settings.user_id
            WHERE settings.gsi_token = ?
            LIMIT 1
            ''',
            (normalized_token,),
        ).fetchone()
    return dict(row) if row else None


def set_user_auto_bet_gsi_state(
    user_id: int,
    *,
    seen_at: float,
    match_id: str,
    game_state: str,
    game_time: int,
    hero_id: int,
    hero_name: str,
    kills: int,
    deaths: int,
    assists: int,
) -> dict[str, Any]:
    _migrate_web_user_settings()
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(user_id)
            VALUES (?)
            ON CONFLICT(user_id) DO NOTHING
            ''',
            (int(user_id),),
        )
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET gsi_last_seen_at = ?,
                gsi_match_id = ?,
                gsi_game_state = ?,
                gsi_game_time = ?,
                gsi_hero_id = ?,
                gsi_hero_name = ?,
                gsi_kills = ?,
                gsi_deaths = ?,
                gsi_assists = ?,
                last_error = '',
                last_error_at = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (
                float(seen_at),
                str(match_id or ''),
                str(game_state or '')[:80],
                int(game_time or 0),
                int(hero_id or 0),
                str(hero_name or '')[:80],
                int(kills or 0),
                int(deaths or 0),
                int(assists or 0),
                int(user_id),
            ),
        )
    return get_user_auto_bet_settings(int(user_id))


def upsert_user_auto_bet_settings(
    user_id: int,
    *,
    dota2_enabled: bool,
    dota2_custom_questions_enabled: bool,
    dota2_custom_kills_enabled: bool,
    dota2_custom_deaths_enabled: bool,
    dota2_custom_assists_enabled: bool,
    dota2_custom_duration_enabled: bool,
    dota2_custom_items_enabled: bool,
    dota2_custom_hero_special_enabled: bool,
    cs2_enabled: bool,
    cs2_custom_questions_enabled: bool,
    cs2_custom_win_enabled: bool,
    cs2_custom_kills_enabled: bool,
    cs2_custom_deaths_enabled: bool,
    cs2_custom_assists_enabled: bool,
    prediction_window_seconds: int,
    prediction_title_template: str,
) -> dict[str, Any]:
    _migrate_web_user_settings()
    normalized_title = str(prediction_title_template or '').strip()[:45] or 'Матч {game}: победа?'
    normalized_window = max(30, min(int(prediction_window_seconds or 120), 1800))
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(
                user_id, dota2_enabled, dota2_custom_questions_enabled,
                dota2_custom_kills_enabled, dota2_custom_deaths_enabled, dota2_custom_assists_enabled,
                dota2_custom_duration_enabled, dota2_custom_items_enabled, dota2_custom_hero_special_enabled,
                cs2_enabled, cs2_custom_questions_enabled, cs2_custom_win_enabled, cs2_custom_kills_enabled,
                cs2_custom_deaths_enabled, cs2_custom_assists_enabled, prediction_window_seconds, prediction_title_template
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                dota2_enabled = excluded.dota2_enabled,
                dota2_custom_questions_enabled = excluded.dota2_custom_questions_enabled,
                dota2_custom_kills_enabled = excluded.dota2_custom_kills_enabled,
                dota2_custom_deaths_enabled = excluded.dota2_custom_deaths_enabled,
                dota2_custom_assists_enabled = excluded.dota2_custom_assists_enabled,
                dota2_custom_duration_enabled = excluded.dota2_custom_duration_enabled,
                dota2_custom_items_enabled = excluded.dota2_custom_items_enabled,
                dota2_custom_hero_special_enabled = excluded.dota2_custom_hero_special_enabled,
                cs2_enabled = excluded.cs2_enabled,
                cs2_custom_questions_enabled = excluded.cs2_custom_questions_enabled,
                cs2_custom_win_enabled = excluded.cs2_custom_win_enabled,
                cs2_custom_kills_enabled = excluded.cs2_custom_kills_enabled,
                cs2_custom_deaths_enabled = excluded.cs2_custom_deaths_enabled,
                cs2_custom_assists_enabled = excluded.cs2_custom_assists_enabled,
                prediction_window_seconds = excluded.prediction_window_seconds,
                prediction_title_template = excluded.prediction_title_template,
                last_error = '',
                last_error_at = 0,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (
                int(user_id),
                1 if dota2_enabled else 0,
                1 if dota2_custom_questions_enabled else 0,
                1 if dota2_custom_kills_enabled else 0,
                1 if dota2_custom_deaths_enabled else 0,
                1 if dota2_custom_assists_enabled else 0,
                1 if dota2_custom_duration_enabled else 0,
                1 if dota2_custom_items_enabled else 0,
                1 if dota2_custom_hero_special_enabled else 0,
                1 if cs2_enabled else 0,
                1 if cs2_custom_questions_enabled else 0,
                1 if cs2_custom_win_enabled else 0,
                1 if cs2_custom_kills_enabled else 0,
                1 if cs2_custom_deaths_enabled else 0,
                1 if cs2_custom_assists_enabled else 0,
                normalized_window,
                normalized_title,
            ),
        )
    return get_user_auto_bet_settings(int(user_id))


def list_auto_bet_enabled_users() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT users.*, settings.dota2_enabled, settings.cs2_enabled,
                   settings.dota2_custom_questions_enabled,
                   settings.dota2_custom_kills_enabled, settings.dota2_custom_deaths_enabled,
                   settings.dota2_custom_assists_enabled, settings.dota2_custom_duration_enabled,
                   settings.dota2_custom_items_enabled, settings.dota2_custom_hero_special_enabled,
                   settings.cs2_custom_questions_enabled, settings.cs2_custom_win_enabled,
                   settings.cs2_custom_kills_enabled, settings.cs2_custom_deaths_enabled,
                   settings.cs2_custom_assists_enabled,
                   settings.prediction_window_seconds, settings.prediction_title_template,
                   settings.steam_id64, settings.dota_account_id, settings.steam_linked_at,
                   settings.gsi_token, settings.gsi_last_seen_at, settings.gsi_match_id,
                   settings.gsi_game_state, settings.gsi_game_time, settings.gsi_hero_id,
                   settings.gsi_hero_name, settings.gsi_kills, settings.gsi_deaths, settings.gsi_assists,
                   settings.active_prediction_id, settings.active_game_key, settings.active_game_name,
                   settings.active_prediction_title, settings.win_outcome_id, settings.loss_outcome_id,
                   settings.win_outcome_title, settings.loss_outcome_title,
                   settings.last_opened_stream_signature, settings.last_error, settings.last_error_at
            FROM web_users AS users
            JOIN user_auto_bet_settings AS settings ON settings.user_id = users.id
            WHERE users.bot_enabled = 1
              AND settings.active_prediction_id != ''
            ORDER BY users.created_at ASC
            '''
        ).fetchall()
    return [dict(row) for row in rows]


def set_user_auto_bet_steam(user_id: int, *, steam_id64: str, dota_account_id: str, linked_at: float) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(user_id)
            VALUES (?)
            ON CONFLICT(user_id) DO NOTHING
            ''',
            (int(user_id),),
        )
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET steam_id64 = ?,
                dota_account_id = ?,
                steam_linked_at = ?,
                last_error = '',
                last_error_at = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (str(steam_id64 or ''), str(dota_account_id or ''), float(linked_at), int(user_id)),
        )
    return get_user_auto_bet_settings(int(user_id))


def clear_user_auto_bet_steam(user_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET steam_id64 = '',
                dota_account_id = '',
                steam_linked_at = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (int(user_id),),
        )
    return get_user_auto_bet_settings(int(user_id))


def set_user_auto_bet_prediction(
    user_id: int,
    *,
    prediction_id: str,
    game_key: str,
    game_name: str,
    title: str,
    win_outcome_id: str,
    loss_outcome_id: str,
    stream_signature: str,
    win_outcome_title: str = 'Победа',
    loss_outcome_title: str = 'Поражение',
) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(user_id)
            VALUES (?)
            ON CONFLICT(user_id) DO NOTHING
            ''',
            (int(user_id),),
        )
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET active_prediction_id = ?,
                active_game_key = ?,
                active_game_name = ?,
                active_prediction_title = ?,
                win_outcome_id = ?,
                loss_outcome_id = ?,
                win_outcome_title = ?,
                loss_outcome_title = ?,
                last_opened_stream_signature = ?,
                last_error = '',
                last_error_at = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (
                str(prediction_id or ''),
                str(game_key or ''),
                str(game_name or ''),
                str(title or ''),
                str(win_outcome_id or ''),
                str(loss_outcome_id or ''),
                str(win_outcome_title or 'Победа')[:25],
                str(loss_outcome_title or 'Поражение')[:25],
                str(stream_signature or ''),
                int(user_id),
            ),
        )
    return get_user_auto_bet_settings(int(user_id))


def clear_user_auto_bet_prediction(user_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET active_prediction_id = '',
                active_game_key = '',
                active_game_name = '',
                active_prediction_title = '',
                win_outcome_id = '',
                loss_outcome_id = '',
                win_outcome_title = 'Победа',
                loss_outcome_title = 'Поражение',
                last_error = '',
                last_error_at = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (int(user_id),),
        )
    return get_user_auto_bet_settings(int(user_id))


def set_user_auto_bet_error(user_id: int, error: str, *, error_at: float) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_settings(user_id)
            VALUES (?)
            ON CONFLICT(user_id) DO NOTHING
            ''',
            (int(user_id),),
        )
        conn.execute(
            '''
            UPDATE user_auto_bet_settings
            SET last_error = ?,
                last_error_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            ''',
            (str(error or '')[:1000], float(error_at), int(user_id)),
        )
    return get_user_auto_bet_settings(int(user_id))


def add_user_auto_bet_history(
    user_id: int,
    *,
    prediction_id: str,
    game_key: str,
    game_name: str,
    title: str,
    outcome_title: str,
    status: str,
    total_channel_points: int,
    total_users: int,
) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_auto_bet_history(
                user_id, prediction_id, game_key, game_name, title, outcome_title, status, total_channel_points, total_users
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                int(user_id),
                str(prediction_id or ''),
                str(game_key or ''),
                str(game_name or ''),
                str(title or '')[:45],
                str(outcome_title or '')[:25],
                str(status or '')[:20],
                max(0, int(total_channel_points or 0)),
                max(0, int(total_users or 0)),
            ),
        )


def list_user_auto_bet_history(user_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    normalized_limit = max(1, min(int(limit or 5), 25))
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, prediction_id, game_key, game_name, title, outcome_title, status,
                   total_channel_points, total_users, created_at
            FROM user_auto_bet_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            ''',
            (int(user_id), normalized_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def log_user_action(
    user_id: int,
    *,
    action: str,
    title: str,
    detail: str = '',
    actor_user_id: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO user_action_logs(user_id, actor_user_id, action, title, detail, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                int(user_id),
                int(actor_user_id) if actor_user_id is not None else None,
                str(action or '').strip() or 'action',
                str(title or '').strip() or 'Действие',
                str(detail or '').strip(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def list_user_action_logs(user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT
                logs.id,
                logs.user_id,
                logs.actor_user_id,
                logs.action,
                logs.title,
                logs.detail,
                logs.metadata,
                logs.created_at,
                actor.login AS actor_login,
                actor.display_name AS actor_display_name
            FROM user_action_logs AS logs
            LEFT JOIN web_users AS actor ON actor.id = logs.actor_user_id
            WHERE logs.user_id = ? AND logs.action != 'channel.switch'
            ORDER BY logs.id DESC
            LIMIT ?
            ''',
            (user_id, max(1, min(int(limit), 100))),
        ).fetchall()
    return [dict(row) for row in rows]


def count_user_action_logs(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_action_logs WHERE user_id = ? AND action != 'channel.switch'",
            (user_id,),
        ).fetchone()
    return int(row['cnt'] if row else 0)


def is_builtin_standard_question_preset(file_name: str) -> bool:
    return str(file_name or '').strip().lower() in BUILTIN_STANDARD_QUESTION_PRESET_FILES


def get_user_question_configs(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, user_id, name, file_path, content_json, is_standard, source_file_name, created_at
            FROM user_question_configs
            WHERE user_id = ?
            ORDER BY is_standard DESC, id ASC
            ''',
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_question_config_by_id(user_id: int, config_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT id, user_id, name, file_path, content_json, is_standard, source_file_name, created_at
            FROM user_question_configs
            WHERE user_id = ? AND id = ?
            ''',
            (user_id, config_id),
        ).fetchone()
    return _config_from_row(row)


def count_user_question_configs(user_id: int, *, include_standard: bool = True) -> int:
    with get_conn() as conn:
        if include_standard:
            row = conn.execute(
                'SELECT COUNT(*) AS cnt FROM user_question_configs WHERE user_id = ?',
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                'SELECT COUNT(*) AS cnt FROM user_question_configs WHERE user_id = ? AND COALESCE(is_standard, 0) = 0',
                (user_id,),
            ).fetchone()
    return int(row['cnt'])


def _validate_questions_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        raise ValueError('JSON должен быть непустым массивом вопросов.')

    cleaned: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError('Каждый вопрос должен быть объектом.')
        answer = str(item.get('answer', '')).strip()
        if not answer:
            raise ValueError('У каждого вопроса должно быть поле answer.')
        cleaned.append(
            {
                'category': str(item.get('category', 'Слово')).strip() or 'Слово',
                'hint': str(item.get('hint', '')).strip(),
                'answer': answer,
                'aliases': [str(alias).strip() for alias in (item.get('aliases') or []) if str(alias).strip()],
            }
        )
    return cleaned


def _safe_questions_stem(value: str) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum() or ch in {'-', '_'})


def _generate_question_preset_slug() -> str:
    return f'preset-{secrets.token_hex(4)}.json'


def _display_name_from_uploaded_file(filename: str) -> str:
    stem = Path(str(filename or '').strip()).stem.strip()
    if not stem:
        return ''
    return stem.replace('_', ' ').replace('-', ' ').strip()


def _candidate_standard_question_preset_paths(file_name: str) -> list[Path]:
    normalized_name = Path(str(file_name or '').strip()).name
    if not normalized_name:
        return []
    return [
        STANDARD_QUESTION_PRESETS_DIR / normalized_name,
        BASE_DIR / 'data' / normalized_name,
    ]


def resolve_standard_question_preset_path(file_name: str) -> Optional[Path]:
    for candidate in _candidate_standard_question_preset_paths(file_name):
        if candidate.exists():
            return candidate
    return None


def _standard_question_preset_title_path(file_name: str) -> Path:
    normalized_name = Path(str(file_name or '').strip()).name
    resolved_path = resolve_standard_question_preset_path(normalized_name)
    base_dir = resolved_path.parent if resolved_path else STANDARD_QUESTION_PRESETS_DIR
    return base_dir / f'{normalized_name}.name.txt'


def _store_standard_question_preset_title(file_name: str, title: str) -> None:
    title_path = _standard_question_preset_title_path(file_name)
    cleaned_title = str(title or '').strip()
    if not cleaned_title:
        if title_path.exists():
            try:
                title_path.unlink()
            except OSError:
                pass
        return
    try:
        title_path.write_text(cleaned_title, encoding='utf-8')
    except OSError as exc:
        raise ValueError('Не удалось сохранить название стандартного конфига.') from exc


def get_standard_question_preset_title(file_name: str) -> str:
    _ensure_question_preset_storage()
    preset = get_standard_question_preset_by_slug(file_name)
    if preset and str(preset.get('name') or '').strip():
        return str(preset.get('name') or '').strip()
    title_path = _standard_question_preset_title_path(file_name)
    if not title_path.exists():
        return ''
    try:
        return title_path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _decode_questions_payload(raw_bytes: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_bytes.decode('utf-8-sig'))
    except Exception as exc:
        raise ValueError('Файл должен быть валидным UTF-8 JSON.') from exc

    return _validate_questions_payload(payload)


def _decode_questions_payload_from_text(raw_text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(str(raw_text or '[]'))
    except (TypeError, json.JSONDecodeError):
        return []
    try:
        return _validate_questions_payload(payload)
    except ValueError:
        return []


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


def _infer_preset_name(slug: str, payload: list[dict[str, Any]]) -> str:
    categories: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        category = _friendly_question_category_name(item.get('category'))
        if not category or category in categories:
            continue
        categories.append(category)
        if len(categories) >= 4:
            break
    if 2 <= len(categories) <= 4:
        return ' / '.join(categories)
    stem = Path(slug).stem.replace('_', ' ').replace('-', ' ').strip()
    if slug.lower() == 'questions.json':
        return 'Стандартная база'
    if slug.lower() == 'questions_dota2.json':
        return 'Dota 2 база'
    return ' '.join(part.capitalize() for part in stem.split()) or slug


def _upsert_question_preset(
    *,
    slug: str,
    name: str,
    questions: list[dict[str, Any]],
    is_builtin: bool,
    created_by_user_id: Optional[int] = None,
) -> dict[str, Any]:
    _ensure_question_preset_storage()
    content_json = json.dumps(questions, ensure_ascii=False, indent=2)
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO question_presets(slug, name, content_json, is_builtin, created_by_user_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                content_json = excluded.content_json,
                is_builtin = excluded.is_builtin,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (slug, name, content_json, 1 if is_builtin else 0, created_by_user_id),
        )
        row = conn.execute(
            'SELECT id, slug, name, content_json, is_builtin, created_by_user_id, created_at, updated_at FROM question_presets WHERE slug = ?',
            (slug,),
        ).fetchone()
    return dict(row) if row else {}


def _migrate_question_presets() -> None:
    _ensure_question_preset_storage()


def _migrate_question_source_refs() -> None:
    with get_conn() as conn:
        standard_rows = conn.execute(
            '''
            SELECT id, user_id, file_path, source_file_name
            FROM user_question_configs
            WHERE COALESCE(is_standard, 0) = 1
              AND COALESCE(source_file_name, '') != ''
            '''
        ).fetchall()
        for row in standard_rows:
            source_file_name = str(row['source_file_name'] or '').strip()
            if not source_file_name:
                continue
            next_ref = build_standard_question_preset_ref(source_file_name)
            previous_path = str(row['file_path'] or '').strip()
            if previous_path != next_ref:
                conn.execute(
                    'UPDATE user_question_configs SET file_path = ? WHERE id = ?',
                    (next_ref, int(row['id'])),
                )
            if previous_path:
                conn.execute(
                    '''
                    UPDATE web_users
                    SET questions_file = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                      AND questions_file = ?
                    ''',
                    (next_ref, int(row['user_id']), previous_path),
                )


def _migrate_user_question_configs_to_db() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, user_id, file_path, content_json, is_standard
            FROM user_question_configs
            WHERE COALESCE(is_standard, 0) = 0
            '''
        ).fetchall()
        for row in rows:
            config_id = int(row['id'])
            current_path = str(row['file_path'] or '').strip()
            content_json = str(row['content_json'] or '[]').strip() or '[]'
            next_ref = build_user_question_config_ref(config_id)

            if not current_path:
                conn.execute(
                    'UPDATE user_question_configs SET file_path = ? WHERE id = ?',
                    (next_ref, config_id),
                )
                continue

            if is_user_question_config_ref(current_path):
                if current_path != next_ref:
                    conn.execute(
                        'UPDATE user_question_configs SET file_path = ? WHERE id = ?',
                        (next_ref, config_id),
                    )
                continue

            if not content_json or content_json == '[]':
                legacy_path = Path(current_path)
                if legacy_path.exists():
                    try:
                        payload = _decode_questions_payload_from_text(legacy_path.read_text(encoding='utf-8'))
                    except OSError:
                        payload = []
                    if payload:
                        content_json = json.dumps(payload, ensure_ascii=False, indent=2)

            conn.execute(
                'UPDATE user_question_configs SET file_path = ?, content_json = ? WHERE id = ?',
                (next_ref, content_json or '[]', config_id),
            )
            conn.execute(
                '''
                UPDATE web_users
                SET questions_file = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND questions_file = ?
                ''',
                (next_ref, int(row['user_id']), current_path),
            )

            legacy_path = Path(current_path)
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except OSError:
                    pass


def get_standard_question_presets() -> list[dict[str, Any]]:
    _ensure_question_preset_storage()
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, slug, name, content_json, is_builtin, created_by_user_id, created_at, updated_at
            FROM question_presets
            ORDER BY is_builtin DESC, id ASC
            '''
        ).fetchall()
    presets: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(str(item.get('content_json') or '[]'))
        except json.JSONDecodeError:
            payload = []
        item['question_count'] = len(payload) if isinstance(payload, list) else 0
        presets.append(item)
    return presets


def get_standard_question_preset_by_slug(slug: str) -> Optional[dict[str, Any]]:
    _ensure_question_preset_storage()
    normalized_slug = Path(str(slug or '').strip()).name
    if not normalized_slug:
        return None
    with get_conn() as conn:
        row = conn.execute(
            'SELECT id, slug, name, content_json, is_builtin, created_by_user_id, created_at, updated_at FROM question_presets WHERE lower(slug) = lower(?)',
            (normalized_slug,),
        ).fetchone()
    return dict(row) if row else None


def get_standard_question_preset_by_name(name: str) -> Optional[dict[str, Any]]:
    _ensure_question_preset_storage()
    normalized_name = str(name or '').strip()
    if not normalized_name:
        return None
    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT id, slug, name, content_json, is_builtin, created_by_user_id, created_at, updated_at
            FROM question_presets
            WHERE lower(name) = lower(?)
            ORDER BY is_builtin DESC, updated_at DESC, id DESC
            LIMIT 1
            ''',
            (normalized_name,),
        ).fetchone()
    return dict(row) if row else None


def load_questions_payload_from_source(path_str: str) -> list[dict[str, Any]]:
    source = str(path_str or '').strip()
    if not source:
        return []
    preset_slug = _standard_question_preset_slug_from_ref(source)
    if preset_slug:
        preset = get_standard_question_preset_by_slug(preset_slug)
        if not preset:
            return []
        return _decode_questions_payload_from_text(str(preset.get('content_json') or '[]'))
    config_id = _user_question_config_id_from_ref(source)
    if config_id is not None:
        with get_conn() as conn:
            row = conn.execute(
                'SELECT content_json FROM user_question_configs WHERE id = ?',
                (config_id,),
            ).fetchone()
        if not row:
            return []
        return _decode_questions_payload_from_text(str(row['content_json'] or '[]'))
    path = Path(source)
    if not path.exists():
        return []
    try:
        return _decode_questions_payload_from_text(path.read_text(encoding='utf-8'))
    except OSError:
        return []


def _write_questions_file(user_id: int, config_name: str, filename: str, raw_bytes: bytes) -> str:
    questions = _decode_questions_payload(raw_bytes)
    base_name = _safe_questions_stem(Path(filename).stem)
    safe_name = _safe_questions_stem(config_name) or base_name or f'user-{user_id}'
    payload = json.dumps(questions, ensure_ascii=False, indent=2)
    file_name = f'{safe_name}-{user_id}-{secrets.token_hex(3)}.json'
    candidate_dirs = [USER_QUESTIONS_DIR, BASE_DIR / 'storage' / 'user_questions']
    seen_dirs: set[str] = set()
    last_error: Optional[OSError] = None

    for directory in candidate_dirs:
        normalized_dir = str(directory)
        if normalized_dir in seen_dirs:
            continue
        seen_dirs.add(normalized_dir)
        output_path = directory / file_name
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding='utf-8')
            return str(output_path)
        except OSError as exc:
            last_error = exc

    raise ValueError('Не удалось сохранить файл вопросов на сервере.') from last_error


def add_standard_question_preset(config_name: str, filename: str, raw_bytes: bytes) -> dict[str, Any]:
    questions = _decode_questions_payload(raw_bytes)
    display_name = str(config_name or '').strip()
    file_display_name = _display_name_from_uploaded_file(filename)
    preset_name = display_name or file_display_name or _infer_preset_name(filename, questions)
    existing_preset = get_standard_question_preset_by_name(preset_name) if preset_name else None
    if existing_preset and not bool(existing_preset.get('is_builtin')):
        output_file_name = str(existing_preset.get('slug') or '').strip() or _generate_question_preset_slug()
    else:
        output_file_name = _generate_question_preset_slug()
    if is_builtin_standard_question_preset(output_file_name):
        raise ValueError('Этот стандартный конфиг защищён и не может быть перезаписан.')
    preset = _upsert_question_preset(
        slug=output_file_name,
        name=preset_name,
        questions=questions,
        is_builtin=False,
    )
    return {
        'file_name': output_file_name,
        'file_path': build_standard_question_preset_ref(output_file_name),
        'question_count': len(questions),
        'name': str(preset.get('name') or preset_name),
    }


def get_standard_question_preset_link_counts() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT source_file_name, COUNT(*) AS cnt
            FROM user_question_configs
            WHERE COALESCE(is_standard, 0) = 1
              AND COALESCE(source_file_name, '') != ''
            GROUP BY source_file_name
            '''
        ).fetchall()
    return {
        str(row['source_file_name'] or '').strip(): int(row['cnt'] or 0)
        for row in rows
        if str(row['source_file_name'] or '').strip()
    }


def add_user_question_config(
    user_id: int,
    config_name: str,
    filename: str,
    raw_bytes: bytes,
    *,
    is_standard: bool = False,
    source_file_name: str = '',
    file_path_override: str = '',
) -> dict[str, Any]:
    if not is_standard and count_user_question_configs(user_id, include_standard=False) >= MAX_USER_CONFIGS:
        raise ValueError('Можно загрузить не больше трех кастомных конфигов.')

    content_json = '[]'
    if is_standard:
        name = config_name.strip() or Path(source_file_name or filename).stem or 'Стандартный конфиг'
        if str(source_file_name or '').strip():
            file_path = build_standard_question_preset_ref(str(source_file_name or '').strip())
        else:
            file_path = str(file_path_override or '').strip()
            if not file_path:
                raise ValueError('Не удалось определить путь к стандартному конфигу.')
    else:
        questions = _decode_questions_payload(raw_bytes)
        name = config_name.strip() or f'Кастомный конфиг {count_user_question_configs(user_id, include_standard=False) + 1}'
        content_json = json.dumps(questions, ensure_ascii=False, indent=2)
        file_path = '__pending__'

    with get_conn() as conn:
        cursor = conn.execute(
            '''
            INSERT INTO user_question_configs(user_id, name, file_path, content_json, is_standard, source_file_name)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (user_id, name, file_path, content_json, 1 if is_standard else 0, str(source_file_name or '').strip()),
        )
        config_id = int(cursor.lastrowid or 0)
        if not is_standard:
            file_path = build_user_question_config_ref(config_id)
            conn.execute(
                'UPDATE user_question_configs SET file_path = ? WHERE id = ?',
                (file_path, config_id),
            )
        row = conn.execute(
            '''
            SELECT id, user_id, name, file_path, content_json, is_standard, source_file_name, created_at
            FROM user_question_configs
            WHERE id = ?
            ''',
            (config_id,),
        ).fetchone()
    return dict(row)


def set_active_user_questions_config(user_id: int, config_id: Optional[int]) -> Optional[str]:
    file_path = ''
    if config_id is not None:
        config = get_question_config_by_id(user_id, config_id)
        if not config:
            raise ValueError('Конфиг не найден.')
        file_path = config['file_path']

    with get_conn() as conn:
        conn.execute(
            'UPDATE web_users SET questions_file = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (file_path, user_id),
        )
    return file_path or None


def delete_user_question_config(user_id: int, config_id: int) -> None:
    config = get_question_config_by_id(user_id, config_id)
    if not config:
        raise ValueError('Конфиг не найден.')
    if bool(config.get('is_standard')):
        raise ValueError('Стандартные конфиги нельзя удалять из кабинета.')

    with get_conn() as conn:
        conn.execute('DELETE FROM user_question_configs WHERE user_id = ? AND id = ?', (user_id, config_id))
        conn.execute(
            '''
            UPDATE web_users
            SET questions_file = CASE WHEN questions_file = ? THEN '' ELSE questions_file END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (config['file_path'], user_id),
        )

    legacy_path = str(config.get('file_path') or '').strip()
    if legacy_path and not is_user_question_config_ref(legacy_path) and not is_standard_question_preset_ref(legacy_path):
        path = Path(legacy_path)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def revoke_standard_question_preset_access(file_name: str) -> dict[str, int]:
    normalized_file_name = str(file_name or '').strip()
    if not normalized_file_name:
        raise ValueError('Стандартный конфиг не найден.')

    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT id, user_id, file_path
            FROM user_question_configs
            WHERE COALESCE(is_standard, 0) = 1
              AND lower(source_file_name) = lower(?)
            ''',
            (normalized_file_name,),
        ).fetchall()
        deleted_links = len(rows)
        if deleted_links:
            linked_paths = sorted({str(row['file_path'] or '').strip() for row in rows if str(row['file_path'] or '').strip()})
            preset_ref = build_standard_question_preset_ref(normalized_file_name)
            if preset_ref not in linked_paths:
                linked_paths.append(preset_ref)
            if linked_paths:
                placeholders = ', '.join('?' for _ in linked_paths)
                conn.execute(
                    f'''
                    UPDATE web_users
                    SET questions_file = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE questions_file IN ({placeholders})
                    ''',
                    tuple(linked_paths),
                )
            conn.execute(
                '''
                DELETE FROM user_question_configs
                WHERE COALESCE(is_standard, 0) = 1
                  AND lower(source_file_name) = lower(?)
                ''',
                (normalized_file_name,),
            )

    if deleted_links == 0 and get_standard_question_preset_by_slug(normalized_file_name) is None:
        raise ValueError('Стандартный конфиг не найден.')

    return {'deleted_links': deleted_links}


def remove_standard_question_preset(file_name: str) -> dict[str, int]:
    normalized_file_name = str(file_name or '').strip()
    if not normalized_file_name:
        raise ValueError('Стандартный конфиг не найден.')

    preset = get_standard_question_preset_by_slug(normalized_file_name)
    target_slugs = {normalized_file_name}
    if preset and not bool(preset.get('is_builtin')):
        with get_conn() as conn:
            duplicate_rows = conn.execute(
                '''
                SELECT slug
                FROM question_presets
                WHERE lower(name) = lower(?)
                  AND COALESCE(is_builtin, 0) = 0
                ''',
                (str(preset.get('name') or '').strip(),),
            ).fetchall()
        target_slugs.update(
            str(row['slug'] or '').strip()
            for row in duplicate_rows
            if str(row['slug'] or '').strip()
        )

    deleted_links = 0
    any_deleted = False
    found_any = preset is not None
    for target_slug in sorted(target_slugs):
        target_preset = get_standard_question_preset_by_slug(target_slug)
        source_path = resolve_standard_question_preset_path(target_slug)
        revoke_result = revoke_standard_question_preset_access(target_slug)
        deleted_links += int(revoke_result['deleted_links'])
        if target_preset is not None or source_path is not None:
            found_any = True
        title_path = _standard_question_preset_title_path(target_slug)
        if title_path.exists():
            try:
                title_path.unlink()
            except OSError:
                pass
        if source_path and source_path.exists():
            try:
                source_path.unlink()
                any_deleted = True
            except OSError:
                pass
        with get_conn() as conn:
            deleted_rows = conn.execute('DELETE FROM question_presets WHERE lower(slug) = lower(?)', (target_slug,)).rowcount
        if deleted_rows:
            any_deleted = True

    if not found_any and deleted_links == 0:
        raise ValueError('Стандартный конфиг не найден.')

    return {
        'deleted_links': deleted_links,
        'file_deleted': 1 if any_deleted else 0,
    }


def get_user_questions_preview_from_path(path_str: str, limit: int = 5) -> list[dict[str, Any]]:
    return load_questions_payload_from_source(path_str)[:limit]


def get_user_questions_preview(user: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    return get_user_questions_preview_from_path(user.get('questions_file') or '', limit=limit)


def get_template_questions() -> list[dict[str, Any]]:
    return [
        {
            'category': 'Слово',
            'hint': 'Стример включает это перед началом эфира',
            'answer': 'микрофон',
            'aliases': [],
        },
        {
            'category': 'Игра',
            'hint': 'Популярная карта в шутере',
            'answer': 'dust2',
            'aliases': ['dust 2'],
        },
    ]


def get_app_settings() -> dict[str, Any]:
    _ensure_app_settings_storage()
    values = dict(APP_SETTINGS_DEFAULTS)
    with get_conn() as conn:
        rows = conn.execute('SELECT key, value_json FROM app_settings').fetchall()
    for row in rows:
        key = str(row['key'] or '').strip()
        if not key:
            continue
        try:
            values[key] = json.loads(str(row['value_json'] or 'null'))
        except json.JSONDecodeError:
            values[key] = APP_SETTINGS_DEFAULTS.get(key)
    return values


def get_app_setting(key: str, default: Any = None) -> Any:
    settings_map = get_app_settings()
    if key in settings_map:
        return settings_map[key]
    return APP_SETTINGS_DEFAULTS.get(key, default)


def set_app_settings(updates: dict[str, Any]) -> dict[str, Any]:
    _ensure_app_settings_storage()
    normalized_updates = {
        str(key or '').strip(): value
        for key, value in (updates or {}).items()
        if str(key or '').strip()
    }
    if not normalized_updates:
        return get_app_settings()
    with get_conn() as conn:
        for key, value in normalized_updates.items():
            conn.execute(
                '''
                INSERT INTO app_settings(key, value_json)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (key, json.dumps(value, ensure_ascii=False)),
            )
    return get_app_settings()
