import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .config import settings


logger = logging.getLogger(__name__)

T = TypeVar('T')


class InlineJobDispatcher:
    def __init__(self, namespace: str = 'app') -> None:
        self._namespace = str(namespace or 'app').strip() or 'app'

    async def dispatch(self, job_name: str, handler: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        del job_name
        return await handler(*args, **kwargs)


def build_job_dispatcher() -> InlineJobDispatcher:
    backend = str(getattr(settings, 'job_dispatcher_backend', 'inline') or 'inline').strip().lower()
    namespace = str(getattr(settings, 'job_dispatcher_namespace', 'app') or 'app').strip() or 'app'
    if backend != 'inline':
        logger.warning('Unsupported job dispatcher backend=%s, falling back to inline dispatcher', backend)
    return InlineJobDispatcher(namespace=namespace)


job_dispatcher = build_job_dispatcher()
