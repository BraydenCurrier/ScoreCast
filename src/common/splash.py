from PIL import Image, ImageDraw

from common.fonts import (
    gfx_5x7_width,
    print_4x5_centered,
    print_gfx_5x7_centered,
)


BLACK = (0, 0, 0)
GREEN = (0, 220, 70)
DIM_GREEN = (0, 70, 24)

_splash_cache = {}


def render_idle_splash(width, height, caption=""):
    """Black ScoreCast screen for idle and update states."""
    caption = str(caption or "").strip().upper()
    cache_key = (width, height, caption)
    cached = _splash_cache.get(cache_key)

    if cached is not None:
        return cached

    image = Image.new(
        "RGB",
        (width, height),
        BLACK,
    )
    draw = ImageDraw.Draw(image)

    word = "SCORECAST"
    word_width = gfx_5x7_width(word)
    center_x = width // 2

    if caption:
        text_y = 7
        caption_y = 19
    else:
        text_y = (height - 7) // 2
        caption_y = None

    line_pad = 10
    line_left = center_x - word_width // 2 - line_pad
    line_right = (
        center_x
        + (word_width + 1) // 2
        + line_pad
    )

    draw.line(
        [
            (line_left, text_y - 4),
            (line_right, text_y - 4),
        ],
        fill=DIM_GREEN,
    )
    print_gfx_5x7_centered(
        draw,
        word,
        center_x,
        text_y,
        GREEN,
    )

    if caption_y is None:
        draw.line(
            [
                (line_left, text_y + 10),
                (line_right, text_y + 10),
            ],
            fill=DIM_GREEN,
        )
    else:
        print_4x5_centered(
            draw,
            caption,
            center_x,
            caption_y,
            GREEN,
        )

    _splash_cache[cache_key] = image
    return image
