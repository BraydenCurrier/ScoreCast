import time

from PIL import Image, ImageDraw
from nfl import nfl_logos

from alerts.models import PossessionAlert
from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import (
    print_4x5,
    get_4x5_width,
    print_4x5_centered,
    print_gfx_5x7,
    gfx_5x7_width,
)


DISPLAY_WIDTH = PANEL_WIDTH
DISPLAY_HEIGHT = PANEL_HEIGHT


def _ordinal_down(down: int) -> str:
    values = {
        1: "1ST",
        2: "2ND",
        3: "3RD",
        4: "4TH",
    }

    return values.get(
        int(down or 0),
        "",
    )


def _quarter_text(quarter: int) -> str:
    quarter = int(quarter or 0)

    if 1 <= quarter <= 4:
        return f"Q{quarter}"

    if quarter == 5:
        return "OT"

    if quarter > 5:
        return f"OT{quarter - 4}"

    return ""

def draw_team_logo(draw, team_abbreviation, x_start, y_start):
    logo_data = getattr(nfl_logos, f"LOGO_{team_abbreviation}", None)
    
    if not logo_data:
        return  
        
    for y, row in enumerate(logo_data):
        for x, rgb_color in enumerate(row):
            if rgb_color != (0, 0, 0):
                draw.point((x_start + x, y_start + y), fill=rgb_color)

def _field_position_text(
    alert: PossessionAlert,
) -> str:
    side = str(
        alert.yardline_side or ""
    ).upper()

    number = int(
        alert.yardline_number or 0
    )

    team = str(
        alert.team or ""
    ).upper()

    if number == 50:
        return "50"

    if not 0 < number < 50:
        return "FIELD POS PENDING"

    if not side:
        return "FIELD POS PENDING"

    if side == team:
        return f"OWN {number}"

    return f"{side} {number}"


def _down_distance_text(
    alert: PossessionAlert,
) -> str:
    down = _ordinal_down(
        alert.down
    )

    distance = int(
        alert.distance or 0
    )

    if down and distance > 0:
        return f"{down}&{distance}"

    if down:
        return down

    return "DOWN PENDING"


def _draw_centered_5x7(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    color: tuple[int, int, int],
) -> None:
    text = str(text).upper()

    width = gfx_5x7_width(text)

    x = (
        DISPLAY_WIDTH - width
    ) // 2

    print_gfx_5x7(
        draw,
        text,
        x,
        y,
        color,
    )


def _draw_centered_4x5(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    color: tuple[int, int, int],
) -> None:
    print_4x5_centered(
        draw,
        str(text).upper(),
        DISPLAY_WIDTH // 2,
        y,
        color,
    )

def _create_team_frame(
    alert: PossessionAlert,
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new(
        "RGB",
        (
            DISPLAY_WIDTH,
            DISPLAY_HEIGHT,
        ),
        alert.primary,
    )

    draw = ImageDraw.Draw(image)

    logo_size = 30
    logo_y = (
        DISPLAY_HEIGHT - logo_size
    ) // 2

    left_logo_x = 1
    right_logo_x = (
        DISPLAY_WIDTH
        - logo_size
        - 1
    )

    draw_team_logo(
        draw,
        alert.team,
        left_logo_x,
        logo_y,
    )

    draw_team_logo(
        draw,
        alert.team,
        right_logo_x,
        logo_y,
    )

    return image, draw

def _render_scaled_pixel_text(
    text: str,
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
) -> Image.Image:
    """
    Draw text using ScoreCast's 5x7 bitmap font and enlarge it with
    nearest-neighbor scaling.

    This keeps every LED edge perfectly sharp.
    """
    text = str(text).upper().strip()

    if not text:
        text = " "

    text_width = gfx_5x7_width(text)
    source_height = 7

    # Add one pixel of padding around the bitmap before scaling.
    source = Image.new(
        "RGB",
        (
            max(1, text_width + 2),
            source_height + 2,
        ),
        background,
    )

    source_draw = ImageDraw.Draw(source)

    print_gfx_5x7(
        source_draw,
        text,
        1,
        1,
        foreground,
    )

    scale_x = max(
        1,
        DISPLAY_WIDTH // source.width,
    )

    scale_y = max(
        1,
        DISPLAY_HEIGHT // source.height,
    )

    scale = max(
        1,
        min(scale_x, scale_y),
    )

    scaled = source.resize(
        (
            source.width * scale,
            source.height * scale,
        ),
        Image.Resampling.NEAREST,
    )

    image = Image.new(
        "RGB",
        (
            DISPLAY_WIDTH,
            DISPLAY_HEIGHT,
        ),
        background,
    )

    x = (
        DISPLAY_WIDTH - scaled.width
    ) // 2

    y = (
        DISPLAY_HEIGHT - scaled.height
    ) // 2

    image.paste(
        scaled,
        (
            x,
            y,
        ),
    )

    return image


def _render_chant_frame(
    alert: PossessionAlert,
    chant_index: int,
) -> Image.Image:
    image, draw = _create_team_frame(
        alert
    )

    chant_text = str(
        alert.chant[chant_index]
    ).upper()

    logo_size = 30
    text_left = logo_size + 7
    text_right = (
        DISPLAY_WIDTH
        - logo_size
        - 7
    )

    available_width = max(
        1,
        text_right - text_left,
    )

    text_width = gfx_5x7_width(
        chant_text
    )

    source = Image.new(
        "RGB",
        (
            max(1, text_width),
            7,
        ),
        alert.primary,
    )

    source_draw = ImageDraw.Draw(
        source
    )

    print_gfx_5x7(
        source_draw,
        chant_text,
        0,
        0,
        alert.accent,
    )

    scale_x = max(
        1,
        available_width // source.width,
    )

    scale_y = max(
        1,
        DISPLAY_HEIGHT // source.height,
    )

    scale = max(
        1,
        min(
            scale_x,
            scale_y,
        ),
    )

    scaled_text = source.resize(
        (
            source.width * scale,
            source.height * scale,
        ),
        Image.Resampling.NEAREST,
    )

    text_x = (
        text_left
        + (
            available_width
            - scaled_text.width
        ) // 2
    )

    text_y = (
        DISPLAY_HEIGHT
        - scaled_text.height
    ) // 2

    image.paste(
        scaled_text,
        (
            text_x,
            text_y,
        ),
    )

    return image

def _render_details_frame(
    alert: PossessionAlert,
) -> Image.Image:
    image, draw = _create_team_frame(alert)

    headline = str(
        getattr(alert, "headline", "")
        or alert.possession_label
    ).upper()

    detail = str(
        getattr(alert, "detail", "")
        or _field_position_text(alert)
    ).upper()

    _draw_centered_5x7(
        draw,
        headline,
        y=2,
        color=alert.accent,
    )

    _draw_centered_5x7(
        draw,
        detail,
        y=18,
        color=(255, 255, 255),
    )

    return image

def _render_blank_frame(
    alert: PossessionAlert,
) -> Image.Image:
    image, _ = _create_team_frame(
        alert
    )

    return image

def render_possession_alert(
    alert: PossessionAlert,
    now: float | None = None,
) -> Image.Image:
    if now is None:
        now = time.monotonic()

    elapsed = max(
        0.0,
        now - alert.created_at,
    )

    word_duration = max(
        0.1,
        alert.chant_frame_seconds,
    )

    blank_duration = max(
        0.05,
        word_duration * 0.30,
    )

    current_time = 0.0

    for chant_index, _word in enumerate(
        alert.chant
    ):
        word_end = (
            current_time
            + word_duration
        )

        if elapsed < word_end:
            return _render_chant_frame(
                alert,
                chant_index,
            )

        current_time = word_end

        blank_end = (
            current_time
            + blank_duration
        )

        if elapsed < blank_end:
            return _render_blank_frame(
                alert
            )

        current_time = blank_end

    return _render_details_frame(
        alert
    )