import asyncio
import json
import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC
from datetime import datetime
from typing import Any, Optional

from . import db
from .config import settings
from .utils import normalize_text, unique_hidden_letters
from .web_db import (
    APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE,
    get_app_setting,
    load_questions_payload_from_source,
)


logger = logging.getLogger(__name__)

TURBO_ROUND_DURATION_SECONDS = 30
TURBO_AUTO_NEXT_DELAY_SECONDS = 10
TURBO_REVEAL_INTERVAL_SECONDS = 5
TURBO_MIN_NEXT_ROUND_FROM_START_SECONDS = 10
NO_WINNER_NEXT_ROUND_DELAY_SECONDS = 2
QUESTION_REPEAT_PROTECTION_ROUNDS = 30
PASSIVE_MODE_MIN_DELAY_SECONDS = 5 * 60
PASSIVE_MODE_MAX_DELAY_SECONDS = 12 * 60
PASSIVE_MODE_RETRY_DELAY_SECONDS = 60
PASSIVE_MODE_RESULT_VISIBLE_SECONDS = 5
ROUND_RESULT_VISIBLE_SECONDS = 5


@dataclass
class RoundState:
    category: str
    hint: str
    answer: str
    aliases: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    opened_letters: set[str] = field(default_factory=set)
    winner: Optional[str] = None
    points_awarded: int = 0
    is_active: bool = True
    reveal_count: int = 0

    @property
    def normalized_answer(self) -> str:
        return normalize_text(self.answer)

    def check_guess(self, guess: str) -> bool:
        normalized_guess = normalize_text(guess)
        if not normalized_guess:
            return False
        if normalized_guess == self.normalized_answer:
            return True
        for alias in self.aliases:
            if normalized_guess == normalize_text(alias):
                return True
        return False

    def masked_answer(self) -> str:
        chars: list[str] = []
        for ch in self.answer:
            low = ch.lower().replace('ё', 'е')
            if ch == ' ':
                chars.append('|')
            elif not ch.isalnum():
                continue
            elif low in self.opened_letters:
                chars.append(ch)
            else:
                chars.append('_')
        return ''.join(chars)


@dataclass
class GameChannelConfig:
    scope_id: str
    broadcaster_id: str
    channel_name: str
    questions_path: str
    questions_path_main: str
    questions_path_dota: str
    questions_category: str = ''
    round_duration_seconds: int = settings.game_round_duration_seconds
    reveal_interval_seconds: int = settings.game_reveal_interval_seconds
    base_score: int = settings.game_base_score
    letter_penalty: int = settings.game_letter_penalty
    time_step_penalty: int = settings.game_time_step_penalty
    auto_next_delay_seconds: int = settings.game_auto_next_delay_seconds
    answer_cooldown_seconds: float = settings.answer_cooldown_seconds
    turbo_mode: bool = False
    passive_mode: bool = False
    quiet_mode: bool = False
    chat_questions_enabled: bool = False
    chat_correct_answers_enabled: bool = False
    chat_winners_enabled: bool = False


class GameManager:
    def __init__(self, config: GameChannelConfig) -> None:
        self.config = config
        self._apply_speed_profile()
        self.current_round: Optional[RoundState] = None
        self.last_winner: Optional[dict[str, Any]] = None
        self.last_no_winner: bool = False
        self.last_round_finished_at: Optional[float] = None
        self.next_round_at: Optional[float] = None
        self.paused: bool = False
        self.questions: list[dict[str, Any]] = self._load_questions()
        self._question_queue: deque[dict[str, Any]] = deque()
        self._clients: set[Any] = set()
        self._round_task: Optional[asyncio.Task] = None
        self._next_round_task: Optional[asyncio.Task] = None
        self._cooldowns: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._recent_question_keys: deque[tuple[str, str, str]] = deque(maxlen=QUESTION_REPEAT_PROTECTION_ROUNDS)
        self._paused_at: Optional[float] = None
        self._next_round_delay_remaining: Optional[int] = None
        self.auto_rounds_stopped: bool = False
        self.passive_waiting_for_live: bool = False
        self._rebuild_question_queue()

    def _cancel_next_round_task(self) -> None:
        if self._next_round_task and not self._next_round_task.done():
            self._next_round_task.cancel()
        self._next_round_task = None

    def _should_schedule_passive_round(self) -> bool:
        return (
            self.config.passive_mode
            and not self.auto_rounds_stopped
            and not self.current_round
            and not self.paused
            and not self.next_round_at
            and bool(self.questions)
            and (self._next_round_task is None or self._next_round_task.done())
        )

    def update_config(
        self,
        *,
        channel_name: Optional[str] = None,
        questions_path: Optional[str] = None,
        answer_cooldown_seconds: Optional[float] = None,
        turbo_mode: Optional[bool] = None,
        passive_mode: Optional[bool] = None,
        quiet_mode: Optional[bool] = None,
        chat_questions_enabled: Optional[bool] = None,
        chat_correct_answers_enabled: Optional[bool] = None,
        chat_winners_enabled: Optional[bool] = None,
    ) -> None:
        should_reload = False
        if channel_name is not None:
            self.config.channel_name = channel_name
        if questions_path is not None and questions_path != self.config.questions_path:
            self.config.questions_path = questions_path
            should_reload = True
        if answer_cooldown_seconds is not None:
            self.config.answer_cooldown_seconds = max(0.0, float(answer_cooldown_seconds))
        if turbo_mode is not None:
            self.config.turbo_mode = bool(turbo_mode)
        if passive_mode is not None:
            next_passive_mode = bool(passive_mode)
            was_passive_mode = bool(self.config.passive_mode)
            self.config.passive_mode = next_passive_mode
            if was_passive_mode and not next_passive_mode and not self.current_round:
                self._cancel_next_round_task()
                self.next_round_at = None
                self._next_round_delay_remaining = None
                self.passive_waiting_for_live = False
                if not self.paused and self.questions and not self.auto_rounds_stopped:
                    self._schedule_next_round(delay_override=0)
            if not was_passive_mode and next_passive_mode and not self.current_round:
                self.auto_rounds_stopped = False
        if quiet_mode is not None:
            self.config.quiet_mode = bool(quiet_mode)
        if chat_questions_enabled is not None:
            self.config.chat_questions_enabled = bool(chat_questions_enabled)
        if chat_correct_answers_enabled is not None:
            self.config.chat_correct_answers_enabled = bool(chat_correct_answers_enabled)
        if chat_winners_enabled is not None:
            self.config.chat_winners_enabled = bool(chat_winners_enabled)
        self._apply_speed_profile()
        if should_reload:
            self.questions = self._load_questions()
            self._rebuild_question_queue()
        if self._should_schedule_passive_round():
            self._schedule_next_round()

    def _apply_speed_profile(self) -> None:
        if self.config.turbo_mode:
            self.config.round_duration_seconds = TURBO_ROUND_DURATION_SECONDS
            self.config.reveal_interval_seconds = TURBO_REVEAL_INTERVAL_SECONDS
            self.config.auto_next_delay_seconds = TURBO_AUTO_NEXT_DELAY_SECONDS
            return
        self.config.round_duration_seconds = settings.game_round_duration_seconds
        self.config.reveal_interval_seconds = settings.game_reveal_interval_seconds
        self.config.auto_next_delay_seconds = settings.game_auto_next_delay_seconds

    def _load_questions(self) -> list[dict[str, Any]]:
        data = load_questions_payload_from_source(self.config.questions_path)
        cleaned: list[dict[str, Any]] = []
        category_filter = self.config.questions_category.strip().lower()
        for item in data:
            if not item.get('answer'):
                continue
            category = item.get('category', 'Слово')
            if category_filter and category.lower() != category_filter:
                continue
            cleaned.append(
                {
                    'category': category,
                    'hint': item.get('hint', ''),
                    'answer': item['answer'],
                    'aliases': item.get('aliases') or [],
                }
            )
        return cleaned

    def _question_key(self, question: dict[str, Any]) -> tuple[str, str, str]:
        return (question.get('category', ''), question.get('hint', ''), question.get('answer', ''))

    def _rebuild_question_queue(self) -> None:
        if not self.questions:
            self._question_queue = deque()
            return

        recent_keys = set(self._recent_question_keys)
        shuffled_questions = [
            question for question in self.questions
            if self._question_key(question) not in recent_keys
        ]
        if not shuffled_questions:
            shuffled_questions = list(self.questions)

        random.shuffle(shuffled_questions)
        self._question_queue = deque(shuffled_questions)

    def _pick_next_question(self) -> dict[str, Any]:
        if not self._question_queue:
            self._rebuild_question_queue()
        return self._question_queue.popleft()

    def _seconds_left(self, round_state: Optional[RoundState]) -> int:
        if not round_state:
            return 0
        left = self.config.round_duration_seconds - int(time.time() - round_state.started_at)
        return max(0, left)

    def _current_score(self, round_state: Optional[RoundState]) -> int:
        if not round_state:
            return 0
        elapsed_steps = int((time.time() - round_state.started_at) // self.config.reveal_interval_seconds)
        score = (
            self.config.base_score
            - len(round_state.opened_letters) * self.config.letter_penalty
            - elapsed_steps * self.config.time_step_penalty
        )
        return max(10, score)

    async def register_client(self, websocket: Any) -> None:
        self._clients.add(websocket)
        await websocket.send_json(self.get_public_state())

    def unregister_client(self, websocket: Any) -> None:
        self._clients.discard(websocket)

    async def tick(self) -> None:
        if self._should_schedule_passive_round():
            self._schedule_next_round()
        if not self._clients:
            return
        await self.broadcast_state()

    async def broadcast_state(self) -> None:
        payload = self.get_public_state()
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister_client(ws)

    def get_public_state(self) -> dict[str, Any]:
        round_state = self.current_round
        latest_season = db.get_latest_quiz_season(self.config.scope_id)
        passive_result_seconds_left = 0
        if self.config.passive_mode and not (round_state and round_state.is_active) and self.last_round_finished_at:
            passive_result_seconds_left = max(
                0,
                int(math.ceil(self.last_round_finished_at + PASSIVE_MODE_RESULT_VISIBLE_SECONDS - time.time())),
            )
        return {
            'is_active': bool(round_state and round_state.is_active),
            'paused': self.paused,
            'passive_mode': bool(self.config.passive_mode),
            'category': round_state.category if round_state else '',
            'hint': round_state.hint if round_state else '',
            'masked_answer': round_state.masked_answer() if round_state else '—',
            'seconds_left': self._seconds_left(round_state),
            'current_score': self._current_score(round_state),
            'last_winner': self.last_winner,
            'last_no_winner': self.last_no_winner,
            'last_round_finished_at': float(self.last_round_finished_at or 0),
            'passive_result_seconds_left': passive_result_seconds_left,
            'passive_waiting_for_live': bool(self.passive_waiting_for_live),
            'auto_rounds_stopped': bool(self.auto_rounds_stopped),
            'next_round_in': max(0, int(math.ceil(self.next_round_at - time.time()))) if self.next_round_at else 0,
            'top_players': db.get_top_players(self.config.scope_id, 3),
            'season': self._build_season_payload(latest_season),
            'season_history': self._build_season_history_payload(latest_season),
            'channel_name': self.config.channel_name,
        }

    def _format_timestamp(self, value: str | None) -> str:
        raw = str(value or '').strip()
        if not raw:
            return ''
        try:
            parsed = datetime.strptime(raw, '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        except ValueError:
            return raw
        return parsed.isoformat()

    def _build_season_payload(self, season: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not season:
            return None

        status = str(season.get('status') or '').strip().lower() or 'finished'
        now = datetime.now(UTC)
        try:
            starts_at = datetime.strptime(str(season.get('starts_at') or ''), '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        except ValueError:
            starts_at = now
        try:
            ends_at = datetime.strptime(str(season.get('ends_at') or ''), '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        except ValueError:
            ends_at = now

        if status == 'scheduled':
            seconds_left = max(0, int((starts_at - now).total_seconds()))
        elif status == 'active':
            seconds_left = max(0, int((ends_at - now).total_seconds()))
        else:
            seconds_left = 0

        return {
            'id': int(season['id']),
            'title': str(season.get('title') or '').strip(),
            'status': status,
            'starts_at': self._format_timestamp(season.get('starts_at')),
            'ends_at': self._format_timestamp(season.get('ends_at')),
            'closed_at': self._format_timestamp(season.get('closed_at')),
            'seconds_left': seconds_left,
            'top_players': db.get_quiz_season_top(self.config.scope_id, int(season['id']), limit=10),
        }

    def _build_season_history_payload(self, current_season: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        current_id = int(current_season['id']) if current_season else None
        for season in db.list_quiz_seasons(self.config.scope_id, limit=5):
            season_id = int(season['id'])
            if current_id is not None and season_id == current_id:
                continue
            history.append(
                {
                    'id': season_id,
                    'title': str(season.get('title') or '').strip(),
                    'status': str(season.get('status') or '').strip().lower() or 'finished',
                    'starts_at': self._format_timestamp(season.get('starts_at')),
                    'ends_at': self._format_timestamp(season.get('ends_at')),
                    'closed_at': self._format_timestamp(season.get('closed_at')),
                    'top_players': db.get_quiz_season_top(self.config.scope_id, season_id, limit=3),
                }
            )
        return history

    async def reload_questions(self) -> int:
        self.questions = self._load_questions()
        self._rebuild_question_queue()
        self._cooldowns.clear()
        await self.broadcast_state()
        return len(self.questions)

    def _passive_delay_seconds(self) -> int:
        return random.randint(PASSIVE_MODE_MIN_DELAY_SECONDS, PASSIVE_MODE_MAX_DELAY_SECONDS)

    def _schedule_next_round(self, delay_override: Optional[int] = None) -> None:
        delay = (
            self._passive_delay_seconds()
            if self.config.passive_mode and delay_override is None
            else (self.config.auto_next_delay_seconds if delay_override is None else delay_override)
        )
        self._next_round_delay_remaining = delay
        self.next_round_at = time.time() + delay if delay > 0 else None
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            self.next_round_at = None
            self._next_round_delay_remaining = None
            return
        if self._next_round_task and not self._next_round_task.done() and self._next_round_task is not current_task:
            self._cancel_next_round_task()
        self.passive_waiting_for_live = False
        self._next_round_task = asyncio.create_task(self._auto_next_round(delay))

    async def set_category(self, category: str) -> str:
        raw = category.strip()
        normalized = raw.lower().replace('  ', ' ')
        if normalized in {'dota', 'dota2', 'dota 2'}:
            self.config.questions_category = 'Dota 2'
        else:
            self.config.questions_category = raw
        count = await self.reload_questions()
        label = self.config.questions_category or 'все'
        return f'Категория: {label}. Вопросов: {count}'

    async def set_source(self, source: str) -> str:
        src = source.strip().lower()
        if src in {'dota', 'dota2', 'dota 2'}:
            self.config.questions_path = self.config.questions_path_dota
            label = 'dota'
        else:
            self.config.questions_path = self.config.questions_path_main
            label = 'main'
        count = await self.reload_questions()
        return f'Источник: {label}. Вопросов: {count}'

    async def start_round(self) -> str:
        async with self._lock:
            if self.paused:
                return 'Игра на паузе.'
            if self.current_round and self.current_round.is_active:
                return 'Раунд уже активен.'
            if not self.questions:
                return 'Нет загадок. Загрузи JSON с вопросами в кабинете.'
            q = self._pick_next_question()
            self.current_round = RoundState(
                category=q['category'],
                hint=q['hint'],
                answer=q['answer'],
                aliases=q.get('aliases') or [],
            )
            self._recent_question_keys.append(self._question_key(q))
            self.last_winner = None
            self.last_no_winner = False
            self.last_round_finished_at = None
            self.next_round_at = None
            self._next_round_delay_remaining = None
            self.passive_waiting_for_live = False
            self.auto_rounds_stopped = False
            self._cancel_next_round_task()
            if self._round_task and not self._round_task.done():
                self._round_task.cancel()
            self._round_task = asyncio.create_task(self._round_loop())
        await self.broadcast_state()
        await self._announce_round_started()
        return f'Раунд начался: {self.current_round.category}'

    async def _announce_round_started(self) -> None:
        if (
            self.config.quiet_mode
            or not self.config.chat_questions_enabled
            or not self.current_round
            or not self.config.broadcaster_id
        ):
            return
        from .twitch_api import twitch_api

        message = (
            f"Новый раунд. Категория: {self.current_round.category}. "
            f"Подсказка: {self.current_round.hint or 'без подсказки'}. "
            f"Слово: {self.current_round.masked_answer()}"
        )
        try:
            await twitch_api.send_chat_message(message, broadcaster_id=self.config.broadcaster_id)
        except Exception as exc:
            logger.warning(
                'Failed to announce round start in chat for broadcaster %s: %s',
                self.config.broadcaster_id,
                exc,
            )

    async def _passive_mode_gate_passed(self) -> bool:
        if not self.config.passive_mode:
            return True
        if bool(get_app_setting(APP_SETTING_QUIZ_PASSIVE_DEBUG_ALLOW_OFFLINE, False)):
            return True
        broadcaster_id = str(self.config.broadcaster_id or '').strip()
        if not broadcaster_id:
            return False
        from .twitch_api import twitch_api

        try:
            live_streams = await twitch_api.get_live_streams([broadcaster_id])
        except Exception as exc:
            logger.warning(
                'Passive quiz live-check failed for broadcaster %s: %s',
                broadcaster_id,
                exc,
            )
            return False
        return broadcaster_id in live_streams

    async def _round_loop(self) -> None:
        while self.current_round and self.current_round.is_active:
            if self.paused:
                await asyncio.sleep(1)
                continue
            round_state = self.current_round
            elapsed = time.time() - round_state.started_at
            if elapsed >= self.config.round_duration_seconds:
                await self.finish_round_no_winner()
                return
            should_reveal = int(elapsed // self.config.reveal_interval_seconds) > round_state.reveal_count
            if elapsed >= self.config.reveal_interval_seconds and should_reveal:
                revealed = self._reveal_next_letter(round_state)
                await self.broadcast_state()
                if revealed is None or not unique_hidden_letters(round_state.answer, round_state.opened_letters):
                    await asyncio.sleep(2)
                    if self.current_round is round_state and round_state.is_active:
                        await self.finish_round_no_winner()
                    return
            await asyncio.sleep(1)

    def _reveal_next_letter(self, round_state: RoundState) -> Optional[str]:
        hidden = unique_hidden_letters(round_state.answer, round_state.opened_letters)
        if not hidden:
            return None
        next_letter = random.choice(hidden)
        round_state.opened_letters.add(next_letter)
        round_state.reveal_count += 1
        return next_letter

    async def handle_guess(self, username: str, message: str) -> tuple[bool, Optional[str]]:
        async with self._lock:
            if not self.current_round or not self.current_round.is_active or self.paused:
                return False, None
            now = time.time()
            last = self._cooldowns.get(username, 0)
            if now - last < self.config.answer_cooldown_seconds:
                return False, None
            self._cooldowns[username] = now
            if not self.current_round.check_guess(message):
                return False, None
            points = self._current_score(self.current_round)
            self.current_round.winner = username.lower()
            self.current_round.points_awarded = points
            self.current_round.is_active = False
            self.current_round.opened_letters = set(
                ch.lower().replace('ё', 'е') for ch in self.current_round.answer if ch.isalnum()
            )
            db.add_points(self.config.scope_id, username, points)
            db.record_round(
                self.config.scope_id,
                category=self.current_round.category,
                hint=self.current_round.hint,
                answer=self.current_round.answer,
                winner=username.lower(),
                points_awarded=points,
            )
            self.last_winner = {'username': username.lower(), 'points': points}
            self.last_no_winner = False
            self.last_round_finished_at = time.time()
            answer = self.current_round.answer
            elapsed = time.time() - self.current_round.started_at
        if self.config.turbo_mode:
            delay_override = max(0, math.ceil(TURBO_MIN_NEXT_ROUND_FROM_START_SECONDS - elapsed))
        else:
            delay_override = max(0, int(30 - elapsed))
        delay_override = max(delay_override, ROUND_RESULT_VISIBLE_SECONDS)
        if self.config.passive_mode:
            self._schedule_next_round()
        else:
            self._schedule_next_round(delay_override=delay_override)
        await self.broadcast_state()
        chat_response = None
        if not self.config.quiet_mode and self.config.chat_winners_enabled:
            chat_response = f'@{username} угадал: {answer} (+{points})'
        return True, chat_response

    async def finish_round_no_winner(self) -> str:
        async with self._lock:
            if not self.current_round:
                return 'Нет активного раунда.'
            answer = self.current_round.answer
            category = self.current_round.category
            hint = self.current_round.hint
            self.current_round.is_active = False
            self.current_round.opened_letters = set(
                ch.lower().replace('ё', 'е') for ch in self.current_round.answer if ch.isalnum()
            )
            db.record_round(self.config.scope_id, category=category, hint=hint, answer=answer, winner=None, points_awarded=0)
            self.last_winner = None
            self.last_no_winner = True
            self.last_round_finished_at = time.time()
        await self.broadcast_state()
        await self._announce_round_finished_without_winner(answer)
        if self.config.passive_mode:
            self._schedule_next_round()
        else:
            self._schedule_next_round(delay_override=max(NO_WINNER_NEXT_ROUND_DELAY_SECONDS, ROUND_RESULT_VISIBLE_SECONDS))
        return f'Время вышло. Ответ: {answer}'

    async def _announce_round_finished_without_winner(self, answer: str) -> None:
        if (
            self.config.quiet_mode
            or not self.config.chat_correct_answers_enabled
            or not self.config.broadcaster_id
        ):
            return
        from .twitch_api import twitch_api

        try:
            await twitch_api.send_chat_message(
                f'Время вышло. Ответ: {answer}',
                broadcaster_id=self.config.broadcaster_id,
            )
        except Exception as exc:
            logger.warning(
                'Failed to announce round result in chat for broadcaster %s: %s',
                self.config.broadcaster_id,
                exc,
            )

    async def skip_round(self) -> str:
        async with self._lock:
            if not self.current_round or not self.current_round.is_active:
                return 'Нет активного раунда.'
            answer = self.current_round.answer
            self.current_round.is_active = False
            db.record_round(
                self.config.scope_id,
                category=self.current_round.category,
                hint=self.current_round.hint,
                answer=answer,
                winner=None,
                points_awarded=0,
            )
            self.last_winner = None
            self.last_no_winner = True
            self.last_round_finished_at = time.time()
        await self.broadcast_state()
        if self.config.passive_mode:
            self._schedule_next_round()
        else:
            self._schedule_next_round(delay_override=ROUND_RESULT_VISIBLE_SECONDS)
        return f'Раунд пропущен. Ответ: {answer}'

    async def refresh_round(self) -> str:
        async with self._lock:
            db.reset_points(self.config.scope_id)
            self._cancel_next_round_task()
            self.next_round_at = None
            self._next_round_delay_remaining = None
            if self.current_round and self.current_round.is_active:
                answer = self.current_round.answer
                self.current_round.is_active = False
                db.record_round(
                    self.config.scope_id,
                    category=self.current_round.category,
                    hint=self.current_round.hint,
                    answer=answer,
                    winner=None,
                    points_awarded=0,
                )
        await self.broadcast_state()
        return await self.start_round()

    async def reveal_answer(self) -> str:
        async with self._lock:
            if not self.current_round:
                return 'Нет активного раунда.'
            answer = self.current_round.answer
        return f'Правильный ответ: {answer}'

    async def pause(self) -> str:
        if self.paused:
            return 'Игра уже на паузе.'
        self._paused_at = time.time()
        self.paused = True
        if self.next_round_at:
            self._next_round_delay_remaining = max(0, int(math.ceil(self.next_round_at - self._paused_at)))
            self.next_round_at = None
            self._cancel_next_round_task()
        await self.broadcast_state()
        return 'Игра поставлена на паузу.'

    async def resume(self) -> str:
        if not self.paused:
            return 'Игра уже продолжена.'
        paused_for = max(0.0, time.time() - self._paused_at) if self._paused_at is not None else 0.0
        if self.current_round and self.current_round.is_active:
            self.current_round.started_at += paused_for
        self._paused_at = None
        self.paused = False
        if self._next_round_delay_remaining is not None:
            remaining = self._next_round_delay_remaining
            self._next_round_delay_remaining = None
            self._schedule_next_round(delay_override=remaining)
        await self.broadcast_state()
        return 'Игра продолжена.'

    async def stop_game(self) -> str:
        async with self._lock:
            if self._round_task and not self._round_task.done():
                self._round_task.cancel()
            self._cancel_next_round_task()
            self.current_round = None
            self.last_winner = None
            self.last_no_winner = False
            self.last_round_finished_at = None
            self.next_round_at = None
            self.paused = False
            self._paused_at = None
            self._next_round_delay_remaining = None
            self.passive_waiting_for_live = False
            self.auto_rounds_stopped = True
            self._cooldowns.clear()
            db.reset_points(self.config.scope_id)
        await self.broadcast_state()
        return 'Игра остановлена, очки сброшены.'

    async def reset_points(self) -> str:
        db.reset_points(self.config.scope_id)
        await self.broadcast_state()
        return 'Очки сброшены.'

    async def get_top_text(self) -> str:
        top = db.get_top_players(self.config.scope_id, 3)
        if not top:
            return 'Топ пуст.'
        formatted = ' | '.join(f"{idx + 1}. {item['username']} — {item['points']}" for idx, item in enumerate(top))
        return f'Топ 3: {formatted}'

    async def _auto_next_round(self, delay: int) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            if self.paused:
                return
            if self.current_round and self.current_round.is_active:
                return
            if self.config.passive_mode and not await self._passive_mode_gate_passed():
                self.passive_waiting_for_live = True
                await self.broadcast_state()
                self._schedule_next_round(delay_override=PASSIVE_MODE_RETRY_DELAY_SECONDS)
                return
            self.passive_waiting_for_live = False
            self.next_round_at = None
            self._next_round_delay_remaining = None
            await self.start_round()
        except asyncio.CancelledError:
            raise
        finally:
            if asyncio.current_task() is self._next_round_task:
                self._next_round_task = None


class GameRuntimeManager:
    def __init__(self) -> None:
        self._games: dict[str, GameManager] = {}
        self._lock = asyncio.Lock()

    def _build_default_config(
        self,
        scope_id: str,
        broadcaster_id: str,
        channel_name: str,
        questions_path: str,
        answer_cooldown_seconds: Optional[float] = None,
        turbo_mode: Optional[bool] = None,
        passive_mode: Optional[bool] = None,
        quiet_mode: Optional[bool] = None,
        chat_questions_enabled: Optional[bool] = None,
        chat_correct_answers_enabled: Optional[bool] = None,
        chat_winners_enabled: Optional[bool] = None,
    ) -> GameChannelConfig:
        return GameChannelConfig(
            scope_id=scope_id,
            broadcaster_id=broadcaster_id,
            channel_name=channel_name,
            questions_path=questions_path,
            questions_path_main='',
            questions_path_dota='',
            questions_category=settings.questions_category,
            answer_cooldown_seconds=(
                settings.answer_cooldown_seconds if answer_cooldown_seconds is None else max(0.0, float(answer_cooldown_seconds))
            ),
            turbo_mode=False if turbo_mode is None else bool(turbo_mode),
            passive_mode=False if passive_mode is None else bool(passive_mode),
            quiet_mode=False if quiet_mode is None else bool(quiet_mode),
            chat_questions_enabled=False if chat_questions_enabled is None else bool(chat_questions_enabled),
            chat_correct_answers_enabled=False if chat_correct_answers_enabled is None else bool(chat_correct_answers_enabled),
            chat_winners_enabled=False if chat_winners_enabled is None else bool(chat_winners_enabled),
        )

    def get_or_create_game(
        self,
        scope_id: str,
        *,
        broadcaster_id: str,
        channel_name: str,
        questions_path: str,
        answer_cooldown_seconds: Optional[float] = None,
        turbo_mode: Optional[bool] = None,
        passive_mode: Optional[bool] = None,
        quiet_mode: Optional[bool] = None,
        chat_questions_enabled: Optional[bool] = None,
        chat_correct_answers_enabled: Optional[bool] = None,
        chat_winners_enabled: Optional[bool] = None,
    ) -> GameManager:
        game = self._games.get(scope_id)
        if game is None:
            game = GameManager(
                self._build_default_config(
                    scope_id,
                    broadcaster_id,
                    channel_name,
                    questions_path,
                    answer_cooldown_seconds=answer_cooldown_seconds,
                    turbo_mode=turbo_mode,
                    passive_mode=passive_mode,
                    quiet_mode=quiet_mode,
                    chat_questions_enabled=chat_questions_enabled,
                    chat_correct_answers_enabled=chat_correct_answers_enabled,
                    chat_winners_enabled=chat_winners_enabled,
                )
            )
            self._games[scope_id] = game
        else:
            game.update_config(
                channel_name=channel_name,
                questions_path=questions_path,
                answer_cooldown_seconds=answer_cooldown_seconds,
                turbo_mode=turbo_mode,
                passive_mode=passive_mode,
                quiet_mode=quiet_mode,
                chat_questions_enabled=chat_questions_enabled,
                chat_correct_answers_enabled=chat_correct_answers_enabled,
                chat_winners_enabled=chat_winners_enabled,
            )
        return game

    def get_default_game(self) -> GameManager:
        return self.get_or_create_game(
            'default',
            broadcaster_id='default',
            channel_name=settings.twitch_channel_name or 'default',
            questions_path='',
        )

    def get_game_by_broadcaster(
        self,
        broadcaster_id: str,
        *,
        channel_name: str = '',
        questions_path: Optional[str] = None,
        answer_cooldown_seconds: Optional[float] = None,
        turbo_mode: Optional[bool] = None,
        passive_mode: Optional[bool] = None,
        quiet_mode: Optional[bool] = None,
        chat_questions_enabled: Optional[bool] = None,
        chat_correct_answers_enabled: Optional[bool] = None,
        chat_winners_enabled: Optional[bool] = None,
    ) -> GameManager:
        scope_id = f'user:{broadcaster_id}'
        return self.get_or_create_game(
            scope_id,
            broadcaster_id=broadcaster_id,
            channel_name=channel_name or settings.twitch_channel_name or broadcaster_id,
            questions_path=questions_path or '',
            answer_cooldown_seconds=answer_cooldown_seconds,
            turbo_mode=turbo_mode,
            passive_mode=passive_mode,
            quiet_mode=quiet_mode,
            chat_questions_enabled=chat_questions_enabled,
            chat_correct_answers_enabled=chat_correct_answers_enabled,
            chat_winners_enabled=chat_winners_enabled,
        )

    async def tick(self) -> None:
        for game in list(self._games.values()):
            await game.tick()


runtime = GameRuntimeManager()
game = runtime.get_default_game()
