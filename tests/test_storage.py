from __future__ import annotations

import getpass
import grp
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from app.config.storage import atomic_write_yaml


class StorageTests(unittest.TestCase):
    def test_atomic_write_yaml_persists_data_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.yaml"
            current_user = getpass.getuser()
            current_group = grp.getgrgid(os.getgid()).gr_name
            atomic_write_yaml(target, {"home_assistant": {"url": "http://homeassistant.local:8123"}}, owner=current_user, group=current_group, mode=0o640)
            self.assertTrue(target.exists())
            self.assertEqual(yaml.safe_load(target.read_text(encoding="utf-8")), {"home_assistant": {"url": "http://homeassistant.local:8123"}})
            self.assertEqual(oct(target.stat().st_mode & 0o777), "0o640")


if __name__ == "__main__":
    unittest.main()
