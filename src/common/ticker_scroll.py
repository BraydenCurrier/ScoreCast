"""Build one ticker strip and scroll it without redrawing every LED."""

import subprocess
import sys
from pathlib import Path

from PIL import Image


def column_refreshes(scroll_speed, refresh_hz):
    """How many panel refreshes to hold each column.

    The hold is an integer number of refreshes, so the step time never
    wanders. The chosen count is the one closest to the requested speed.
    """
    speed = max(1.0, float(scroll_speed))
    refresh_hz = max(1, int(refresh_hz))
    guess = refresh_hz / speed
    low = max(1, int(guess) - 2)
    high = min(255, refresh_hz, int(guess) + 2)
    best_fraction = 1
    best_error = abs(refresh_hz - speed)
    for fraction in range(low, high + 1):
        error = abs((refresh_hz / fraction) - speed)
        if error < best_error:
            best_fraction = fraction
            best_error = error
    return best_fraction


def build_strip(cards):
    """Paste (image, step) cards into one strip. Gaps stay black."""
    period = sum(step for _, step in cards)
    if period <= 0 or not cards:
        return None, 0

    height = cards[0][0].height
    strip = Image.new("RGB", (period, height), (0, 0, 0))
    x = 0
    for image, step in cards:
        strip.paste(image, (x, 0))
        x += step
    return strip, period


def paint_viewport(dest, strip, origin, period):
    dest.paste((0, 0, 0), (0, 0, dest.width, dest.height))
    if strip is None or period <= 0:
        return

    x = -(origin % period)
    while x > 0:
        x -= period
    while x < dest.width:
        dest.paste(strip, (x, 0))
        x += period


def load_panel_shift():
    """Import the column-shift helper, building it once if it is missing."""

    def _import():
        sys.modules.pop("common.panel_shift", None)
        from common import panel_shift
        return (
            panel_shift.canvas_key,
            panel_shift.scroll_columns,
            panel_shift.capture_buffer,
        )

    try:
        return _import()
    except Exception as first_error:
        script = Path(__file__).resolve().parents[2] / "scripts" / "build_panel_shift.sh"
        if not script.is_file():
            print("Panel scroll helper unavailable:", first_error)
            return None, None, None

        subprocess.run(
            ["bash", str(script), str(script.parent.parent)],
            check=False,
        )
        try:
            return _import()
        except Exception as error:
            print("Panel scroll helper unavailable:", error)
            return None, None, None


def scroll_shift_matches(canvas, scroll_columns, capture_buffer):
    """True when a column shift matches a full redraw of the same picture.

    The check writes only the hidden frame, so the panel does not show it.
    """
    try:
        width = int(canvas.width)
        height = int(canvas.height)
    except Exception:
        return False

    pattern = bytearray(width * height * 3)
    for y in range(height):
        row = y * width * 3
        for x in range(width):
            pixel = row + x * 3
            pattern[pixel] = (x * 3) & 255
            pattern[pixel + 1] = (y * 17) & 255
            pattern[pixel + 2] = (x + y) & 255
    source = Image.frombytes("RGB", (width, height), bytes(pattern))
    raw = bytes(pattern)

    for amount in (1, 2):
        expected_image = Image.new("RGB", (width, height))
        expected_image.paste(source, (-amount, 0))
        expected_image.paste(source.crop((0, 0, amount, height)), (width - amount, 0))
        canvas.SetImage(expected_image)
        expected = capture_buffer(canvas)
        canvas.SetImage(source)
        if not scroll_columns(canvas, amount, raw, width, height, amount, width):
            return False
        if capture_buffer(canvas) != expected or not expected:
            return False
    return True
