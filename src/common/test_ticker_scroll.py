import unittest

from PIL import Image

from common.ticker_scroll import (
    build_strip,
    column_refreshes,
    paint_viewport,
)


class TickerScrollTests(unittest.TestCase):
    def test_column_hold_is_the_closest_steady_step(self):
        self.assertEqual(column_refreshes(35, 140), 4)
        self.assertEqual(column_refreshes(30, 140), 5)
        self.assertEqual(column_refreshes(140, 140), 1)
        self.assertEqual(column_refreshes(1, 140), 140)

    def test_viewport_wraps_to_the_start_of_the_strip(self):
        cards = []
        for index, step in enumerate((40, 55, 30)):
            image = Image.new("RGB", (step - 10, 8), (index + 1, 20, 30))
            cards.append((image, step))

        strip, period = build_strip(cards)
        view = Image.new("RGB", (36, 8))
        origin = period - 4
        paint_viewport(view, strip, origin, period)

        manual = Image.new("RGB", (36, 8))
        manual.paste(strip, (-origin, 0))
        manual.paste(strip, (period - origin, 0))
        self.assertEqual(view.tobytes(), manual.tobytes())


if __name__ == "__main__":
    unittest.main()
