import unittest
from datetime import datetime

from common.football_week import MONDAY, TUESDAY, week_date_range
from common.timezone import get_local_timezone


class FootballWeekTests(unittest.TestCase):
    def test_cfb_keeps_saturday_late_through_monday(self):
        now = datetime(2026, 10, 17, 23, 0, tzinfo=get_local_timezone())
        start, end = week_date_range(hold_until_weekday=MONDAY, now=now)
        self.assertEqual(str(start), "2026-10-15")
        self.assertEqual(str(end), "2026-10-19")

    def test_cfb_rolls_on_tuesday(self):
        now = datetime(2026, 10, 20, 0, 1, tzinfo=get_local_timezone())
        start, end = week_date_range(hold_until_weekday=MONDAY, now=now)
        self.assertEqual(str(start), "2026-10-22")
        self.assertEqual(str(end), "2026-10-26")

    def test_nfl_keeps_finished_games_through_tuesday_night(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=get_local_timezone())
        start, end = week_date_range(hold_until_weekday=TUESDAY, now=now)
        self.assertEqual(str(start), "2026-10-15")
        self.assertEqual(str(end), "2026-10-20")

    def test_nfl_rolls_wednesday(self):
        now = datetime(2026, 10, 21, 0, 1, tzinfo=get_local_timezone())
        start, end = week_date_range(hold_until_weekday=TUESDAY, now=now)
        self.assertEqual(str(start), "2026-10-22")
        self.assertEqual(str(end), "2026-10-27")


if __name__ == "__main__":
    unittest.main()
