from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from app.doctor import _touch_plausible


class DoctorTests(unittest.TestCase):
    @patch("app.doctor.subprocess.run")
    def test_touch_detection_uses_libinput_capabilities(self, mock_run) -> None:
        mock_proc = subprocess.CompletedProcess(
            args=["libinput", "list-devices"],
            returncode=0,
            stdout="""
Device:           wch.cn USB2IIC_CTP_CONTROL
Kernel:           /dev/input/event3
Capabilities:     touch
""",
            stderr="",
        )
        mock_run.return_value = mock_proc
        ok, detail = _touch_plausible()
        self.assertTrue(ok)
        self.assertIn("Capabilities: touch", detail)


if __name__ == "__main__":
    unittest.main()
