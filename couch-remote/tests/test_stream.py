import tempfile
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class Stream(unittest.TestCase):
    def setUp(self):
        server.STREAM.update(on=False, device="")
        self.addCleanup(server.STREAM.update, on=False, device="")
        p = mock.patch.object(server, "emit")
        self.emit = p.start()
        self.addCleanup(p.stop)

    def test_on_then_off_emits_and_updates(self):
        server.set_stream(True, "Apple TV")
        self.assertEqual(server.STREAM, {"on": True, "device": "Apple TV"})
        self.emit.assert_called_with("stream:Apple TV")
        server.set_stream(False)
        self.assertIs(server.STREAM["on"], False)
        self.emit.assert_called_with("stream:off")

    def test_on_without_device_names_another_screen(self):
        server.set_stream(True, "")
        self.assertEqual(server.STREAM["device"], "another screen")

    def test_off_without_on_is_fine(self):
        server.set_stream(False)
        self.emit.assert_called_with("stream:off")

    def test_device_name_trimmed_to_40_chars(self):
        server.set_stream(True, "x" * 60)
        self.assertEqual(len(server.STREAM["device"]), 40)

    def test_audio_left_alone_while_streaming(self):
        args = ({"id": "tv", "name": "TV"}, ["other"], {"tv": "TV", "other": "Speakers"})
        self.assertEqual(server.audio_replaced(*args), {"Speakers"})
        server.STREAM["on"] = True
        self.assertIsNone(server.audio_replaced(*args))


class SunshineLog(unittest.TestCase):
    def setUp(self):
        server.STREAM.update(on=False, device="")
        self.addCleanup(server.STREAM.update, on=False, device="")
        p = mock.patch.object(server, "emit")
        p.start()
        self.addCleanup(p.stop)

    def test_disconnect_ends_the_stream(self):
        server.set_stream(True, "Apple TV")
        server.sunshine_events("[2026-11-22 20:08:38.094]: Info: CLIENT DISCONNECTED\n")
        self.assertIs(server.STREAM["on"], False)

    def test_reconnect_to_open_session_brings_back_last_device(self):
        server.set_stream(True, "Apple TV")
        server.sunshine_events("Info: CLIENT DISCONNECTED\nWarning: ControllerNumber already allocated [0]\n")
        server.sunshine_events("[x]: Info: CLIENT CONNECTED\n")
        self.assertEqual(server.STREAM, {"on": True, "device": "Apple TV"})

    def test_other_lines_change_nothing(self):
        server.sunshine_events("Info: Gamepad 0 will be Xbox 360 controller (default)\n")
        self.assertIs(server.STREAM["on"], False)


class VibepolloOrSunshine(unittest.TestCase):
    def status(self, installed):
        def run(cmd, **kw):
            out = "SERVICE_NAME: x  STATE : 4  RUNNING" if cmd[-1] in installed else "OpenService FAILED 1060"
            return mock.Mock(stdout=out)
        with mock.patch.object(server.subprocess, "run", run):
            return server.sunshine_status(), server.STREAM_HOST[0]

    def test_vibepollo_wins_over_a_leftover_sunshine(self):
        self.assertEqual(self.status({"ApolloService", "SunshineService"}), ("running", "Vibepollo"))

    def test_a_pc_still_on_sunshine_keeps_working(self):
        self.assertEqual(self.status({"SunshineService"}), ("running", "Sunshine"))

    def test_neither_installed_asks_for_vibepollo(self):
        self.assertEqual(self.status(set()), (None, "Vibepollo"))

    def test_newest_log_is_followed(self):
        root = Path(tempfile.mkdtemp())
        old, new = root / "Sunshine" / "sunshine.log", root / "Apollo" / "logs" / "sunshine-20261125-1.log"
        for f, t in ((old, 1000), (new, 2000)):
            f.parent.mkdir(parents=True)
            f.write_text("x")
            os.utime(f, (t, t))
        with mock.patch.object(server, "STREAM_DIRS", [root / "Apollo", root / "Sunshine"]):
            self.assertEqual(server.stream_log(), new)


if __name__ == "__main__":
    unittest.main()
