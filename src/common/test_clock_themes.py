import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

from common import splash
from clock_themes.page import cards_for, render_clock_themes_page
from common.clock_themes import (
    CHRISTMAS,
    clock_ink,
    clock_palette,
    normalize_clock_theme,
    paint_theme,
    theme_by_id,
    theme_name,
)
from common.team_clock import abbreviations, themes_for_league


def _pixels(image):
    data = getattr(image, "get_flattened_data", None) or image.getdata
    return list(data())


class ClockThemeTests(unittest.TestCase):
    def test_christmas_moves_and_keeps_a_broken_snow_line(self):
        first = Image.new("RGB", (384, 32))
        later = Image.new("RGB", (384, 32))
        paint_theme(first, CHRISTMAS, 0.4)
        paint_theme(later, CHRISTMAS, 2.8)

        self.assertNotEqual(_pixels(first), _pixels(later))
        center = first.getpixel((192, 15))
        self.assertLess(sum(center), 80)
        self.assertGreater(max(sum(pixel) for pixel in _pixels(first)), sum(center) + 80)

    def test_christmas_stays_behind_the_clock(self):
        splash._splash_cache.clear()
        splash._standby_cache.update(
            {"image": None, "key": None, "checked_at": 0.0}
        )
        splash._theme_cache.update({"theme": None, "at": 0.0})

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 12, 24, 21, 4, 5, tzinfo=tz)

        with (
            patch.object(splash, "active_theme", return_value=CHRISTMAS),
            patch.object(splash, "standby_weather", return_value=None),
            patch.object(splash, "countdown_line", return_value=None),
            patch.object(splash, "datetime", Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("America/Chicago"),
            ),
        ):
            image = splash.render_idle_splash(384, 32)

        self.assertIn(clock_ink(CHRISTMAS), _pixels(image))
        self.assertNotIn(splash.CYAN, _pixels(image))
        self.assertNotIn(splash.BLUE, _pixels(image))
        self.assertNotEqual(image.getpixel((8, 0)), splash.NAVY)

    def test_christmas_status_box_hugs_the_line(self):
        when_bits = dict(
            time_text="9:04:05",
            period="PM",
            theme=CHRISTMAS,
            phase=4.2,
        )
        short = ("HOME", "28", "SNOW")
        long = ("W" * 18, "-80", "OVERCAST")

        def draw(above, bottom):
            return splash._draw_standby(
                384, 32, datetime(2026, 12, 24, 21, 4, 5), 4,
                bottom=bottom, above=above, **when_bits,
            )

        quiet = draw(("weather", short), ("weather", short))
        busy = draw(("weather", long), ("weather", long))
        colors = {tuple(clock_palette(CHRISTMAS)[name]) for name in ("ink", "mark", "soft")}

        def ink_span(image, y):
            xs = [
                x for x in range(384)
                if image.getpixel((x, y)) in colors
            ]
            return min(xs), max(xs)

        quiet_top = ink_span(quiet, 4)
        busy_top = ink_span(busy, 4)
        self.assertLess(quiet_top[1] - quiet_top[0], busy_top[1] - busy_top[0])
        for image, y in ((quiet, 2), (busy, 2), (quiet, 24)):
            left, right = ink_span(image, y + 2)
            self.assertEqual(image.getpixel((left - 1, y + 2)), (0, 0, 0))
            self.assertEqual(image.getpixel((right + 1, y + 2)), (0, 0, 0))
            self.assertEqual(image.getpixel((left, y - 1)), (0, 0, 0))
            self.assertEqual(image.getpixel((left, y + 5)), (0, 0, 0))
            self.assertNotEqual(image.getpixel((left - 2, y + 2)), (0, 0, 0))

    def test_christmas_is_the_only_seasonal_theme(self):
        self.assertEqual(normalize_clock_theme("christmas"), "christmas")
        theme = theme_by_id("christmas")
        image = Image.new("RGB", (384, 32))
        later = Image.new("RGB", (384, 32))
        paint_theme(image, theme, 0.4)
        paint_theme(later, theme, 3.2)
        center = image.getpixel((192, 15))
        self.assertLess(sum(center), 140)
        self.assertNotEqual(_pixels(image), _pixels(later))
        self.assertNotEqual(
            clock_palette(theme)["ink"],
            clock_palette(theme)["mark"],
        )
        for theme_id in ("autumn", "spring", "summer", "july", "newyear", "halloween"):
            self.assertEqual(normalize_clock_theme(theme_id), "off")
            self.assertIsNone(theme_by_id(theme_id))
        self.assertEqual(normalize_clock_theme("missing"), "off")

    def test_every_team_in_a_league_has_its_own_theme(self):
        for league in ("nfl", "nba", "mlb", "nhl", "cfb", "cbb", "soccer"):
            teams = abbreviations(league)
            themes = themes_for_league(league)
            self.assertGreater(len(teams), 20, league)
            self.assertEqual(len(themes), len(teams), league)
            self.assertEqual(
                len({theme["id"] for theme in themes}),
                len(themes),
                league,
            )

        chiefs = theme_by_id("team_nfl_KC")
        self.assertEqual(chiefs["name"], "Kansas City Chiefs")
        self.assertEqual(theme_name("team_nfl_KC"), "Kansas City Chiefs")
        self.assertEqual(normalize_clock_theme("team_nfl_KC"), "team_nfl_KC")
        self.assertEqual(normalize_clock_theme("team_nfl_NOPE"), "off")
        self.assertNotIn("Chiefs", theme_by_id("team_mlb_KC")["name"])
        self.assertIn("Royals", theme_by_id("team_mlb_KC")["name"])

    def test_a_team_theme_shows_the_logo_and_stays_dark(self):
        theme = theme_by_id("team_nfl_KC")
        first = Image.new("RGB", (384, 32))
        later = Image.new("RGB", (384, 32))
        paint_theme(first, theme, 0.2)
        paint_theme(later, theme, 2.4)
        center = first.getpixel((192, 15))
        self.assertLess(sum(center), 80)
        self.assertEqual(first.getpixel((8, 8)), center)
        self.assertEqual(first.getpixel((370, 8)), center)
        self.assertEqual(later.getpixel((192, 15)), center)
        logo = [
            first.getpixel((x, y))
            for x in range(100, 130)
            for y in range(1, 31)
        ]
        self.assertGreater(len(set(logo)), 8)
        self.assertNotEqual(first.getpixel((115, 16)), center)

    def test_clock_text_uses_the_theme_color(self):
        chiefs = theme_by_id("team_nfl_KC")
        packers = theme_by_id("team_nfl_GB")
        lakers = theme_by_id("team_nba_LAL")
        chiefs_ink = clock_ink(chiefs)
        chiefs_mark = clock_palette(chiefs)["mark"]
        packers_ink = clock_ink(packers)
        packers_mark = clock_palette(packers)["mark"]
        lakers_mark = clock_palette(lakers)["mark"]
        self.assertGreater(chiefs_ink[0], 180)
        self.assertLess(chiefs_ink[1], 80)
        self.assertGreater(chiefs_mark[0], 200)
        self.assertGreater(chiefs_mark[1], 140)
        self.assertGreater(packers_ink[0], 200)
        self.assertGreater(packers_ink[1], 140)
        self.assertGreater(packers_mark[1], packers_mark[0])
        self.assertGreater(lakers_mark[2], lakers_mark[0])
        self.assertNotEqual(tuple(lakers["accent"]), tuple(lakers["primary"]))
        self.assertEqual(clock_ink(CHRISTMAS), (255, 236, 200))
        self.assertNotEqual(
            clock_palette(CHRISTMAS)["ink"],
            clock_palette(CHRISTMAS)["mark"],
        )

        splash._splash_cache.clear()
        splash._standby_cache.update(
            {"image": None, "key": None, "checked_at": 0.0}
        )
        splash._theme_cache.update({"theme": None, "at": 0.0})

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 9, 21, 4, 5, tzinfo=tz)

        with (
            patch.object(splash, "active_theme", return_value=chiefs),
            patch.object(splash, "standby_weather", return_value=None),
            patch.object(splash, "countdown_line", return_value=None),
            patch.object(splash, "datetime", Clock),
            patch.object(
                splash,
                "_display_zone",
                return_value=ZoneInfo("America/Chicago"),
            ),
        ):
            image = splash.render_idle_splash(384, 32)

        pixels = _pixels(image)
        self.assertIn(chiefs_ink, pixels)
        self.assertIn(chiefs_mark, pixels)
        self.assertNotIn(splash.CYAN, pixels)
        self.assertNotIn(splash.BLUE, pixels)

    def test_the_picker_page_lists_teams(self):
        cards = cards_for("nfl", {})
        names = {card["name"] for card in cards}
        self.assertIn("Kansas City Chiefs", names)
        self.assertEqual(len(cards), len(abbreviations("nfl")))
        featured = cards_for("featured", {"favorite_teams": {"nba": ["LAL"]}})
        featured_ids = [card["id"] for card in featured]
        self.assertEqual(featured_ids[0], "off")
        self.assertEqual(featured_ids[1], "christmas")
        self.assertNotIn("autumn", featured_ids)
        self.assertNotIn("newyear", featured_ids)
        self.assertGreater(
            featured_ids.index("team_nba_LAL"),
            featured_ids.index("christmas"),
        )
        html = render_clock_themes_page("", "", {}, "nfl", "team_nfl_KC")
        self.assertIn("Kansas City Chiefs", html)
        self.assertIn("College Football", html)
        self.assertIn("/clock-themes/use", html)
        self.assertNotIn("Hogwarts", html)
        self.assertIn("On the clock", html)
        self.assertIn("/logo-preview/nfl/KC/", html)
