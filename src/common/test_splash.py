import time
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from common import splash


def _pixels(image):
    data = getattr(image, "get_flattened_data", None) or image.getdata
    return list(data())


def _bottom_band(image):
    width, height = image.size
    pixels = _pixels(image)
    return pixels[(height - 8) * width:]


def _above_clock(image):
    width, height = image.size
    pixels = _pixels(image)
    top = max(0, (height - 11) // 2)
    return pixels[:top * width]


def _Game(kind, away, home, status, away_score, home_score, **fields):
    game = type(kind, (), {})()
    game.away = away
    game.home = home
    game.status = status
    game.away_score = away_score
    game.home_score = home_score
    for name, value in fields.items():
        setattr(game, name, value)
    return game


class _Clock(datetime):
    second = 7

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 21, 21, 41, cls.second, tzinfo=tz)


class SplashTests(unittest.TestCase):
    def setUp(self):
        splash._splash_cache.clear()
        splash._standby_cache.update(
            {"image": None, "key": None, "checked_at": 0.0}
        )
        splash._zone_cache.update({"zone": None, "at": 0.0})
        splash._link_cache.update(
            {"bars": 0, "kind": "off", "at": 0.0}
        )
        _Clock.second = 7
        self._weather = patch.object(
            splash,
            "standby_weather",
            return_value=None,
        )
        self._weather.start()
        self.addCleanup(self._weather.stop)

    def test_updating_caption_stays_a_wordmark(self):
        image = splash.render_idle_splash(384, 32, "UPDATING")
        self.assertEqual(image.size, (384, 32))
        self.assertIs(splash.render_idle_splash(384, 32, "updating"), image)
        self.assertIn(splash.CYAN, _pixels(image))
        self.assertNotIn(splash.WHITE, _pixels(image))

    def test_empty_board_shows_clock_date_and_signal(self):
        splash._link_cache.update(
            {"bars": 3, "kind": "wifi", "at": time.monotonic()}
        )
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("America/Chicago"),
            ),
        ):
            image = splash.render_idle_splash(384, 32)

        self.assertEqual(image.size, (384, 32))
        pixels = set(_pixels(image))
        self.assertIn(splash.NAVY, pixels)
        self.assertIn(splash.WHITE, pixels)
        self.assertIn(splash.CYAN, pixels)
        self.assertIn(splash.MUTED, pixels)
        self.assertIn(splash.BAR_OFF, pixels)
        self.assertIs(splash.render_idle_splash(384, 32), image)

    def test_signal_strength_redraws_when_the_minute_holds(self):
        splash._link_cache.update(
            {"bars": 4, "kind": "wifi", "at": time.monotonic()}
        )
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
        ):
            full = splash.render_idle_splash(384, 32)
            splash._standby_cache["checked_at"] = 0.0
            splash._link_cache.update(
                {"bars": 0, "kind": "off", "at": time.monotonic()}
            )
            offline = splash.render_idle_splash(384, 32)

        self.assertIsNot(full, offline)
        self.assertGreater(
            _pixels(full).count(splash.CYAN),
            _pixels(offline).count(splash.CYAN),
        )

    def test_seconds_tick_without_rebuilding_the_same_second(self):
        splash._link_cache.update(
            {"bars": 4, "kind": "wifi", "at": time.monotonic()}
        )
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
        ):
            splash._standby_cache["checked_at"] = 0.0
            first = splash.render_idle_splash(384, 32)
            splash._standby_cache["checked_at"] = 0.0
            held = splash.render_idle_splash(384, 32)
            _Clock.second = 8
            splash._standby_cache["checked_at"] = 0.0
            nxt = splash.render_idle_splash(384, 32)

        self.assertIs(first, held)
        self.assertIsNot(first, nxt)

    def test_live_games_cycle_and_skip_finals(self):
        games = [
            _Game("FootballGame", "BUF", "KC", "FINAL", 17, 24),
            _Game("BasketballGame", "BOS", "LAL", "LIVE", 108, 99),
            _Game("FootballGame", "GB", "DET", "LIVE", 14, 14),
            _Game("BaseballGame", "NYM", "LAD", "SCHEDULED", 0, 0),
            _Game("FantasyMatchup", "ALPH", "BETA", "LIVE", 112, 98),
        ]
        slides = splash._live_slides(games)
        self.assertEqual(
            [(slide[0], slide[1], slide[2]) for slide in slides],
            [("NBA", "BOS", "LAL"), ("NFL", "GB", "DET")],
        )

        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
            patch.object(splash.time, "monotonic", return_value=0),
        ):
            splash._standby_cache["checked_at"] = 0.0
            first = splash.render_idle_splash(384, 32, games=games)
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
            patch.object(splash.time, "monotonic", return_value=4),
        ):
            splash._standby_cache["checked_at"] = 0.0
            second = splash.render_idle_splash(384, 32, games=games)

        self.assertEqual(first.size, (384, 32))
        self.assertIn(splash.MUTED, _pixels(first))
        self.assertIn(splash.WHITE, _pixels(first))
        first_line = _bottom_band(first)
        second_line = _bottom_band(second)
        self.assertIn(splash.CYAN, first_line)
        self.assertIn(splash.WHITE, first_line)
        self.assertNotEqual(first_line, second_line)
        self.assertNotIn(splash.CYAN, _bottom_band(
            splash.render_idle_splash(384, 32)
        ))

    def test_live_line_shows_period_and_clock(self):
        games = [
            _Game(
                "BasketballGame", "BOS", "LAL", "LIVE", 108, 99,
                quarter=3, clock="4:32",
            ),
            _Game(
                "SoccerGame", "ARS", "MCI", "LIVE", 1, 1,
                league_short="EPL", clock="67:00",
            ),
            _Game(
                "HockeyGame", "TOR", "BOS", "LIVE", 2, 1,
                period=2, clock="12:04",
            ),
            _Game(
                "FootballGame", "GB", "DET", "HALFTIME", 14, 14,
                quarter=2,
            ),
        ]
        situations = {
            slide[0]: slide[7] for slide in splash._live_slides(games)
        }
        self.assertEqual(situations["NBA"], "Q3 4:32")
        self.assertEqual(situations["EPL"], "67:00")
        self.assertEqual(situations["NHL"], "P2 12:04")
        self.assertEqual(situations["NFL"], "HT")

    def test_quiet_slate_keeps_the_clock(self):
        games = [_Game("FootballGame", "BUF", "KC", "FINAL", 17, 24)]
        splash._link_cache.update(
            {"bars": 2, "kind": "wifi", "at": time.monotonic()}
        )
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
        ):
            image = splash.render_idle_splash(384, 32, games=games)
        self.assertIn(splash.MUTED, _pixels(image))

    def test_weather_holds_the_line_when_nothing_is_live(self):
        splash._link_cache.update(
            {"bars": 4, "kind": "wifi", "at": time.monotonic()}
        )
        weather = ("AUSTIN", "72", "CLEAR")
        with (
            patch.object(splash, "datetime", _Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("UTC"),
            ),
            patch.object(splash, "standby_weather", return_value=weather),
        ):
            image = splash.render_idle_splash(384, 32)
            self.assertIsNone(splash._bottom_item([]))
        self.assertIn(splash.CYAN, _bottom_band(image))
        self.assertIn(splash.WHITE, _bottom_band(image))

    def test_weather_sits_above_the_clock_while_games_rotate(self):
        games = [
            _Game("BasketballGame", "BOS", "LAL", "LIVE", 108, 99),
            _Game("FootballGame", "GB", "DET", "LIVE", 14, 14),
        ]
        weather = ("AUSTIN", "72", "CLEAR")
        splash._link_cache.update(
            {"bars": 4, "kind": "wifi", "at": time.monotonic()}
        )

        def frame(now):
            splash._standby_cache.update(
                {"image": None, "key": None, "checked_at": 0.0}
            )
            with (
                patch.object(splash, "datetime", _Clock),
                patch.object(
                    splash,
                    "_display_zone",
                    return_value=ZoneInfo("UTC"),
                ),
                patch.object(splash, "standby_weather", return_value=weather),
                patch.object(splash.time, "monotonic", return_value=now),
            ):
                return splash.render_idle_splash(384, 32, games=games)

        first = frame(0)
        second = frame(4)
        self.assertNotEqual(_bottom_band(first), _bottom_band(second))
        self.assertIn(splash.WHITE, _above_clock(first))
        self.assertIn(splash.CYAN, _above_clock(first))
        self.assertIn(splash.WHITE, _above_clock(second))
        self.assertNotIn(splash.WHITE, _above_clock(
            splash.render_idle_splash(384, 32)
        ))

    def test_twenty_four_hour_clock_drops_am_pm(self):
        splash._link_cache.update(
            {"bars": 4, "kind": "wifi", "at": time.monotonic()}
        )

        def render(fmt):
            splash._standby_cache.update(
                {"image": None, "key": None, "checked_at": 0.0}
            )
            with (
                patch.object(splash, "datetime", _Clock),
                patch.object(
                    splash,
                    "_display_zone",
                    return_value=ZoneInfo("America/Chicago"),
                ),
                patch("common.timezone.hour_clock", return_value=fmt),
            ):
                return splash.render_idle_splash(384, 32)

        twelve = render("12")
        twenty_four = render("24")
        self.assertNotEqual(_pixels(twelve), _pixels(twenty_four))

    def test_quality_maps_onto_four_bars(self):
        self.assertEqual(splash._bars_for_quality(None), 4)
        self.assertEqual(splash._bars_for_quality(0), 1)
        self.assertEqual(splash._bars_for_quality(30), 2)
        self.assertEqual(splash._bars_for_quality(50), 3)
        self.assertEqual(splash._bars_for_quality(80), 4)


if __name__ == "__main__":
    unittest.main()
