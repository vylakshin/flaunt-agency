import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .twitch_api import twitch_api


GIVEAWAY_TYPES = {'active', 'keyword', 'points'}
DEFAULT_POINTS_REWARD_TITLE = 'Участвовать в розыгрыше'
DEFAULT_POINTS_REWARD_COST = 100
DEFAULT_MULTIPLIERS = {
    'default': 1.0,
    'follower': 1.0,
    'vip': 1.0,
    'subscriber': 1.0,
}

logger = logging.getLogger(__name__)


@dataclass
class GiveawayParticipant:
    user_id: str
    login: str
    display_name: str
    is_follower: bool = False
    is_vip: bool = False
    is_subscriber: bool = False
    entry_count: int = 1
    message_count: int = 0
    last_message_at: float = 0


@dataclass
class GiveawayState:
    running: bool = False
    giveaway_type: str = 'active'
    keyword: str = ''
    chat_announcements: bool = False
    points_reward_title: str = DEFAULT_POINTS_REWARD_TITLE
    points_reward_cost: int = DEFAULT_POINTS_REWARD_COST
    points_allow_multiple_entries: bool = False
    points_reward_id: str = ''
    multipliers: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MULTIPLIERS))
    participants: dict[str, GiveawayParticipant] = field(default_factory=dict)
    ignored_participants: set[str] = field(default_factory=set)
    winner_login: str = ''
    winner_messages: list[dict[str, Any]] = field(default_factory=list)
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    wheel_eliminated_logins: set[str] = field(default_factory=set)
    wheel_last_result_login: str = ''
    wheel_last_mode: str = 'normal'
    wheel_last_source: str = ''


class GiveawayRuntime:
    def __init__(self) -> None:
        self._states: dict[int, GiveawayState] = {}

    def get_state(self, owner_id: int) -> GiveawayState:
        state = self._states.get(owner_id)
        if state is None:
            state = GiveawayState()
            self._states[owner_id] = state
        return state

    def payload(self, owner: dict[str, Any]) -> dict[str, Any]:
        state = self.get_state(int(owner['id']))
        winner = state.participants.get(state.winner_login) if state.winner_login else None
        return {
            'running': state.running,
            'giveaway_type': state.giveaway_type,
            'keyword': state.keyword,
            'chat_announcements': state.chat_announcements,
            'points_reward_title': state.points_reward_title,
            'points_reward_cost': state.points_reward_cost,
            'points_allow_multiple_entries': state.points_allow_multiple_entries,
            'points_reward_id': state.points_reward_id,
            'points_reward_ready': bool(state.points_reward_id),
            'multipliers': dict(state.multipliers),
            'participants': [
                self._participant_payload(participant, state)
                for participant in sorted(
                    state.participants.values(),
                    key=lambda item: (-item.last_message_at, item.login),
                )
            ],
            'winner': self._participant_payload(winner, state) if winner else None,
            'winner_messages': list(state.winner_messages[-100:]),
            'recent_messages': list(state.recent_messages[-100:]),
            'wheel_eliminated_logins': sorted(state.wheel_eliminated_logins),
            'wheel_last_result': self._participant_payload(
                state.participants.get(state.wheel_last_result_login),
                state,
            ) if state.wheel_last_result_login else None,
            'wheel_last_mode': state.wheel_last_mode,
            'wheel_last_source': state.wheel_last_source,
        }

    def update_settings(
        self,
        owner_id: int,
        *,
        giveaway_type: str,
        keyword: str,
        chat_announcements: bool,
        points_reward_title: str,
        points_reward_cost: Any,
        points_allow_multiple_entries: bool,
        multipliers: dict[str, Any],
    ) -> GiveawayState:
        state = self.get_state(owner_id)
        normalized_type = str(giveaway_type or 'active').strip().lower()
        state.giveaway_type = normalized_type if normalized_type in GIVEAWAY_TYPES else 'active'
        state.keyword = str(keyword or '').strip()
        state.chat_announcements = bool(chat_announcements)
        state.points_reward_title = self._normalize_reward_title(points_reward_title)
        state.points_reward_cost = self._normalize_reward_cost(points_reward_cost)
        state.points_allow_multiple_entries = bool(points_allow_multiple_entries)
        state.multipliers = {
            key: self._normalize_multiplier(multipliers.get(key, DEFAULT_MULTIPLIERS[key]))
            for key in DEFAULT_MULTIPLIERS
        }
        return state

    def set_points_reward(self, owner_id: int, reward: dict[str, Any]) -> GiveawayState:
        state = self.get_state(owner_id)
        reward_id = str(reward.get('id') or '').strip()
        if reward_id:
            state.points_reward_id = reward_id
        if reward.get('title'):
            state.points_reward_title = self._normalize_reward_title(reward.get('title'))
        if reward.get('cost') is not None:
            state.points_reward_cost = self._normalize_reward_cost(reward.get('cost'))
        return state

    def clear_points_reward(self, owner_id: int) -> GiveawayState:
        state = self.get_state(owner_id)
        state.points_reward_id = ''
        state.running = False
        return state

    def set_running(self, owner_id: int, running: bool) -> GiveawayState:
        state = self.get_state(owner_id)
        state.running = bool(running)
        if state.running:
            state.winner_login = ''
            state.winner_messages.clear()
        return state

    def roll(self, owner_id: int) -> GiveawayParticipant | None:
        state = self.get_state(owner_id)
        weighted_pool: list[GiveawayParticipant] = []
        for participant in state.participants.values():
            weight = max(0.0, self._participant_multiplier(participant, state))
            tickets = max(1, int(round(weight))) if weight > 0 else 0
            weighted_pool.extend([participant] * tickets)
        if not weighted_pool:
            return None
        winner = random.choice(weighted_pool)
        state.winner_login = winner.login
        state.winner_messages.clear()
        return winner

    def wheel_total_tickets(self, owner_id: int, mode: str = 'normal') -> int:
        _, total_tickets = self._wheel_candidates(self.get_state(owner_id), mode)
        return total_tickets

    def wheel_spin(self, owner_id: int, mode: str, ticket: int, source: str) -> GiveawayParticipant | None:
        state = self.get_state(owner_id)
        normalized_mode = 'elimination' if mode == 'elimination' else 'normal'
        candidates, total_tickets = self._wheel_candidates(state, normalized_mode)
        if not candidates:
            return None
        if normalized_mode == 'elimination' and len(candidates) == 1:
            selected = candidates[0][0]
            state.wheel_last_result_login = selected.login
            state.wheel_last_mode = normalized_mode
            state.wheel_last_source = source
            state.winner_login = selected.login
            state.winner_messages.clear()
            return selected
        selected_ticket = max(1, min(int(ticket), total_tickets))
        cursor = 0
        selected: GiveawayParticipant | None = None
        for participant, tickets in candidates:
            cursor += tickets
            if selected_ticket <= cursor:
                selected = participant
                break
        if selected is None:
            selected = candidates[-1][0]

        state.wheel_last_result_login = selected.login
        state.wheel_last_mode = normalized_mode
        state.wheel_last_source = source
        if normalized_mode == 'elimination':
            state.wheel_eliminated_logins.add(selected.login)
            remaining = [participant for participant in state.participants.values() if participant.login not in state.wheel_eliminated_logins]
            if len(remaining) == 1:
                state.winner_login = remaining[0].login
                state.winner_messages.clear()
        else:
            state.winner_login = selected.login
            state.winner_messages.clear()
        return selected

    async def handle_chat_message(self, owner: dict[str, Any], event: dict[str, Any], text: str) -> None:
        state = self.get_state(int(owner['id']))
        chatter_login = str(event.get('chatter_user_login') or '').strip().lower()
        chatter_id = str(event.get('chatter_user_id') or '').strip()
        display_name = str(event.get('chatter_user_name') or chatter_login).strip() or chatter_login
        if not chatter_login or not chatter_id:
            return
        if settings.twitch_bot_user_login and chatter_login == str(settings.twitch_bot_user_login).strip().lower():
            return

        self._append_recent_message(state, display_name, chatter_login, text)
        if state.winner_login and chatter_login == state.winner_login:
            self._append_winner_message(state, display_name, chatter_login, text)

        if not state.running:
            return
        if chatter_login in state.ignored_participants:
            return
        participant = state.participants.get(chatter_login)
        if state.giveaway_type == 'points' and participant is None:
            return
        if state.giveaway_type == 'keyword':
            keyword = state.keyword.strip().lower()
            if not keyword or keyword not in text.lower():
                return

        is_subscriber = self._has_badge(event, {'subscriber', 'founder'})
        is_vip = self._has_badge(event, {'vip'})
        is_follower = await self._is_follower(owner, chatter_id)
        self._upsert_participant(
            state,
            user_id=chatter_id,
            login=chatter_login,
            display_name=display_name,
            is_follower=is_follower,
            is_vip=is_vip,
            is_subscriber=is_subscriber,
        )

    async def handle_points_redemption(self, owner: dict[str, Any], event: dict[str, Any]) -> None:
        state = self.get_state(int(owner['id']))
        reward = event.get('reward') or {}
        reward_id = str(reward.get('id') or '').strip()
        redemption_id = str(event.get('id') or '').strip()
        if not state.points_reward_id or reward_id != state.points_reward_id:
            logger.info(
                'Ignoring giveaway redemption owner=%s reward=%s expected=%s',
                owner.get('id'),
                reward_id,
                state.points_reward_id,
            )
            return
        if not state.running or state.giveaway_type != 'points':
            logger.info(
                'Canceling giveaway redemption owner=%s running=%s type=%s redemption=%s',
                owner.get('id'),
                state.running,
                state.giveaway_type,
                redemption_id,
            )
            await self._settle_points_redemption(owner, reward_id, redemption_id, 'CANCELED')
            return
        login = str(event.get('user_login') or '').strip().lower()
        user_id = str(event.get('user_id') or '').strip()
        display_name = str(event.get('user_name') or login).strip() or login
        if not login or not user_id:
            logger.info('Ignoring giveaway redemption owner=%s without user data: %s', owner.get('id'), event)
            await self._settle_points_redemption(owner, reward_id, redemption_id, 'CANCELED')
            return
        if login in state.ignored_participants:
            await self._settle_points_redemption(owner, reward_id, redemption_id, 'CANCELED')
            return
        existing_participant = state.participants.get(login)
        if existing_participant is not None and not state.points_allow_multiple_entries:
            logger.info(
                'Canceling duplicate giveaway redemption owner=%s login=%s redemption=%s because multiple entries are disabled',
                owner.get('id'),
                login,
                redemption_id,
            )
            await self._settle_points_redemption(owner, reward_id, redemption_id, 'CANCELED')
            return
        is_follower = await self._is_follower(owner, user_id)
        self._upsert_participant(
            state,
            user_id=user_id,
            login=login,
            display_name=display_name,
            is_follower=is_follower,
            is_vip=False,
            is_subscriber=False,
            entry_increment=1 if existing_participant is not None else 0,
        )
        await self._settle_points_redemption(owner, reward_id, redemption_id, 'FULFILLED')

    def remove_participant(self, owner_id: int, login: str) -> bool:
        state = self.get_state(owner_id)
        normalized_login = str(login or '').strip().lower()
        if not normalized_login:
            return False
        removed = state.participants.pop(normalized_login, None) is not None
        state.ignored_participants.add(normalized_login)
        if state.winner_login == normalized_login:
            state.winner_login = ''
            state.winner_messages.clear()
        return removed

    def clear(self, owner_id: int) -> GiveawayState:
        state = self.get_state(owner_id)
        state.participants.clear()
        state.ignored_participants.clear()
        state.winner_login = ''
        state.winner_messages.clear()
        state.wheel_eliminated_logins.clear()
        state.wheel_last_result_login = ''
        state.wheel_last_mode = 'normal'
        state.wheel_last_source = ''
        return state

    def _wheel_candidates(self, state: GiveawayState, mode: str) -> tuple[list[tuple[GiveawayParticipant, int]], int]:
        candidates: list[tuple[GiveawayParticipant, int]] = []
        for participant in state.participants.values():
            if mode == 'elimination' and participant.login in state.wheel_eliminated_logins:
                continue
            tickets = max(0, int(round(self._participant_multiplier(participant, state) * 100)))
            if tickets > 0:
                candidates.append((participant, tickets))
        return candidates, sum(tickets for _, tickets in candidates)

    def _participant_payload(self, participant: GiveawayParticipant | None, state: GiveawayState) -> dict[str, Any] | None:
        if participant is None:
            return None
        return {
            'user_id': participant.user_id,
            'login': participant.login,
            'display_name': participant.display_name,
            'entry_count': participant.entry_count,
            'message_count': participant.message_count,
            'is_follower': participant.is_follower,
            'is_vip': participant.is_vip,
            'is_subscriber': participant.is_subscriber,
            'multiplier': self._participant_multiplier(participant, state),
        }

    def _participant_multiplier(self, participant: GiveawayParticipant, state: GiveawayState) -> float:
        multiplier = self._normalize_multiplier(state.multipliers.get('default', 1))
        if participant.is_follower:
            multiplier = max(multiplier, self._normalize_multiplier(state.multipliers.get('follower', 1)))
        if participant.is_vip:
            multiplier = max(multiplier, self._normalize_multiplier(state.multipliers.get('vip', 1)))
        if participant.is_subscriber:
            multiplier = max(multiplier, self._normalize_multiplier(state.multipliers.get('subscriber', 1)))
        return multiplier * max(1, int(participant.entry_count or 1))

    def _normalize_multiplier(self, value: Any) -> float:
        try:
            multiplier = float(value)
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, min(multiplier, 100.0))

    def _normalize_reward_title(self, value: Any) -> str:
        title = str(value or '').strip()
        if not title:
            return DEFAULT_POINTS_REWARD_TITLE
        return title[:45]

    def _normalize_reward_cost(self, value: Any) -> int:
        try:
            cost = int(value)
        except (TypeError, ValueError):
            return DEFAULT_POINTS_REWARD_COST
        return max(1, min(cost, 1_000_000))

    def _upsert_participant(
        self,
        state: GiveawayState,
        *,
        user_id: str,
        login: str,
        display_name: str,
        is_follower: bool,
        is_vip: bool,
        is_subscriber: bool,
        entry_increment: int = 0,
    ) -> GiveawayParticipant:
        participant = state.participants.get(login)
        if participant is None:
            participant = GiveawayParticipant(
                user_id=user_id,
                login=login,
                display_name=display_name,
                is_follower=is_follower,
                is_vip=is_vip,
                is_subscriber=is_subscriber,
            )
            state.participants[login] = participant
        participant.display_name = display_name
        participant.is_follower = participant.is_follower or is_follower
        participant.is_vip = participant.is_vip or is_vip
        participant.is_subscriber = participant.is_subscriber or is_subscriber
        participant.entry_count = max(1, int(participant.entry_count or 1) + max(0, int(entry_increment)))
        participant.message_count += 1
        participant.last_message_at = time.time()
        return participant

    def _append_winner_message(self, state: GiveawayState, display_name: str, login: str, text: str) -> None:
        state.winner_messages.append(
            {
                'display_name': display_name,
                'login': login,
                'text': text,
                'created_at': time.strftime('%H:%M:%S'),
            }
        )
        state.winner_messages = state.winner_messages[-100:]

    def _append_recent_message(self, state: GiveawayState, display_name: str, login: str, text: str) -> None:
        state.recent_messages.append(
            {
                'display_name': display_name,
                'login': login,
                'text': text,
                'created_at': time.strftime('%H:%M:%S'),
            }
        )
        state.recent_messages = state.recent_messages[-100:]

    async def _is_follower(self, owner: dict[str, Any], chatter_user_id: str) -> bool:
        broadcaster_id = str(owner.get('twitch_user_id') or '').strip()
        if not broadcaster_id or not chatter_user_id:
            return False
        try:
            return await twitch_api.is_user_follower(broadcaster_id, chatter_user_id)
        except Exception:
            return False

    async def _settle_points_redemption(self, owner: dict[str, Any], reward_id: str, redemption_id: str, status: str) -> None:
        if not redemption_id:
            return
        try:
            await twitch_api.update_custom_reward_redemption_status_for_user(owner, reward_id, redemption_id, status)
        except Exception as exc:
            logger.warning(
                'Failed to settle giveaway redemption owner=%s reward=%s redemption=%s status=%s error=%s',
                owner.get('id'),
                reward_id,
                redemption_id,
                status,
                exc,
            )

    def _has_badge(self, event: dict[str, Any], badge_ids: set[str]) -> bool:
        for badge in event.get('badges') or []:
            if isinstance(badge, dict):
                badge_id = str(badge.get('set_id') or badge.get('id') or '').strip().lower()
            else:
                badge_id = str(badge or '').strip().lower()
            if badge_id in badge_ids:
                return True
        return False


giveaway_runtime = GiveawayRuntime()
