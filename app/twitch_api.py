import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from .config import apply_runtime_settings, persist_settings_env, settings
from .service_metrics import service_metrics
from .web_db import set_web_user_bot_enabled, update_web_user_tokens


logger = logging.getLogger(__name__)

LIVE_STREAMS_CACHE_FRESH_SECONDS = 45.0
LIVE_STREAMS_CACHE_STALE_SECONDS = 600.0


class TwitchAPI:
    def __init__(self) -> None:
        self.base = 'https://api.twitch.tv/helix'
        self.auth_base = 'https://id.twitch.tv/oauth2'
        self._app_token: Optional[str] = None
        self._lock = asyncio.Lock()
        self._follower_cache: dict[tuple[str, str], tuple[bool, float]] = {}
        self._moderator_cache: dict[tuple[str, str], tuple[bool, float]] = {}
        self._live_streams_cache: dict[str, tuple[Optional[dict[str, Any]], float]] = {}
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=20,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_app_access_token(self) -> str:
        async with self._lock:
            if self._app_token:
                return self._app_token
            client = self._get_client()
            resp = await client.post(
                f'{self.auth_base}/token',
                params={
                    'client_id': settings.twitch_client_id,
                    'client_secret': settings.twitch_client_secret,
                    'grant_type': 'client_credentials',
                },
            )
            resp.raise_for_status()
            self._app_token = resp.json()['access_token']
            return self._app_token

    async def refresh_user_access_token(self, refresh_token: str) -> dict[str, Any]:
        client = self._get_client()
        resp = await client.post(
            f'{self.auth_base}/token',
            params={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': settings.twitch_client_id,
                'client_secret': settings.twitch_client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def validate_user_access_token(self, access_token: str) -> dict[str, Any]:
        normalized_token = str(access_token or '').strip()
        if not normalized_token:
            return {}
        client = self._get_client()
        resp = await client.get(
            f'{self.auth_base}/validate',
            headers={'Authorization': f'Bearer {normalized_token}'},
        )
        if resp.status_code == 401:
            return {}
        resp.raise_for_status()
        return resp.json()

    async def refresh_bot_access_token(self) -> str:
        refresh_token = str(settings.twitch_bot_user_refresh_token or '').strip()
        if not refresh_token:
            raise RuntimeError('TWITCH_BOT_USER_REFRESH_TOKEN is required to refresh the bot token')
        token_data = await self.refresh_user_access_token(refresh_token)
        new_access_token = str(token_data.get('access_token') or '')
        new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
        if not new_access_token:
            raise RuntimeError('Twitch did not return a new bot access token')
        updates = {
            'TWITCH_BOT_USER_ACCESS_TOKEN': new_access_token,
            'TWITCH_BOT_USER_REFRESH_TOKEN': new_refresh_token,
        }
        persist_settings_env(updates)
        apply_runtime_settings(updates)
        return new_access_token

    async def _bot_api_request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        allow_refresh: bool = True,
    ) -> httpx.Response:
        token = str(settings.twitch_bot_user_access_token or '').strip()
        if not token:
            raise RuntimeError('TWITCH_BOT_USER_ACCESS_TOKEN is required for bot API requests')
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        if json is not None:
            headers['Content-Type'] = 'application/json'
        client = self._get_client()
        resp = await client.request(
            method,
            f'{self.base}{path}',
            headers=headers,
            json=json,
            params=params,
        )
        if resp.status_code == 401 and allow_refresh and settings.twitch_bot_user_refresh_token:
            logger.warning('Refreshing bot OAuth token after 401 for %s %s', method, path)
            await self.refresh_bot_access_token()
            return await self._bot_api_request(
                method,
                path,
                json=json,
                params=params,
                allow_refresh=False,
            )
        return resp

    async def _app_api_request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        allow_refresh: bool = True,
    ) -> httpx.Response:
        token = await self.get_app_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        if json is not None:
            headers['Content-Type'] = 'application/json'
        client = self._get_client()
        resp = await client.request(
            method,
            f'{self.base}{path}',
            headers=headers,
            json=json,
            params=params,
        )
        if resp.status_code == 401 and allow_refresh:
            self._app_token = None
            return await self._app_api_request(
                method,
                path,
                json=json,
                params=params,
                allow_refresh=False,
            )
        return resp

    async def _user_api_request(
        self,
        user: dict[str, Any],
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        allow_refresh: bool = True,
    ) -> httpx.Response:
        access_token = str(user.get('access_token') or '').strip()
        refresh_token = str(user.get('refresh_token') or '').strip()
        if not access_token:
            raise RuntimeError('Для канала нет актуального Twitch-токена. Войди через Twitch заново.')
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Client-Id': settings.twitch_client_id,
        }
        if json is not None:
            headers['Content-Type'] = 'application/json'
        client = self._get_client()
        resp = await client.request(
            method,
            f'{self.base}{path}',
            headers=headers,
            json=json,
            params=params,
        )
        if resp.status_code == 401 and allow_refresh and refresh_token and user.get('id'):
            token_data = await self.refresh_user_access_token(refresh_token)
            new_access_token = str(token_data.get('access_token') or '')
            new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
            if new_access_token:
                update_web_user_tokens(int(user['id']), new_access_token, new_refresh_token)
                user['access_token'] = new_access_token
                user['refresh_token'] = new_refresh_token
                return await self._user_api_request(
                    user,
                    method,
                    path,
                    json=json,
                    params=params,
                    allow_refresh=False,
                )
        return resp

    async def create_subscription(
        self,
        session_id: str,
        sub_type: str,
        broadcaster_id: str,
        version: str = '1',
    ) -> dict[str, Any]:
        body = {
            'type': sub_type,
            'version': version,
            'condition': {
                'broadcaster_user_id': broadcaster_id,
                'user_id': settings.twitch_bot_user_id,
            },
            'transport': {
                'method': 'websocket',
                'session_id': session_id,
            },
        }
        resp = await self._bot_api_request('POST', '/eventsub/subscriptions', json=body)
        if resp.status_code == 409:
            return resp.json()
        if resp.is_error:
            logger.error(
                'Failed to create EventSub subscription type=%s broadcaster_id=%s status=%s body=%s',
                sub_type,
                broadcaster_id,
                resp.status_code,
                resp.text,
            )
        resp.raise_for_status()
        return resp.json()

    async def create_webhook_subscription(
        self,
        callback_url: str,
        secret: str,
        sub_type: str,
        broadcaster_id: str,
        *,
        version: str = '1',
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_callback_url = str(callback_url or '').strip()
        normalized_secret = str(secret or '').strip()
        normalized_user_id = str(user_id or settings.twitch_bot_user_id or '').strip()
        if not normalized_callback_url:
            raise RuntimeError('Webhook callback URL is required for EventSub webhook subscriptions')
        if not normalized_secret:
            raise RuntimeError('TWITCH_EVENTSUB_SECRET is required for EventSub webhook subscriptions')
        if not normalized_user_id:
            raise RuntimeError('TWITCH_BOT_USER_ID is required for EventSub webhook subscriptions')
        body = {
            'type': sub_type,
            'version': version,
            'condition': {
                'broadcaster_user_id': broadcaster_id,
                'user_id': normalized_user_id,
            },
            'transport': {
                'method': 'webhook',
                'callback': normalized_callback_url,
                'secret': normalized_secret,
            },
        }
        resp = await self._app_api_request('POST', '/eventsub/subscriptions', json=body)
        if resp.status_code == 409:
            return resp.json()
        if resp.is_error:
            logger.error(
                'Failed to create webhook EventSub subscription type=%s broadcaster_id=%s callback=%s status=%s body=%s',
                sub_type,
                broadcaster_id,
                normalized_callback_url,
                resp.status_code,
                resp.text,
            )
        resp.raise_for_status()
        return resp.json()

    async def create_user_subscription(
        self,
        user: dict[str, Any],
        session_id: str,
        sub_type: str,
        condition: dict[str, Any],
        version: str = '1',
    ) -> dict[str, Any]:
        body = {
            'type': sub_type,
            'version': version,
            'condition': condition,
            'transport': {
                'method': 'websocket',
                'session_id': session_id,
            },
        }
        resp = await self._user_api_request(user, 'POST', '/eventsub/subscriptions', json=body)
        if resp.status_code == 409:
            return resp.json()
        if resp.is_error:
            logger.error(
                'Failed to create user EventSub subscription type=%s condition=%s status=%s body=%s',
                sub_type,
                condition,
                resp.status_code,
                resp.text,
            )
        if resp.status_code in {401, 403} and sub_type == 'channel.channel_points_custom_reward_redemption.add':
            raise RuntimeError(await self._redemption_scope_error(user, 'подписаться на покупки награды'))
        if resp.is_error and sub_type == 'channel.channel_points_custom_reward_redemption.add':
            detail = self._response_error_detail(resp)
            scope_detail = await self._redemption_scope_error(user, 'подписаться на покупки награды')
            raise RuntimeError(f'EventSub не подключил покупки награды. Twitch вернул {resp.status_code}: {detail}. {scope_detail}')
        resp.raise_for_status()
        return resp.json()

    async def _redemption_scope_error(self, user: dict[str, Any], action: str) -> str:
        try:
            validation = await self.validate_user_access_token(str(user.get('access_token') or ''))
        except httpx.HTTPError as exc:
            logger.warning('Unable to validate user token for redemption scope error: %s', exc)
            validation = {}
        scopes = {str(scope) for scope in validation.get('scopes') or []}
        missing = [
            scope
            for scope in ('channel:manage:redemptions', 'channel:read:redemptions')
            if scope not in scopes
        ]
        if missing:
            current = ', '.join(sorted(scopes)) if scopes else 'Twitch не вернул список прав'
            return (
                f'Twitch не дал {action}: в токене нет {", ".join(missing)}. '
                f'Сейчас в токене: {current}. Открой /auth/twitch/login?force=1 и подтверди новые права.'
            )
        return (
            f'Twitch не дал {action}, хотя права для наград в токене есть. '
            'Проверь, что канал Affiliate/Partner и награды за баллы доступны на канале.'
        )

    def _response_error_detail(self, resp: httpx.Response) -> str:
        try:
            payload = resp.json()
        except ValueError:
            return resp.text[:500] or 'без текста ошибки'
        detail = payload.get('message') or payload.get('error') or payload
        return str(detail)[:500]

    async def ensure_giveaway_points_reward_for_user(
        self,
        user: dict[str, Any],
        *,
        title: str,
        cost: int,
    ) -> dict[str, Any]:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            raise RuntimeError('У канала нет Twitch ID. Войди через Twitch заново.')
        normalized_title = str(title or 'Участвовать в розыгрыше').strip()[:45] or 'Участвовать в розыгрыше'
        try:
            normalized_cost = int(cost or 100)
        except (TypeError, ValueError):
            normalized_cost = 100
        normalized_cost = max(1, min(normalized_cost, 1_000_000))

        params = {
            'broadcaster_id': broadcaster_id,
            'only_manageable_rewards': 'true',
        }
        try:
            resp = await self._user_api_request(user, 'GET', '/channel_points/custom_rewards', params=params)
        except httpx.HTTPError as exc:
            logger.warning('Unable to list custom rewards broadcaster_id=%s error=%s', broadcaster_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось проверить награды за баллы.') from exc
        if resp.status_code == 401:
            raise RuntimeError(await self._redemption_scope_error(user, 'проверить награды за баллы'))
        if resp.status_code == 403:
            raise RuntimeError('Twitch не разрешил награды за баллы для этого канала. Проверь, что канал Affiliate/Partner и владелец заново вошёл через Twitch.')
        resp.raise_for_status()
        for reward in resp.json().get('data') or []:
            if str(reward.get('title') or '').strip().lower() == normalized_title.lower():
                if (
                    not bool(reward.get('is_enabled', True))
                    or bool(reward.get('is_paused', False))
                    or int(reward.get('cost') or normalized_cost) != normalized_cost
                    or bool(reward.get('should_redemptions_skip_request_queue', False))
                ):
                    update_resp = await self._user_api_request(
                        user,
                        'PATCH',
                        '/channel_points/custom_rewards',
                        params={
                            'broadcaster_id': broadcaster_id,
                            'id': str(reward.get('id') or ''),
                        },
                        json={
                            'is_enabled': True,
                            'is_paused': False,
                            'cost': normalized_cost,
                            'should_redemptions_skip_request_queue': False,
                        },
                    )
                    if update_resp.status_code == 401:
                        raise RuntimeError(await self._redemption_scope_error(user, 'обновить награду за баллы'))
                    if update_resp.status_code == 403:
                        raise RuntimeError('Twitch не разрешил обновить награду. Проверь, что канал Affiliate/Partner и награда создана этим приложением.')
                    update_resp.raise_for_status()
                    updated_data = update_resp.json().get('data') or []
                    if updated_data:
                        return updated_data[0]
                return reward

        body = {
            'title': normalized_title,
            'cost': normalized_cost,
            'prompt': 'Купи награду, чтобы попасть в розыгрыш.',
            'is_enabled': True,
            'is_user_input_required': False,
            'should_redemptions_skip_request_queue': False,
        }
        try:
            resp = await self._user_api_request(
                user,
                'POST',
                '/channel_points/custom_rewards',
                params={'broadcaster_id': broadcaster_id},
                json=body,
            )
        except httpx.HTTPError as exc:
            logger.warning('Unable to create custom reward broadcaster_id=%s error=%s', broadcaster_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось создать награду за баллы.') from exc
        if resp.status_code == 401:
            raise RuntimeError(await self._redemption_scope_error(user, 'создать награду за баллы'))
        if resp.status_code == 403:
            raise RuntimeError('Twitch не разрешил создать награду. Проверь, что канал Affiliate/Partner и владелец заново вошёл через Twitch.')
        if resp.status_code == 400:
            detail = ''
            try:
                detail = str(resp.json().get('message') or '')
            except ValueError:
                detail = resp.text
            raise RuntimeError(f'Twitch не создал награду. Проверь название и стоимость. {detail}'.strip())
        resp.raise_for_status()
        data = resp.json().get('data') or []
        if not data:
            raise RuntimeError('Twitch создал награду, но не вернул её ID. Попробуй запустить розыгрыш ещё раз.')
        return data[0]

    async def delete_custom_reward_for_user(self, user: dict[str, Any], reward_id: str) -> None:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        normalized_reward_id = str(reward_id or '').strip()
        if not broadcaster_id or not normalized_reward_id:
            return
        try:
            resp = await self._user_api_request(
                user,
                'DELETE',
                '/channel_points/custom_rewards',
                params={
                    'broadcaster_id': broadcaster_id,
                    'id': normalized_reward_id,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning('Unable to delete custom reward broadcaster_id=%s reward_id=%s error=%s', broadcaster_id, normalized_reward_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось удалить награду за баллы.') from exc
        if resp.status_code == 401:
            raise RuntimeError(await self._redemption_scope_error(user, 'удалить награду за баллы'))
        if resp.status_code == 403:
            raise RuntimeError('Twitch не разрешил удалить награду. Проверь, что награда создана этим приложением и владелец канала вошёл через Twitch.')
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    async def update_custom_reward_redemption_status_for_user(
        self,
        user: dict[str, Any],
        reward_id: str,
        redemption_id: str,
        status: str,
    ) -> bool:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        normalized_reward_id = str(reward_id or '').strip()
        normalized_redemption_id = str(redemption_id or '').strip()
        normalized_status = str(status or '').strip().upper()
        if not broadcaster_id or not normalized_reward_id or not normalized_redemption_id:
            return False
        if normalized_status not in {'CANCELED', 'FULFILLED'}:
            raise ValueError(f'Unsupported redemption status: {status}')
        try:
            resp = await self._user_api_request(
                user,
                'PATCH',
                '/channel_points/custom_rewards/redemptions',
                params={
                    'broadcaster_id': broadcaster_id,
                    'reward_id': normalized_reward_id,
                    'id': normalized_redemption_id,
                },
                json={'status': normalized_status},
            )
        except httpx.HTTPError as exc:
            logger.warning(
                'Unable to update custom reward redemption broadcaster_id=%s reward_id=%s redemption_id=%s status=%s error=%s',
                broadcaster_id,
                normalized_reward_id,
                normalized_redemption_id,
                normalized_status,
                exc,
            )
            return False
        if resp.status_code == 401:
            raise RuntimeError(await self._redemption_scope_error(user, 'обновить покупку награды'))
        if resp.status_code == 403:
            raise RuntimeError('Twitch не разрешил обновить покупку награды. Проверь, что награда создана этим приложением.')
        if resp.status_code in {400, 404}:
            logger.warning(
                'Twitch did not update custom reward redemption broadcaster_id=%s reward_id=%s redemption_id=%s status=%s code=%s body=%s',
                broadcaster_id,
                normalized_reward_id,
                normalized_redemption_id,
                normalized_status,
                resp.status_code,
                resp.text,
            )
            return False
        resp.raise_for_status()
        return True

    async def _prediction_scope_error(self, user: dict[str, Any], action: str) -> str:
        try:
            validation = await self.validate_user_access_token(str(user.get('access_token') or ''))
        except httpx.HTTPError as exc:
            logger.warning('Unable to validate user token for prediction scope error: %s', exc)
            validation = {}
        scopes = {str(scope) for scope in validation.get('scopes') or []}
        if 'channel:manage:predictions' not in scopes:
            current = ', '.join(sorted(scopes)) if scopes else 'Twitch не вернул список прав'
            return (
                f'Twitch не дал {action}: в токене нет channel:manage:predictions. '
                f'Сейчас в токене: {current}. Открой /auth/twitch/login?force=1 и подтверди новые права.'
            )
        return (
            f'Twitch не дал {action}, хотя право channel:manage:predictions в токене есть. '
            'Проверь, что это токен владельца канала и на канале доступны Channel Points Predictions.'
        )

    async def create_prediction_for_user(
        self,
        user: dict[str, Any],
        *,
        title: str,
        prediction_window_seconds: int,
        outcomes: list[str],
    ) -> dict[str, Any]:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            raise RuntimeError('У канала нет Twitch ID. Войди через Twitch заново.')
        normalized_title = str(title or 'Матч: победа?').strip()[:45] or 'Матч: победа?'
        normalized_outcomes = [str(item or '').strip()[:25] for item in outcomes if str(item or '').strip()]
        if len(normalized_outcomes) != 2:
            normalized_outcomes = ['Победа', 'Поражение']
        try:
            window_seconds = int(prediction_window_seconds or 120)
        except (TypeError, ValueError):
            window_seconds = 120
        window_seconds = max(30, min(window_seconds, 1800))

        body = {
            'broadcaster_id': broadcaster_id,
            'title': normalized_title,
            'outcomes': [{'title': item} for item in normalized_outcomes],
            'prediction_window': window_seconds,
        }
        try:
            resp = await self._user_api_request(user, 'POST', '/predictions', json=body)
        except httpx.HTTPError as exc:
            logger.warning('Unable to create prediction broadcaster_id=%s error=%s', broadcaster_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось открыть prediction.') from exc
        if resp.status_code in {401, 403}:
            raise RuntimeError(await self._prediction_scope_error(user, 'открыть prediction'))
        if resp.status_code == 400:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не открыл prediction: {detail}')
        if resp.is_error:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не открыл prediction. Код {resp.status_code}: {detail}')
        resp.raise_for_status()
        data = resp.json().get('data') or []
        if not data:
            raise RuntimeError('Twitch открыл prediction, но не вернул его ID.')
        return data[0]

    async def get_prediction_for_user(
        self,
        user: dict[str, Any],
        *,
        prediction_id: str,
    ) -> Optional[dict[str, Any]]:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        normalized_prediction_id = str(prediction_id or '').strip()
        if not broadcaster_id or not normalized_prediction_id:
            return None
        try:
            resp = await self._user_api_request(
                user,
                'GET',
                '/predictions',
                params={'broadcaster_id': broadcaster_id, 'id': normalized_prediction_id},
            )
        except httpx.HTTPError as exc:
            logger.warning('Unable to get prediction broadcaster_id=%s prediction_id=%s error=%s', broadcaster_id, normalized_prediction_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось проверить prediction.') from exc
        if resp.status_code in {401, 403}:
            raise RuntimeError(await self._prediction_scope_error(user, 'проверить prediction'))
        if resp.is_error:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не проверил prediction. Код {resp.status_code}: {detail}')
        data = resp.json().get('data') or []
        return data[0] if data else None

    async def get_current_prediction_for_user(self, user: dict[str, Any]) -> Optional[dict[str, Any]]:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        if not broadcaster_id:
            return None
        try:
            resp = await self._user_api_request(
                user,
                'GET',
                '/predictions',
                params={'broadcaster_id': broadcaster_id, 'first': 20},
            )
        except httpx.HTTPError as exc:
            logger.warning('Unable to get current prediction broadcaster_id=%s error=%s', broadcaster_id, exc)
            raise RuntimeError('Twitch временно недоступен. Не удалось проверить активную prediction.') from exc
        if resp.status_code in {401, 403}:
            raise RuntimeError(await self._prediction_scope_error(user, 'проверить активную prediction'))
        if resp.is_error:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не проверил активную prediction. Код {resp.status_code}: {detail}')
        for prediction in resp.json().get('data') or []:
            if str(prediction.get('status') or '').strip().upper() in {'ACTIVE', 'LOCKED'}:
                return prediction
        return None

    async def end_prediction_for_user(
        self,
        user: dict[str, Any],
        *,
        prediction_id: str,
        status: str,
        winning_outcome_id: str = '',
    ) -> Optional[dict[str, Any]]:
        broadcaster_id = str(user.get('twitch_user_id') or '').strip()
        normalized_prediction_id = str(prediction_id or '').strip()
        normalized_status = str(status or '').strip().upper()
        if not broadcaster_id or not normalized_prediction_id:
            return None
        if normalized_status not in {'RESOLVED', 'CANCELED', 'LOCKED'}:
            raise ValueError(f'Unsupported prediction status: {status}')
        body: dict[str, Any] = {
            'broadcaster_id': broadcaster_id,
            'id': normalized_prediction_id,
            'status': normalized_status,
        }
        if normalized_status == 'RESOLVED':
            normalized_winning_outcome_id = str(winning_outcome_id or '').strip()
            if not normalized_winning_outcome_id:
                raise RuntimeError('Не выбран исход для закрытия prediction.')
            body['winning_outcome_id'] = normalized_winning_outcome_id
        try:
            resp = await self._user_api_request(user, 'PATCH', '/predictions', json=body)
        except httpx.HTTPError as exc:
            logger.warning(
                'Unable to end prediction broadcaster_id=%s prediction_id=%s status=%s error=%s',
                broadcaster_id,
                normalized_prediction_id,
                normalized_status,
                exc,
            )
            raise RuntimeError('Twitch временно недоступен. Не удалось закрыть prediction.') from exc
        if resp.status_code in {401, 403}:
            raise RuntimeError(await self._prediction_scope_error(user, 'закрыть prediction'))
        if resp.status_code in {400, 404}:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не закрыл prediction: {detail}')
        if resp.is_error:
            detail = self._response_error_detail(resp)
            raise RuntimeError(f'Twitch не закрыл prediction. Код {resp.status_code}: {detail}')
        resp.raise_for_status()
        data = resp.json().get('data') or []
        return data[0] if data else None

    async def get_eventsub_subscriptions(self) -> list[dict[str, Any]]:
        if not settings.twitch_bot_user_access_token:
            return []
        resp = await self._bot_api_request('GET', '/eventsub/subscriptions')
        resp.raise_for_status()
        return list(resp.json().get('data') or [])

    async def get_app_eventsub_subscriptions(self) -> list[dict[str, Any]]:
        resp = await self._app_api_request('GET', '/eventsub/subscriptions')
        resp.raise_for_status()
        return list(resp.json().get('data') or [])

    async def delete_eventsub_subscription(self, subscription_id: str) -> None:
        if not settings.twitch_bot_user_access_token or not subscription_id:
            return
        resp = await self._bot_api_request(
            'DELETE',
            '/eventsub/subscriptions',
            params={'id': subscription_id},
        )
        if resp.status_code not in {202, 204}:
            resp.raise_for_status()

    async def delete_app_eventsub_subscription(self, subscription_id: str) -> None:
        if not subscription_id:
            return
        resp = await self._app_api_request(
            'DELETE',
            '/eventsub/subscriptions',
            params={'id': subscription_id},
        )
        if resp.status_code not in {202, 204}:
            resp.raise_for_status()

    async def delete_chat_message_subscriptions_for_broadcaster(self, broadcaster_id: str) -> None:
        if not broadcaster_id:
            return
        subscriptions = await self.get_eventsub_subscriptions()
        for item in subscriptions:
            condition = item.get('condition') or {}
            if item.get('type') != 'channel.chat.message':
                continue
            if str(condition.get('broadcaster_user_id') or '') != str(broadcaster_id):
                continue
            if settings.twitch_bot_user_id and str(condition.get('user_id') or '') != str(settings.twitch_bot_user_id):
                continue
            subscription_id = str(item.get('id') or '')
            if subscription_id:
                try:
                    await self.delete_eventsub_subscription(subscription_id)
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        'Failed to delete subscription id=%s broadcaster_id=%s status=%s body=%s',
                        subscription_id,
                        broadcaster_id,
                        exc.response.status_code,
                        exc.response.text,
                    )

    async def delete_webhook_chat_message_subscriptions_for_broadcaster(
        self,
        broadcaster_id: str,
        *,
        callback_url: Optional[str] = None,
    ) -> None:
        if not broadcaster_id:
            return
        subscriptions = await self.get_app_eventsub_subscriptions()
        normalized_callback_url = str(callback_url or '').strip()
        for item in subscriptions:
            condition = item.get('condition') or {}
            transport = item.get('transport') or {}
            if item.get('type') != 'channel.chat.message':
                continue
            if str(condition.get('broadcaster_user_id') or '') != str(broadcaster_id):
                continue
            if settings.twitch_bot_user_id and str(condition.get('user_id') or '') != str(settings.twitch_bot_user_id):
                continue
            if str(transport.get('method') or '') != 'webhook':
                continue
            if normalized_callback_url and str(transport.get('callback') or '').strip() != normalized_callback_url:
                continue
            subscription_id = str(item.get('id') or '')
            if subscription_id:
                try:
                    await self.delete_app_eventsub_subscription(subscription_id)
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        'Failed to delete webhook subscription id=%s broadcaster_id=%s status=%s body=%s',
                        subscription_id,
                        broadcaster_id,
                        exc.response.status_code,
                        exc.response.text,
                    )

    def _build_send_chat_message_payload(self, message: str, broadcaster_id: Optional[str] = None) -> dict[str, Any]:
        normalized_broadcaster_id = str(broadcaster_id or settings.twitch_broadcaster_id or '').strip()
        normalized_sender_id = str(settings.twitch_bot_user_id or '').strip()
        normalized_message = str(message or '').strip()[:500]
        if not normalized_broadcaster_id:
            raise RuntimeError('TWITCH_BROADCASTER_ID is required to send chat messages')
        if not normalized_sender_id:
            raise RuntimeError('TWITCH_BOT_USER_ID is required to send chat messages')
        if not normalized_message:
            raise RuntimeError('Message is empty')
        return {
            'broadcaster_id': normalized_broadcaster_id,
            'sender_id': normalized_sender_id,
            'message': normalized_message,
        }

    async def _send_chat_message_via_user_token(self, payload: dict[str, Any]) -> None:
        if not settings.twitch_bot_user_access_token:
            raise RuntimeError('TWITCH_BOT_USER_ACCESS_TOKEN is required for user-token chat messages')
        resp = await self._bot_api_request('POST', '/chat/messages', json=payload)
        resp.raise_for_status()

    async def _send_chat_message_via_app_token(self, payload: dict[str, Any]) -> None:
        resp = await self._app_api_request('POST', '/chat/messages', json=payload)
        resp.raise_for_status()

    async def send_chat_message(self, message: str, broadcaster_id: Optional[str] = None) -> None:
        payload = self._build_send_chat_message_payload(message, broadcaster_id)
        service_metrics.increment('chat.send.attempts')
        if settings.chatbot_badge_mode:
            try:
                await self._send_chat_message_via_app_token(payload)
                service_metrics.increment('chat.send.app_token.success')
                return
            except (httpx.HTTPError, RuntimeError) as exc:
                service_metrics.increment('chat.send.app_token.fallbacks')
                service_metrics.record_error(
                    'chat.send.app_token',
                    str(exc),
                    context={'broadcaster_id': payload.get('broadcaster_id'), 'sender_id': payload.get('sender_id')},
                )
                logger.warning(
                    'App-token chat message send failed broadcaster_id=%s sender_id=%s error=%s; falling back to user token',
                    payload.get('broadcaster_id'),
                    payload.get('sender_id'),
                    exc,
                )
        if not settings.twitch_bot_user_access_token:
            service_metrics.increment('chat.send.skipped_no_user_token')
            return
        try:
            await self._send_chat_message_via_user_token(payload)
        except Exception as exc:
            service_metrics.increment('chat.send.user_token.failures')
            service_metrics.record_error(
                'chat.send.user_token',
                str(exc),
                context={'broadcaster_id': payload.get('broadcaster_id'), 'sender_id': payload.get('sender_id')},
            )
            raise
        else:
            service_metrics.increment('chat.send.user_token.success')

    async def get_user_by_login(self, login: str) -> Optional[dict[str, Any]]:
        token = await self.get_app_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        client = self._get_client()
        resp = await client.get(f'{self.base}/users', headers=headers, params={'login': login})
        resp.raise_for_status()
        data = resp.json().get('data') or []
        return data[0] if data else None

    async def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        normalized_user_id = str(user_id or '').strip()
        if not normalized_user_id:
            return None
        token = await self.get_app_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        client = self._get_client()
        resp = await client.get(f'{self.base}/users', headers=headers, params={'id': normalized_user_id})
        resp.raise_for_status()
        data = resp.json().get('data') or []
        return data[0] if data else None

    async def get_live_streams(self, broadcaster_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized_ids = list(dict.fromkeys(str(item).strip() for item in broadcaster_ids if str(item).strip()))
        if not normalized_ids:
            return {}

        now = time.time()
        fresh_cache: dict[str, dict[str, Any]] = {}
        cache_ready = True
        for broadcaster_id in normalized_ids:
            cached_entry = self._live_streams_cache.get(broadcaster_id)
            if not cached_entry:
                cache_ready = False
                break
            cached_stream, cached_at = cached_entry
            if now - float(cached_at) >= LIVE_STREAMS_CACHE_FRESH_SECONDS:
                cache_ready = False
                break
            if cached_stream:
                fresh_cache[broadcaster_id] = cached_stream
        if cache_ready:
            service_metrics.increment('twitch.get_live_streams.cache_hits')
            return fresh_cache

        started_at = time.perf_counter()
        service_metrics.increment('twitch.get_live_streams.calls')
        token = await self.get_app_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        client = self._get_client()
        live_streams: dict[str, dict[str, Any]] = {}

        for index in range(0, len(normalized_ids), 100):
            chunk = normalized_ids[index:index + 100]
            params = [('user_id', broadcaster_id) for broadcaster_id in chunk]
            try:
                resp = await client.get(f'{self.base}/streams', headers=headers, params=params)
                resp.raise_for_status()
                for stream in resp.json().get('data') or []:
                    user_id = str(stream.get('user_id') or '').strip()
                    if user_id:
                        live_streams[user_id] = stream
            except Exception as exc:
                service_metrics.increment('twitch.get_live_streams.failures')
                stale_cache: dict[str, dict[str, Any]] = {}
                stale_ids: list[str] = []
                for broadcaster_id in normalized_ids:
                    cached_entry = self._live_streams_cache.get(broadcaster_id)
                    if not cached_entry:
                        continue
                    cached_stream, cached_at = cached_entry
                    if now - float(cached_at) < LIVE_STREAMS_CACHE_STALE_SECONDS:
                        stale_ids.append(broadcaster_id)
                        if cached_stream:
                            stale_cache[broadcaster_id] = cached_stream
                if stale_ids:
                    service_metrics.increment('twitch.get_live_streams.stale_cache_hits')
                    service_metrics.record_error(
                        'twitch.get_live_streams',
                        f'{exc} (using stale cache)',
                        context={'chunk_size': len(chunk), 'cached_ids': len(stale_ids)},
                    )
                    logger.warning(
                        'Twitch live streams request failed, using stale cache for %s broadcaster(s): %s',
                        len(stale_ids),
                        exc,
                    )
                    service_metrics.observe_duration('twitch.get_live_streams', time.perf_counter() - started_at)
                    return stale_cache
                service_metrics.record_error('twitch.get_live_streams', str(exc), context={'chunk_size': len(chunk)})
                raise

        fetched_at = time.time()
        for broadcaster_id in normalized_ids:
            self._live_streams_cache[broadcaster_id] = (live_streams.get(broadcaster_id), fetched_at)

        service_metrics.observe_duration('twitch.get_live_streams', time.perf_counter() - started_at)
        return live_streams

    async def get_user_from_user_token(self, user_token: str) -> Optional[dict[str, Any]]:
        headers = {
            'Authorization': f'Bearer {user_token}',
            'Client-Id': settings.twitch_client_id,
        }
        client = self._get_client()
        resp = await client.get(f'{self.base}/users', headers=headers)
        resp.raise_for_status()
        data = resp.json().get('data') or []
        return data[0] if data else None

    async def resolve_missing_ids(self) -> None:
        if not settings.twitch_broadcaster_id and settings.twitch_channel_name:
            user = await self.get_user_by_login(settings.twitch_channel_name)
            if user and user.get('id'):
                settings.twitch_broadcaster_id = user['id']
                logger.info('Resolved broadcaster id for channel %s', settings.twitch_channel_name)
            else:
                logger.warning('Unable to resolve broadcaster id for channel %s', settings.twitch_channel_name)

        if not settings.twitch_bot_user_id:
            if settings.twitch_bot_user_access_token:
                user = await self.get_user_from_user_token(settings.twitch_bot_user_access_token)
                if user and user.get('id'):
                    settings.twitch_bot_user_id = user['id']
                    if not settings.twitch_bot_user_login and user.get('login'):
                        settings.twitch_bot_user_login = user['login']
                    logger.info('Resolved bot user id from user access token')
                else:
                    logger.warning('Unable to resolve bot user id from user access token')
            elif settings.twitch_bot_user_login:
                user = await self.get_user_by_login(settings.twitch_bot_user_login)
                if user and user.get('id'):
                    settings.twitch_bot_user_id = user['id']
                    logger.info('Resolved bot user id for login %s', settings.twitch_bot_user_login)
                else:
                    logger.warning('Unable to resolve bot user id for login %s', settings.twitch_bot_user_login)

    async def resolve_bot_user_id(self, *, force: bool = False) -> str:
        if settings.twitch_bot_user_id and not force:
            return str(settings.twitch_bot_user_id)

        user: Optional[dict[str, Any]] = None
        if settings.twitch_bot_user_access_token:
            try:
                user = await self.get_user_from_user_token(settings.twitch_bot_user_access_token)
            except httpx.HTTPError as exc:
                logger.warning('Unable to resolve bot user id from bot token: %s', exc)
        if not user and settings.twitch_bot_user_login:
            try:
                user = await self.get_user_by_login(settings.twitch_bot_user_login)
            except httpx.HTTPError as exc:
                logger.warning('Unable to resolve bot user id for login %s: %s', settings.twitch_bot_user_login, exc)

        bot_user_id = str((user or {}).get('id') or '').strip()
        if not bot_user_id:
            return str(settings.twitch_bot_user_id or '')

        updates = {'TWITCH_BOT_USER_ID': bot_user_id}
        bot_login = str((user or {}).get('login') or '').strip()
        if bot_login:
            updates['TWITCH_BOT_USER_LOGIN'] = bot_login
        persist_settings_env(updates)
        apply_runtime_settings(updates)
        logger.info('Resolved bot user id %s for login %s', bot_user_id, bot_login or settings.twitch_bot_user_login)
        return bot_user_id

    async def describe_add_moderator_not_found(
        self,
        user: dict[str, Any],
        *,
        broadcaster_id: str,
        bot_user_id: str,
        access_token: str,
    ) -> str:
        try:
            token_user = await self.get_user_from_user_token(access_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return 'Twitch-токен владельца канала устарел или не подходит. Владелец выбранного канала должен заново войти через Twitch.'
            logger.warning('Unable to inspect broadcaster token after moderator 404: status=%s body=%s', exc.response.status_code, exc.response.text)
            token_user = None
        except httpx.HTTPError as exc:
            logger.warning('Unable to inspect broadcaster token after moderator 404: %s', exc)
            token_user = None

        token_user_id = str((token_user or {}).get('id') or '').strip()
        if token_user_id and token_user_id != broadcaster_id:
            token_login = str((token_user or {}).get('login') or '').strip()
            channel_login = str(user.get('login') or '').strip()
            return (
                f'Twitch-токен принадлежит @{token_login or token_user_id}, а выбран канал @{channel_login or broadcaster_id}. '
                'Владельцу выбранного канала нужно заново войти через Twitch.'
            )

        try:
            broadcaster_user = await self.get_user_by_id(broadcaster_id)
        except httpx.HTTPError as exc:
            logger.warning('Unable to inspect broadcaster id after moderator 404: %s', exc)
            broadcaster_user = None
        if not broadcaster_user:
            channel_login = str(user.get('login') or '').strip()
            return f'Twitch не нашел выбранный канал @{channel_login or broadcaster_id}. Попроси владельца канала заново войти через Twitch.'

        try:
            bot_user = await self.get_user_by_id(bot_user_id)
        except httpx.HTTPError as exc:
            logger.warning('Unable to inspect bot user id after moderator 404: %s', exc)
            bot_user = None
        if not bot_user:
            bot_label = settings.twitch_bot_user_login or bot_user_id
            return f'Twitch не нашел аккаунт бота @{bot_label}. Проверь TWITCH_BOT_USER_LOGIN и заново авторизуй бот-аккаунт в дашборде.'

        return 'Twitch нашел канал и бота, но все равно вернул 404. Заново войди через Twitch владельцем канала и заново авторизуй бот-аккаунт.'

    async def is_user_follower(self, broadcaster_id: str, user_id: str) -> bool:
        if not broadcaster_id or not user_id:
            return False
        cache_key = (broadcaster_id, user_id)
        cached = self._follower_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[1] < settings.follower_cache_ttl:
            return cached[0]

        token = await self.get_app_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Client-Id': settings.twitch_client_id,
        }
        params = {'broadcaster_id': broadcaster_id, 'user_id': user_id}
        client = self._get_client()
        resp = await client.get(f'{self.base}/channels/followers', headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json().get('data') or []
        is_follower = len(data) > 0
        self._follower_cache[cache_key] = (is_follower, now)
        return is_follower

    async def is_user_moderator_in_channel(
        self,
        broadcaster_token: str,
        broadcaster_id: str,
        user_id: str,
        *,
        use_cache: bool = True,
    ) -> bool:
        if not broadcaster_token or not broadcaster_id or not user_id:
            return False
        cache_key = (broadcaster_id, user_id)
        cached = self._moderator_cache.get(cache_key)
        now = time.time()
        if use_cache and cached and now - cached[1] < settings.moderator_cache_ttl:
            return cached[0]

        headers = {
            'Authorization': f'Bearer {broadcaster_token}',
            'Client-Id': settings.twitch_client_id,
        }
        params = {
            'broadcaster_id': broadcaster_id,
            'user_id': user_id,
        }
        client = self._get_client()
        resp = await client.get(f'{self.base}/moderation/moderators', headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json().get('data') or []
        is_moderator = len(data) > 0
        self._moderator_cache[cache_key] = (is_moderator, now)
        return is_moderator

    async def is_bot_moderator_in_channel(
        self,
        broadcaster_token: str,
        broadcaster_id: str,
        *,
        use_cache: bool = True,
    ) -> bool:
        if not settings.twitch_bot_user_id:
            return False
        return await self.is_user_moderator_in_channel(
            broadcaster_token,
            broadcaster_id,
            settings.twitch_bot_user_id,
            use_cache=use_cache,
        )

    async def is_user_moderator_for_user(
        self,
        broadcaster_user: dict[str, Any],
        moderator_user_id: str,
        *,
        use_cache: bool = True,
    ) -> bool:
        if not broadcaster_user or not moderator_user_id:
            return False
        access_token = str(broadcaster_user.get('access_token') or '')
        refresh_token = str(broadcaster_user.get('refresh_token') or '')
        broadcaster_id = str(broadcaster_user.get('twitch_user_id') or '')
        if not access_token or not broadcaster_id:
            return False
        try:
            return await self.is_user_moderator_in_channel(
                access_token,
                broadcaster_id,
                str(moderator_user_id),
                use_cache=use_cache,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401 or not refresh_token or not broadcaster_user.get('id'):
                raise

        token_data = await self.refresh_user_access_token(refresh_token)
        new_access_token = str(token_data.get('access_token') or '')
        new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
        if not new_access_token:
            return False
        update_web_user_tokens(int(broadcaster_user['id']), new_access_token, new_refresh_token)
        broadcaster_user['access_token'] = new_access_token
        broadcaster_user['refresh_token'] = new_refresh_token
        return await self.is_user_moderator_in_channel(
            new_access_token,
            broadcaster_id,
            str(moderator_user_id),
            use_cache=use_cache,
        )

    async def is_bot_moderator_for_user(
        self,
        user: dict[str, Any],
        broadcaster_id: str,
        *,
        use_cache: bool = True,
    ) -> bool:
        if not user or not broadcaster_id:
            return False
        access_token = str(user.get('access_token') or '')
        refresh_token = str(user.get('refresh_token') or '')
        if not access_token:
            return False
        try:
            return await self.is_bot_moderator_in_channel(access_token, broadcaster_id, use_cache=use_cache)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401 or not refresh_token or not user.get('id'):
                raise

        try:
            token_data = await self.refresh_user_access_token(refresh_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 401} and user.get('id'):
                set_web_user_bot_enabled(int(user['id']), False)
            raise

        new_access_token = str(token_data.get('access_token') or '')
        new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
        if not new_access_token:
            return False
        update_web_user_tokens(int(user['id']), new_access_token, new_refresh_token)
        user['access_token'] = new_access_token
        user['refresh_token'] = new_refresh_token
        return await self.is_bot_moderator_in_channel(new_access_token, broadcaster_id, use_cache=use_cache)

    async def add_bot_as_moderator_for_user(self, user: dict[str, Any]) -> str:
        bot_user_id = await self.resolve_bot_user_id()
        if not user or not bot_user_id:
            return 'Не настроен Twitch ID бот-аккаунта.'
        access_token = str(user.get('access_token') or '')
        refresh_token = str(user.get('refresh_token') or '')
        broadcaster_id = str(user.get('twitch_user_id') or '')
        if not access_token or not broadcaster_id:
            return 'Для канала нет актуального Twitch-токена. Войди через Twitch заново.'

        async def _request(token: str) -> httpx.Response:
            headers = {
                'Authorization': f'Bearer {token}',
                'Client-Id': settings.twitch_client_id,
            }
            client = self._get_client()
            return await client.post(
                f'{self.base}/moderation/moderators',
                headers=headers,
                params={
                    'broadcaster_id': broadcaster_id,
                    'user_id': settings.twitch_bot_user_id,
                },
            )

        try:
            resp = await _request(access_token)
        except httpx.HTTPError as exc:
            logger.warning(
                'Failed to request bot moderator add broadcaster_id=%s bot_user_id=%s error=%s',
                broadcaster_id,
                settings.twitch_bot_user_id,
                exc,
            )
            return 'Twitch временно недоступен. Попробуй добавить бота модератором еще раз.'
        if resp.status_code == 401 and refresh_token and user.get('id'):
            try:
                token_data = await self.refresh_user_access_token(refresh_token)
            except httpx.HTTPStatusError:
                return 'Не удалось обновить Twitch-токен канала. Владелец канала должен заново войти через Twitch.'
            except httpx.HTTPError:
                return 'Twitch временно недоступен. Попробуй добавить бота модератором еще раз.'
            new_access_token = str(token_data.get('access_token') or '')
            new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
            if new_access_token:
                update_web_user_tokens(int(user['id']), new_access_token, new_refresh_token)
                user['access_token'] = new_access_token
                user['refresh_token'] = new_refresh_token
                try:
                    resp = await _request(new_access_token)
                except httpx.HTTPError:
                    return 'Twitch временно недоступен. Попробуй добавить бота модератором еще раз.'

        if resp.status_code == 404:
            old_bot_user_id = str(settings.twitch_bot_user_id or '')
            resolved_bot_user_id = await self.resolve_bot_user_id(force=True)
            if resolved_bot_user_id and resolved_bot_user_id != old_bot_user_id:
                try:
                    resp = await _request(str(user.get('access_token') or access_token))
                except httpx.HTTPError:
                    return 'Twitch временно недоступен. Попробуй добавить бота модератором еще раз.'

        if resp.status_code == 404:
            return await self.describe_add_moderator_not_found(
                user,
                broadcaster_id=broadcaster_id,
                bot_user_id=str(settings.twitch_bot_user_id or bot_user_id),
                access_token=str(user.get('access_token') or access_token),
            )

        if resp.status_code == 204:
            self._moderator_cache[(broadcaster_id, settings.twitch_bot_user_id)] = (True, time.time())
            return ''
        if resp.status_code == 400:
            try:
                if await self.is_user_moderator_in_channel(access_token, broadcaster_id, settings.twitch_bot_user_id, use_cache=False):
                    return ''
            except Exception:
                pass
            detail = ''
            try:
                detail = str(resp.json().get('message') or '')
            except ValueError:
                detail = resp.text
            return f'Twitch не добавил модератора: {detail or "проверь, что бот не забанен на канале и ID указаны верно."}'
        if resp.status_code == 422:
            return 'Twitch не добавил модератора. Возможно, бот уже модератор или указан тот же аккаунт, что и владелец канала.'
        if resp.status_code in {401, 403}:
            return 'Twitch не разрешил добавить модератора. Владелец канала должен заново войти через Twitch с правом channel:manage:moderators.'

        logger.warning(
            'Failed to add bot moderator broadcaster_id=%s bot_user_id=%s status=%s body=%s',
            broadcaster_id,
            settings.twitch_bot_user_id,
            resp.status_code,
            resp.text,
        )
        if resp.status_code == 404:
            return await self.describe_add_moderator_not_found(
                user,
                broadcaster_id=broadcaster_id,
                bot_user_id=str(settings.twitch_bot_user_id or bot_user_id),
                access_token=str(user.get('access_token') or access_token),
            )
        return f'Twitch не добавил модератора. Код ответа: {resp.status_code}.'

    async def remove_bot_as_moderator_for_user(self, user: dict[str, Any]) -> str:
        bot_user_id = await self.resolve_bot_user_id()
        if not user or not bot_user_id:
            return 'Не настроен Twitch ID бот-аккаунта.'
        access_token = str(user.get('access_token') or '')
        refresh_token = str(user.get('refresh_token') or '')
        broadcaster_id = str(user.get('twitch_user_id') or '')
        if not access_token or not broadcaster_id:
            return 'Для канала нет актуального Twitch-токена. Войди через Twitch заново.'

        async def _request(token: str) -> httpx.Response:
            headers = {
                'Authorization': f'Bearer {token}',
                'Client-Id': settings.twitch_client_id,
            }
            client = self._get_client()
            return await client.delete(
                f'{self.base}/moderation/moderators',
                headers=headers,
                params={
                    'broadcaster_id': broadcaster_id,
                    'user_id': settings.twitch_bot_user_id,
                },
            )

        try:
            resp = await _request(access_token)
        except httpx.HTTPError as exc:
            logger.warning(
                'Failed to request bot moderator remove broadcaster_id=%s bot_user_id=%s error=%s',
                broadcaster_id,
                settings.twitch_bot_user_id,
                exc,
            )
            return 'Twitch временно недоступен. Попробуй снять модератора с бота еще раз.'

        if resp.status_code == 401 and refresh_token and user.get('id'):
            try:
                token_data = await self.refresh_user_access_token(refresh_token)
            except httpx.HTTPStatusError:
                return 'Не удалось обновить Twitch-токен канала. Владелец канала должен заново войти через Twitch.'
            except httpx.HTTPError:
                return 'Twitch временно недоступен. Попробуй снять модератора с бота еще раз.'
            new_access_token = str(token_data.get('access_token') or '')
            new_refresh_token = str(token_data.get('refresh_token') or refresh_token)
            if new_access_token:
                update_web_user_tokens(int(user['id']), new_access_token, new_refresh_token)
                user['access_token'] = new_access_token
                user['refresh_token'] = new_refresh_token
                try:
                    resp = await _request(new_access_token)
                except httpx.HTTPError:
                    return 'Twitch временно недоступен. Попробуй снять модератора с бота еще раз.'

        if resp.status_code == 404:
            old_bot_user_id = str(settings.twitch_bot_user_id or '')
            resolved_bot_user_id = await self.resolve_bot_user_id(force=True)
            if resolved_bot_user_id and resolved_bot_user_id != old_bot_user_id:
                try:
                    resp = await _request(str(user.get('access_token') or access_token))
                except httpx.HTTPError:
                    return 'Twitch временно недоступен. Попробуй снять модератора с бота еще раз.'

        if resp.status_code in {204, 404, 422}:
            self._moderator_cache[(broadcaster_id, settings.twitch_bot_user_id)] = (False, time.time())
            return ''
        if resp.status_code in {401, 403}:
            return 'Twitch не разрешил снять модератора. Владелец канала должен заново войти через Twitch с правом channel:manage:moderators.'

        logger.warning(
            'Failed to remove bot moderator broadcaster_id=%s bot_user_id=%s status=%s body=%s',
            broadcaster_id,
            settings.twitch_bot_user_id,
            resp.status_code,
            resp.text,
        )
        return f'Twitch не снял модератора. Код ответа: {resp.status_code}.'


twitch_api = TwitchAPI()
