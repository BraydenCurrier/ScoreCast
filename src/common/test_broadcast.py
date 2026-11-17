import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from common import broadcast
from common.broadcast import (
    broadcast_logo_url,
    draw_broadcast_logo,
    format_broadcast,
)


def _png(color, size=(24, 12)) -> bytes:
    image = Image.new("RGBA", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class BroadcastLogoTests(unittest.TestCase):
    def setUp(self):
        broadcast._logo_memory.clear()
        broadcast._logo_failures.clear()

    def test_the_shown_network_keeps_espn_dark_logo(self):
        competition = {
            "broadcasts": [
                {"market": "national", "names": ["ESPN"]},
            ],
            "geoBroadcasts": [
                {
                    "market": {"type": "national"},
                    "media": {
                        "shortName": "ESPN",
                        "logo": "https://a.espncdn.com/guid/espn/logos/default.png",
                        "darkLogo": "https://a.espncdn.com/guid/espn/logos/default-dark.png",
                    },
                },
            ],
        }

        self.assertEqual(format_broadcast(competition=competition), "ESPN")
        self.assertEqual(
            broadcast_logo_url(competition=competition),
            "https://a.espncdn.com/guid/espn/logos/default-dark.png",
        )

    def test_a_later_network_logo_does_not_replace_the_first(self):
        competition = {
            "geoBroadcasts": [
                {
                    "market": {"type": "national"},
                    "media": {"shortName": "Fox"},
                },
                {
                    "market": {"type": "national"},
                    "media": {
                        "shortName": "ESPN",
                        "darkLogo": "https://a.espncdn.com/guid/espn/logos/default-dark.png",
                    },
                },
            ],
        }

        self.assertEqual(format_broadcast(competition=competition), "Fox, ESPN")
        self.assertEqual(broadcast_logo_url(competition=competition), "")

    def test_logo_hosts_outside_espn_are_ignored(self):
        competition = {
            "geoBroadcasts": [
                {
                    "market": {"type": "national"},
                    "media": {
                        "shortName": "ESPN",
                        "darkLogo": "https://example.com/espn.png",
                        "logo": "http://a.espncdn.com/guid/espn/logos/default.png",
                    },
                },
            ],
        }

        self.assertEqual(broadcast_logo_url(competition=competition), "")

    def test_espn_mark_is_drawn_and_a_black_mark_is_lifted(self):
        image = Image.new("RGB", (80, 32), (0, 0, 0))
        url = "https://a.espncdn.com/guid/abc/logos/default-dark.png"
        with patch.object(broadcast, "_download_logo", return_value=_png((0, 0, 0, 255))):
            drawn = draw_broadcast_logo(image, "ABC", 40, 16, {}, url)

        self.assertTrue(drawn)
        whites = [
            pixel for pixel in image.getdata()
            if pixel[0] > 200 and pixel[1] > 200 and pixel[2] > 200
        ]
        self.assertTrue(whites)
        logo = broadcast.broadcast_logo_image("ABC", {}, url)
        self.assertLessEqual(logo.width, 40)
        self.assertLessEqual(logo.height, 14)

    def test_a_colored_espn_mark_keeps_its_color(self):
        image = Image.new("RGB", (80, 32), (0, 0, 0))
        url = "https://a.espncdn.com/guid/espn/logos/default.png"
        with patch.object(broadcast, "_download_logo", return_value=_png((220, 10, 10, 255), (40, 10))):
            drawn = draw_broadcast_logo(image, "ESPN", 40, 16, {}, url)

        self.assertTrue(drawn)
        reds = [pixel for pixel in image.getdata() if pixel[0] > 180 and pixel[1] < 40]
        self.assertTrue(reds)

    def test_a_network_without_an_espn_logo_uses_the_saved_logo(self):
        image = Image.new("RGB", (80, 32), (0, 0, 0))
        drawn = draw_broadcast_logo(image, "FOX", 40, 16, {})
        self.assertTrue(drawn)
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in image.getdata()))
