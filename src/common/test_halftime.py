import unittest
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from common.football_focus import (
    CLOCK_AMBER,
    _draw_live_center,
    _halftime_clock,
)
from common.football_play import halftime_break
from nfl.focus_renderer import NFL_FOCUS_STYLE
from nfl.models import FootballGame
from cfb.focus_renderer import CFB_FOCUS_STYLE


def _game(**overrides):
    game = FootballGame(
        away="PHI",
        home="WSH",
        status="STATUS_HALFTIME",
        start_time="1:00",
        away_score=14,
        home_score=10,
        away_wins=6,
        away_losses=2,
        home_wins=5,
        home_losses=3,
        quarter=2,
        clock="0:00",
        possession="",
        down=0,
        distance=0,
        yardline_side="",
        yardline_number=0,
    )
    for key, value in overrides.items():
        setattr(game, key, value)
    return game


def _payload(season_type=2, week=8):
    return {
        "header": {"season": {"type": season_type}, "week": week},
        "drives": {
            "previous": [
                {
                    "plays": [
                        {
                            "period": {"number": 1},
                            "type": {"text": "End of Quarter"},
                            "text": "END QUARTER 1",
                            "wallclock": "2026-11-02T02:10:00Z",
                        },
                        {
                            "period": {"number": 2},
                            "type": {"text": "End of Half"},
                            "text": "END QUARTER 2",
                            "wallclock": "2026-11-02T02:56:35Z",
                        },
                    ],
                },
            ],
        },
    }


class HalftimeBreakTests(unittest.TestCase):
    def test_regular_and_playoff_breaks_are_thirteen_minutes(self):
        started, length = halftime_break(_payload())
        playoff, playoff_length = halftime_break(
            _payload(season_type=3, week=1)
        )

        self.assertEqual(started, "2026-11-02T02:56:35Z")
        self.assertEqual(length, 13 * 60)
        self.assertEqual(playoff, started)
        self.assertEqual(playoff_length, 13 * 60)

    def test_super_bowl_break_is_thirty_minutes(self):
        started, length = halftime_break(
            _payload(season_type=3, week=5)
        )

        self.assertEqual(started, "2026-11-02T02:56:35Z")
        self.assertEqual(length, 30 * 60)

    def test_college_break_is_twenty_minutes(self):
        started, length = halftime_break(_payload(), "cfb")

        self.assertEqual(started, "2026-11-02T02:56:35Z")
        self.assertEqual(length, 20 * 60)

    def test_clock_counts_down_and_stops_at_zero(self):
        started = datetime(2026, 11, 2, 2, 56, 35, tzinfo=timezone.utc)
        game = _game(
            halftime_started_at="2026-11-02T02:56:35Z",
            halftime_seconds=13 * 60,
        )

        self.assertEqual(
            _halftime_clock(game, started + timedelta(seconds=75)),
            "11:45",
        )
        self.assertEqual(
            _halftime_clock(game, started + timedelta(minutes=13)),
            "0:00",
        )
        self.assertEqual(_halftime_clock(_game(), started), "")

    def test_focus_draws_the_countdown_under_halftime(self):
        started = datetime(2026, 11, 2, 2, 56, 35, tzinfo=timezone.utc)
        ticking = _center(
            _game(
                halftime_started_at="2026-11-02T02:56:35Z",
                halftime_seconds=13 * 60,
            ),
            NFL_FOCUS_STYLE,
            started + timedelta(seconds=75),
        )
        plain = _center(_game(), NFL_FOCUS_STYLE, started)
        college = _center(
            _game(
                halftime_started_at="2026-11-02T02:56:35Z",
                halftime_seconds=20 * 60,
            ),
            CFB_FOCUS_STYLE,
            started + timedelta(seconds=75),
        )

        self.assertIn(CLOCK_AMBER, _band(ticking, 11, 13))
        self.assertIn(CLOCK_AMBER, _band(college, 11, 13))
        self.assertNotIn(CLOCK_AMBER, _band(plain, 11, 13))


def _center(game, style, now):
    image = Image.new("RGB", (384, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    original = _halftime_clock

    def clock(game, now=None):
        return original(game, now if now is not None else _center.now)

    _center.now = now
    from common import football_focus
    football_focus._halftime_clock = clock
    try:
        football_focus._draw_live_center(draw, game, style)
    finally:
        football_focus._halftime_clock = original
    return image


def _band(image, y0, y1):
    found = set()
    for y in range(y0, y1):
        for x in range(150, 240):
            pixel = image.getpixel((x, y))
            if pixel != (0, 0, 0):
                found.add(pixel)
    return found
