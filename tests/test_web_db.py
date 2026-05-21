import tempfile
import unittest
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app import db
from app import web_db


class WebUserBootstrapTests(unittest.TestCase):
    def test_bot_auth_allowed_login_does_not_become_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            with patch.object(web_db.settings, 'db_path', str(db_path)):
                with patch.object(web_db.settings, 'bot_auth_allowed_logins', 'bot-manager'):
                    web_db.init_web_db()
                    user = web_db.upsert_web_user(
                        twitch_user_id='123',
                        login='bot-manager',
                        display_name='Bot Manager',
                        access_token='token',
                    )

        self.assertEqual(int(user['is_admin']), 0)


class QuestionConfigWriteTests(unittest.TestCase):
    def test_write_questions_file_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_questions_dir = Path(tmp_dir) / 'user_questions'
            payload = '[{"category":"Кино","hint":"Подсказка","answer":"ответ","aliases":[]}]'.encode('utf-8-sig')

            with patch.object(web_db, 'USER_QUESTIONS_DIR', user_questions_dir):
                written_path = Path(web_db._write_questions_file(1, 'bom-test', 'quiz.json', payload))
                written_bytes = written_path.read_bytes()

                self.assertTrue(written_path.exists())
                self.assertEqual(written_bytes[:1], b'[')

    def test_write_questions_file_surfaces_storage_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_questions_dir = Path(tmp_dir) / 'user_questions'
            payload = '[{"category":"Кино","hint":"Подсказка","answer":"ответ","aliases":[]}]'.encode('utf-8')

            with patch.object(web_db, 'USER_QUESTIONS_DIR', user_questions_dir):
                with patch.object(Path, 'write_text', side_effect=OSError('disk full')):
                    with self.assertRaisesRegex(ValueError, 'Не удалось сохранить файл вопросов на сервере'):
                        web_db._write_questions_file(1, 'broken', 'quiz.json', payload)


class QuizSeasonTests(unittest.TestCase):
    def test_quiz_season_top_persists_even_after_runtime_points_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            future_end = datetime.now(UTC) + timedelta(days=7)
            with patch.object(db.settings, 'db_path', str(db_path)):
                db.init_db()
                season = db.create_quiz_season('user:1', 'Неделя знаний', ends_at=future_end)
                db.record_round('user:1', category='Кино', hint='Подсказка', answer='Ответ', winner='alpha', points_awarded=40)
                db.record_round('user:1', category='Кино', hint='Подсказка 2', answer='Ответ 2', winner='beta', points_awarded=20)
                db.reset_points('user:1')

                top = db.get_quiz_season_top('user:1', int(season['id']), limit=10)

        self.assertEqual([(item['username'], item['points']) for item in top], [('alpha', 40), ('beta', 20)])

    def test_quiz_season_can_be_finished_and_returned_from_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            now = datetime.now(UTC)
            with patch.object(db.settings, 'db_path', str(db_path)):
                db.init_db()
                created = db.create_quiz_season('user:2', 'Тестовый сезон', starts_at=now, ends_at=now + timedelta(days=3))
                finished = db.finish_quiz_season('user:2', int(created['id']), finished_at=now + timedelta(hours=2))
                latest = db.get_latest_quiz_season('user:2')
                history = db.list_quiz_seasons('user:2', limit=5)

        self.assertIsNotNone(finished)
        self.assertEqual(str((finished or {}).get('status')), 'finished')
        self.assertTrue(str((finished or {}).get('closed_at') or '').strip())
        self.assertEqual(str((latest or {}).get('status')), 'finished')
        self.assertEqual(len(history), 1)


class StandardQuestionConfigTests(unittest.TestCase):
    def test_uploaded_standard_preset_keeps_human_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            standard_dir = Path(tmp_dir) / 'data'
            standard_dir.mkdir(parents=True, exist_ok=True)
            payload = '[{"category":"????????","hint":"??????????????????","answer":"??????????","aliases":[]}]'.encode('utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                with patch.object(web_db, 'STANDARD_QUESTION_PRESETS_DIR', standard_dir):
                    web_db.init_web_db()
                    preset = web_db.add_standard_question_preset('?????????? ?????? (??????????/????????????/????????????/??????????????????)', 'quiz.json', payload)
                    stored_title = web_db.get_standard_question_preset_title(preset['file_name'])

        self.assertEqual(stored_title, '?????????? ?????? (??????????/????????????/????????????/??????????????????)')

    def test_uploaded_standard_preset_reuses_existing_human_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            standard_dir = Path(tmp_dir) / 'data'
            standard_dir.mkdir(parents=True, exist_ok=True)
            first_payload = '[{"category":"РљРёРЅРѕ","hint":"РџРѕРґСЃРєР°Р·РєР°","answer":"РѕС‚РІРµС‚","aliases":[]}]'.encode('utf-8')
            second_payload = '[{"category":"РЎР»РѕРІРѕ","hint":"Р•С‰С‘ РїРѕРґСЃРєР°Р·РєР°","answer":"РґСЂСѓРіРѕР№","aliases":[]},{"category":"Р¤РёР»СЊРј","hint":"РљРёРЅРѕ","answer":"РєР°РґСЂ","aliases":[]}]'.encode('utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                with patch.object(web_db, 'STANDARD_QUESTION_PRESETS_DIR', standard_dir):
                    web_db.init_web_db()
                    first = web_db.add_standard_question_preset('РћР±С‰РёР№ РїР°Рє', 'quiz.json', first_payload)
                    second = web_db.add_standard_question_preset('РћР±С‰РёР№ РїР°Рє', 'another.json', second_payload)
                    presets = web_db.get_standard_question_presets()

        self.assertEqual(first['file_name'], second['file_name'])
        self.assertTrue(first['file_name'].startswith('preset-'))
        self.assertEqual(len(presets), 1)
        self.assertEqual(int(presets[0]['question_count']), 2)

    def test_standard_config_does_not_consume_custom_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            preset_path = Path(tmp_dir) / 'questions.json'
            preset_path.write_text('[]', encoding='utf-8')
            payload = '[{"category":"Кино","hint":"Подсказка","answer":"ответ","aliases":[]}]'.encode('utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                web_db.init_web_db()
                with web_db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, '')",
                        ('1', 'owner', 'Owner', 'token', '', 'owner-slug'),
                    )
                web_db.add_user_question_config(1, 'Общий пак', 'questions.json', b'[]', is_standard=True, source_file_name='questions.json', file_path_override=str(preset_path))
                for index in range(3):
                    web_db.add_user_question_config(1, f'Кастом {index}', f'custom-{index}.json', payload)

                configs = web_db.get_user_question_configs(1)
                custom_count = web_db.count_user_question_configs(1, include_standard=False)

        self.assertEqual(custom_count, 3)
        self.assertEqual(len(configs), 4)

    def test_standard_config_cannot_be_deleted_from_user_cabinet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            preset_path = Path(tmp_dir) / 'questions.json'
            preset_path.write_text('[]', encoding='utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                web_db.init_web_db()
                with web_db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, '')",
                        ('1', 'owner', 'Owner', 'token', '', 'owner-slug'),
                    )
                config = web_db.add_user_question_config(
                    1,
                    'Общий пак',
                    'questions.json',
                    b'[]',
                    is_standard=True,
                    source_file_name='questions.json',
                    file_path_override=str(preset_path),
                )

                with self.assertRaisesRegex(ValueError, 'Стандартные конфиги нельзя удалять из кабинета'):
                    web_db.delete_user_question_config(1, int(config['id']))

    def test_admin_can_revoke_or_delete_any_standard_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            standard_dir = Path(tmp_dir) / 'data'
            standard_dir.mkdir(parents=True, exist_ok=True)
            builtin_path = standard_dir / 'questions.json'
            builtin_path.write_text('[]', encoding='utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                with patch.object(web_db, 'STANDARD_QUESTION_PRESETS_DIR', standard_dir):
                    web_db.init_web_db()
                    with web_db.get_conn() as conn:
                        conn.execute(
                            "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, '')",
                            ('1', 'owner', 'Owner', 'token', '', 'owner-slug'),
                        )
                        conn.execute(
                            "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, '')",
                            ('2', 'viewer', 'Viewer', 'token', '', 'viewer-slug'),
                        )

                    web_db.add_user_question_config(
                        1,
                        'Стандартная база',
                        'questions.json',
                        b'[]',
                        is_standard=True,
                        source_file_name='questions.json',
                        file_path_override=str(builtin_path),
                    )
                    web_db.add_user_question_config(
                        2,
                        'Стандартная база',
                        'questions.json',
                        b'[]',
                        is_standard=True,
                        source_file_name='questions.json',
                        file_path_override=str(builtin_path),
                    )
                    web_db.set_active_user_questions_config(1, 1)

                    revoke_result = web_db.revoke_standard_question_preset_access('questions.json')
                    self.assertEqual(revoke_result['deleted_links'], 2)
                    self.assertEqual(web_db.get_user_question_configs(1), [])
                    self.assertEqual(web_db.get_user_question_configs(2), [])
                    self.assertTrue(builtin_path.exists())

                    web_db.add_user_question_config(
                        1,
                        'Стандартная база',
                        'questions.json',
                        b'[]',
                        is_standard=True,
                        source_file_name='questions.json',
                        file_path_override=str(builtin_path),
                    )
                    delete_result = web_db.remove_standard_question_preset('questions.json')

        self.assertEqual(delete_result['deleted_links'], 1)
        self.assertEqual(delete_result['file_deleted'], 1)
        self.assertFalse(builtin_path.exists())

    def test_delete_standard_preset_removes_legacy_duplicates_with_same_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            standard_dir = Path(tmp_dir) / 'data'
            standard_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                with patch.object(web_db, 'STANDARD_QUESTION_PRESETS_DIR', standard_dir):
                    web_db.init_web_db()
                    with web_db.get_conn() as conn:
                        conn.execute(
                            '''
                            INSERT INTO question_presets(slug, name, content_json, is_builtin)
                            VALUES (?, ?, ?, 0), (?, ?, ?, 0)
                            ''',
                            (
                                'общийпаксловафильмыактерыпословицы.json',
                                'Общий пак (Слова/Фильмы/Актеры/Пословицы)',
                                '[{"category":"Кино","hint":"a","answer":"b","aliases":[]}]',
                                'общийпаксловафильмыактерыпословицы-b348.json',
                                'Общий пак (Слова/Фильмы/Актеры/Пословицы)',
                                '[{"category":"Кино","hint":"c","answer":"d","aliases":[]}]',
                            ),
                        )

                    result = web_db.remove_standard_question_preset('общийпаксловафильмыактерыпословицы.json')
                    presets = web_db.get_standard_question_presets()

        self.assertEqual(result['file_deleted'], 1)
        self.assertEqual(presets, [])

    def test_personal_question_config_is_stored_via_db_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            payload = b'[{"category":"Movie","hint":"Test hint","answer":"test","aliases":[]}]'

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                web_db.init_web_db()
                with web_db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, '')",
                        ('1', 'owner', 'Owner', 'token', '', 'owner-slug'),
                    )

                config = web_db.add_user_question_config(1, 'Personal pack', 'quiz.json', payload)
                loaded = web_db.load_questions_payload_from_source(str(config['file_path']))

        self.assertTrue(str(config['file_path']).startswith(web_db.DB_USER_QUESTION_CONFIG_PREFIX))
        self.assertEqual(loaded[0]['answer'], 'test')

    def test_init_web_db_migrates_personal_file_configs_into_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'test.db'
            legacy_path = Path(tmp_dir) / 'legacy-pack.json'
            legacy_path.write_text('[{"category":"Movie","hint":"Legacy hint","answer":"legacy","aliases":[]}]', encoding='utf-8')

            with patch.object(web_db.settings, 'db_path', str(db_path)):
                web_db.init_web_db()
                with web_db.get_conn() as conn:
                    conn.execute(
                        "INSERT INTO web_users(twitch_user_id, login, display_name, access_token, refresh_token, overlay_slug, questions_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ('1', 'owner', 'Owner', 'token', '', 'owner-slug', str(legacy_path)),
                    )
                    conn.execute(
                        "INSERT INTO user_question_configs(user_id, name, file_path, content_json, is_standard, source_file_name) VALUES (?, ?, ?, ?, 0, '')",
                        (1, 'Legacy pack', str(legacy_path), '[]'),
                    )

                web_db.init_web_db()
                config = web_db.get_question_config_by_id(1, 1)
                user = web_db.get_web_user_by_id(1)
                loaded = web_db.load_questions_payload_from_source(str((config or {}).get('file_path') or ''))

        self.assertIsNotNone(config)
        self.assertTrue(str((config or {}).get('file_path') or '').startswith(web_db.DB_USER_QUESTION_CONFIG_PREFIX))
        self.assertEqual(str((user or {}).get('questions_file') or ''), str((config or {}).get('file_path') or ''))
        self.assertEqual(loaded[0]['answer'], 'legacy')
        self.assertFalse(legacy_path.exists())
