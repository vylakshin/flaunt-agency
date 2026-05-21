import unittest
from io import BytesIO
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import UploadFile

import app.web_site_presence as web_site_presence


class StandardQuestionPresetRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_can_upload_standard_question_preset(self) -> None:
        request = object()
        admin_user = {"id": 1, "login": "admin", "display_name": "admin", "is_admin": 1}
        upload = UploadFile(filename="quiz.json", file=BytesIO(b"[]"))

        with patch.object(web_site_presence, "require_admin_user", return_value=admin_user):
            with patch.object(
                web_site_presence,
                "add_standard_question_preset",
                return_value={"file_name": "quiz-pack.json"},
            ):
                with patch.object(web_site_presence, "_log_user_action") as log_mock:
                    response = await web_site_presence.api_app_settings_question_presets_upload(
                        request,
                        config_name="Новый пак",
                        questions_file=upload,
                    )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["file_name"], "quiz-pack.json")
        log_mock.assert_called_once()

    async def test_admin_can_delete_uploaded_standard_question_preset(self) -> None:
        request = object()
        admin_user = {"id": 1, "login": "admin", "display_name": "admin", "is_admin": 1}

        with patch.object(web_site_presence, "require_admin_user", return_value=admin_user):
            with patch.object(
                web_site_presence,
                "remove_standard_question_preset",
                return_value={"deleted_links": 4, "file_deleted": 1},
            ):
                with patch.object(web_site_presence, "_log_user_action") as log_mock:
                    response = await web_site_presence.api_app_settings_question_presets_delete(
                        request,
                        {"file_name": "quiz-pack.json"},
                    )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted_links"], 4)
        log_mock.assert_called_once()

    async def test_admin_can_revoke_standard_question_preset_access(self) -> None:
        request = object()
        admin_user = {"id": 1, "login": "admin", "display_name": "admin", "is_admin": 1}

        with patch.object(web_site_presence, "require_admin_user", return_value=admin_user):
            with patch.object(
                web_site_presence,
                "revoke_standard_question_preset_access",
                return_value={"deleted_links": 7},
            ):
                with patch.object(web_site_presence, "_log_user_action") as log_mock:
                    response = await web_site_presence.api_app_settings_question_presets_revoke(
                        request,
                        {"file_name": "questions.json"},
                    )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted_links"], 7)
        log_mock.assert_called_once()


class StandardQuestionPresetUserProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_cannot_delete_standard_config_from_dashboard(self) -> None:
        request = object()
        user = {"id": 4, "login": "owner", "display_name": "owner", "twitch_user_id": "123"}
        config = {"id": 11, "name": "Общий пак", "file_path": "/tmp/questions.json", "is_standard": 1}

        with patch.object(web_site_presence, "require_channel_user", AsyncMock(return_value=user)):
            with patch.object(web_site_presence, "get_question_config_by_id", return_value=config):
                with patch.object(
                    web_site_presence,
                    "delete_user_question_config",
                    side_effect=ValueError("Стандартные конфиги нельзя удалять из кабинета."),
                ):
                    response = await web_site_presence.api_app_dashboard_questions_delete(
                        request,
                        {"config_id": 11},
                    )

        payload = web_site_presence.json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Стандартные конфиги нельзя удалять из кабинета.")
