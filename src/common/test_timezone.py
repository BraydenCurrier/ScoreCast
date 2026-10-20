import json
import os
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from common import timezone as timezone_module
from common.timezone import (
    clear_timezone_cache,
    detect_timezone_name,
    ensure_network_timezone,
    format_local_date,
    format_local_time,
    get_local_timezone,
    normalize_timezone_setting,
    timezone_from_detection_body,
    timezone_status,
)


class TimezoneTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self._settings_dir = Path(self._temp.name)
        self._dir_patch = patch.object(
            timezone_module,
            "SETTINGS_DIR",
            self._settings_dir,
        )
        self._dir_patch.start()
        clear_timezone_cache()
        self.addCleanup(self._dir_patch.stop)
        self.addCleanup(clear_timezone_cache)
        self.addCleanup(self._temp.cleanup)

    def test_manual_timezone_overrides_network_and_system_zone(self):
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Auckland"
        time.tzset()
        try:
            with self._settings({"timezone": "America/Los_Angeles"}):
                zone = get_local_timezone()
                self.assertEqual(zone.key, "America/Los_Angeles")
                self.assertEqual(
                    timezone_status()["source"],
                    "setting",
                )
        finally:
            self._restore_tz(old_tz)

    def test_automatic_without_detection_uses_utc(self):
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Honolulu"
        time.tzset()
        try:
            with self._settings({"timezone": "auto"}):
                zone = get_local_timezone()
                self.assertEqual(zone.key, "UTC")
                now = __import__("datetime").datetime.now(zone)
                self.assertEqual(now.utcoffset(), timedelta(0))
                self.assertEqual(
                    timezone_status()["source"],
                    "fallback",
                )
        finally:
            self._restore_tz(old_tz)

    def test_saved_network_zone_is_used_for_automatic(self):
        self._write_cache("America/Chicago", time.time())
        with self._settings({"timezone": "auto"}):
            self.assertEqual(
                get_local_timezone().key,
                "America/Chicago",
            )
            self.assertEqual(timezone_status()["source"], "network")

    def test_formatted_kickoff_follows_the_saved_timezone(self):
        stamp = "2026-10-22T18:00:00Z"
        with self._settings({"timezone": "America/Chicago"}):
            self.assertEqual(format_local_time(stamp), "1:00")
            self.assertEqual(format_local_date(stamp), "Oct 22")
        clear_timezone_cache()
        with self._settings({"timezone": "America/Los_Angeles"}):
            self.assertEqual(format_local_time(stamp), "11:00")
            self.assertEqual(format_local_date(stamp), "Oct 22")

        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Auckland"
        time.tzset()
        try:
            with self._settings({"timezone": "America/Chicago"}):
                self.assertEqual(
                    format_local_time("2026-10-22T18:00:00"),
                    "1:00",
                )
        finally:
            self._restore_tz(old_tz)

    def test_invalid_setting_falls_back_to_automatic(self):
        self.assertEqual(
            normalize_timezone_setting("Not/A Zone"),
            "auto",
        )
        self.assertEqual(
            normalize_timezone_setting("America/Chicago"),
            "America/Chicago",
        )

    def test_detection_parses_known_services(self):
        ipwho = json.dumps({
            "success": True,
            "timezone": {"id": "America/Chicago"},
        })
        ipapi = json.dumps({"timezone": "America/Denver"})
        ipinfo = json.dumps({"timezone": "America/Los_Angeles"})
        failed = json.dumps({"error": True, "reason": "RateLimited"})
        self.assertEqual(
            timezone_from_detection_body("ipwho", ipwho),
            "America/Chicago",
        )
        self.assertEqual(
            timezone_from_detection_body("ipapi", ipapi),
            "America/Denver",
        )
        self.assertEqual(
            timezone_from_detection_body("ipinfo", ipinfo),
            "America/Los_Angeles",
        )
        self.assertIsNone(
            timezone_from_detection_body("ipapi", failed)
        )

    def test_detection_skips_a_down_service(self):
        def fake_get(url, timeout, headers=None):
            if "ipwho.is" in url:
                raise OSError("down")
            if "ipapi.co" in url:
                return json.dumps({"error": True})
            if "ipinfo.io" in url:
                return json.dumps({"timezone": "America/Chicago"})
            raise AssertionError(url)

        with patch.object(timezone_module, "get_body", fake_get):
            self.assertEqual(
                detect_timezone_name(timeout=2),
                "America/Chicago",
            )

    def test_fresh_cache_skips_the_network(self):
        self._write_cache("America/Denver", time.time())

        def fail_get(url, timeout, headers=None):
            raise AssertionError(url)

        with (
            self._settings({"timezone": "auto"}),
            patch.object(timezone_module, "get_body", fail_get),
        ):
            self.assertEqual(
                ensure_network_timezone(block=True, timeout=1),
                "America/Denver",
            )

    def test_stale_cache_is_replaced_by_a_new_lookup(self):
        self._write_cache("America/Denver", time.time() - (13 * 60 * 60))

        def fake_get(url, timeout, headers=None):
            return json.dumps({
                "success": True,
                "timezone": {"id": "America/Phoenix"},
            })

        with (
            self._settings({"timezone": "auto"}),
            patch.object(timezone_module, "get_body", fake_get),
        ):
            self.assertEqual(
                ensure_network_timezone(block=True, timeout=2),
                "America/Phoenix",
            )
            self.assertEqual(
                get_local_timezone().key,
                "America/Phoenix",
            )

    def test_manual_timezone_does_not_call_the_network(self):
        def fail_get(url, timeout, headers=None):
            raise AssertionError(url)

        with (
            self._settings({"timezone": "America/Phoenix"}),
            patch.object(timezone_module, "get_body", fail_get),
        ):
            self.assertEqual(
                ensure_network_timezone(block=True, timeout=1),
                "America/Phoenix",
            )
            self.assertEqual(
                get_local_timezone(),
                ZoneInfo("America/Phoenix"),
            )

    def _settings(self, values):
        return patch.object(
            timezone_module,
            "get_settings",
            return_value=values,
        )

    def _write_cache(self, name, detected_at):
        path = self._settings_dir / "timezone.json"
        path.write_text(json.dumps({
            "timezone": name,
            "detected_at": detected_at,
        }), encoding="utf-8")

    def _restore_tz(self, old_tz):
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


if __name__ == "__main__":
    unittest.main()
