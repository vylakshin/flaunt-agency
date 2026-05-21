import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config


class PersistSettingsEnvTests(unittest.TestCase):
    def test_persist_updates_values_and_preserves_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("# comment\nA=1\nB=2\n", encoding="utf-8")

            with patch.object(config, "ENV_FILE", env_path):
                config.persist_settings_env({"B": "3", "C": "4"})

            self.assertEqual(env_path.read_text(encoding="utf-8"), "# comment\nA=1\nB=3\nC=4\n")

    def test_persist_creates_missing_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"

            with patch.object(config, "ENV_FILE", env_path):
                config.persist_settings_env({"A": "1"})

            self.assertEqual(env_path.read_text(encoding="utf-8"), "A=1\n")
