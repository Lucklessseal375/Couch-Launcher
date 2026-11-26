import base64
import http.client
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

RUNNING = """SERVICE_NAME: SunshineService
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_PRESHUTDOWN)
"""
STOPPED = """SERVICE_NAME: SunshineService
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
"""
MISSING = """[SC] EnumQueryServicesStatus:OpenService FAILED 1060:

The specified service does not exist as an installed service.
"""


class SunshineStatus(unittest.TestCase):
    def test_running(self):
        self.assertEqual(server.parse_sc(RUNNING), "running")

    def test_stopped(self):
        self.assertEqual(server.parse_sc(STOPPED), "stopped")

    def test_not_installed(self):
        self.assertIsNone(server.parse_sc(MISSING))


class SunshineLogin(unittest.TestCase):
    def setUp(self):  # never the real login file, never the real Sunshine
        p = mock.patch.object(server, "SUNSHINE_CRED", Path(tempfile.mkdtemp()) / "sunshine.cred")
        self.cred = p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def fake(self, status=200, body=None):
        def urlopen(req, timeout, context):
            self.calls.append(req)
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, "no", {}, io.BytesIO(b""))
            return io.BytesIO(json.dumps(body or {"status": True}).encode())
        return mock.patch("urllib.request.urlopen", urlopen)

    def test_dpapi_round_trip(self):
        sealed = server.dpapi(b"user:pa ss", protect=True)
        self.assertNotIn(b"pa ss", sealed)
        self.assertEqual(server.dpapi(sealed, protect=False), b"user:pa ss")

    def test_login_saved_only_when_sunshine_accepts_it(self):
        with self.fake(401):
            self.assertFalse(server.sunshine_login("me", "wrong"))
        self.assertFalse(server.SUNSHINE_CRED.exists())
        with self.fake(200):
            self.assertTrue(server.sunshine_login("me", "right"))
        self.assertTrue(server.SUNSHINE_CRED.exists())
        self.assertNotIn(b"right", server.SUNSHINE_CRED.read_bytes())

    def test_calls_carry_the_saved_login_to_localhost_only(self):
        with self.fake(200):
            server.sunshine_login("me", "pw")
        with self.fake(200, {"pairings": [{"id": "abc"}]}):
            r = server.sunshine_api("GET", "/api/pin")
        self.assertEqual(r, {"pairings": [{"id": "abc"}]})
        req = self.calls[-1]
        self.assertEqual(req.full_url, "https://localhost:47990/api/pin")
        self.assertEqual(req.get_header("Authorization"), "Basic " + base64.b64encode(b"me:pw").decode())

    def test_rejected_saved_login_is_forgotten(self):
        with self.fake(200):
            server.sunshine_login("me", "pw")
        with self.fake(401):
            with self.assertRaises(PermissionError):
                server.sunshine_api("POST", "/api/restart", {})
        self.assertFalse(server.SUNSHINE_CRED.exists())

    def test_a_restart_that_hangs_up_without_answering_worked(self):  # Vibepollo does this
        with self.fake(200):
            server.sunshine_login("me", "pw")
        gone = mock.patch("urllib.request.urlopen", side_effect=http.client.RemoteDisconnected("closed"))
        with gone:
            self.assertEqual(server.sunshine_api("POST", "/api/restart", {}), {})
            with self.assertRaises(OSError):
                server.sunshine_api("GET", "/api/clients/list")

    def test_end_stream_closes_sunshines_app(self):
        self.assertEqual(server.SUNSHINE_ACTIONS["close"](), ("POST", "/api/apps/close", {}))

    def test_no_login_yet(self):
        with self.assertRaises(PermissionError):
            server.sunshine_api("GET", "/api/clients/list")


if __name__ == "__main__":
    unittest.main()
