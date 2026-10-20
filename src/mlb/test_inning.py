import unittest

from mlb.models import BaseballGame


class DashboardInningTests(unittest.TestCase):
    def test_live_status_shows_half_inning(self):
        from web.app import get_display_status

        top = BaseballGame(
            "NYY", "BOS", "Live", "6:10",
            2, 1, 42, 31, 38, 36,
            6, True, False, False, False, 1,
        )
        bottom = BaseballGame(
            "NYY", "BOS", "Live", "6:10",
            2, 1, 42, 31, 38, 36,
            6, False, False, False, False, 1,
        )
        self.assertEqual(get_display_status(top, "mlb"), "T6")
        self.assertEqual(get_display_status(bottom, "mlb"), "B6")


if __name__ == "__main__":
    unittest.main()
