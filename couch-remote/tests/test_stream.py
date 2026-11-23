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


if __name__ == "__main__":
    unittest.main()
