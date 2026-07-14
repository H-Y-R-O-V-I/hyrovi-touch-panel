from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from app import update


class UpdateHealthcheckTests(unittest.TestCase):
    def _response(self, status_code: int = 200, payload=None):
        response = MagicMock()
        response.status_code = status_code
        response.json = MagicMock(return_value=payload)
        if status_code >= 400:
            response.raise_for_status = MagicMock(side_effect=requests.HTTPError(response=response))
        else:
            response.raise_for_status = MagicMock(return_value=None)
        return response

    @patch("app.update.time.sleep")
    @patch("app.update.requests.get")
    def test_admin_healthcheck_retries_until_ok(self, mock_get, mock_sleep) -> None:
        mock_get.side_effect = [
            requests.ConnectionError("refused"),
            self._response(200, {"ok": False, "status": "starting"}),
            self._response(200, {"ok": True, "status": "ready"}),
        ]

        ok, detail = update._admin_healthcheck()

        self.assertTrue(ok)
        self.assertEqual(detail, "ready")
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("app.update.time.sleep")
    @patch("app.update.requests.get")
    def test_admin_healthcheck_keeps_retrying_on_http_errors(self, mock_get, mock_sleep) -> None:
        mock_get.side_effect = [self._response(503)] * 30

        ok, detail = update._admin_healthcheck(timeout=0.1)

        self.assertFalse(ok)
        self.assertEqual(detail, "Admin healthcheck failed with HTTP 503.")
        self.assertEqual(mock_get.call_count, 30)
        self.assertEqual(mock_sleep.call_count, 30)


if __name__ == "__main__":
    unittest.main()
