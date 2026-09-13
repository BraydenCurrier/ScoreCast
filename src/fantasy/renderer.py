from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from common.fonts import (
    print_3x5,
    print_3x5_right,
    print_4x5_centered,
    print_gfx_5x7,
    draw_text_right,
)

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)
PROJECTION = (105, 165, 235)
BADGE_BG = (28, 31, 38)
BADGE_EDGE = (72, 76, 86)

# Match the physical structure used by NBA/NHL/MLB:
# 30px away logo + 79px score panel + 30px home logo = 139px.
LOGO_SIZE = 30
SCORE_WIDTH = 83
CARD_WIDTH = LOGO_SIZE + SCORE_WIDTH + LOGO_SIZE


def _score(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0.00"

    return f"{value:.2f}"


def _projection(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"

    if value <= 0:
        return "-"

    return f"{value:.2f}"


def _abbr(value):
    return str(value or "---").upper()[:4]


@lru_cache(maxsize=128)
def _load_avatar(path):
    if not path or not Path(path).is_file():
        return None
    try:
        with Image.open(path) as source:
            avatar = source.convert("RGBA")
            avatar.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
            return avatar.copy()
    except Exception:
        return None


def _draw_fallback_logo(draw, x, y, abbrev):
    """Fallback resembles a team-logo tile when no Sleeper avatar is available."""
    draw.rounded_rectangle(
        (x + 1, y, x + LOGO_SIZE - 2, y + LOGO_SIZE - 1),
        radius=4,
        fill=BADGE_BG,
        outline=BADGE_EDGE,
    )
    label = _abbr(abbrev)[:3]
    width = len(label) * 6 - 1
    print_gfx_5x7(draw, label, x + (LOGO_SIZE - width) // 2, y + 11, WHITE)


def _draw_team_logo(image, draw, path, x, abbrev):
    avatar = _load_avatar(path)
    if avatar is None:
        _draw_fallback_logo(draw, x, 1, abbrev)
        return

    px = x + (LOGO_SIZE - avatar.width) // 2
    py = 1 + (LOGO_SIZE - avatar.height) // 2
    if image.mode == "RGBA":
        image.alpha_composite(avatar, (px, py))
    else:
        image.paste(avatar, (px, py), avatar)


def _draw_score_right(draw, text, right_x, y, color):
    draw_text_right(draw, text, right_x, y, color)


def render_fantasy_game_onto(image, draw, game, offset_x, settings):
    """Render the 69px center panel between the two fantasy team avatars."""
    away = _abbr(game.away_abbrev or game.away)
    home = _abbr(game.home_abbrev or game.home)

    # Top row mirrors other cards: away abbreviation | game state | home abbreviation.
    print_gfx_5x7(draw, away, offset_x + 2, 2, WHITE)
    _draw_score_right(draw, home, offset_x + SCORE_WIDTH - 2, 2, WHITE)
    print_4x5_centered(draw, f"W{game.week}", offset_x + SCORE_WIDTH // 2, 3, GREY)

    # Current fantasy points are the primary score, in the same yellow visual role
    # as live scores on the NBA/NFL/NHL cards.
    away_score = _score(game.away_score)
    home_score = _score(game.home_score)
    print_gfx_5x7(draw, away_score, offset_x + 2, 13, YELLOW)
    _draw_score_right(draw, home_score, offset_x + SCORE_WIDTH - 2, 13, YELLOW)

    # Projection row is intentionally secondary and compact.
    away_proj = _projection(game.away_projected)
    home_proj = _projection(game.home_projected)
    print_3x5(draw, away_proj, offset_x + 2, 24, PROJECTION)
    print_3x5_right(draw, home_proj, offset_x + SCORE_WIDTH - 6, 24, PROJECTION)

def render_game_strip_onto(image, draw, game, offset_x, settings):
    away = game.away_abbrev or game.away
    home = game.home_abbrev or game.home

    _draw_team_logo(image, draw, game.away_logo, offset_x, away)
    render_fantasy_game_onto(image, draw, game, offset_x + LOGO_SIZE, settings)
    _draw_team_logo(
        image,
        draw,
        game.home_logo,
        offset_x + LOGO_SIZE + SCORE_WIDTH,
        home,
    )