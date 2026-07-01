import time
from PIL import Image, ImageDraw

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import GFX_5X7, print_gfx_5x7
import nfl.nfl_logos as nfl_logos


BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
RED = (255, 0, 0)
BLUE = (0, 140, 255)
GREEN = (0, 255, 90)


def draw_logo(draw, team, x, y):
    logo = getattr(nfl_logos, f"LOGO_{team}", None)

    if logo is None:
        return

    for row, pixels in enumerate(logo):
        for col, color in enumerate(pixels):
            if color is not None:
                draw.point((x + col, y + row), fill=color)


def big_text_width(text, scale=2):
    return len(str(text)) * 6 * scale - scale


def draw_big_text(draw, text, x, y, color, scale=2):
    cursor_x = x

    for char in str(text).upper():
        bitmap = GFX_5X7.get(char, GFX_5X7[" "])

        for col in range(5):
            column_data = bitmap[col]

            for row in range(7):
                if (column_data >> row) & 1:
                    draw.rectangle(
                        (
                            cursor_x + col * scale,
                            y + row * scale,
                            cursor_x + col * scale + scale - 1,
                            y + row * scale + scale - 1,
                        ),
                        fill=color,
                    )

        cursor_x += 6 * scale


def draw_firework(draw, cx, cy, radius, color):
    if radius <= 0:
        return

    points = [
        (cx, cy - radius),
        (cx, cy + radius),
        (cx - radius, cy),
        (cx + radius, cy),
        (cx - radius, cy - radius),
        (cx + radius, cy - radius),
        (cx - radius, cy + radius),
        (cx + radius, cy + radius),
    ]

    for x, y in points:
        draw.line((cx, cy, x, y), fill=color)

    draw.point((cx, cy), fill=WHITE)


def render_touchdown_alert(team, color=YELLOW, show_text=True):
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)

    draw_logo(draw, team, 6, 1)

    if show_text:
        text = "TOUCHDOWN"
        scale = 2
        text_width = big_text_width(text, scale)

        text_area_left = 44
        text_area_width = PANEL_WIDTH - text_area_left

        text_x = text_area_left + ((text_area_width - text_width) // 2)
        text_y = 9

        draw_big_text(draw, text, text_x, text_y, color, scale)

    return image


def render_touchdown_detail(team, message, color=YELLOW):
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)

    draw_logo(draw, team, 4, 1)

    draw_big_text(draw, "TD", 42, 2, color, scale=2)

    clean_message = message.upper()

    print_gfx_5x7(
        draw,
        clean_message[:42],
        42,
        20,
        WHITE
    )

    return image


def play_touchdown_fireworks(matrix, team, message, color=YELLOW):
    firework_colors = [
        RED,
        YELLOW,
        BLUE,
        WHITE,
        GREEN,
    ]

    # Big TD screen with fireworks
    for frame in range(18):
        image = render_touchdown_alert(
            team,
            color=color,
            show_text=True
        )

        draw = ImageDraw.Draw(image)

        radius = frame % 9

        draw_firework(
            draw,
            PANEL_WIDTH - 58,
            8,
            radius,
            firework_colors[frame % len(firework_colors)]
        )

        draw_firework(
            draw,
            PANEL_WIDTH - 24,
            23,
            radius,
            firework_colors[(frame + 2) % len(firework_colors)]
        )

        draw_firework(
            draw,
            PANEL_WIDTH - 92,
            24,
            max(0, radius - 2),
            firework_colors[(frame + 3) % len(firework_colors)]
        )

        matrix.SetImage(image)
        time.sleep(0.06)

    # Flash the TD text
    for i in range(6):
        image = render_touchdown_alert(
            team,
            color=color,
            show_text=(i % 2 == 0)
        )

        matrix.SetImage(image)
        time.sleep(0.15)

    # Detail screen
    matrix.SetImage(
        render_touchdown_detail(
            team,
            message,
            color=color
        )
    )

    time.sleep(5)