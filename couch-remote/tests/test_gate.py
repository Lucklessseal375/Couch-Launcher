"""Checks the network gate that protects the remote (home network only, no PIN).  Run:  python -m unittest discover tests"""
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

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



class PadStatusTest(unittest.TestCase):
    def test_weakest_battery_wins(self):
        self.assertEqual(server.pad_status_for([]), "pad:none")
        self.assertEqual(server.pad_status_for(["full", "low"]), "pad:low")
        self.assertEqual(server.pad_status_for(["wired", "medium"]), "pad:medium")
        self.assertEqual(server.pad_status_for(["unknown"]), "pad:max")


class PickRunningTest(unittest.TestCase):
    def test_game_window_beats_store_windows(self):
        self.assertIsNone(server.pick_running([]))
        self.assertEqual(server.pick_running([(1, "steam.exe"), (2, "game.exe"), (3, "steamwebhelper.exe")]), 2)
        self.assertEqual(server.pick_running([(1, "steam.exe"), (3, "steamwebhelper.exe")]), 3)  # Big Picture


class ChoicesTest(unittest.TestCase):
    def test_hide_pin_and_show_again(self):
        epic = [{"id": "gta5", "name": "GTA"}]
        steam = [{"appid": 1, "name": "A"}, {"appid": 2, "name": "B"}]
        with (tempfile.TemporaryDirectory() as d,
              mock.patch.object(server, "CHOICES_FILE", Path(d) / "choices.json"),
              mock.patch.object(server, "load_games", lambda: [dict(g) for g in epic]),
              mock.patch.object(server, "steam_games", lambda: [dict(g) for g in steam])):
            server.set_choice("pin", "steam:2")
            server.set_choice("hide", "gta5")
            shown, hidden = server.library()
            self.assertEqual([g["name"] for g in shown], ["B", "A"])
            self.assertEqual(hidden, ["GTA"])
            server.set_choice("unpin", "steam:2")
            server.set_choice("unhide-all")
            self.assertEqual([g["name"] for g in server.library()[0]], ["GTA", "A", "B"])
            with self.assertRaises(KeyError):
                server.set_choice("hide", "steam:999")  # only games that exist


class AudioKeeperTest(unittest.TestCase):
    def test_when_to_switch_back(self):
        tv = {"id": "tv", "name": "SAMSUNG"}
        names = {"tv": "SAMSUNG", "spdif": "Digital Audio (S/PDIF)", "rp": "Speakers (Steam Streaming Speakers)"}
        self.assertIsNone(server.audio_replaced(tv, ("tv", "tv", "tv"), names))              # already right
        self.assertEqual(server.audio_replaced(tv, ("tv", "tv", "spdif"), names), {"Digital Audio (S/PDIF)"})
        self.assertIsNone(server.audio_replaced(tv, ("spdif",) * 3, {"spdif": "S/PDIF"}))    # TV is off: wait
        self.assertIsNone(server.audio_replaced(tv, ("rp", "rp", "rp"), names))              # Remote Play: leave it


class PlaytimeTest(unittest.TestCase):
    def test_reads_steams_minutes_played(self):
        vdf = ('"UserLocalConfigStore" { "Software" { "valve" { "Steam" { "apps" {'
               ' "220" { "Playtime" "95" } "440" { "LastPlayed" "1" } } } } } }')
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "userdata" / "123" / "config"
            cfg.mkdir(parents=True)
            (cfg / "localconfig.vdf").write_text(vdf, encoding="utf-8")
            with mock.patch.object(server, "steam_path", lambda: Path(d)):
                self.assertEqual(server.steam_playtime(), {220: 95})


class AppIconTest(unittest.TestCase):
    def test_extracts_a_256px_png(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "python.png"
            self.assertTrue(server.exe_icon_png(sys.executable, out))
            png = out.read_bytes()
            self.assertEqual(png[1:4], b"PNG")  # PNG signature
            self.assertEqual(int.from_bytes(png[16:20], "big"), 256)  # width in the PNG header


class AudioNamesPermissionTest(unittest.TestCase):
    def test_grants_the_page_in_its_profile_and_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "PROFILES", Path(d)):
            prefs = Path(d) / "launcher" / "Default" / "Preferences"
            server.allow_audio_names("launcher", "http://127.0.0.1:8765")  # no profile yet: nothing happens
            self.assertFalse(prefs.exists())
            prefs.parent.mkdir(parents=True)
            prefs.write_text('{"zoom": 1}', encoding="utf-8")
            server.allow_audio_names("launcher", "http://127.0.0.1:8765")
            data = json.loads(prefs.read_text(encoding="utf-8"))
            self.assertEqual(data["zoom"], 1)
            self.assertEqual(data["profile"]["content_settings"]["exceptions"]["media_stream_mic"]
                             ["http://127.0.0.1:8765,*"], {"setting": 1})


if __name__ == "__main__":
    unittest.main()
