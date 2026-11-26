import unittest

from PIL import Image, ImageDraw

from cfb.cfb_renderer import CARD_WIDTH, LOGO_SIZE, is_halftime, render_game_strip_onto
from cfb.colors import YELLOW
from cfb.models import CollegeFootballGame
from common.fonts import print_4x5_centered

GRASS = (0, 180, 30)


def _game(status, quarter=2):
    return CollegeFootballGame(
        away="TEX",
        home="UGA",
        status=status,
        start_time="7:30",
        away_score=21,
        home_score=17,
        away_wins=8,
        away_losses=1,
        home_wins=9,
        home_losses=0,
        quarter=quarter,
        clock="0:00",
        possession="UGA",
        down=1,
        distance=10,
        yardline_side="TEX",
        yardline_number=25,
        away_rank=3,
        home_rank=1,
        date="NOV 15",
        week=12,
    )


def _render(game):
    width = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE
    image = Image.new("RGB", (width, 32), (0, 0, 0))
    render_game_strip_onto(image, ImageDraw.Draw(image), game, 0, {})
    return image


def _colors(image):
    raw = image.convert("RGB").tobytes()
    return {tuple(raw[index:index + 3]) for index in range(0, len(raw), 3)}


def _pixels(image):
    raw = image.convert("RGB").tobytes()
    width = image.width
    points = set()
    for index in range(0, len(raw), 3):
        color = tuple(raw[index:index + 3])
        if color == (0, 0, 0):
            continue
        pixel = index // 3
        points.add((pixel % width, pixel // width, color))
    return points


class CfbHalftimeCardTests(unittest.TestCase):
    def test_halftime_card_says_ht_instead_of_q2_clock(self):
        self.assertTrue(is_halftime(_game("STATUS_HALFTIME")))
        self.assertFalse(is_halftime(_game("STATUS_IN_PROGRESS")))

        halftime = _render(_game("STATUS_HALFTIME"))
        live = _render(_game("STATUS_IN_PROGRESS"))
        mark = Image.new("RGB", halftime.size, (0, 0, 0))
        print_4x5_centered(
            ImageDraw.Draw(mark),
            "HT",
            LOGO_SIZE + 51,
            8,
            YELLOW,
        )

        self.assertTrue(_pixels(mark) <= _pixels(halftime))
        self.assertFalse(_pixels(mark) <= _pixels(live))
        self.assertNotIn(GRASS, _colors(halftime))
        self.assertIn(GRASS, _colors(live))


if __name__ == "__main__":
    unittest.main()
