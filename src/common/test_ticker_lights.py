import unittest

from PIL import Image, ImageDraw

from common.ticker_lights import (
    Twinkle,
    christmas_lights_enabled,
    drape_christmas_lights,
)


_WIRE = (44, 96, 56)


class TickerLightTests(unittest.TestCase):
    def test_only_the_christmas_clock_lights_the_ticker(self):
        self.assertFalse(christmas_lights_enabled({"clock_theme": "off"}))
        self.assertTrue(christmas_lights_enabled({"clock_theme": "christmas"}))
        self.assertFalse(christmas_lights_enabled({"clock_theme": "team_nfl_KC"}))

    def test_the_wire_is_straight_on_the_card_and_sags_between_them(self):
        card_width = 130
        gap = 15
        image = Image.new("RGB", (card_width + gap, 32), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 16, 90, 24), fill=(255, 214, 40))
        score = image.getpixel((60, 20))

        drape_christmas_lights(image, [(0, card_width, card_width + gap)])

        self.assertEqual(image.getpixel((60, 20)), score)
        for x in (40, 65, 90):
            self.assertEqual(image.getpixel((x, 0)), _WIRE)
            for y in range(2, 10):
                self.assertNotEqual(image.getpixel((x, y)), _WIRE)
        on_the_logo = [
            y
            for y in range(2, 10)
            if image.getpixel((card_width - 8, y)) == _WIRE
        ]
        self.assertTrue(on_the_logo)
        dipped = [
            (x, y)
            for x in range(card_width - 4, card_width + gap)
            for y in range(4, 16)
            if image.getpixel((x, y)) == _WIRE
        ]
        self.assertTrue(dipped)

    def test_the_wire_does_not_cut_a_letter(self):
        card_width = 130
        image = Image.new("RGB", (card_width, 32), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((48, 2, 70, 8), fill=(255, 255, 255))

        drape_christmas_lights(image, [(0, card_width, card_width)])

        for y in range(2, 9):
            for x in range(48, 71):
                self.assertNotEqual(image.getpixel((x, y)), _WIRE)

    def test_snow_piles_change_shape_between_the_cards(self):
        gap = 15
        card = 130
        step = card + gap
        image = Image.new("RGB", (step * 2, 32), (0, 0, 0))
        drape_christmas_lights(
            image,
            [(0, card, step), (step, card, step)],
        )

        left = _snow_columns(image, card, gap)
        right = _snow_columns(image, step + card, gap)
        self.assertTrue(any(left))
        self.assertNotEqual(left, right)
        self.assertGreater(max(left), 3)
        self.assertLess(max(left), 10)
        on_the_logo = [
            x
            for x in range(card - 20, card)
            if any(_is_snow(image.getpixel((x, y))) for y in range(image.height))
        ]
        self.assertGreater(len(on_the_logo), 8)
        for x in range(card, card + gap):
            for y in range(0, 16):
                self.assertFalse(_is_snow(image.getpixel((x, y))))
            if left[x - card]:
                self.assertTrue(_is_snow(image.getpixel((x, 31))))
        for x in range(48, 82):
            for y in range(image.height - 1):
                self.assertFalse(_is_snow(image.getpixel((x, y))))
            self.assertEqual(image.getpixel((x, image.height - 1)), (255, 255, 255))

    def test_the_bulbs_stay_lit_and_wink_on_their_own(self):
        card_width = 130
        spans = [(0, card_width, card_width + 15)]
        samples = []
        for step in range(160):
            image = Image.new("RGB", (card_width + 15, 32), (0, 0, 0))
            drape_christmas_lights(image, spans, moment=step * 0.1)
            samples.append((image.getpixel((45, 1)), image.getpixel((58, 1))))
            self.assertEqual(image.getpixel((65, 0)), _WIRE)

        for series in ((sample[0] for sample in samples), (sample[1] for sample in samples)):
            colors = list(series)
            bright = max(colors, key=max)
            full = [color for color in colors if color == bright]
            dim = [color for color in colors if color != bright]
            self.assertGreater(len(full) / len(colors), 0.85)
            self.assertEqual(len(set(full)), 1)
            self.assertTrue(dim)
            for color in dim:
                self.assertGreater(max(color), 50)
                self.assertLess(max(color), max(bright) * 0.75)
                self.assertNotEqual(color, (0, 0, 0))
        bright_first = max((sample[0] for sample in samples), key=max)
        bright_second = max((sample[1] for sample in samples), key=max)
        dim_first = {
            step for step, sample in enumerate(samples) if sample[0] != bright_first
        }
        dim_second = {
            step for step, sample in enumerate(samples) if sample[1] != bright_second
        }
        self.assertTrue(dim_first.isdisjoint(dim_second))

    def test_a_bulb_is_redrawn_only_when_its_brightness_changes(self):
        card_width = 130
        image = Image.new("RGB", (card_width + 15, 32), (0, 0, 0))
        spans = [(0, card_width, card_width + 15)]
        drape_christmas_lights(image, spans, moment=0)
        wire = bytes(image.tobytes())
        show = Twinkle(image, spans)
        show.advance(0)
        show.sync("canvas")
        self.assertEqual(list(show.pokes("canvas", 0, 384)), [])

        held = bytes(show.rgb)
        show.advance(0)
        self.assertEqual(bytes(show.rgb), held)

        changed = False
        for step in range(1, 80):
            show.advance(step * 0.25)
            if bytes(show.rgb) != held:
                changed = True
                break
        self.assertTrue(changed)
        self.assertTrue(show.pokes("canvas", 0, 384))
        self.assertEqual(list(show.pokes("canvas", 0, 384)), [])
        # The wire on top of the card is not part of the twinkle.
        self.assertEqual(bytes(show.rgb[65 * 3:65 * 3 + 3]), bytes(_WIRE))
        self.assertEqual(bytes(wire[65 * 3:65 * 3 + 3]), bytes(_WIRE))


def _is_snow(color):
    red, green, blue = color
    return red > 140 and green > 160 and blue > 170 and blue + 12 >= red


def _snow_columns(image, x0, gap):
    return tuple(
        sum(1 for y in range(image.height) if _is_snow(image.getpixel((x0 + dx, y))))
        for dx in range(gap)
    )


if __name__ == "__main__":
    unittest.main()
