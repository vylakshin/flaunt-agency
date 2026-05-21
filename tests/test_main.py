import unittest

from starlette.middleware.sessions import SessionMiddleware

from app.main import app
from app.main import settings


class SessionMiddlewareTests(unittest.TestCase):
    def test_session_cookie_is_secure_in_production(self) -> None:
        middleware = next(item for item in app.user_middleware if item.cls is SessionMiddleware)
        self.assertEqual(middleware.kwargs.get("https_only"), not settings.debug)
        self.assertEqual(middleware.kwargs.get("same_site"), "lax")
