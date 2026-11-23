import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
