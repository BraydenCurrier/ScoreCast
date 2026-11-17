import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

import common.message as message


def _form(**fields):
    class Form:
        def get(self, key, default=None):
            value = fields.get(key, default)
            if isinstance(value, list):
                return value[0] if value else default
            return value

        def getlist(self, key):
            value = fields.get(key, [])
            if isinstance(value, list):
                return value
            return [value]

    return Form()


def _png(color, size=(4, 4)):
    image = Image.new("RGBA", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class MessageTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self._previous = message.MESSAGE_DIR
        message.MESSAGE_DIR = Path(self._temp.name)
        message.clear_message_cache()
        self.addCleanup(setattr, message, "MESSAGE_DIR", self._previous)
        self.addCleanup(message.clear_message_cache)

    def test_text_is_drawn_in_the_chosen_color_and_place(self):
        designed = message.normalize_message({
            "enabled": True,
            "scroll": False,
            "background": "#000000",
            "items": [{
                "id": "abcd1234",
                "kind": "text",
                "text": "A",
                "x": 0,
                "y": 0,
                "color": "#ff0000",
                "font": "5x7",
            }],
        })
        frame = message.render_frame(designed, 0)
        self.assertEqual(frame.size, (384, 32))
        self.assertEqual(frame.getpixel((0, 2)), (255, 0, 0))
        self.assertEqual(frame.getpixel((0, 0)), (0, 0, 0))

    def test_an_uploaded_image_lands_on_its_pixel(self):
        image_id = message.save_message_image(_png((0, 255, 0, 255)))
        designed = message.normalize_message({
            "scroll": False,
            "items": [{
                "id": "abcd1234",
                "kind": "image",
                "image": image_id,
                "x": 10,
                "y": 3,
            }],
        })
        frame = message.render_frame(designed, 0)
        self.assertEqual(frame.getpixel((10, 3)), (0, 255, 0))
        self.assertEqual(frame.getpixel((9, 3)), (0, 0, 0))

    def test_scroll_moves_the_design_and_a_still_message_does_not(self):
        image_id = message.save_message_image(_png((255, 255, 0, 255), (2, 2)))
        designed = message.normalize_message({
            "scroll": True,
            "speed": 30,
            "items": [{
                "id": "abcd1234",
                "kind": "image",
                "image": image_id,
                "x": 10,
                "y": 0,
            }],
        })
        still = message.render_frame(designed, 0)
        moved = message.render_frame(designed, 4)
        self.assertEqual(still.getpixel((10, 0)), moved.getpixel((6, 0)))
        self.assertNotEqual(still.tobytes(), moved.tobytes())

        parked = message.normalize_message({**designed, "scroll": False})
        self.assertEqual(
            message.render_frame(parked, 0).tobytes(),
            message.render_frame(parked, 20).tobytes(),
        )
        self.assertEqual(message.strip_width(parked), 384)

    def test_the_form_keeps_text_color_speed_and_scroll(self):
        parsed = message.message_from_form(_form(
            enabled="1",
            scroll="1",
            speed="12",
            background="#112233",
            item=["abcd1234"],
            kind_abcd1234="text",
            text_abcd1234="go cats",
            x_abcd1234="8",
            y_abcd1234="12",
            color_abcd1234="#00ff00",
            font_abcd1234="4x5",
        ))
        self.assertTrue(parsed["enabled"])
        self.assertTrue(parsed["scroll"])
        self.assertEqual(parsed["speed"], 12)
        self.assertEqual(parsed["background"], "#112233")
        self.assertEqual(parsed["items"][0]["text"], "GO CATS")
        self.assertEqual(parsed["items"][0]["color"], "#00ff00")
        self.assertEqual(parsed["items"][0]["font"], "4x5")
        self.assertEqual(parsed["items"][0]["x"], 8)

        off = message.message_from_form(_form(speed="1", item=[]))
        self.assertFalse(off["enabled"])
        self.assertFalse(off["scroll"])
        self.assertEqual(off["speed"], message.SPEED_MIN)

    def test_a_turned_off_message_does_not_take_the_board(self):
        self.assertIsNone(message.render_message_frame({"message": {"enabled": False}}, 0))

    def test_the_page_offers_text_images_and_scroll_speed(self):
        from messages.page import render_message_page

        designed = message.normalize_message({
            "enabled": True,
            "scroll": True,
            "speed": 40,
            "items": [{
                "id": "abcd1234",
                "kind": "text",
                "text": "HELLO",
                "x": 4,
                "y": 12,
                "color": "#ffffff",
                "font": "5x7",
            }],
        })
        html = render_message_page("", "", designed, [])
        self.assertIn("HELLO", html)
        self.assertIn("Show on the board", html)
        self.assertIn('name="scroll"', html)
        self.assertIn('name="speed"', html)
        self.assertIn("Upload image", html)
        self.assertIn('value="40"', html)

    def test_message_punctuation_is_drawn(self):
        marks = "!?'\",;/\\()*$=_"
        for font in ("5x7", "4x5"):
            for mark in marks:
                designed = message.normalize_message({
                    "scroll": False,
                    "items": [{
                        "id": "abcd1234",
                        "kind": "text",
                        "text": mark,
                        "x": 0,
                        "y": 0,
                        "color": "#ffffff",
                        "font": font,
                    }],
                })
                frame = message.render_frame(designed, 0)
                self.assertTrue(
                    any(pixel != (0, 0, 0) for pixel in frame.getdata()),
                    f"{font} did not draw {mark!r}",
                )
