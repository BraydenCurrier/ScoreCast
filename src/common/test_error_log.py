import tempfile
import unittest
from pathlib import Path

from common.error_log import (
    clear_errors,
    describe,
    recent_errors,
    record_error,
    report_text,
)
from logs.page import render_logs_page


class ErrorLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "error_log.json"

    def tearDown(self):
        self.directory.cleanup()

    def test_record_keeps_code_summary_and_detail(self):
        saved = record_error(
            "sport-nfl",
            TimeoutError("read timed out"),
            path=self.path,
            min_interval=0,
        )

        self.assertEqual(saved["code"], "SPORT-NFL")
        self.assertIn("Football scores could not be loaded", saved["summary"])
        self.assertIn("did not answer in time", saved["summary"])
        self.assertIn("TimeoutError", saved["detail"])
        self.assertEqual(recent_errors(path=self.path)[0]["code"], "SPORT-NFL")

    def test_repeat_bumps_the_count(self):
        record_error("WEB-ERROR", "ValueError: bad", path=self.path, min_interval=0)
        record_error("WEB-ERROR", "ValueError: bad", path=self.path, min_interval=0)

        entries = recent_errors(path=self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["count"], 2)

    def test_repeat_inside_the_interval_is_not_rewritten(self):
        record_error("WEB-ERROR", "ValueError: bad", path=self.path, min_interval=60)
        skipped = record_error(
            "WEB-ERROR",
            "ValueError: bad",
            path=self.path,
            min_interval=60,
        )

        self.assertIsNone(skipped)
        self.assertEqual(recent_errors(path=self.path)[0]["count"], 1)

    def test_report_is_plain_text(self):
        record_error("CARD-DRAW", "OSError: disk", path=self.path, min_interval=0)
        text = report_text(path=self.path)

        self.assertIn("CARD-DRAW", text)
        self.assertIn("score card could not be drawn", text.lower())
        self.assertIn("OSError: disk", text)

    def test_clear_empties_the_log(self):
        record_error("APP-CRASH", "RuntimeError: boom", path=self.path, min_interval=0)
        self.assertTrue(clear_errors(path=self.path))
        self.assertEqual(recent_errors(path=self.path), [])
        self.assertIn("No errors recorded.", report_text(path=self.path))

    def test_corrupt_file_is_replaced(self):
        self.path.write_text("{not json", encoding="utf-8")
        record_error("SETTINGS-LOAD", "JSONDecodeError: bad", path=self.path, min_interval=0)
        self.assertEqual(len(recent_errors(path=self.path)), 1)

    def test_page_shows_the_code_and_explanation(self):
        record_error(
            "SPORT-NBA",
            "HTTPError: 503 unavailable",
            path=self.path,
            min_interval=0,
        )
        html = render_logs_page(
            "",
            "<header>Logs</header>",
            recent_errors(path=self.path),
            report_text(path=self.path),
        )

        self.assertIn("SPORT-NBA", html)
        self.assertIn("Basketball scores could not be loaded", html)
        self.assertIn("problem on its side", html)
        self.assertIn("503 unavailable", html)
        self.assertIn("Copy log", html)

    def test_network_reasons(self):
        self.assertIn("without internet", describe("SPORT-MLB", "Failed to resolve name"))
        self.assertIn("refused the request", describe("SPORT-NHL", "403 Forbidden"))
        self.assertIn("could not read", describe("SPORT-PGA", "JSONDecodeError: Expecting value"))


if __name__ == "__main__":
    unittest.main()
