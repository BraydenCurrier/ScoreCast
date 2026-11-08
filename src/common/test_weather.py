import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from common import weather as weather_module
from common.fonts import get_4x5_width
from common.weather import (
    board_place,
    clear_weather_cache,
    condition_label,
    location_from_detection_body,
    normalize_weather_location,
    place_from_geocode_body,
    place_from_zip_body,
    reading_from_forecast_body,
    refresh_weather,
    standby_weather,
    weather_status,
)


IPWHO = json.dumps({
    "success": True,
    "city": "Austin",
    "region": "Texas",
    "latitude": 30.2672,
    "longitude": -97.7431,
})

IPAPI = json.dumps({
    "city": "Denver",
    "region": "Colorado",
    "latitude": "39.7392",
    "longitude": "-104.9903",
    "error": False,
})

IPINFO = json.dumps({
    "city": "Seattle",
    "region": "Washington",
    "loc": "47.6062,-122.3321",
})

GEOCODE = json.dumps({
    "results": [{
        "name": "Austin",
        "admin1": "Texas",
        "latitude": 30.2672,
        "longitude": -97.7431,
    }],
})

ZIP = json.dumps({
    "places": [{
        "place name": "Austin",
        "state": "Texas",
        "latitude": "30.2672",
        "longitude": "-97.7431",
    }],
})

FORECAST = json.dumps({
    "current": {
        "temperature_2m": 72.4,
        "weather_code": 0,
    },
})


class WeatherParseTests(unittest.TestCase):
    def test_ip_lookups_share_a_place_shape(self):
        austin = location_from_detection_body("ipwho", IPWHO)
        denver = location_from_detection_body("ipapi", IPAPI)
        seattle = location_from_detection_body("ipinfo", IPINFO)

        self.assertEqual(austin["name"], "Austin")
        self.assertEqual(austin["region"], "Texas")
        self.assertAlmostEqual(austin["latitude"], 30.2672)
        self.assertEqual(denver["name"], "Denver")
        self.assertEqual(seattle["name"], "Seattle")
        self.assertAlmostEqual(seattle["longitude"], -122.3321)
        self.assertIsNone(location_from_detection_body(
            "ipwho",
            json.dumps({"success": False}),
        ))

    def test_a_saved_place_can_be_a_city_or_a_zip(self):
        city = place_from_geocode_body(GEOCODE)
        zip_code = place_from_zip_body(ZIP)
        reading = reading_from_forecast_body(FORECAST)

        self.assertEqual(city["name"], "Austin")
        self.assertEqual(city["source"], "setting")
        self.assertEqual(zip_code["region"], "Texas")
        self.assertEqual(reading, {"temperature": 72, "condition": "CLEAR"})
        self.assertEqual(condition_label(95), "STORM")
        self.assertEqual(condition_label(999), "")
        self.assertEqual(board_place("São Paulo"), "SAO PAULO")
        self.assertEqual(normalize_weather_location("  Austin,   TX "), "Austin, TX")
        self.assertGreater(get_4x5_width("72°"), get_4x5_width("72"))


class WeatherRefreshTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._dir = patch.object(
            weather_module,
            "SETTINGS_DIR",
            Path(self._temp.name),
        )
        self._dir.start()
        clear_weather_cache()
        self.addCleanup(self._dir.stop)
        self.addCleanup(clear_weather_cache)
        self.addCleanup(self._temp.cleanup)

    def test_a_saved_place_overrides_the_network(self):
        def get_body(url, timeout, headers=None):
            if "ipwho.is" in url or "ipapi.co" in url or "ipinfo.io" in url:
                raise AssertionError(url)
            if "geocoding-api" in url:
                return GEOCODE
            if "forecast" in url:
                return FORECAST
            raise AssertionError(url)

        with (
            self._settings("Austin, TX"),
            patch.object(weather_module, "get_body", get_body),
        ):
            refresh_weather()
            self.assertEqual(standby_weather(), ("AUSTIN", "72", "CLEAR"))
            status = weather_status()

        self.assertEqual(status["source"], "setting")
        self.assertEqual(status["place"], "Austin, Texas")
        self.assertIn("72°", status["detail"])

    def test_a_blank_place_uses_the_public_ip(self):
        calls = []

        def get_body(url, timeout, headers=None):
            calls.append(url)
            if "ipwho.is" in url:
                return IPWHO
            if "forecast" in url:
                return FORECAST
            raise AssertionError(url)

        with (
            self._settings(""),
            patch.object(weather_module, "get_body", get_body),
        ):
            refresh_weather()
            self.assertEqual(standby_weather(), ("AUSTIN", "72", "CLEAR"))
            self.assertIn("from this network", weather_status()["detail"])
            refresh_weather()

        self.assertEqual(len(calls), 2)
        self.assertTrue(any("ipwho.is" in url for url in calls))

    def test_a_zip_code_is_looked_up_before_the_city_search(self):
        def get_body(url, timeout, headers=None):
            if "zippopotam" in url:
                return ZIP
            if "forecast" in url:
                return FORECAST
            raise AssertionError(url)

        with (
            self._settings("78701"),
            patch.object(weather_module, "get_body", get_body),
        ):
            refresh_weather()
            self.assertEqual(standby_weather()[0], "AUSTIN")

    def test_an_unknown_place_leaves_the_clock_without_weather(self):
        def get_body(url, timeout, headers=None):
            if "geocoding-api" in url:
                return json.dumps({"results": []})
            raise AssertionError(url)

        with (
            self._settings("Nowhereville"),
            patch.object(weather_module, "get_body", get_body),
        ):
            refresh_weather()
            self.assertIsNone(standby_weather())
            self.assertIn("did not match", weather_status()["detail"])

    def test_a_fresh_reading_is_kept_while_the_forecast_is_down(self):
        calls = {"forecast": 0}

        def get_body(url, timeout, headers=None):
            if "geocoding-api" in url:
                return GEOCODE
            if "forecast" in url:
                calls["forecast"] += 1
                if calls["forecast"] == 1:
                    return FORECAST
                return None
            raise AssertionError(url)

        with (
            self._settings("Austin"),
            patch.object(weather_module, "get_body", get_body),
        ):
            refresh_weather()
            with weather_module._lock:
                located_at = weather_module._state["located_at"]
                weather_module._state["fetched_at"] = (
                    time.time() - weather_module.WEATHER_FRESH_SECONDS - 5
                )
            refresh_weather()
            with weather_module._lock:
                self.assertEqual(
                    weather_module._state["located_at"],
                    located_at,
                )
            self.assertEqual(standby_weather(), ("AUSTIN", "72", "CLEAR"))

    def test_a_saved_reading_survives_a_restart(self):
        with (
            self._settings("Austin"),
            patch.object(
                weather_module,
                "get_body",
                side_effect=self._austin_bodies,
            ),
        ):
            refresh_weather()

        with weather_module._lock:
            weather_module._loaded = False
            weather_module._reset_state()

        with self._settings("Austin"):
            self.assertEqual(standby_weather(), ("AUSTIN", "72", "CLEAR"))

    def _settings(self, location):
        return patch.object(
            weather_module,
            "get_settings",
            return_value={"weather": {"location": location}},
        )

    @staticmethod
    def _austin_bodies(url, timeout, headers=None):
        if "geocoding-api" in url:
            return GEOCODE
        if "forecast" in url:
            return FORECAST
        raise AssertionError(url)


if __name__ == "__main__":
    unittest.main()
