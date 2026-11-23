import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log


class PadLevels(unittest.TestCase):
    def test_sdl_levels_map_to_pygame_names(self):
        self.assertEqual([server.sdl_power_level(n) for n in (-1, 0, 1, 2, 3, 4, 5, 9)],
                         ["unknown", "empty", "low", "medium", "full", "wired", "max", "unknown"])

    def test_virtual_pad_without_battery_doesnt_alarm(self):
        # Sunshine's virtual Xbox pad reports wired/unknown: never "empty" or "low"
        self.assertEqual(server.pad_status_for([server.sdl_power_level(-1)]), "pad:max")

    def test_charging_pad_is_marked(self):
        self.assertEqual(server.pad_status_for(["empty", "wired"], charging=(0,)), "pad:empty+,wired")


if __name__ == "__main__":
    unittest.main()
