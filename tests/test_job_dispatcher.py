import unittest
from unittest.mock import patch

from app.job_dispatcher import InlineJobDispatcher
from app.job_dispatcher import build_job_dispatcher


class JobDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_dispatcher_awaits_handler(self) -> None:
        dispatcher = InlineJobDispatcher(namespace='test')
        calls: list[str] = []

        async def handler() -> str:
            calls.append('called')
            return 'ok'

        result = await dispatcher.dispatch('runtime.tick', handler)

        self.assertEqual(result, 'ok')
        self.assertEqual(calls, ['called'])

    async def test_build_job_dispatcher_falls_back_to_inline_for_unknown_backend(self) -> None:
        with patch('app.job_dispatcher.settings.job_dispatcher_backend', 'arq'):
            with patch('app.job_dispatcher.settings.job_dispatcher_namespace', 'test'):
                dispatcher = build_job_dispatcher()

        self.assertIsInstance(dispatcher, InlineJobDispatcher)
