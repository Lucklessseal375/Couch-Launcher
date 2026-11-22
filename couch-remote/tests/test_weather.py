import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
server.log.disabled = True  # keep test runs out of the real server.log

PLACE = {"results": [{"name": "Springfield", "latitude": 1.0, "longitude": 2.0}]}
NOW = {"current": {"temperature_2m": 64.6, "weather_code": 61, "is_day": 0},
       "daily": {"temperature_2m_max": [70.2], "temperature_2m_min": [51.9]}}


class Weather(unittest.TestCase):
    def setUp(self):
        server.WEATHER.update(at=0.0, place=None, now=None)
        self.addCleanup(server.WEATHER.update, at=0.0, place=None, now=None)

    def run_with(self, cfg, replies):
        urls = []

        def urlopen(req, timeout):
            urls.append(req.full_url)
            return io.BytesIO(json.dumps(replies.pop(0)).encode())
        with mock.patch.dict(server.CONFIG, {"weather": cfg} if cfg else {}, clear=False), \
                mock.patch("urllib.request.urlopen", urlopen):
            if not cfg:
                server.CONFIG.pop("weather", None)
            return server.weather(), urls

    def test_no_city_sends_nothing(self):
        now, urls = self.run_with(None, [])
        self.assertIsNone(now)
        self.assertEqual(urls, [])

    def test_reads_city_then_weather(self):
        now, urls = self.run_with({"city": "Springfield"}, [PLACE, NOW])
        self.assertEqual(now, {"city": "Springfield", "temp": 65, "code": 61, "day": False, "hi": 70, "lo": 52})
        self.assertIn("name=Springfield", urls[0])
        self.assertIn("temperature_unit=fahrenheit", urls[1])

    def test_cached_for_30_minutes(self):
        self.run_with({"city": "Springfield"}, [PLACE, NOW])
        now, urls = self.run_with({"city": "Springfield"}, [])
        self.assertEqual(urls, [])  # no new request
        self.assertEqual(now["temp"], 65)


if __name__ == "__main__":
    unittest.main()
