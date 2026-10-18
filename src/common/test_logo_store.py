import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from common.logo_store import (
    LOGO_SIZE,
    LogoError,
    _knockout_background,
    custom_logo_variants,
    delete_custom_logo,
    get_logo_variants,
    get_selected_logo_variant,
    get_team_logo_catalog,
    load_logo,
    normalize_variant_name,
    save_custom_logo,
)


def _png_bytes(color=(220, 30, 40, 255), size=(80, 40)):
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class CustomLogoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patcher = patch(
            "common.logo_store.CUSTOM_LOGO_ROOT",
            self.root,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_normalize_variant_name(self):
        self.assertEqual(
            normalize_variant_name("City Connect"),
            "city_connect",
        )
        with self.assertRaises(LogoError):
            normalize_variant_name("current")
        with self.assertRaises(LogoError):
            normalize_variant_name("   ")

    def test_save_lists_and_loads_custom_logo(self):
        variant = save_custom_logo(
            "mlb",
            "LAD",
            "City Connect",
            _png_bytes(),
        )
        self.assertEqual(variant, "city_connect")
        self.assertIn("city_connect", get_logo_variants("mlb", "LAD"))
        self.assertEqual(
            custom_logo_variants("mlb", "LAD"),
            ["city_connect"],
        )

        logo = load_logo("mlb", "LAD", "city_connect")
        self.assertEqual(logo.size, (LOGO_SIZE, LOGO_SIZE))
        self.assertEqual(
            get_selected_logo_variant(
                {"logo_variants": {"mlb": {"LAD": "city_connect"}}},
                "mlb",
                "LAD",
            ),
            "city_connect",
        )

        delete_custom_logo("mlb", "LAD", "city_connect")
        self.assertNotIn(
            "city_connect",
            get_logo_variants("mlb", "LAD"),
        )

    def test_rejects_reserved_and_missing_file(self):
        with self.assertRaises(LogoError):
            save_custom_logo("mlb", "LAD", "Home", b"")
        with self.assertRaises(LogoError):
            save_custom_logo("mlb", "LAD", "Home", b"not-an-image")

    def test_knockout_removes_white_background(self):
        image = Image.new("RGBA", (80, 80), (255, 255, 255, 255))
        for x in range(25, 55):
            for y in range(25, 55):
                image.putpixel((x, y), (200, 20, 40, 255))
        cleared = _knockout_background(image)
        self.assertEqual(cleared.getpixel((0, 0))[3], 0)
        self.assertGreater(cleared.getpixel((40, 40))[3], 200)

    def test_catalog_is_cached_and_includes_custom(self):
        first = get_team_logo_catalog("mlb")
        second = get_team_logo_catalog("mlb")
        self.assertEqual(first, second)
        self.assertIn("LAD", first)
        save_custom_logo("mlb", "LAD", "Night", _png_bytes())
        self.assertIn("night", get_logo_variants("mlb", "LAD"))


if __name__ == "__main__":
    unittest.main()
