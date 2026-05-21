import sqlite3
from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from .config import settings


Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)


def _configure_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db() -> None:
    with sqlite3.connect(settings.db_path) as raw_conn:
        conn = _configure_conn(raw_conn)
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS players_scoped (
                scope_id TEXT NOT NULL,
                username TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (scope_id, username)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS rounds_scoped (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_id TEXT NOT NULL,
                category TEXT NOT NULL,
                hint TEXT,
                answer TEXT NOT NULL,
                winner TEXT,
                points_awarded INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS quiz_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_id TEXT NOT NULL,
                title TEXT NOT NULL,
                starts_at DATETIME NOT NULL,
                ends_at DATETIME NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                closed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_quiz_seasons_scope_status
            ON quiz_seasons(scope_id, status, starts_at DESC)
            '''
        )
        conn.execute(
            '''
            CREATE INDEX IF NOT EXISTS idx_rounds_scoped_scope_created
            ON rounds_scoped(scope_id, created_at DESC)
            '''
        )
        conn.commit()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _configure_conn(sqlite3.connect(settings.db_path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_points(scope_id: str, username: str, points: int) -> None:
    username = username.lower()
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO players_scoped(scope_id, username, points, wins)
            VALUES(?, ?, ?, 1)
            ON CONFLICT(scope_id, username) DO UPDATE SET
                points = points + excluded.points,
                wins = wins + 1,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (scope_id, username, points),
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _db_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')


def _parse_db_timestamp(value: str | None) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    return datetime.strptime(raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)


def _touch_quiz_seasons(conn: sqlite3.Connection, scope_id: str, now: Optional[datetime] = None) -> None:
    current = now or _utc_now()
    current_ts = _db_timestamp(current)
    conn.execute(
        '''
        UPDATE quiz_seasons
        SET status = 'active',
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_id = ?
          AND status = 'scheduled'
          AND starts_at <= ?
        ''',
        (scope_id, current_ts),
    )
    conn.execute(
        '''
        UPDATE quiz_seasons
        SET status = 'finished',
            closed_at = COALESCE(closed_at, ends_at),
            updated_at = CURRENT_TIMESTAMP
        WHERE scope_id = ?
          AND status IN ('scheduled', 'active')
          AND ends_at <= ?
        ''',
        (scope_id, current_ts),
    )


def create_quiz_season(
    scope_id: str,
    title: str,
    *,
    ends_at: datetime,
    starts_at: Optional[datetime] = None,
) -> dict:
    start_value = (starts_at or _utc_now()).astimezone(UTC)
    end_value = ends_at.astimezone(UTC)
    if end_value <= start_value:
        raise ValueError('Сезон должен заканчиваться позже старта.')

    with get_conn() as conn:
        _touch_quiz_seasons(conn, scope_id, start_value)
        active = conn.execute(
            '''
            SELECT id
            FROM quiz_seasons
            WHERE scope_id = ?
              AND status IN ('scheduled', 'active')
            ORDER BY starts_at DESC, id DESC
            LIMIT 1
            ''',
            (scope_id,),
        ).fetchone()
        if active:
            raise ValueError('Сначала заверши текущий сезон викторины.')

        status = 'scheduled' if start_value > _utc_now() else 'active'
        conn.execute(
            '''
            INSERT INTO quiz_seasons(scope_id, title, starts_at, ends_at, status)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (scope_id, title.strip(), _db_timestamp(start_value), _db_timestamp(end_value), status),
        )
        row = conn.execute(
            '''
            SELECT *
            FROM quiz_seasons
            WHERE scope_id = ?
            ORDER BY id DESC
            LIMIT 1
            ''',
            (scope_id,),
        ).fetchone()
    return dict(row) if row else {}


def finish_quiz_season(scope_id: str, season_id: Optional[int] = None, *, finished_at: Optional[datetime] = None) -> Optional[dict]:
    finish_value = (finished_at or _utc_now()).astimezone(UTC)
    with get_conn() as conn:
        _touch_quiz_seasons(conn, scope_id, finish_value)
        if season_id is None:
            target = conn.execute(
                '''
                SELECT *
                FROM quiz_seasons
                WHERE scope_id = ?
                  AND status IN ('scheduled', 'active')
                ORDER BY starts_at DESC, id DESC
                LIMIT 1
                ''',
                (scope_id,),
            ).fetchone()
        else:
            target = conn.execute(
                'SELECT * FROM quiz_seasons WHERE scope_id = ? AND id = ?',
                (scope_id, int(season_id)),
            ).fetchone()
        if not target:
            return None

        start_value = _parse_db_timestamp(target['starts_at']) or finish_value
        close_value = finish_value if finish_value >= start_value else start_value
        conn.execute(
            '''
            UPDATE quiz_seasons
            SET status = 'finished',
                closed_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE scope_id = ? AND id = ?
            ''',
            (_db_timestamp(close_value), scope_id, int(target['id'])),
        )
        row = conn.execute(
            'SELECT * FROM quiz_seasons WHERE scope_id = ? AND id = ?',
            (scope_id, int(target['id'])),
        ).fetchone()
    return dict(row) if row else None


def get_latest_quiz_season(scope_id: str) -> Optional[dict]:
    with get_conn() as conn:
        _touch_quiz_seasons(conn, scope_id)
        row = conn.execute(
            '''
            SELECT *
            FROM quiz_seasons
            WHERE scope_id = ?
            ORDER BY starts_at DESC, id DESC
            LIMIT 1
            ''',
            (scope_id,),
        ).fetchone()
    return dict(row) if row else None


def list_quiz_seasons(scope_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        _touch_quiz_seasons(conn, scope_id)
        rows = conn.execute(
            '''
            SELECT *
            FROM quiz_seasons
            WHERE scope_id = ?
            ORDER BY starts_at DESC, id DESC
            LIMIT ?
            ''',
            (scope_id, max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def get_quiz_season_top(scope_id: str, season_id: int, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        _touch_quiz_seasons(conn, scope_id)
        season = conn.execute(
            'SELECT * FROM quiz_seasons WHERE scope_id = ? AND id = ?',
            (scope_id, int(season_id)),
        ).fetchone()
        if not season:
            return []

        starts_at = str(season['starts_at'])
        now = _utc_now()
        ends_at_dt = _parse_db_timestamp(season['ends_at']) or now
        closed_at_dt = _parse_db_timestamp(season['closed_at'])
        upper_bound = closed_at_dt or min(now, ends_at_dt)
        rows = conn.execute(
            '''
            SELECT winner AS username,
                   SUM(points_awarded) AS points,
                   COUNT(*) AS wins
            FROM rounds_scoped
            WHERE scope_id = ?
              AND winner IS NOT NULL
              AND created_at >= ?
              AND created_at <= ?
            GROUP BY winner
            ORDER BY points DESC, wins DESC, username ASC
            LIMIT ?
            ''',
            (scope_id, starts_at, _db_timestamp(upper_bound), max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def get_top_players(scope_id: str, limit: int = 3) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            '''
            SELECT username, points, wins
            FROM players_scoped
            WHERE scope_id = ?
            ORDER BY points DESC, wins DESC, username ASC
            LIMIT ?
            ''',
            (scope_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def reset_points(scope_id: str) -> None:
    with get_conn() as conn:
        conn.execute('DELETE FROM players_scoped WHERE scope_id = ?', (scope_id,))


def record_round(
    scope_id: str,
    category: str,
    hint: str,
    answer: str,
    winner: Optional[str],
    points_awarded: int = 0,
) -> None:
    with get_conn() as conn:
        conn.execute(
            '''
            INSERT INTO rounds_scoped(scope_id, category, hint, answer, winner, points_awarded)
            VALUES(?, ?, ?, ?, ?, ?)
            ''',
            (scope_id, category, hint, answer, winner, points_awarded),
        )
