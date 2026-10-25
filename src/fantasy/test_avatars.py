import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from fantasy.api import (
    _avatar_urls,
    _user_avatar,
    ensure_avatar,
    get_cached_avatar,
)
from fantasy.models import FantasyMatchup
from fantasy.renderer import render_game_strip_onto


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
            image = Image.new("RGB", (143, 32), (0, 0, 0))
            render_game_strip_onto(image, ImageDraw.Draw(image), game, 0, {})
            self.assertEqual(image.getpixel((8, 8)), (255, 0, 0))
            self.assertEqual(image.getpixel((120, 8)), (255, 0, 0))
