from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from common.fonts import (
    FONT_4x5_DATA,
    get_3x5_width,
    get_4x5_width,
    print_3x5,
    print_3x5_right,
    print_4x5_centered,
    print_gfx_5x7,
    draw_text_right,
)

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)
RECORD = (80, 175, 255)
BADGE_BG = (28, 31, 38)
BADGE_EDGE = (72, 76, 86)

# Decimal scores need more room than the other boards. Both detail
# edges use the same inset as the names and scores.
LOGO_SIZE = 30
SCORE_WIDTH = 108
CARD_WIDTH = LOGO_SIZE + SCORE_WIDTH + LOGO_SIZE
NAME_Y = 1
LEAGUE_Y = 10
SCORE_Y = 17
DETAIL_Y = 26


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


def _fit_4x5(text, max_width):
    characters = []
    for char in str(text or "").upper():
        if char == " " or char in FONT_4x5_DATA:
            characters.append(char)
    label = " ".join("".join(characters).split()) or "FANTASY"
    words = label.split()
    fitted = []
    for word in words:
        trial = " ".join(fitted + [word])
        if get_4x5_width(trial) <= max_width:
            fitted.append(word)
            continue
        break
    if fitted:
        return " ".join(fitted)
    while label and get_4x5_width(label) > max_width:
        label = label[:-1].rstrip()
    return label or "FANTASY"


@lru_cache(maxsize=128)
def _load_avatar(path):
    if not path or not Path(path).is_file():
        return None
    try:
        with Image.open(path) as source:
            avatar = source.convert("RGBA")
            avatar.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.BOX)
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


def _record(wins, losses, ties):
    try:
        wins = int(wins)
        losses = int(losses)
    except (TypeError, ValueError):
        return ""
    if wins < 0 or losses < 0:
        return ""
    text = f"{wins}-{losses}"
    try:
        ties = int(ties or 0)
    except (TypeError, ValueError):
        ties = 0
    if ties > 0:
        text = f"{text}-{ties}"
    return text


def _draw_detail_row(draw, offset_x, away_proj, away_record, home_proj, home_record):
    """Projection under each score, record just inside it, both edges matched."""
    left = offset_x + 2
    right = offset_x + SCORE_WIDTH - 2
    print_3x5(draw, away_proj, left, DETAIL_Y, GREY)
    print_3x5_right(draw, home_proj, right, DETAIL_Y, GREY)

    away_proj_end = left + get_3x5_width(away_proj)
    home_proj_start = right - get_3x5_width(home_proj)
    gap = 4
    away_x = away_proj_end + gap if away_record else None
    home_x = (
        home_proj_start - gap - get_3x5_width(home_record) if home_record else None
    )
    if (
        away_x is not None
        and home_x is not None
        and away_x + get_3x5_width(away_record) >= home_x
    ):
        gap = 2
        away_x = away_proj_end + gap
        home_x = home_proj_start - gap - get_3x5_width(home_record)
    if away_x is not None:
        away_end = away_x + get_3x5_width(away_record)
        limit = home_x if home_x is not None else home_proj_start - 2
        if away_end < limit:
            print_3x5(draw, away_record, away_x, DETAIL_Y, RECORD)
    if home_x is not None and home_x + get_3x5_width(home_record) < home_proj_start:
        blocked = away_x is not None and away_x + get_3x5_width(away_record) >= home_x
        if not blocked:
            print_3x5(draw, home_record, home_x, DETAIL_Y, RECORD)


def render_fantasy_game_onto(image, draw, game, offset_x, settings):
    """Names, league, scores, then projection and record. Each row has a gap."""
    away = _abbr(game.away_abbrev or game.away)
    home = _abbr(game.home_abbrev or game.home)
    center = offset_x + SCORE_WIDTH // 2

    print_gfx_5x7(draw, away, offset_x + 2, NAME_Y, WHITE)
    _draw_score_right(draw, home, offset_x + SCORE_WIDTH - 2, NAME_Y, WHITE)
    week = f"W{int(game.week)}" if getattr(game, "week", 0) else ""
    if week:
        print_4x5_centered(draw, week, center, NAME_Y + 1, YELLOW)

    league = _fit_4x5(str(getattr(game, "league_name", "") or ""), SCORE_WIDTH - 8)
    print_4x5_centered(draw, league, center, LEAGUE_Y, WHITE)

    print_gfx_5x7(draw, _score(game.away_score), offset_x + 2, SCORE_Y, YELLOW)
    _draw_score_right(
        draw,
        _score(game.home_score),
        offset_x + SCORE_WIDTH - 2,
        SCORE_Y,
        YELLOW,
    )
    _draw_detail_row(
        draw,
        offset_x,
        _projection(game.away_projected),
        _record(
            getattr(game, "away_wins", -1),
            getattr(game, "away_losses", -1),
            getattr(game, "away_ties", 0),
        ),
        _projection(game.home_projected),
        _record(
            getattr(game, "home_wins", -1),
            getattr(game, "home_losses", -1),
            getattr(game, "home_ties", 0),
        ),
    )

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