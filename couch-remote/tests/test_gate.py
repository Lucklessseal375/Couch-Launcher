"""Checks the network gate that protects the remote (home network only, no PIN).  Run:  python -m unittest discover tests"""
import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

spec = importlib.util.spec_from_file_location("server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def call(host, port, path, headers=None):
    req = urllib.request.Request(f"http://{host}:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class GateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.ThreadingHTTPServer(("0.0.0.0", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.lan = (server.lan_ips() or [None])[0]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_local_needs_custom_header(self):
        self.assertEqual(call("127.0.0.1", self.port, "/api/ping"), 403)
        self.assertEqual(call("127.0.0.1", self.port, "/api/ping", {"X-Couch": "1"}), 200)

    def test_foreign_host_header_rejected(self):  # blocks DNS-rebinding tricks from websites
        self.assertEqual(call("127.0.0.1", self.port, "/api/ping", {"X-Couch": "1", "Host": "evil.example"}), 403)

    def test_lan_works_without_pin(self):
        if not self.lan:
            self.skipTest("no LAN address")
        self.assertEqual(call(self.lan, self.port, "/api/ping", {"X-Couch": "1"}), 200)

    def test_events_stream_is_local_only(self):
        if not self.lan:
            self.skipTest("no LAN address")
        self.assertEqual(call(self.lan, self.port, "/api/events", {"X-Couch": "1"}), 404)


class VdfTest(unittest.TestCase):
    def test_parses_nested_and_escaped(self):
        text = '"a"\n{\n\t"path"\t\t"C:\\\\Steam"\n\t"apps"\n\t{\n\t\t"10"\t"1"\n\t}\n\t"empty"\t""\n}'
        self.assertEqual(server.parse_vdf(text), {"a": {"path": "C:\\Steam", "apps": {"10": "1"}, "empty": ""}})


if __name__ == "__main__":
    unittest.main()
