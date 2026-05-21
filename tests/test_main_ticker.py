import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import app.main as main


class MainTickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_ticker_dispatches_all_background_ticks(self) -> None:
        dispatch_mock = AsyncMock(side_effect=[None, None, None, asyncio.CancelledError()])

        async def no_sleep(_: float) -> None:
            return None

        with patch.object(main, 'job_dispatcher', new=SimpleNamespace(dispatch=dispatch_mock)):
            with patch.object(main.asyncio, 'sleep', side_effect=no_sleep):
                await main._run_runtime_ticker()

        dispatched_jobs = [call.args[0] for call in dispatch_mock.await_args_list[:3]]
        self.assertEqual(dispatched_jobs, ['runtime.tick', 'timers.tick', 'autobet.tick'])
