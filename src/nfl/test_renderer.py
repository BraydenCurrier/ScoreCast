import unittest

from PIL import Image, ImageDraw

from nfl.models import FootballGame
from nfl.nfl_renderer import (
    CARD_WIDTH,
    LOGO_SIZE,
    final_label,
    is_final,
    render_game_strip_onto,
)


GRASS = (0, 180, 30)


def _game(status, quarter=4):
    return FootballGame(
        away="GB",
        home="DET",
        status=status,
        start_time="7:20",
        away_score=21,
        home_score=17,
        away_wins=10,
        away_losses=4,
        home_wins=11,
        home_losses=3,
        quarter=quarter,
        clock="0:00",
        possession="DET",
        down=3,
        distance=22,
        yardline_side="DET",
        yardline_number=22,
        date="OCT 22",
        week=7,
    )


def _render(game):
    width = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE
    image = Image.new("RGB", (width, 32), (0, 0, 0))
    render_game_strip_onto(image, ImageDraw.Draw(image), game, 0, {})
    return image


def _colors(image):
    raw = image.convert("RGB").tobytes()
    return {tuple(raw[index:index + 3]) for index in range(0, len(raw), 3)}


class NflNameAlignmentTests(unittest.TestCase):
    def test_home_abbreviation_shares_a_right_edge(self):
        short_game = _game("STATUS_FINAL")
        short_game.home = "NE"
        long_game = _game("STATUS_FINAL")
        long_game.home = "LAC"
        short = _render(short_game)
        long_image = _render(long_game)

        def right_edge(image):
            panel_start = LOGO_SIZE
            panel_end = LOGO_SIZE + CARD_WIDTH
            raw = image.convert("RGB").tobytes()
            width = image.width
            edge = 0
            for y in range(2, 9):
                for x in range(panel_start, panel_end):
                    index = (y * width + x) * 3
                    if raw[index:index + 3] != b"\x00\x00\x00":
                        edge = max(edge, x)
            return edge

        self.assertEqual(right_edge(short), right_edge(long_image))
        self.assertGreater(right_edge(short), LOGO_SIZE + 60)


class NflFinalCardTests(unittest.TestCase):
    def test_final_statuses(self):
        self.assertTrue(is_final(_game("STATUS_FINAL")))
        self.assertTrue(is_final(_game("STATUS_FINAL_OVERTIME")))
        self.assertTrue(is_final(_game("Final")))
        self.assertFalse(is_final(_game("STATUS_IN_PROGRESS")))
        self.assertFalse(is_final(_game("STATUS_SCHEDULED")))
        self.assertEqual(final_label(_game("STATUS_FINAL")), "FINAL")
        self.assertEqual(final_label(_game("STATUS_FINAL_OVERTIME", quarter=5)), "F-OT")

    def test_final_card_drops_the_live_field(self):
        live = _colors(_render(_game("STATUS_IN_PROGRESS")))
        final = _colors(_render(_game("STATUS_FINAL")))
        overtime = _render(_game("STATUS_FINAL_OVERTIME", quarter=5))

        self.assertIn(GRASS, live)
        self.assertNotIn(GRASS, final)
        self.assertNotEqual(
            _render(_game("STATUS_FINAL")).convert("RGB").tobytes(),
            overtime.convert("RGB").tobytes(),
        )


if __name__ == "__main__":
    unittest.main()
