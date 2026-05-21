import logging
import random
import time
from typing import Any, Optional

import httpx

from .config import settings as app_settings
from .runtime_state import runtime_state
from .service_metrics import service_metrics
from .twitch_api import twitch_api
from .web_db import (
    add_user_auto_bet_history,
    clear_user_auto_bet_prediction,
    get_user_auto_bet_settings,
    list_auto_bet_enabled_users,
    set_user_auto_bet_gsi_state,
    set_user_auto_bet_error,
    set_user_auto_bet_prediction,
    upsert_user_auto_bet_settings,
)


logger = logging.getLogger(__name__)

GAME_LABELS: dict[str, str] = {
    'dota2': 'Dota 2',
    'cs2': 'CS2',
}

DOTA_CUSTOM_ITEM_KEYS: tuple[tuple[str, str], ...] = (
    ('black_king_bar', 'BKB'),
    ('blink', 'Blink'),
    ('ultimate_scepter', 'Aghanim'),
    ('manta', 'Manta'),
    ('desolator', 'Desolator'),
    ('bfury', 'Battle Fury'),
)
DOTA_HERO_PUDGE = 14
DOTA_HERO_LEGION_COMMANDER = 104
DOTA_BUFF_PUDGE_FLESH_HEAP = 4
DOTA_BUFF_LEGION_COMMANDER_DUEL = 5
CS2_ALLOWED_MODES = {'competitive', 'premier'}
CS2_MARKET_KINDS = ('win', 'kills_over', 'deaths_over', 'assists_over')


class OpenDotaThrottledError(RuntimeError):
    pass


class AutoBetRuntime:
    PREDICTION_OPEN_LOCK_TTL_SECONDS = 30.0
    GSI_DEBUG_TTL_SECONDS = 12 * 60 * 60.0
    OPENDOTA_STATUS_CACHE_TTL_SECONDS = 300.0
    OPENDOTA_LIVE_CACHE_TTL_SECONDS = 300.0
    OPENDOTA_REFERENCE_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60.0
    OPENDOTA_PROFILE_CACHE_TTL_SECONDS = 60.0
    OPENDOTA_RECENT_MATCHES_CACHE_TTL_SECONDS = 60.0
    OPENDOTA_MATCH_DETAILS_CACHE_TTL_SECONDS = 15 * 60.0
    OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS = 90.0

    def __init__(self) -> None:
        self._next_tick_at = 0.0

    async def tick(self) -> None:
        now = time.time()
        if now < self._next_tick_at:
            return
        self._next_tick_at = now + 15

        users = list_auto_bet_enabled_users()
        if not users:
            return

        for user in users:
            try:
                await self._process_user(user, now)
            except Exception as exc:
                logger.warning('Failed to process auto-bet user=%s: %s', user.get('id'), exc)

    def payload(self, user: dict[str, Any]) -> dict[str, Any]:
        settings = get_user_auto_bet_settings(int(user['id']))
        return {
            'settings': settings,
            'games': [
                {'key': 'dota2', 'label': GAME_LABELS['dota2'], 'enabled': bool(settings.get('dota2_enabled'))},
                {'key': 'cs2', 'label': GAME_LABELS['cs2'], 'enabled': bool(settings.get('cs2_enabled'))},
            ],
        }

    @staticmethod
    def _gsi_debug_cache_key(user_id: int, game_key: str) -> str:
        return f'autobet:gsi-debug:{int(user_id)}:{str(game_key or "").strip().lower()}'

    def _set_gsi_debug_state(self, user_id: int, game_key: str, payload: dict[str, Any]) -> None:
        runtime_state.set(
            self._gsi_debug_cache_key(user_id, game_key),
            {
                **payload,
                'updated_at': float(payload.get('updated_at') or time.time()),
            },
            ttl_seconds=self.GSI_DEBUG_TTL_SECONDS,
        )

    def get_gsi_debug_state(self, user_id: int, game_key: str) -> dict[str, Any]:
        cached = runtime_state.get(self._gsi_debug_cache_key(user_id, game_key))
        return cached if isinstance(cached, dict) else {}

    def update_settings(
        self,
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
        return upsert_user_auto_bet_settings(
            int(user_id),
            dota2_enabled=dota2_enabled,
            dota2_custom_questions_enabled=dota2_custom_questions_enabled,
            dota2_custom_kills_enabled=dota2_custom_kills_enabled,
            dota2_custom_deaths_enabled=dota2_custom_deaths_enabled,
            dota2_custom_assists_enabled=dota2_custom_assists_enabled,
            dota2_custom_duration_enabled=dota2_custom_duration_enabled,
            dota2_custom_items_enabled=dota2_custom_items_enabled,
            dota2_custom_hero_special_enabled=dota2_custom_hero_special_enabled,
            cs2_enabled=cs2_enabled,
            cs2_custom_questions_enabled=cs2_custom_questions_enabled,
            cs2_custom_win_enabled=cs2_custom_win_enabled,
            cs2_custom_kills_enabled=cs2_custom_kills_enabled,
            cs2_custom_deaths_enabled=cs2_custom_deaths_enabled,
            cs2_custom_assists_enabled=cs2_custom_assists_enabled,
            prediction_window_seconds=prediction_window_seconds,
            prediction_title_template=prediction_title_template,
        )

    async def opendota_status(self, account_id: str) -> dict[str, Any]:
        normalized_account_id = str(account_id or '').strip()
        if not normalized_account_id:
            return {
                'ok': False,
                'account_id': '',
                'profile_found': False,
                'history_available': False,
                'fh_unavailable': False,
                'recent_matches_count': 0,
                'error': 'Dota account_id не привязан.',
            }
        now = time.time()
        started_at = time.perf_counter()
        cache_key = f'opendota:status:{normalized_account_id}'
        cached_payload = self._cache_get(cache_key)
        cached_at = self._cache_get_cached_at(cache_key)
        throttle_state = self._get_opendota_throttle_state(now)
        if cached_payload:
            service_metrics.increment('opendota.status.cache_hits')
            cached_payload = dict(cached_payload)
            if not throttle_state:
                cached_payload = self._clear_opendota_degraded_flags(cached_payload)
            max_age = 60 if bool(cached_payload.get('ok')) else 30
            if now - cached_at < max_age or throttle_state:
                if throttle_state:
                    service_metrics.increment('opendota.status.throttled')
                    cached_payload = self._decorate_opendota_payload(cached_payload, throttle_state)
                service_metrics.observe_duration('opendota.status', time.perf_counter() - started_at)
                return cached_payload
        else:
            service_metrics.increment('opendota.status.cache_misses')
        error_payload = {
            'ok': False,
            'account_id': normalized_account_id,
            'profile_found': False,
            'history_available': False,
            'fh_unavailable': False,
            'recent_matches_count': 0,
            'error': 'OpenDota временно недоступен. Попробуй обновить позже.',
        }
        if throttle_state:
            service_metrics.increment('opendota.status.throttled')
            decorated_error = self._decorate_opendota_payload(error_payload, throttle_state)
            self._cache_set(
                cache_key,
                decorated_error,
                now=now,
                ttl_seconds=max(1.0, min(self.OPENDOTA_STATUS_CACHE_TTL_SECONDS, throttle_state['remaining_seconds'])),
            )
            service_metrics.observe_duration('opendota.status', time.perf_counter() - started_at)
            return dict(decorated_error)
        success_payload: dict[str, Any]
        try:
            profile_payload = await self._get_opendota_profile(normalized_account_id, now)
            recent_matches = await self._get_opendota_recent_matches(normalized_account_id, now)
        except OpenDotaThrottledError as exc:
            service_metrics.increment('opendota.status.throttled')
            active_throttle = self._get_opendota_throttle_state(now)
            decorated_payload = self._decorate_opendota_payload(
                cached_payload or error_payload,
                active_throttle,
                fallback_message=str(exc),
            )
            self._cache_set(
                cache_key,
                decorated_payload,
                now=now,
                ttl_seconds=max(
                    1.0,
                    min(
                        self.OPENDOTA_STATUS_CACHE_TTL_SECONDS,
                        float((active_throttle or {}).get('remaining_seconds') or 30.0),
                    ),
                ),
            )
            service_metrics.observe_duration('opendota.status', time.perf_counter() - started_at)
            return dict(decorated_payload)
        except Exception as exc:
            service_metrics.increment('opendota.status.failures')
            service_metrics.record_error('opendota.status', str(exc), context={'account_id': normalized_account_id})
            logger.warning('Failed to check OpenDota status account_id=%s: %s', normalized_account_id, exc)
            self._cache_set(
                cache_key,
                error_payload,
                now=now,
                ttl_seconds=self.OPENDOTA_STATUS_CACHE_TTL_SECONDS,
            )
            service_metrics.observe_duration('opendota.status', time.perf_counter() - started_at)
            return dict(error_payload)

        profile = profile_payload.get('profile') or {}
        recent_matches_count = len(recent_matches) if isinstance(recent_matches, list) else 0
        fh_unavailable = bool(profile.get('fh_unavailable'))
        success_payload = {
            'ok': True,
            'account_id': normalized_account_id,
            'profile_found': bool(profile),
            'history_available': recent_matches_count > 0 and not fh_unavailable,
            'fh_unavailable': fh_unavailable,
            'recent_matches_count': recent_matches_count,
            'personaname': profile.get('personaname') or '',
            'profileurl': profile.get('profileurl') or '',
            'error': '',
        }
        self._cache_set(
            cache_key,
            success_payload,
            now=now,
            ttl_seconds=self.OPENDOTA_STATUS_CACHE_TTL_SECONDS,
        )
        service_metrics.increment('opendota.status.success')
        service_metrics.observe_duration('opendota.status', time.perf_counter() - started_at)
        return dict(success_payload)

    async def refresh_opendota_player(self, account_id: str) -> dict[str, Any]:
        normalized_account_id = str(account_id or '').strip()
        if not normalized_account_id:
            raise RuntimeError('Dota account_id не привязан.')
        refresh_error = ''
        try:
            throttle_state = self._get_opendota_throttle_state(time.time())
            if throttle_state:
                raise OpenDotaThrottledError(self._opendota_throttle_message(throttle_state))
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(f'https://api.opendota.com/api/players/{normalized_account_id}/refresh')
                resp.raise_for_status()
        except Exception as exc:
            logger.warning('Failed to request OpenDota refresh account_id=%s: %s', normalized_account_id, exc)
            if self._is_opendota_rate_limited_error(exc):
                throttle_state = self._activate_opendota_throttle(
                    time.time(),
                    source='opendota.status',
                    context={'account_id': normalized_account_id},
                )
                refresh_error = self._opendota_throttle_message(throttle_state)
            else:
                refresh_error = 'OpenDota сейчас не принял запрос на обновление. Статус профиля проверен, историю можно проверить позже.'
        runtime_state.delete(f'opendota:status:{normalized_account_id}')
        runtime_state.delete(f'opendota:status:{normalized_account_id}:meta')
        status = await self.opendota_status(normalized_account_id)
        status['refresh_accepted'] = not bool(refresh_error)
        status['refresh_error'] = refresh_error
        return status

    async def handle_gsi_payload(self, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        user_id = int(user['id'])
        now = time.time()
        state = self._parse_gsi_payload(payload)
        self._set_gsi_debug_state(
            user_id,
            'dota2',
            {
                **state,
                'updated_at': now,
            },
        )
        settings = set_user_auto_bet_gsi_state(
            user_id,
            seen_at=now,
            match_id=state['match_id'],
            game_state=state['game_state'],
            game_time=int(state['game_time']),
            hero_id=int(state['hero_id']),
            hero_name=state['hero_name'],
            kills=int(state['kills']),
            deaths=int(state['deaths']),
            assists=int(state['assists']),
        )
        opened = False
        if (
            bool(settings.get('dota2_enabled'))
            and not str(settings.get('active_prediction_id') or '').strip()
            and self._gsi_ready_for_prediction_open(state)
            and self._gsi_match_mode_is_allowed(state)
            and state['match_id']
        ):
            if await self._stream_online_gate_passed(user):
                opened = await self._open_gsi_prediction(user, settings, state, now)
        elif str(settings.get('active_game_key') or '') == 'dota2' and str(settings.get('active_prediction_id') or '').strip():
            await self._resolve_dota_gsi_prediction(user, settings, state)
        return {'ok': True, 'opened': opened, 'gsi': state}

    async def handle_cs2_gsi_payload(self, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        user_id = int(user['id'])
        now = time.time()
        state = self._parse_cs2_gsi_payload(payload)
        self._set_gsi_debug_state(
            user_id,
            'cs2',
            {
                **state,
                'updated_at': now,
            },
        )
        previous_settings = get_user_auto_bet_settings(user_id)
        display_kills = int(state['kills']) if bool(state.get('stats_reliable')) else int(previous_settings.get('gsi_kills') or 0)
        display_deaths = int(state['deaths']) if bool(state.get('stats_reliable')) else int(previous_settings.get('gsi_deaths') or 0)
        display_assists = int(state['assists']) if bool(state.get('stats_reliable')) else int(previous_settings.get('gsi_assists') or 0)
        state = {
            **state,
            'kills': display_kills,
            'deaths': display_deaths,
            'assists': display_assists,
        }
        settings = set_user_auto_bet_gsi_state(
            user_id,
            seen_at=now,
            match_id=state['match_id'],
            game_state=f"CS2 {state['mode']} {state['phase']}".strip(),
            game_time=int(state['round']),
            hero_id=0,
            hero_name=str(state.get('map_name') or 'CS2'),
            kills=display_kills,
            deaths=display_deaths,
            assists=display_assists,
        )
        opened = False
        if (
            bool(settings.get('cs2_enabled'))
            and not str(settings.get('active_prediction_id') or '').strip()
            and self._cs2_mode_is_allowed(state)
            and self._cs2_match_is_live(state)
            and state['match_id']
        ):
            if await self._stream_online_gate_passed(user):
                opened = await self._open_cs2_gsi_prediction(user, settings, state, now)
        elif str(settings.get('active_game_key') or '') == 'cs2' and str(settings.get('active_prediction_id') or '').strip():
            await self._resolve_cs2_gsi_prediction(user, settings, state)
        return {'ok': True, 'opened': opened, 'gsi': state}

    async def debug_open_dota_gsi_prediction(
        self,
        user: dict[str, Any],
        *,
        match_id: str = '',
        hero_id: int = DOTA_HERO_PUDGE,
        hero_name: str = 'Pudge',
        kills: int = 1,
        deaths: int = 0,
        assists: int = 2,
        game_mode: str = '22',
        lobby_type: str = '7',
        game_time: int = 75,
    ) -> dict[str, Any]:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        if not bool(settings.get('dota2_enabled')):
            raise RuntimeError('Сначала включи автоставку Dota 2.')
        if str(settings.get('active_prediction_id') or '').strip():
            raise RuntimeError('Сначала закрой текущую активную ставку.')
        now = time.time()
        normalized_match_id = str(match_id or '').strip() or f'debug-dota-{int(now)}'
        state = {
            'match_id': normalized_match_id,
            'game_state': 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS',
            'game_mode': str(game_mode or '22').strip(),
            'lobby_type': str(lobby_type or '7').strip(),
            'game_time': int(game_time or 0),
            'hero_id': int(hero_id or 0),
            'hero_name': self._clean_gsi_hero_name(str(hero_name or 'Pudge')),
            'kills': int(kills or 0),
            'deaths': int(deaths or 0),
            'assists': int(assists or 0),
            'allplayers': [],
        }
        self._set_gsi_debug_state(
            user_id,
            'dota2',
            {
                **state,
                'updated_at': now,
            },
        )
        settings = set_user_auto_bet_gsi_state(
            user_id,
            seen_at=now,
            match_id=state['match_id'],
            game_state=state['game_state'],
            game_time=state['game_time'],
            hero_id=state['hero_id'],
            hero_name=state['hero_name'],
            kills=state['kills'],
            deaths=state['deaths'],
            assists=state['assists'],
        )
        opened = await self._open_gsi_prediction(user, settings, state, now)
        return {'ok': True, 'opened': opened, 'match_id': normalized_match_id, 'gsi': state}

    async def debug_open_cs2_gsi_prediction(
        self,
        user: dict[str, Any],
        *,
        match_id: str = '',
        map_name: str = 'de_mirage',
        mode: str = 'premier',
        round_number: int = 7,
        player_team: str = 'CT',
        kills: int = 8,
        deaths: int = 5,
        assists: int = 2,
        ct_score: int = 3,
        t_score: int = 4,
    ) -> dict[str, Any]:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        if not bool(settings.get('cs2_enabled')):
            raise RuntimeError('Сначала включи автоставку CS2.')
        if str(settings.get('active_prediction_id') or '').strip():
            raise RuntimeError('Сначала закрой текущую активную ставку.')
        now = time.time()
        normalized_match_id = str(match_id or '').strip() or f'debug-cs2-{int(now)}'
        state = {
            'match_id': normalized_match_id,
            'map_name': str(map_name or 'de_mirage').strip(),
            'mode': str(mode or 'premier').strip().lower(),
            'phase': 'live',
            'round': int(round_number or 0),
            'player_team': str(player_team or 'CT').strip().upper(),
            'kills': int(kills or 0),
            'deaths': int(deaths or 0),
            'assists': int(assists or 0),
            'ct_score': int(ct_score or 0),
            't_score': int(t_score or 0),
            'stats_reliable': True,
        }
        self._set_gsi_debug_state(
            user_id,
            'cs2',
            {
                **state,
                'updated_at': now,
            },
        )
        settings = set_user_auto_bet_gsi_state(
            user_id,
            seen_at=now,
            match_id=state['match_id'],
            game_state=f"CS2 {state['mode']} {state['phase']}".strip(),
            game_time=state['round'],
            hero_id=0,
            hero_name=state['map_name'] or 'CS2',
            kills=state['kills'],
            deaths=state['deaths'],
            assists=state['assists'],
        )
        opened = await self._open_cs2_gsi_prediction(user, settings, state, now)
        return {'ok': True, 'opened': opened, 'match_id': normalized_match_id, 'gsi': state}

    async def debug_close_cs2_gsi_prediction(
        self,
        user: dict[str, Any],
        *,
        match_id: str = '',
        map_name: str = 'de_mirage',
        mode: str = 'premier',
        round_number: int = 24,
        player_team: str = 'CT',
        kills: int = 18,
        deaths: int = 11,
        assists: int = 6,
        ct_score: int = 13,
        t_score: int = 10,
    ) -> dict[str, Any]:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        active_prediction_id = str(settings.get('active_prediction_id') or '').strip()
        if not active_prediction_id:
            raise RuntimeError('Сейчас нет активной CS2 ставки для закрытия.')
        if str(settings.get('active_game_key') or '').strip() != 'cs2':
            raise RuntimeError('Активная ставка относится не к CS2.')
        normalized_match_id = str(match_id or self._active_cs2_match_id(settings) or '').strip()
        if not normalized_match_id:
            raise RuntimeError('Не удалось определить match_id для закрытия CS2 ставки.')
        now = time.time()
        state = {
            'match_id': normalized_match_id,
            'map_name': str(map_name or settings.get('gsi_hero_name') or 'de_mirage').strip(),
            'mode': str(mode or 'premier').strip().lower(),
            'phase': 'matchover',
            'round': int(round_number or 0),
            'player_team': str(player_team or 'CT').strip().upper(),
            'kills': int(kills or 0),
            'deaths': int(deaths or 0),
            'assists': int(assists or 0),
            'ct_score': int(ct_score or 0),
            't_score': int(t_score or 0),
            'stats_reliable': True,
        }
        self._set_gsi_debug_state(
            user_id,
            'cs2',
            {
                **state,
                'updated_at': now,
            },
        )
        settings = set_user_auto_bet_gsi_state(
            user_id,
            seen_at=now,
            match_id=state['match_id'],
            game_state=f"CS2 {state['mode']} {state['phase']}".strip(),
            game_time=state['round'],
            hero_id=0,
            hero_name=state['map_name'] or 'CS2',
            kills=state['kills'],
            deaths=state['deaths'],
            assists=state['assists'],
        )
        await self._resolve_cs2_gsi_prediction(user, settings, state)
        updated_settings = get_user_auto_bet_settings(user_id)
        resolved = not str(updated_settings.get('active_prediction_id') or '').strip()
        return {'ok': True, 'resolved': resolved, 'match_id': normalized_match_id, 'gsi': state}

    async def _stream_online_gate_passed(self, user: dict[str, Any]) -> bool:
        if not bool(app_settings.autobet_require_stream_online):
            return True
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            return False
        try:
            live_streams = await twitch_api.get_live_streams([broadcaster_id])
        except Exception as exc:
            logger.warning('Auto-bet stream online check failed user=%s error=%s', user.get('id'), exc)
            return False
        return broadcaster_id in live_streams

    async def resolve_prediction(self, user: dict[str, Any], result: str) -> dict[str, Any]:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        prediction_id = str(settings.get('active_prediction_id') or '').strip()
        external_prediction: Optional[dict[str, Any]] = None
        if not prediction_id:
            external_prediction = await twitch_api.get_current_prediction_for_user(user)
            prediction_id = str((external_prediction or {}).get('id') or '').strip()
        if not prediction_id:
            raise RuntimeError('Активной автоставки нет.')

        normalized_result = str(result or '').strip().lower()
        if external_prediction:
            outcomes = external_prediction.get('outcomes') or []
            if normalized_result == 'win' and len(outcomes) >= 1 and isinstance(outcomes[0], dict):
                settings['win_outcome_id'] = str(outcomes[0].get('id') or '')
                settings['win_outcome_title'] = str(outcomes[0].get('title') or 'Победа')
            elif normalized_result == 'loss' and len(outcomes) >= 2 and isinstance(outcomes[1], dict):
                settings['loss_outcome_id'] = str(outcomes[1].get('id') or '')
                settings['loss_outcome_title'] = str(outcomes[1].get('title') or 'Поражение')
            settings['active_prediction_id'] = prediction_id
            settings['active_prediction_title'] = str(external_prediction.get('title') or '')
            settings['active_game_key'] = 'twitch'
            settings['active_game_name'] = 'Twitch'

        if normalized_result == 'win':
            winning_outcome_id = str(settings.get('win_outcome_id') or '').strip()
            status = 'RESOLVED'
        elif normalized_result == 'loss':
            winning_outcome_id = str(settings.get('loss_outcome_id') or '').strip()
            status = 'RESOLVED'
        elif normalized_result == 'cancel':
            winning_outcome_id = ''
            status = 'CANCELED'
        else:
            raise RuntimeError('Неизвестный результат автоставки.')

        ended_prediction = await twitch_api.end_prediction_for_user(
            user,
            prediction_id=prediction_id,
            status=status,
            winning_outcome_id=winning_outcome_id,
        )
        self._record_prediction_history(user_id, settings, ended_prediction, status=status, winning_outcome_id=winning_outcome_id)
        return clear_user_auto_bet_prediction(user_id)

    async def open_manual_prediction(
        self,
        user: dict[str, Any],
        *,
        game_key: str,
        title: str,
        first_outcome_title: str,
        second_outcome_title: str,
        prediction_window_seconds: int,
    ) -> dict[str, Any]:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        if settings.get('active_prediction_id'):
            raise RuntimeError('Уже есть активная ставка. Сначала закрой её победой, поражением или отменой.')

        normalized_game_key = str(game_key or '').strip().lower()
        if normalized_game_key not in GAME_LABELS:
            normalized_game_key = 'dota2'
        game_name = GAME_LABELS[normalized_game_key]
        lock_key = f'manual:{int(user_id)}:{normalized_game_key}'
        if not self._begin_prediction_open(lock_key):
            raise RuntimeError('Ставка уже создаётся. Подожди пару секунд и попробуй ещё раз.')
        prediction_title = str(title or '').strip()
        if not prediction_title:
            prediction_title = self._prediction_title(settings, game_name)
        first_title = str(first_outcome_title or '').strip()[:25] or 'Победа'
        second_title = str(second_outcome_title or '').strip()[:25] or 'Поражение'
        try:
            window_seconds = int(prediction_window_seconds or settings.get('prediction_window_seconds') or 120)
        except (TypeError, ValueError):
            window_seconds = int(settings.get('prediction_window_seconds') or 120)
        try:
            prediction = await twitch_api.create_prediction_for_user(
                user,
                title=prediction_title,
                prediction_window_seconds=window_seconds,
                outcomes=[first_title, second_title],
            )
            outcomes = prediction.get('outcomes') or []
            win_outcome_id = str(outcomes[0].get('id') or '') if len(outcomes) >= 1 and isinstance(outcomes[0], dict) else ''
            loss_outcome_id = str(outcomes[1].get('id') or '') if len(outcomes) >= 2 and isinstance(outcomes[1], dict) else ''
            return set_user_auto_bet_prediction(
                user_id,
                prediction_id=str(prediction.get('id') or ''),
                game_key=normalized_game_key,
                game_name=game_name,
                title=prediction_title.strip()[:45],
                win_outcome_id=win_outcome_id,
                loss_outcome_id=loss_outcome_id,
                win_outcome_title=first_title,
                loss_outcome_title=second_title,
                stream_signature=f'manual:{int(time.time())}:{normalized_game_key}',
            )
        finally:
            self._finish_prediction_open(lock_key)

    async def _process_user(self, user: dict[str, Any], now: float) -> None:
        user_id = int(user['id'])
        settings = get_user_auto_bet_settings(user_id)
        if settings.get('active_prediction_id'):
            await self._sync_active_prediction(user, settings, now)
        return

    async def _sync_active_prediction(self, user: dict[str, Any], settings: dict[str, Any], now: float) -> None:
        prediction_id = str(settings.get('active_prediction_id') or '').strip()
        if not prediction_id:
            return
        if settings.get('last_error') and now - float(settings.get('last_error_at') or 0) < 600:
            return
        try:
            prediction = await twitch_api.get_prediction_for_user(user, prediction_id=prediction_id)
        except RuntimeError as exc:
            set_user_auto_bet_error(int(user['id']), str(exc), error_at=now)
            logger.warning('Auto-bet prediction sync failed user=%s prediction_id=%s error=%s', user.get('id'), prediction_id, exc)
            return
        if not prediction:
            clear_user_auto_bet_prediction(int(user['id']))
            return
        status = str(prediction.get('status') or '').strip().upper()
        if status in {'CANCELED', 'RESOLVED'}:
            self._record_prediction_history(
                int(user['id']),
                settings,
                prediction,
                status=status,
                winning_outcome_id=str(prediction.get('winning_outcome_id') or ''),
            )
            clear_user_auto_bet_prediction(int(user['id']))
            return
        return

    async def _process_opendota_match(self, user: dict[str, Any], settings: dict[str, Any], now: float) -> bool:
        account_id = str(settings.get('dota_account_id') or '').strip()
        if not account_id:
            return False
        live_match = await self._find_live_opendota_match(account_id, now)
        if not live_match:
            return False
        match, player = live_match
        match_id = str(match.get('match_id') or '').strip()
        if not match_id:
            return False
        last_signature = str(settings.get('last_opened_stream_signature') or '')
        if last_signature == f'opendota:{match_id}' or last_signature.startswith(f'opendota-custom:{match_id}:'):
            return False
        lock_key = f'auto-open:{int(user["id"])}:dota2:{match_id}'
        if not self._begin_prediction_open(lock_key):
            return False

        try:
            hero_id = int(player.get('hero_id') or 0)
            hero_name = await self._opendota_hero_name(hero_id, now)
            game_name = f'Dota 2 - {hero_name}' if hero_name else 'Dota 2'
            market = await self._build_opendota_market(match, player, hero_name, settings, now)
            title = self._repair_mojibake_text(str(market['title']))
            outcomes_titles = [self._repair_mojibake_text(str(item)) for item in list(market['outcomes'])]
            stream_signature = str(market['signature'])
            try:
                prediction = await twitch_api.create_prediction_for_user(
                    user,
                    title=title,
                    prediction_window_seconds=int(settings.get('prediction_window_seconds') or 120),
                    outcomes=outcomes_titles,
                )
            except RuntimeError as exc:
                set_user_auto_bet_error(int(user['id']), str(exc), error_at=now)
                logger.warning('OpenDota auto-bet prediction was not opened user=%s match_id=%s error=%s', user.get('id'), match_id, exc)
                return False

            outcomes = prediction.get('outcomes') or []
            win_outcome_id = str(outcomes[0].get('id') or '') if len(outcomes) >= 1 and isinstance(outcomes[0], dict) else ''
            loss_outcome_id = str(outcomes[1].get('id') or '') if len(outcomes) >= 2 and isinstance(outcomes[1], dict) else ''
            set_user_auto_bet_prediction(
                int(user['id']),
                prediction_id=str(prediction.get('id') or ''),
                game_key='dota2',
                game_name=game_name,
                title=title.strip()[:45],
                win_outcome_id=win_outcome_id,
                loss_outcome_id=loss_outcome_id,
                win_outcome_title=outcomes_titles[0] if outcomes_titles else 'Победа',
                loss_outcome_title=outcomes_titles[1] if len(outcomes_titles) > 1 else 'Поражение',
                stream_signature=stream_signature,
            )
            logger.info('OpenDota auto-bet prediction opened user=%s match_id=%s hero=%s', user.get('id'), match_id, hero_name)
            return True
        finally:
            self._finish_prediction_open(lock_key)

    async def _open_gsi_prediction(
        self,
        user: dict[str, Any],
        settings: dict[str, Any],
        state: dict[str, Any],
        now: float,
    ) -> bool:
        match_id = str(state.get('match_id') or '').strip()
        if not match_id:
            return False
        last_signature = str(settings.get('last_opened_stream_signature') or '')
        if (
            last_signature == f'opendota:{match_id}'
            or last_signature.startswith(f'opendota-custom:{match_id}:')
            or last_signature.startswith(f'dota-gsi:{match_id}:')
        ):
            return False
        lock_key = f'auto-open:{int(user["id"])}:dota2:{match_id}'
        if not self._begin_prediction_open(lock_key):
            return False

        try:
            hero_name = str(state.get('hero_name') or '').strip() or 'Dota 2'
            hero_id = int(state.get('hero_id') or 0)
            market = await self._build_gsi_market(
                match_id,
                hero_id,
                hero_name,
                settings,
                state,
                now,
            )
            title = self._repair_mojibake_text(str(market['title']))
            outcomes_titles = [self._repair_mojibake_text(str(item)) for item in list(market['outcomes'])]
            stream_signature = str(market['signature'])
            try:
                prediction = await twitch_api.create_prediction_for_user(
                    user,
                    title=title,
                    prediction_window_seconds=int(settings.get('prediction_window_seconds') or 120),
                    outcomes=outcomes_titles,
                )
            except RuntimeError as exc:
                set_user_auto_bet_error(int(user['id']), str(exc), error_at=now)
                logger.warning('GSI auto-bet prediction was not opened user=%s match_id=%s error=%s', user.get('id'), match_id, exc)
                return False

            outcomes = prediction.get('outcomes') or []
            win_outcome_id = str(outcomes[0].get('id') or '') if len(outcomes) >= 1 and isinstance(outcomes[0], dict) else ''
            loss_outcome_id = str(outcomes[1].get('id') or '') if len(outcomes) >= 2 and isinstance(outcomes[1], dict) else ''
            set_user_auto_bet_prediction(
                int(user['id']),
                prediction_id=str(prediction.get('id') or ''),
                game_key='dota2',
                game_name=f'Dota 2 - {hero_name}' if hero_name else 'Dota 2',
                title=title.strip()[:45],
                win_outcome_id=win_outcome_id,
                loss_outcome_id=loss_outcome_id,
                win_outcome_title=outcomes_titles[0] if outcomes_titles else 'Победа',
                loss_outcome_title=outcomes_titles[1] if len(outcomes_titles) > 1 else 'Поражение',
                stream_signature=stream_signature,
            )
            logger.info('GSI auto-bet prediction opened user=%s match_id=%s hero=%s', user.get('id'), match_id, hero_name)
            return True
        finally:
            self._finish_prediction_open(lock_key)

    async def _open_cs2_gsi_prediction(
        self,
        user: dict[str, Any],
        settings: dict[str, Any],
        state: dict[str, Any],
        now: float,
    ) -> bool:
        match_id = str(state.get('match_id') or '').strip()
        if not match_id:
            return False
        last_signature = str(settings.get('last_opened_stream_signature') or '')
        if last_signature.startswith(f'cs2-gsi:{match_id}:'):
            return False
        lock_key = f'auto-open:{int(user["id"])}:cs2:{match_id}'
        if not self._begin_prediction_open(lock_key):
            return False

        try:
            market = self._build_cs2_gsi_market(
                match_id,
                {
                    **state,
                    'custom_questions_enabled': bool(settings.get('cs2_custom_questions_enabled')),
                    'custom_win_enabled': bool(settings.get('cs2_custom_win_enabled', True)),
                    'custom_kills_enabled': bool(settings.get('cs2_custom_kills_enabled', True)),
                    'custom_deaths_enabled': bool(settings.get('cs2_custom_deaths_enabled', True)),
                    'custom_assists_enabled': bool(settings.get('cs2_custom_assists_enabled', True)),
                },
            )
            title = self._repair_mojibake_text(str(market['title']))
            outcomes_titles = [self._repair_mojibake_text(str(item)) for item in list(market['outcomes'])]
            stream_signature = str(market['signature'])
            try:
                prediction = await twitch_api.create_prediction_for_user(
                    user,
                    title=title,
                    prediction_window_seconds=int(settings.get('prediction_window_seconds') or 120),
                    outcomes=outcomes_titles,
                )
            except RuntimeError as exc:
                set_user_auto_bet_error(int(user['id']), str(exc), error_at=now)
                logger.warning('CS2 GSI auto-bet prediction was not opened user=%s match_id=%s error=%s', user.get('id'), match_id, exc)
                return False

            outcomes = prediction.get('outcomes') or []
            win_outcome_id = str(outcomes[0].get('id') or '') if len(outcomes) >= 1 and isinstance(outcomes[0], dict) else ''
            loss_outcome_id = str(outcomes[1].get('id') or '') if len(outcomes) >= 2 and isinstance(outcomes[1], dict) else ''
            set_user_auto_bet_prediction(
                int(user['id']),
                prediction_id=str(prediction.get('id') or ''),
                game_key='cs2',
                game_name='CS2',
                title=title.strip()[:45],
                win_outcome_id=win_outcome_id,
                loss_outcome_id=loss_outcome_id,
                win_outcome_title=outcomes_titles[0] if outcomes_titles else 'Победа',
                loss_outcome_title=outcomes_titles[1] if len(outcomes_titles) > 1 else 'Поражение',
                stream_signature=stream_signature,
            )
            logger.info('CS2 GSI auto-bet prediction opened user=%s match_id=%s title=%s', user.get('id'), match_id, title)
            return True
        finally:
            self._finish_prediction_open(lock_key)

    async def _build_opendota_market(
        self,
        match: dict[str, Any],
        player: dict[str, Any],
        hero_name: str,
        settings: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        match_id = str(match.get('match_id') or '').strip()
        hero_id = int(player.get('hero_id') or 0)
        if not bool(settings.get('dota2_custom_questions_enabled')):
            title = f'{hero_name}: победа?' if hero_name else 'Dota 2: победа?'
            return {
                'title': title.strip()[:45],
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'opendota:{match_id}',
            }

        hero_label = hero_name or 'Герой'
        special_market = self._special_hero_market(match_id, hero_id, hero_label) if bool(settings.get('dota2_custom_hero_special_enabled', True)) else None
        if special_market:
            return special_market

        markets: list[dict[str, Any]] = []
        if bool(settings.get('dota2_custom_kills_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(player.get('kills') or 0),
                minimum=app_settings.autobet_dota_kills_min,
                maximum=app_settings.autobet_dota_kills_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: убийств > {threshold}?',
                'outcomes': None,
                'kind': 'kills_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_deaths_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(player.get('deaths') or 0),
                minimum=app_settings.autobet_dota_deaths_min,
                maximum=app_settings.autobet_dota_deaths_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: смертей > {threshold}?',
                'outcomes': None,
                'kind': 'deaths_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_assists_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(player.get('assists') or 0),
                minimum=app_settings.autobet_dota_assists_min,
                maximum=app_settings.autobet_dota_assists_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: ассистов > {threshold}?',
                'outcomes': None,
                'kind': 'assists_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_duration_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=max(0, int(match.get('game_time') or 0) // 60),
                minimum=app_settings.autobet_dota_duration_min,
                maximum=app_settings.autobet_dota_duration_max,
                absolute_minimum=1,
                absolute_maximum=240,
                current_offset=0,
            )
            markets.append({
                'title': f'Матч дольше {threshold} мин?',
                'outcomes': ['Да', 'Нет'],
                'kind': 'duration_over',
                'signature_value': threshold,
            })

        item_market = await self._random_item_market(match, now) if bool(settings.get('dota2_custom_items_enabled', True)) else None
        if item_market:
            markets.append(item_market)

        if not markets:
            title = f'{hero_name}: победа?' if hero_name else 'Dota 2: победа?'
            return {
                'title': title.strip()[:45],
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'opendota:{match_id}',
            }

        market = random.choice(markets)
        kind = str(market['kind'])
        threshold = self._market_threshold(market['title'])
        outcomes = market.get('outcomes') or [f'Больше {threshold}', f'Меньше/равно {threshold}']
        signature_value = str(market.get('signature_value') or threshold)
        return {
            'title': str(market['title']).strip()[:45],
            'outcomes': [str(outcomes[0])[:25], str(outcomes[1])[:25]],
            'signature': f'opendota-custom:{match_id}:{kind}:{signature_value}',
        }

    async def _build_gsi_market(
        self,
        match_id: str,
        hero_id: int,
        hero_name: str,
        settings: dict[str, Any],
        state: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        hero_label = hero_name or 'Герой'
        if not bool(settings.get('dota2_custom_questions_enabled')):
            return {
                'title': f'{hero_label}: победа?'[:45],
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'dota-gsi:{match_id}:win:0',
            }

        markets: list[dict[str, Any]] = []
        if bool(settings.get('dota2_custom_kills_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(state.get('kills') or 0),
                minimum=app_settings.autobet_dota_kills_min,
                maximum=app_settings.autobet_dota_kills_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: убийств > {threshold}?',
                'outcomes': None,
                'kind': 'kills_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_deaths_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(state.get('deaths') or 0),
                minimum=app_settings.autobet_dota_deaths_min,
                maximum=app_settings.autobet_dota_deaths_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: смертей > {threshold}?',
                'outcomes': None,
                'kind': 'deaths_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_assists_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=int(state.get('assists') or 0),
                minimum=app_settings.autobet_dota_assists_min,
                maximum=app_settings.autobet_dota_assists_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            markets.append({
                'title': f'{hero_label}: ассистов > {threshold}?',
                'outcomes': None,
                'kind': 'assists_over',
                'signature_value': threshold,
            })
        if bool(settings.get('dota2_custom_duration_enabled', True)):
            threshold = self._threshold_from_range(
                current_value=max(0, int(state.get('game_time') or 0) // 60),
                minimum=app_settings.autobet_dota_duration_min,
                maximum=app_settings.autobet_dota_duration_max,
                absolute_minimum=1,
                absolute_maximum=240,
                current_offset=0,
            )
            markets.append({
                'title': f'Матч дольше {threshold} мин?',
                'outcomes': ['Да', 'Нет'],
                'kind': 'duration_over',
                'signature_value': threshold,
            })

        if not markets:
            return {
                'title': f'{hero_label}: победа?'[:45],
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'dota-gsi:{match_id}:win:0',
            }
        market = random.choice(markets)
        kind = str(market['kind'])
        threshold = self._market_threshold(market['title'])
        outcomes = market.get('outcomes') or [f'Больше {threshold}', f'Меньше/равно {threshold}']
        signature_value = str(market.get('signature_value') or threshold)
        return {
            'title': str(market['title']).strip()[:45],
            'outcomes': [str(outcomes[0])[:25], str(outcomes[1])[:25]],
            'signature': f'dota-gsi:{match_id}:{kind}:{signature_value}',
        }

    def _build_cs2_gsi_market(self, match_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if not bool(state.get('custom_questions_enabled')):
            return {
                'title': 'CS2: победа?',
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'cs2-gsi:{match_id}:win:0',
            }
        enabled_kinds: list[str] = []
        if bool(state.get('custom_win_enabled', True)):
            enabled_kinds.append('win')
        if bool(state.get('custom_kills_enabled', True)):
            enabled_kinds.append('kills_over')
        if bool(state.get('custom_deaths_enabled', True)):
            enabled_kinds.append('deaths_over')
        if bool(state.get('custom_assists_enabled', True)):
            enabled_kinds.append('assists_over')
        kind = random.choice(enabled_kinds or ['win'])
        if kind == 'win':
            return {
                'title': 'CS2: победа?',
                'outcomes': ['Победа', 'Поражение'],
                'signature': f'cs2-gsi:{match_id}:win:0',
            }
        if kind == 'kills_over':
            threshold = self._cs2_kill_threshold(state)
            return {
                'title': f'CS2: киллов > {threshold}?',
                'outcomes': [f'Больше {threshold}', f'Меньше/равно {threshold}'],
                'signature': f'cs2-gsi:{match_id}:kills_over:{threshold}',
            }
        if kind == 'deaths_over':
            threshold = self._cs2_death_threshold(state)
            return {
                'title': f'CS2: смертей > {threshold}?',
                'outcomes': [f'Больше {threshold}', f'Меньше/равно {threshold}'],
                'signature': f'cs2-gsi:{match_id}:deaths_over:{threshold}',
            }
        threshold = self._cs2_assist_threshold(state)
        return {
            'title': f'CS2: ассистов > {threshold}?',
            'outcomes': [f'Больше {threshold}', f'Меньше/равно {threshold}'],
            'signature': f'cs2-gsi:{match_id}:assists_over:{threshold}',
        }

    def _special_hero_market(self, match_id: str, hero_id: int, hero_label: str) -> Optional[dict[str, Any]]:
        if hero_id == DOTA_HERO_PUDGE:
            threshold = self._threshold_from_range(
                current_value=0,
                minimum=app_settings.autobet_dota_pudge_flesh_heap_min,
                maximum=app_settings.autobet_dota_pudge_flesh_heap_max,
                absolute_minimum=0,
                absolute_maximum=999,
            )
            return {
                'title': f'{hero_label}: пассивок > {threshold}?',
                'outcomes': [f'Больше {threshold}', f'Меньше/равно {threshold}'],
                'signature': f'opendota-custom:{match_id}:pudge_flesh_heap_over:{threshold}',
            }
        if hero_id == DOTA_HERO_LEGION_COMMANDER:
            threshold = self._threshold_from_range(
                current_value=0,
                minimum=app_settings.autobet_dota_legion_duel_min,
                maximum=app_settings.autobet_dota_legion_duel_max,
                absolute_minimum=0,
                absolute_maximum=9999,
            )
            return {
                'title': f'{hero_label}: бонус дуэли > {threshold}?',
                'outcomes': [f'Больше {threshold}', f'Меньше/равно {threshold}'],
                'signature': f'opendota-custom:{match_id}:legion_duel_damage_over:{threshold}',
            }
        return None

    def _parse_gsi_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        map_state = payload.get('map') if isinstance(payload.get('map'), dict) else {}
        hero = payload.get('hero') if isinstance(payload.get('hero'), dict) else {}
        player = payload.get('player') if isinstance(payload.get('player'), dict) else {}
        allplayers = payload.get('allplayers') if isinstance(payload.get('allplayers'), dict) else {}
        match_id = (
            map_state.get('matchid')
            or map_state.get('match_id')
            or payload.get('matchid')
            or payload.get('match_id')
            or ''
        )
        hero_name = (
            hero.get('localized_name')
            or hero.get('name')
            or player.get('hero_name')
            or ''
        )
        normalized_hero_name = self._clean_gsi_hero_name(str(hero_name or '').strip())
        hero_id = self._int_value(hero.get('id') or hero.get('hero_id') or 0)
        if hero_id <= 0:
            hero_id = self._gsi_hero_id_from_name(str(hero.get('name') or hero_name or ''))
        return {
            'match_id': str(match_id or '').strip(),
            'game_state': str(map_state.get('game_state') or map_state.get('name') or '').strip(),
            'game_mode': str(map_state.get('game_mode') or map_state.get('mode') or payload.get('game_mode') or '').strip(),
            'lobby_type': str(map_state.get('lobby_type') or payload.get('lobby_type') or '').strip(),
            'game_time': self._int_value(map_state.get('clock_time') or map_state.get('game_time') or 0),
            'hero_id': hero_id,
            'hero_name': normalized_hero_name,
            'kills': self._int_value(player.get('kills') or 0),
            'deaths': self._int_value(player.get('deaths') or 0),
            'assists': self._int_value(player.get('assists') or 0),
            'player_team': str(player.get('team_name') or player.get('team') or hero.get('team_name') or '').strip(),
            'winner_team': str(map_state.get('win_team') or map_state.get('winner') or payload.get('winner') or '').strip(),
            'radiant_win': self._optional_bool(map_state.get('radiant_win') if 'radiant_win' in map_state else payload.get('radiant_win')),
            'allplayers': self._parse_gsi_allplayers(allplayers),
        }

    def _parse_cs2_gsi_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = payload.get('provider') if isinstance(payload.get('provider'), dict) else {}
        map_state = payload.get('map') if isinstance(payload.get('map'), dict) else {}
        round_state = payload.get('round') if isinstance(payload.get('round'), dict) else {}
        player = payload.get('player') if isinstance(payload.get('player'), dict) else {}
        player_id = payload.get('player_id') if isinstance(payload.get('player_id'), dict) else {}
        player_state = payload.get('player_state') if isinstance(payload.get('player_state'), dict) else {}
        match_stats = payload.get('player_match_stats') if isinstance(payload.get('player_match_stats'), dict) else {}
        allplayers = payload.get('allplayers') if isinstance(payload.get('allplayers'), dict) else {}
        if not match_stats and isinstance(player.get('match_stats'), dict):
            match_stats = player.get('match_stats')
        team_ct = map_state.get('team_ct') if isinstance(map_state.get('team_ct'), dict) else {}
        team_t = map_state.get('team_t') if isinstance(map_state.get('team_t'), dict) else {}
        local_steam_id = str(provider.get('steamid') or '').strip()
        player_id_steam_id = str(
            player_id.get('steamid')
            or player.get('steamid')
            or local_steam_id
            or ''
        ).strip()
        map_name = str(map_state.get('name') or '').strip()
        mode = str(map_state.get('mode') or '').strip().lower()
        stable_fallback_match_id = '-'.join(part for part in [player_id_steam_id, map_name, mode] if part)
        match_id = map_state.get('matchid') or map_state.get('match_id') or stable_fallback_match_id or ''
        local_player = self._find_cs2_local_player(allplayers, local_steam_id)
        local_match_stats = local_player.get('match_stats') if isinstance(local_player.get('match_stats'), dict) else {}
        local_state = local_player.get('state') if isinstance(local_player.get('state'), dict) else {}
        stats_reliable = bool(local_match_stats) or (bool(local_steam_id) and local_steam_id == player_id_steam_id)
        return {
            'match_id': str(match_id or '').strip(),
            'map_name': map_name,
            'mode': mode,
            'phase': str(map_state.get('phase') or round_state.get('phase') or '').strip().lower(),
            'round': self._int_value(map_state.get('round') or 0),
            'player_team': str(local_state.get('team') or player.get('team') or player_state.get('team') or '').strip().upper(),
            'kills': self._int_value(local_match_stats.get('kills') or match_stats.get('kills') or 0),
            'deaths': self._int_value(local_match_stats.get('deaths') or match_stats.get('deaths') or 0),
            'assists': self._int_value(local_match_stats.get('assists') or match_stats.get('assists') or 0),
            'ct_score': self._int_value(team_ct.get('score') or 0),
            't_score': self._int_value(team_t.get('score') or 0),
            'stats_reliable': stats_reliable,
        }

    @staticmethod
    def _find_cs2_local_player(allplayers: dict[str, Any], local_steam_id: str) -> dict[str, Any]:
        normalized_local_steam_id = str(local_steam_id or '').strip()
        if not normalized_local_steam_id or not allplayers:
            return {}
        direct_match = allplayers.get(normalized_local_steam_id)
        if isinstance(direct_match, dict):
            return direct_match
        for raw_player in allplayers.values():
            if not isinstance(raw_player, dict):
                continue
            raw_id = raw_player.get('id') if isinstance(raw_player.get('id'), dict) else {}
            if str(raw_id.get('steamid') or '').strip() == normalized_local_steam_id:
                return raw_player
        return {}

    @staticmethod
    def _active_cs2_match_id(settings: dict[str, Any]) -> str:
        signature = str(settings.get('last_opened_stream_signature') or '').strip()
        if signature.startswith('cs2-gsi:'):
            parts = signature.split(':')
            if len(parts) >= 4:
                return str(parts[1] or '').strip()
        return str(settings.get('gsi_match_id') or '').strip()

    def _parse_gsi_allplayers(self, allplayers: dict[str, Any]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for key, raw_player in allplayers.items():
            if not isinstance(raw_player, dict):
                continue
            raw_hero = raw_player.get('hero') if isinstance(raw_player.get('hero'), dict) else {}
            hero_name = (
                raw_hero.get('localized_name')
                or raw_hero.get('name')
                or raw_player.get('hero_name')
                or raw_player.get('hero')
                or ''
            )
            hero_id = self._int_value(raw_hero.get('id') or raw_hero.get('hero_id') or raw_player.get('hero_id') or 0)
            if hero_id <= 0:
                hero_id = self._gsi_hero_id_from_name(str(hero_name or ''))
            account_id = str(raw_player.get('accountid') or raw_player.get('account_id') or raw_player.get('accountid32') or '').strip()
            if account_id == '0':
                account_id = ''
            if hero_id <= 0 and not hero_name:
                continue
            parsed.append({
                'slot': str(key or ''),
                'account_id': account_id,
                'hero_id': hero_id,
                'hero_name': self._clean_gsi_hero_name(str(hero_name or '')),
            })
        return parsed

    @staticmethod
    def _clean_gsi_hero_name(value: str) -> str:
        hero_name = str(value or '').strip()
        if hero_name.startswith('npc_dota_hero_'):
            hero_name = hero_name.removeprefix('npc_dota_hero_').replace('_', ' ').title()
        return hero_name

    @staticmethod
    def _gsi_hero_id_from_name(value: str) -> int:
        normalized = str(value or '').strip().lower()
        if normalized.endswith('pudge') or normalized == 'pudge':
            return DOTA_HERO_PUDGE
        if normalized.endswith('legion_commander') or normalized in {'legion commander', 'legion_commander'}:
            return DOTA_HERO_LEGION_COMMANDER
        return 0

    @staticmethod
    def _gsi_game_is_in_progress(game_state: str) -> bool:
        normalized_state = str(game_state or '').upper()
        return 'GAME_IN_PROGRESS' in normalized_state or normalized_state in {'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS', 'GAME_IN_PROGRESS'}

    @staticmethod
    def _gsi_all_heroes_picked(state: dict[str, Any]) -> bool:
        players = state.get('allplayers') or []
        if not isinstance(players, list):
            return False
        picked = [player for player in players if isinstance(player, dict) and int(player.get('hero_id') or 0) > 0]
        if len(picked) < 10:
            return False
        unique_slots = {str(player.get('slot') or '').strip() for player in picked if str(player.get('slot') or '').strip()}
        if unique_slots:
            return len(unique_slots) >= 10
        return len(picked) >= 10

    @staticmethod
    def _gsi_has_live_match_signals(state: dict[str, Any]) -> bool:
        if AutoBetRuntime._gsi_match_is_finished(state):
            return False
        if int(state.get('hero_id') or 0) <= 0:
            return False
        return int(state.get('game_time') or 0) > 0

    @classmethod
    def _gsi_ready_for_prediction_open(cls, state: dict[str, Any]) -> bool:
        game_state = str(state.get('game_state') or '').strip()
        if cls._gsi_game_is_in_progress(game_state):
            return True
        if cls._gsi_match_is_finished(state):
            return False
        if cls._gsi_has_live_match_signals(state):
            return True
        return cls._gsi_all_heroes_picked(state)

    @staticmethod
    def _gsi_match_mode_is_allowed(state: dict[str, Any]) -> bool:
        raw_game_mode = str(state.get('game_mode') or '').strip()
        raw_lobby_type = str(state.get('lobby_type') or '').strip()
        normalized_mode = raw_game_mode.upper().replace(' ', '_')
        normalized_lobby = raw_lobby_type.upper().replace(' ', '_')
        blocked_markers = {'PRACTICE', 'TUTORIAL', 'DEMO'}

        if any(value in normalized_mode for value in blocked_markers):
            return False
        if any(value in normalized_lobby for value in blocked_markers):
            return False

        if raw_game_mode.isdigit():
            game_mode_value = int(raw_game_mode)
            # 1 = All Pick, 22 = Ranked All Pick, 23 = Turbo.
            if game_mode_value in {1, 22, 23}:
                return True
            # Real GSI payloads are not always consistent here; if the match is live and
            # the mode is not an explicit training/demo variant, allow it.
            if game_mode_value > 0:
                return True

        if any(value in normalized_mode for value in {'TURBO', 'RANKED_ALL_PICK', 'ALL_PICK', 'ALLPICK'}):
            return True

        if raw_lobby_type.isdigit() and int(raw_lobby_type) > 0:
            return True
        if 'RANKED' in normalized_lobby:
            return True

        if normalized_mode or normalized_lobby:
            return True

        return True

    @staticmethod
    def _gsi_match_is_finished(state: dict[str, Any]) -> bool:
        normalized_state = str(state.get('game_state') or '').upper()
        return any(value in normalized_state for value in {'POST_GAME', 'GAME_OVER', 'GAME_ENDED', 'DISCONNECT'})

    @staticmethod
    def _normalize_dota_team(value: Any) -> str:
        normalized = str(value or '').strip().lower().replace(' ', '_')
        if normalized in {'radiant', 'goodguys', '2'}:
            return 'radiant'
        if normalized in {'dire', 'badguys', '3'}:
            return 'dire'
        return ''

    @staticmethod
    def _optional_bool(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        normalized = str(value or '').strip().lower()
        if normalized in {'1', 'true', 'yes'}:
            return True
        if normalized in {'0', 'false', 'no'}:
            return False
        return None

    @staticmethod
    def _cs2_mode_is_allowed(state: dict[str, Any]) -> bool:
        mode = str(state.get('mode') or '').strip().lower()
        if mode in CS2_ALLOWED_MODES:
            return True
        return any(allowed in mode for allowed in CS2_ALLOWED_MODES)

    @staticmethod
    def _cs2_match_is_live(state: dict[str, Any]) -> bool:
        phase = str(state.get('phase') or '').strip().lower()
        return phase == 'live'

    @staticmethod
    def _cs2_match_is_finished(state: dict[str, Any]) -> bool:
        phase = str(state.get('phase') or '').strip().lower()
        if phase in {'over', 'gameover', 'matchover', 'postgame', 'game_over', 'match_over', 'ended'}:
            return True
        return any(token in phase for token in ('gameover', 'matchover', 'game_over', 'match_over'))

    @staticmethod
    def _cs2_kill_threshold(state: dict[str, Any]) -> int:
        return AutoBetRuntime._threshold_from_range(
            current_value=int(state.get('kills') or 0),
            minimum=app_settings.autobet_cs2_kills_min,
            maximum=app_settings.autobet_cs2_kills_max,
            absolute_minimum=0,
            absolute_maximum=999,
        )

    @staticmethod
    def _cs2_death_threshold(state: dict[str, Any]) -> int:
        return AutoBetRuntime._threshold_from_range(
            current_value=int(state.get('deaths') or 0),
            minimum=app_settings.autobet_cs2_deaths_min,
            maximum=app_settings.autobet_cs2_deaths_max,
            absolute_minimum=0,
            absolute_maximum=999,
        )

    @staticmethod
    def _cs2_assist_threshold(state: dict[str, Any]) -> int:
        return AutoBetRuntime._threshold_from_range(
            current_value=int(state.get('assists') or 0),
            minimum=app_settings.autobet_cs2_assists_min,
            maximum=app_settings.autobet_cs2_assists_max,
            absolute_minimum=0,
            absolute_maximum=999,
        )

    @staticmethod
    def _threshold_from_range(
        *,
        current_value: int,
        minimum: int,
        maximum: int,
        absolute_minimum: int,
        absolute_maximum: int,
        current_offset: int = 1,
    ) -> int:
        normalized_min = max(absolute_minimum, min(int(minimum), int(maximum)))
        normalized_max = min(absolute_maximum, max(int(minimum), int(maximum)))
        if normalized_max < normalized_min:
            normalized_max = normalized_min
        base_min = min(absolute_maximum, normalized_min)
        base_max = min(absolute_maximum, normalized_max)
        if base_max < base_min:
            base_max = base_min
        base_value = random.randint(base_min, base_max)
        current_floor = max(absolute_minimum, int(current_value or 0) + int(current_offset))
        return min(base_max, max(current_floor, base_value))

    async def _resolve_cs2_gsi_prediction(self, user: dict[str, Any], settings: dict[str, Any], state: dict[str, Any]) -> None:
        signature = str(settings.get('last_opened_stream_signature') or '')
        prediction_id = str(settings.get('active_prediction_id') or '').strip()
        if not prediction_id or not signature.startswith('cs2-gsi:') or not self._cs2_match_is_finished(state):
            return
        parts = signature.split(':')
        if len(parts) != 4:
            return
        _, match_id, kind, raw_value = parts
        if match_id and state.get('match_id') and str(state.get('match_id')) != str(match_id):
            return
        kills_value = int(state.get('kills') or settings.get('gsi_kills') or 0)
        deaths_value = int(state.get('deaths') or settings.get('gsi_deaths') or 0)
        assists_value = int(state.get('assists') or settings.get('gsi_assists') or 0)
        first_outcome_won: Optional[bool]
        if kind == 'kills_over':
            first_outcome_won = kills_value > self._int_value(raw_value)
        elif kind == 'deaths_over':
            first_outcome_won = deaths_value > self._int_value(raw_value)
        elif kind == 'assists_over':
            first_outcome_won = assists_value > self._int_value(raw_value)
        elif kind == 'win':
            player_team = str(state.get('player_team') or '').upper()
            ct_score = int(state.get('ct_score') or 0)
            t_score = int(state.get('t_score') or 0)
            if player_team == 'CT':
                first_outcome_won = ct_score > t_score
            elif player_team in {'T', 'TERRORIST'}:
                first_outcome_won = t_score > ct_score
            else:
                logger.info(
                    'CS2 GSI resolve skipped user=%s match_id=%s because player_team is unknown',
                    user.get('id'),
                    match_id,
                )
                return
        else:
            return
        if not bool(state.get('stats_reliable')) and kind in {'kills_over', 'deaths_over', 'assists_over'}:
            logger.info(
                'CS2 GSI resolve uses cached final stats user=%s match_id=%s kind=%s kills=%s deaths=%s assists=%s',
                user.get('id'),
                match_id,
                kind,
                kills_value,
                deaths_value,
                assists_value,
            )
        winning_outcome_id = str(
            (settings.get('win_outcome_id') if first_outcome_won else settings.get('loss_outcome_id')) or ''
        ).strip()
        if not winning_outcome_id:
            return
        ended_prediction = await twitch_api.end_prediction_for_user(
            user,
            prediction_id=prediction_id,
            status='RESOLVED',
            winning_outcome_id=winning_outcome_id,
        )
        self._record_prediction_history(int(user['id']), settings, ended_prediction, status='RESOLVED', winning_outcome_id=winning_outcome_id)
        clear_user_auto_bet_prediction(int(user['id']))
        logger.info('CS2 GSI auto-bet prediction resolved user=%s match_id=%s first_outcome_won=%s', user.get('id'), match_id, first_outcome_won)

    async def _resolve_dota_gsi_prediction(self, user: dict[str, Any], settings: dict[str, Any], state: dict[str, Any]) -> None:
        signature = str(settings.get('last_opened_stream_signature') or '')
        prediction_id = str(settings.get('active_prediction_id') or '').strip()
        if not prediction_id or not signature.startswith('dota-gsi:') or not self._gsi_match_is_finished(state):
            return
        parts = signature.split(':')
        if len(parts) != 4:
            return
        _, match_id, kind, raw_value = parts
        if match_id and state.get('match_id') and str(state.get('match_id')) != str(match_id):
            return
        first_outcome_won: Optional[bool]
        if kind == 'kills_over':
            first_outcome_won = int(state.get('kills') or 0) > self._int_value(raw_value)
        elif kind == 'deaths_over':
            first_outcome_won = int(state.get('deaths') or 0) > self._int_value(raw_value)
        elif kind == 'assists_over':
            first_outcome_won = int(state.get('assists') or 0) > self._int_value(raw_value)
        elif kind == 'duration_over':
            first_outcome_won = int(state.get('game_time') or 0) > self._int_value(raw_value) * 60
        elif kind == 'win':
            player_team = self._normalize_dota_team(state.get('player_team'))
            winner_team = self._normalize_dota_team(state.get('winner_team'))
            radiant_win = state.get('radiant_win')
            if player_team and isinstance(radiant_win, bool):
                first_outcome_won = radiant_win if player_team == 'radiant' else not radiant_win
            elif player_team and winner_team:
                first_outcome_won = player_team == winner_team
            else:
                set_user_auto_bet_error(
                    int(user['id']),
                    'Dota GSI не прислал понятный итог матча. Закрой ставку вручную или дождись следующего обновления.',
                    error_at=time.time(),
                )
                logger.info(
                    'Dota GSI resolve skipped user=%s match_id=%s because winner data is missing',
                    user.get('id'),
                    match_id,
                )
                return
        else:
            return
        winning_outcome_id = str(
            (settings.get('win_outcome_id') if first_outcome_won else settings.get('loss_outcome_id')) or ''
        ).strip()
        if not winning_outcome_id:
            return
        ended_prediction = await twitch_api.end_prediction_for_user(
            user,
            prediction_id=prediction_id,
            status='RESOLVED',
            winning_outcome_id=winning_outcome_id,
        )
        self._record_prediction_history(int(user['id']), settings, ended_prediction, status='RESOLVED', winning_outcome_id=winning_outcome_id)
        clear_user_auto_bet_prediction(int(user['id']))
        logger.info('Dota GSI auto-bet prediction resolved user=%s match_id=%s first_outcome_won=%s', user.get('id'), match_id, first_outcome_won)

    async def _random_item_market(self, match: dict[str, Any], now: float) -> Optional[dict[str, Any]]:
        match_id = str(match.get('match_id') or '').strip()
        target_players = [
            player
            for player in match.get('players') or []
            if int(player.get('hero_id') or 0) > 0
        ]
        if not target_players:
            return None
        target_player = random.choice(target_players)
        target_account_id = str(target_player.get('account_id') or '').strip()
        if target_account_id == '0':
            target_account_id = ''
        target_hero_id = int(target_player.get('hero_id') or 0)
        target_hero_name = await self._opendota_hero_name(target_hero_id, now)
        target_label = target_hero_name or 'Герой'
        items = await self._opendota_items(now)
        candidates: list[dict[str, Any]] = []
        for item_key, label in DOTA_CUSTOM_ITEM_KEYS:
            item = items.get(item_key) or {}
            item_id = int(item.get('id') or 0)
            if item_id > 0:
                candidates.append({
                    'title': f'{target_label}: соберет {label}?',
                    'outcomes': ['Да', 'Нет'],
                    'kind': 'item_built',
                    'signature_value': f'{item_id},{item_key},{target_account_id},{target_hero_id}',
                })
        if not candidates:
            return None
        return random.choice(candidates)

    async def _random_gsi_item_market(self, state: dict[str, Any], now: float) -> Optional[dict[str, Any]]:
        target_players = [
            player
            for player in state.get('allplayers') or []
            if int(player.get('hero_id') or 0) > 0
        ]
        if not target_players:
            return None
        target_player = random.choice(target_players)
        target_account_id = str(target_player.get('account_id') or '').strip()
        target_hero_id = int(target_player.get('hero_id') or 0)
        target_label = str(target_player.get('hero_name') or '').strip()
        if not target_label and target_hero_id > 0:
            target_label = await self._opendota_hero_name(target_hero_id, now)
        target_label = target_label or 'Герой'
        items = await self._opendota_items(now)
        candidates: list[dict[str, Any]] = []
        for item_key, label in DOTA_CUSTOM_ITEM_KEYS:
            item = items.get(item_key) or {}
            item_id = int(item.get('id') or 0)
            if item_id > 0:
                candidates.append({
                    'title': f'{target_label}: соберет {label}?',
                    'outcomes': ['Да', 'Нет'],
                    'kind': 'item_built',
                    'signature_value': f'{item_id},{item_key},{target_account_id},{target_hero_id}',
                })
        if not candidates:
            return None
        return random.choice(candidates)

    @staticmethod
    def _market_threshold(title: str) -> int:
        digits = ''.join(ch if ch.isdigit() else ' ' for ch in title).split()
        return int(digits[-1]) if digits else 0

    async def _resolve_finished_opendota_match(self, user: dict[str, Any], settings: dict[str, Any], now: float) -> None:
        signature = str(settings.get('last_opened_stream_signature') or '')
        if not signature.startswith('opendota:') and not signature.startswith('opendota-custom:'):
            return
        if str(settings.get('active_game_key') or '') != 'dota2':
            return
        account_id = str(settings.get('dota_account_id') or '').strip()
        prediction_id = str(settings.get('active_prediction_id') or '').strip()
        if not account_id or not prediction_id:
            return
        if signature.startswith('opendota-custom:'):
            result = await self._get_custom_opendota_result(account_id, signature)
        else:
            match_id = signature.split(':', 1)[1]
            match_result = await self._get_finished_opendota_match(account_id, match_id)
            result = {'first_outcome_won': bool(match_result['won']), 'match_id': match_id, **match_result} if match_result else None
        if not result:
            return
        outcome_value = settings.get('win_outcome_id') if result['first_outcome_won'] else settings.get('loss_outcome_id')
        winning_outcome_id = str(outcome_value or '').strip()
        if not winning_outcome_id:
            return
        ended_prediction = await twitch_api.end_prediction_for_user(
            user,
            prediction_id=prediction_id,
            status='RESOLVED',
            winning_outcome_id=winning_outcome_id,
        )
        self._record_prediction_history(int(user['id']), settings, ended_prediction, status='RESOLVED', winning_outcome_id=winning_outcome_id)
        clear_user_auto_bet_prediction(int(user['id']))
        logger.info(
            'OpenDota auto-bet prediction resolved user=%s match_id=%s first_outcome_won=%s kda=%s/%s/%s',
            user.get('id'),
            result.get('match_id') or '',
            result['first_outcome_won'],
            result.get('kills'),
            result.get('deaths'),
            result.get('assists'),
        )

    @staticmethod
    def _repair_mojibake_text(value: str) -> str:
        raw = str(value or '')
        if not raw or ('Р' not in raw and 'С' not in raw):
            return raw
        try:
            return raw.encode('cp1251').decode('utf-8')
        except Exception:
            return raw

    @staticmethod
    def _cache_get_cached_at(key: str) -> float:
        meta = runtime_state.get(f'{key}:meta')
        if not isinstance(meta, dict):
            return 0.0
        try:
            return float(meta.get('cached_at') or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _cache_get(key: str) -> Any:
        return runtime_state.get(key)

    @staticmethod
    def _cache_set(key: str, value: Any, *, now: float, ttl_seconds: float) -> None:
        runtime_state.set(key, value, ttl_seconds=ttl_seconds)
        runtime_state.set(f'{key}:meta', {'cached_at': now}, ttl_seconds=ttl_seconds)

    def _get_opendota_throttle_state(self, now: float) -> Optional[dict[str, Any]]:
        state = runtime_state.get('opendota:cooldown')
        if not isinstance(state, dict):
            self._set_opendota_cooldown_gauges(0.0)
            return None
        try:
            until = float(state.get('until') or 0.0)
        except (TypeError, ValueError):
            until = 0.0
        remaining_seconds = max(0.0, until - float(now))
        if remaining_seconds <= 0:
            runtime_state.delete('opendota:cooldown')
            runtime_state.delete('opendota:cooldown:meta')
            self._set_opendota_cooldown_gauges(0.0)
            return None
        self._set_opendota_cooldown_gauges(remaining_seconds)
        return {
            'until': until,
            'remaining_seconds': remaining_seconds,
            'source': str(state.get('source') or ''),
        }

    def _activate_opendota_throttle(self, now: float, *, source: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        until = float(now) + self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS
        state = {
            'until': until,
            'source': str(source or 'opendota'),
        }
        runtime_state.set('opendota:cooldown', state, ttl_seconds=self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS)
        runtime_state.set(
            'opendota:cooldown:meta',
            {'cached_at': now},
            ttl_seconds=self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS,
        )
        self._set_opendota_cooldown_gauges(self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS)
        service_metrics.increment('opendota.cooldowns')
        service_metrics.record_error(
            str(source or 'opendota'),
            self._opendota_throttle_message({'remaining_seconds': self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS}),
            context=context,
        )
        return {
            'until': until,
            'remaining_seconds': self.OPENDOTA_RATE_LIMIT_COOLDOWN_SECONDS,
            'source': str(source or 'opendota'),
        }

    @staticmethod
    def _set_opendota_cooldown_gauges(remaining_seconds: float) -> None:
        remaining = max(0.0, float(remaining_seconds or 0.0))
        service_metrics.set_gauge('opendota.cooldown_remaining_seconds', remaining)
        service_metrics.set_gauge('opendota.cooldown_active', 1.0 if remaining > 0 else 0.0)

    @staticmethod
    def _is_opendota_rate_limited_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            response = getattr(exc, 'response', None)
            return response is not None and int(getattr(response, 'status_code', 0) or 0) == 429
        message = str(exc or '').lower()
        return '429' in message and 'too many requests' in message

    def _opendota_throttle_message(self, throttle_state: Optional[dict[str, Any]]) -> str:
        remaining_seconds = float((throttle_state or {}).get('remaining_seconds') or 0.0)
        if remaining_seconds > 0:
            return f'OpenDota упёрся в лимит запросов. Работаем из кэша ещё примерно {int(max(1.0, remaining_seconds))} сек.'
        return 'OpenDota упёрся в лимит запросов. Временно работаем из кэша.'

    def _decorate_opendota_payload(
        self,
        payload: Any,
        throttle_state: Optional[dict[str, Any]],
        *,
        fallback_message: str = '',
    ) -> dict[str, Any]:
        decorated = dict(payload or {})
        decorated['throttled'] = bool(throttle_state)
        decorated['degraded'] = bool(throttle_state)
        decorated['cooldown_seconds'] = int(max(0.0, float((throttle_state or {}).get('remaining_seconds') or 0.0)))
        if throttle_state:
            decorated['error'] = fallback_message or self._opendota_throttle_message(throttle_state)
        return decorated

    @staticmethod
    def _clear_opendota_degraded_flags(payload: Any) -> dict[str, Any]:
        cleaned = dict(payload or {})
        cleaned.pop('throttled', None)
        cleaned.pop('degraded', None)
        cleaned.pop('cooldown_seconds', None)
        if str(cleaned.get('error') or '').startswith('OpenDota упёрся в лимит запросов'):
            cleaned['error'] = ''
        return cleaned

    async def _opendota_get_json(self, url: str, *, now: float, timeout: float, metric_key: str) -> Any:
        throttle_state = self._get_opendota_throttle_state(now)
        if throttle_state:
            service_metrics.increment(f'{metric_key}.throttled')
            raise OpenDotaThrottledError(self._opendota_throttle_message(throttle_state))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
            self._set_opendota_cooldown_gauges(0.0)
            return response.json() or {}
        except Exception as exc:
            if self._is_opendota_rate_limited_error(exc):
                service_metrics.increment(f'{metric_key}.rate_limited')
                throttle_state = self._activate_opendota_throttle(now, source=metric_key, context={'url': url})
                raise OpenDotaThrottledError(self._opendota_throttle_message(throttle_state)) from exc
            raise

    async def _get_opendota_profile(self, account_id: str, now: float) -> dict[str, Any]:
        normalized_account_id = str(account_id or '').strip()
        cache_key = f'opendota:profile:{normalized_account_id}'
        cached_payload = self._cache_get(cache_key) or {}
        cached_at = self._cache_get_cached_at(cache_key)
        if cached_payload and now - cached_at < 60:
            return dict(cached_payload)
        throttle_state = self._get_opendota_throttle_state(now)
        if throttle_state:
            if cached_payload:
                return dict(cached_payload)
            raise OpenDotaThrottledError(self._opendota_throttle_message(throttle_state))
        payload = await self._opendota_get_json(
            f'https://api.opendota.com/api/players/{normalized_account_id}',
            now=now,
            timeout=8,
            metric_key='opendota.status',
        ) or {}
        self._cache_set(cache_key, payload, now=now, ttl_seconds=self.OPENDOTA_PROFILE_CACHE_TTL_SECONDS)
        return dict(payload)

    async def _get_opendota_recent_matches(self, account_id: str, now: float) -> list[dict[str, Any]]:
        normalized_account_id = str(account_id or '').strip()
        cache_key = f'opendota:recent-matches:{normalized_account_id}'
        cached_matches = self._cache_get(cache_key) or []
        cached_at = self._cache_get_cached_at(cache_key)
        if now - cached_at < 30:
            return list(cached_matches)
        throttle_state = self._get_opendota_throttle_state(now)
        if throttle_state:
            if cached_matches:
                return list(cached_matches)
            raise OpenDotaThrottledError(self._opendota_throttle_message(throttle_state))
        payload = await self._opendota_get_json(
            f'https://api.opendota.com/api/players/{normalized_account_id}/recentMatches',
            now=now,
            timeout=15,
            metric_key='opendota.status',
        ) or []
        matches = list(payload)
        self._cache_set(cache_key, matches, now=now, ttl_seconds=self.OPENDOTA_RECENT_MATCHES_CACHE_TTL_SECONDS)
        return matches

    def _begin_prediction_open(self, lock_key: str) -> bool:
        normalized_key = str(lock_key or '').strip()
        if not normalized_key:
            return True
        return runtime_state.acquire_lock(
            f'autobet-open:{normalized_key}',
            ttl_seconds=self.PREDICTION_OPEN_LOCK_TTL_SECONDS,
        )

    def _finish_prediction_open(self, lock_key: str) -> None:
        normalized_key = str(lock_key or '').strip()
        if not normalized_key:
            return
        runtime_state.release_lock(f'autobet-open:{normalized_key}')

    def _prediction_title(self, settings: dict[str, Any], game_name: str) -> str:
        template = self._repair_mojibake_text(str(settings.get('prediction_title_template') or '').strip()) or 'Матч {game}: победа?'
        try:
            title = template.format(game=game_name)
        except (KeyError, ValueError):
            title = f'{game_name}: победа?'
        return self._repair_mojibake_text(title).strip()[:45] or 'Матч: победа?'

    def _record_prediction_history(
        self,
        user_id: int,
        settings: dict[str, Any],
        prediction: Optional[dict[str, Any]],
        *,
        status: str,
        winning_outcome_id: str,
    ) -> None:
        outcomes = list((prediction or {}).get('outcomes') or [])
        total_points = sum(int(outcome.get('channel_points') or 0) for outcome in outcomes if isinstance(outcome, dict))
        total_users = sum(int(outcome.get('users') or 0) for outcome in outcomes if isinstance(outcome, dict))
        outcome_title = 'Отмена'
        if str(status or '').upper() == 'RESOLVED':
            if winning_outcome_id:
                outcome_title = self._outcome_title_by_id(outcomes, winning_outcome_id) or (
                    str(settings.get('win_outcome_title') or 'Победа')
                    if str(winning_outcome_id or '') == str(settings.get('win_outcome_id') or '')
                    else str(settings.get('loss_outcome_title') or 'Поражение')
                )
            else:
                outcome_title = 'Завершена'
        add_user_auto_bet_history(
            int(user_id),
            prediction_id=str((prediction or {}).get('id') or settings.get('active_prediction_id') or ''),
            game_key=str(settings.get('active_game_key') or ''),
            game_name=str(settings.get('active_game_name') or ''),
            title=str((prediction or {}).get('title') or settings.get('active_prediction_title') or ''),
            outcome_title=self._repair_mojibake_text(outcome_title),
            status=str(status or ''),
            total_channel_points=total_points,
            total_users=total_users,
        )

    @staticmethod
    def _outcome_title_by_id(outcomes: list[Any], outcome_id: str) -> str:
        normalized_outcome_id = str(outcome_id or '')
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            if str(outcome.get('id') or '') == normalized_outcome_id:
                return str(outcome.get('title') or '')
        return ''


    async def _find_live_opendota_match(self, account_id: str, now: float) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
        matches = await self._get_opendota_live_matches(now)
        normalized_account_id = str(account_id or '').strip()
        for match in matches:
            for player in match.get('players') or []:
                if str(player.get('account_id') or '').strip() == normalized_account_id:
                    return match, player
        return None

    async def _get_opendota_live_matches(self, now: float) -> list[dict[str, Any]]:
        cache_key = 'opendota:live'
        started_at = time.perf_counter()
        cached_matches = self._cache_get(cache_key) or []
        cached_at = self._cache_get_cached_at(cache_key)
        if now - cached_at < 30:
            service_metrics.increment('opendota.live.cache_hits')
            service_metrics.observe_duration('opendota.live', time.perf_counter() - started_at)
            return cached_matches
        throttle_state = self._get_opendota_throttle_state(now)
        if throttle_state:
            service_metrics.increment('opendota.live.cache_hits')
            service_metrics.increment('opendota.live.throttled')
            service_metrics.observe_duration('opendota.live', time.perf_counter() - started_at)
            return cached_matches
        service_metrics.increment('opendota.live.cache_misses')
        try:
            matches = list(
                await self._opendota_get_json(
                    'https://api.opendota.com/api/live',
                    now=now,
                    timeout=15,
                    metric_key='opendota.live',
                ) or []
            )
        except OpenDotaThrottledError as exc:
            service_metrics.increment('opendota.live.throttled')
            logger.warning('Failed to fetch OpenDota live matches: %s', exc)
            matches = cached_matches
        except Exception as exc:
            service_metrics.increment('opendota.live.failures')
            service_metrics.record_error('opendota.live', str(exc))
            logger.warning('Failed to fetch OpenDota live matches: %s', exc)
            matches = cached_matches
        self._cache_set(cache_key, matches, now=now, ttl_seconds=self.OPENDOTA_LIVE_CACHE_TTL_SECONDS)
        service_metrics.observe_duration('opendota.live', time.perf_counter() - started_at)
        return matches

    async def _opendota_hero_name(self, hero_id: int, now: float) -> str:
        cache_key = 'opendota:heroes'
        cached_heroes = self._cache_get(cache_key) or {}
        cached_at = self._cache_get_cached_at(cache_key)
        if now - cached_at >= 86400 or not cached_heroes:
            try:
                payload = await self._opendota_get_json(
                    'https://api.opendota.com/api/heroes',
                    now=now,
                    timeout=15,
                    metric_key='opendota.reference',
                )
                cached_heroes = {
                    int(hero.get('id')): str(hero.get('localized_name') or '')
                    for hero in payload or []
                    if hero.get('id') is not None
                }
                self._cache_set(cache_key, cached_heroes, now=now, ttl_seconds=self.OPENDOTA_REFERENCE_CACHE_TTL_SECONDS)
            except OpenDotaThrottledError:
                pass
            except Exception as exc:
                logger.warning('Failed to fetch OpenDota heroes: %s', exc)
        return str(cached_heroes.get(int(hero_id), '') or '')

    async def _opendota_items(self, now: float) -> dict[str, dict[str, Any]]:
        cache_key = 'opendota:items'
        cached_items = self._cache_get(cache_key) or {}
        cached_at = self._cache_get_cached_at(cache_key)
        if now - cached_at >= 86400 or not cached_items:
            try:
                payload = await self._opendota_get_json(
                    'https://api.opendota.com/api/constants/items',
                    now=now,
                    timeout=15,
                    metric_key='opendota.reference',
                ) or {}
                cached_items = {
                    str(key): dict(value)
                    for key, value in payload.items()
                    if isinstance(value, dict)
                }
                self._cache_set(cache_key, cached_items, now=now, ttl_seconds=self.OPENDOTA_REFERENCE_CACHE_TTL_SECONDS)
            except OpenDotaThrottledError:
                pass
            except Exception as exc:
                logger.warning('Failed to fetch OpenDota items: %s', exc)
        return cached_items

    async def _get_custom_opendota_result(self, account_id: str, signature: str) -> Optional[dict[str, Any]]:
        parts = signature.split(':')
        if len(parts) != 4:
            return None
        _, match_id, kind, raw_value = parts
        recent_match = await self._get_finished_opendota_match(account_id, match_id)
        if not recent_match:
            return None
        first_outcome_won: Optional[bool]

        if kind == 'kills_over':
            value = self._int_value(raw_value)
            first_outcome_won = int(recent_match.get('kills') or 0) > value
        elif kind == 'deaths_over':
            value = self._int_value(raw_value)
            first_outcome_won = int(recent_match.get('deaths') or 0) > value
        elif kind == 'assists_over':
            value = self._int_value(raw_value)
            first_outcome_won = int(recent_match.get('assists') or 0) > value
        elif kind == 'duration_over':
            value = self._int_value(raw_value)
            first_outcome_won = int(recent_match.get('duration') or 0) > value * 60
        elif kind == 'item_built':
            item_id, item_key, target_account_id, target_hero_id = self._parse_item_market_value(raw_value)
            first_outcome_won = await self._player_has_item(
                target_account_id,
                match_id,
                item_id,
                item_key=item_key,
                hero_id=target_hero_id,
            )
            if first_outcome_won is None:
                return None
        elif kind == 'pudge_flesh_heap_over':
            value = self._int_value(raw_value)
            stack_count = await self._player_permanent_buff_stack(account_id, match_id, DOTA_BUFF_PUDGE_FLESH_HEAP)
            if stack_count is None:
                return None
            first_outcome_won = stack_count > value
        elif kind == 'legion_duel_damage_over':
            value = self._int_value(raw_value)
            stack_count = await self._player_permanent_buff_stack(account_id, match_id, DOTA_BUFF_LEGION_COMMANDER_DUEL)
            if stack_count is None:
                return None
            first_outcome_won = stack_count > value
        else:
            return None

        return {
            'first_outcome_won': first_outcome_won,
            'match_id': match_id,
            **recent_match,
        }

    @staticmethod
    def _int_value(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_item_market_value(value: str) -> tuple[int, str, str, int]:
        parts = str(value or '').split(',')
        item_id = AutoBetRuntime._int_value(parts[0] if parts else '')
        if len(parts) >= 4:
            item_key = parts[1]
            target_account_id = parts[2]
            target_hero_id = AutoBetRuntime._int_value(parts[3])
        else:
            # Backward-compatible parser for active predictions created before item_key was stored.
            item_key = ''
            target_account_id = parts[1] if len(parts) > 1 else ''
            target_hero_id = AutoBetRuntime._int_value(parts[2] if len(parts) > 2 else '')
        return item_id, item_key, target_account_id, target_hero_id

    async def _player_permanent_buff_stack(self, account_id: str, match_id: str, buff_id: int) -> Optional[int]:
        player = await self._get_full_match_player(account_id, match_id)
        if not player:
            return None
        if 'permanent_buffs' not in player or player.get('permanent_buffs') is None:
            return None
        for buff in player.get('permanent_buffs') or []:
            if int(buff.get('permanent_buff') or 0) == int(buff_id):
                return int(buff.get('stack_count') or 0)
        return 0

    async def _player_has_item(
        self,
        account_id: str,
        match_id: str,
        item_id: int,
        *,
        item_key: str = '',
        hero_id: int = 0,
    ) -> Optional[bool]:
        if item_id <= 0:
            return None
        player = await self._get_full_match_player(account_id, match_id, hero_id=hero_id)
        if not player:
            return None
        item_keys = await self._opendota_item_keys_for_id(item_id, time.time())
        if item_key:
            item_keys.add(str(item_key))

        purchase = player.get('purchase')
        if isinstance(purchase, dict):
            for key in item_keys:
                if int(purchase.get(key) or 0) > 0:
                    return True
            if int(purchase.get(str(item_id)) or 0) > 0:
                return True

        purchase_log = player.get('purchase_log')
        if isinstance(purchase_log, list):
            for entry in purchase_log:
                if not isinstance(entry, dict):
                    continue
                purchased_key = str(entry.get('key') or '').strip()
                if purchased_key in item_keys or purchased_key == str(item_id):
                    return True

        item_ids = {
            int(player.get(field) or 0)
            for field in (
                'item_0',
                'item_1',
                'item_2',
                'item_3',
                'item_4',
                'item_5',
                'backpack_0',
                'backpack_1',
                'backpack_2',
                'item_neutral',
            )
        }
        return int(item_id) in item_ids

    async def _opendota_item_keys_for_id(self, item_id: int, now: float) -> set[str]:
        if item_id <= 0:
            return set()
        items = await self._opendota_items(now)
        return {
            str(key)
            for key, item in items.items()
            if int(item.get('id') or 0) == int(item_id)
        }

    async def _get_full_match_player(self, account_id: str, match_id: str, *, hero_id: int = 0) -> Optional[dict[str, Any]]:
        now = time.time()
        cache_key = f'opendota:match-details:{match_id}'
        payload = self._cache_get(cache_key) or {}
        cached_at = self._cache_get_cached_at(cache_key)
        if not payload or now - cached_at >= 60:
            try:
                payload = await self._opendota_get_json(
                    f'https://api.opendota.com/api/matches/{match_id}',
                    now=now,
                    timeout=20,
                    metric_key='opendota.match',
                ) or {}
                self._cache_set(cache_key, payload, now=now, ttl_seconds=self.OPENDOTA_MATCH_DETAILS_CACHE_TTL_SECONDS)
            except OpenDotaThrottledError:
                payload = payload or {}
            except Exception as exc:
                logger.warning('Failed to fetch OpenDota match details match_id=%s: %s', match_id, exc)
                payload = payload or {}
        if not payload:
            return None

        players = list(payload.get('players') or [])
        normalized_account_id = str(account_id or '').strip()
        if normalized_account_id == '0':
            normalized_account_id = ''
        for player in players:
            if not normalized_account_id:
                continue
            if str(player.get('account_id') or '').strip() != normalized_account_id:
                continue
            return player
        if hero_id > 0:
            for player in players:
                if int(player.get('hero_id') or 0) == int(hero_id):
                    return player
        return None

    async def _get_finished_opendota_match(self, account_id: str, match_id: str) -> Optional[dict[str, Any]]:
        try:
            matches = await self._get_opendota_recent_matches(account_id, time.time())
        except OpenDotaThrottledError:
            return None
        except Exception as exc:
            logger.warning('Failed to fetch OpenDota recent matches account_id=%s: %s', account_id, exc)
            return None

        for match in matches:
            if str(match.get('match_id') or '').strip() != str(match_id):
                continue
            player_slot = int(match.get('player_slot') or 0)
            is_radiant = player_slot < 128
            radiant_win = bool(match.get('radiant_win'))
            return {
                'won': radiant_win == is_radiant,
                'match_id': str(match.get('match_id') or ''),
                'kills': int(match.get('kills') or 0),
                'deaths': int(match.get('deaths') or 0),
                'assists': int(match.get('assists') or 0),
                'hero_id': int(match.get('hero_id') or 0),
                'duration': int(match.get('duration') or 0),
            }
        return None


auto_bet_runtime = AutoBetRuntime()

