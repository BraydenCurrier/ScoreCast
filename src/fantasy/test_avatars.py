import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from fantasy.api import (
    _avatar_urls,
    _image_request_kwargs,
    _user_avatar,
    download_avatar,
    ensure_avatar,
    get_cached_avatar,
    prefetch_avatars,
)
from fantasy.models import FantasyMatchup
from common.fonts import get_4x5_width
from fantasy.renderer import (
    CARD_WIDTH,
    DETAIL_Y,
    GREY,
    LEAGUE_Y,
    LOGO_SIZE,
    NAME_Y,
    RECORD,
    SCORE_WIDTH,
    YELLOW,
    SCORE_Y,
    _fit_4x5,
    render_game_strip_onto,
)


class FantasyAvatarTests(unittest.TestCase):
    def test_team_logo_beats_the_profile_picture(self):
        avatar = _user_avatar({
            "avatar": "profile",
            "metadata": {"avatar": "teamlogo"},
        })
        self.assertEqual(avatar, "teamlogo")

    def test_hash_uses_the_thumb_then_the_full_image(self):
        self.assertEqual(
            _avatar_urls("abc123"),
            [
                "https://sleepercdn.com/avatars/thumbs/abc123",
                "https://sleepercdn.com/avatars/abc123",
            ],
        )

    def test_cached_file_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            image = Image.new("RGB", (8, 8), (255, 0, 0))
            image.save(cache / "abc123.png")
            with patch("fantasy.api.AVATAR_CACHE", cache):
                self.assertTrue(get_cached_avatar("abc123").endswith("abc123.png"))
                self.assertTrue(ensure_avatar("abc123").endswith("abc123.png"))

    def test_saved_logo_is_not_downloaded_again(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            Image.new("RGB", (8, 8), (0, 255, 0)).save(cache / "abc123.png")
            with patch("fantasy.api.AVATAR_CACHE", cache), \
                    patch("fantasy.api._session.get") as get:
                path = download_avatar("abc123")
            get.assert_not_called()
            self.assertTrue(str(path).endswith("abc123.png"))

    def test_oversized_cached_logo_is_shrunk_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            Image.new("RGB", (400, 400), (12, 40, 90)).save(cache / "abc123.png")
            with patch("fantasy.api.AVATAR_CACHE", cache), \
                    patch("fantasy.api.SMALL_LOGO_BYTES", 0), \
                    patch("fantasy.api._session.get") as get:
                path = download_avatar("abc123")
            get.assert_not_called()
            with Image.open(path) as saved:
                self.assertLessEqual(max(saved.size), 64)

    def test_rows_stay_apart_and_records_draw(self):
        game = FantasyMatchup(
            away="BEARS",
            home="PACK",
            status="Live",
            start_time="",
            date="Wk 12",
            away_score=118.7,
            home_score=140.25,
            league_id="1",
            league_name="Sunday Legends",
            away_roster_id=1,
            home_roster_id=2,
            week=12,
            matchup_id=1,
            away_projected=131.2,
            home_projected=126.8,
            away_abbrev="BEARS",
            home_abbrev="PACK",
            away_wins=12,
            away_losses=10,
            away_ties=1,
            home_wins=8,
            home_losses=4,
        )
        image = Image.new("RGB", (CARD_WIDTH, 32), (0, 0, 0))
        render_game_strip_onto(image, ImageDraw.Draw(image), game, 0, {})
        plate = image.crop((LOGO_SIZE, 0, LOGO_SIZE + SCORE_WIDTH, 32))
        gaps = (8, 9, 15, 16, 24, 25)
        for y in gaps:
            self.assertTrue(
                all(pixel == (0, 0, 0) for pixel in (plate.getpixel((x, y)) for x in range(plate.width))),
                f"row {y} should be empty",
            )
        def ink(y0, y1):
            return any(
                plate.getpixel((x, y)) != (0, 0, 0)
                for y in range(y0, y1)
                for x in range(plate.width)
            )
        self.assertTrue(ink(NAME_Y, NAME_Y + 7))
        self.assertTrue(
            any(
                plate.getpixel((x, y)) == YELLOW
                for y in range(NAME_Y, NAME_Y + 7)
                for x in range(plate.width // 2 - 8, plate.width // 2 + 8)
            ),
            "week should sit in the top middle",
        )
        self.assertTrue(ink(LEAGUE_Y, LEAGUE_Y + 5))
        self.assertTrue(ink(SCORE_Y, SCORE_Y + 7))
        self.assertTrue(ink(DETAIL_Y, DETAIL_Y + 5))
        logo_start = LOGO_SIZE + SCORE_WIDTH
        for y in range(DETAIL_Y, DETAIL_Y + 5):
            for x in range(logo_start, CARD_WIDTH):
                self.assertNotEqual(
                    image.getpixel((x, y)),
                    GREY,
                    f"projection reached the home logo at {(x, y)}",
                )
        rightmost = max(
            x
            for y in range(DETAIL_Y, DETAIL_Y + 5)
            for x in range(image.width)
            if image.getpixel((x, y)) == GREY
        )
        self.assertLessEqual(rightmost, logo_start - 3)
        self.assertGreaterEqual(rightmost, logo_start - 4)
        self.assertTrue(
            any(
                image.getpixel((x, y)) == RECORD
                for y in range(DETAIL_Y, DETAIL_Y + 5)
                for x in range(LOGO_SIZE, logo_start)
            ),
            "record should use its own color",
        )

    def test_league_name_keeps_whole_words(self):
        fitted = _fit_4x5("The Championship of Champions", SCORE_WIDTH - 8)
        self.assertEqual(fitted, "THE CHAMPIONSHIP OF")
        self.assertNotIn("CHAMPIONSHI ", fitted)
        self.assertLessEqual(get_4x5_width(fitted), SCORE_WIDTH - 8)

    def test_strip_draws_the_avatar(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logo.png"
            Image.new("RGB", (20, 20), (255, 0, 0)).save(path)
            game = FantasyMatchup(
                away="AWAY",
                home="HOME",
                status="Live",
                start_time="",
                date="Wk 7",
                away_score=10,
                home_score=8,
                league_id="1",
                league_name="League",
                away_roster_id=1,
                home_roster_id=2,
                week=7,
                matchup_id=1,
                away_logo=str(path),
                home_logo=str(path),
            )
            image = Image.new("RGB", (CARD_WIDTH, 32), (0, 0, 0))
            render_game_strip_onto(image, ImageDraw.Draw(image), game, 0, {})
            home_logo_x = LOGO_SIZE + SCORE_WIDTH + (LOGO_SIZE - 20) // 2
            self.assertEqual(image.getpixel((8, 8)), (255, 0, 0))
            self.assertEqual(image.getpixel((home_logo_x + 2, 8)), (255, 0, 0))

    def test_svg_logo_is_saved_as_png(self):
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
            b'<rect width="8" height="8" fill="red"/></svg>'
        )
        response = _response(svg, "image/svg+xml")
        with tempfile.TemporaryDirectory() as directory:
            with patch("fantasy.api.AVATAR_CACHE", Path(directory)), \
                    patch("fantasy.api._fetch_avatar", return_value=response):
                path = download_avatar(
                    "https://g.espncdn.com/lm-static/logo.svg"
                )
            with Image.open(path) as saved:
                self.assertEqual(saved.format, "PNG")
                self.assertGreater(saved.size[0], 0)

    def test_cold_cache_downloads_on_its_own_connection(self):
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), (0, 0, 255)).save(buffer, format="PNG")
        response = _response(buffer.getvalue(), "image/png")
        with tempfile.TemporaryDirectory() as directory:
            with patch("fantasy.api.AVATAR_CACHE", Path(directory)), \
                    patch("fantasy.api._fetch_avatar", return_value=response) as fetch, \
                    patch("fantasy.api._session.get", side_effect=AssertionError("shared session")):
                prefetch_avatars(["alpha11", "beta22"])
            self.assertGreaterEqual(fetch.call_count, 2)
            self.assertTrue((Path(directory) / "alpha11.png").is_file())
            self.assertTrue((Path(directory) / "beta22.png").is_file())

    def test_private_espn_logos_send_the_saved_login(self):
        with patch("fantasy.api.get_settings", return_value={
            "fantasy": {"espn_swid": "%7Babc%7D", "espn_s2": "secret"},
        }):
            private = _image_request_kwargs(
                "https://mystique-api.fantasy.espn.com/apis/v1/domains/lm/images/abc"
            )
            public = _image_request_kwargs(
                "https://g.espncdn.com/lm-static/logo.svg"
            )
        self.assertEqual(private["cookies"], {"SWID": "{abc}", "espn_s2": "secret"})
        self.assertIsNone(public["cookies"])


def _response(content, content_type):
    class Response:
        headers = {"content-type": content_type}

        def raise_for_status(self):
            return None

    response = Response()
    response.content = content
    return response
