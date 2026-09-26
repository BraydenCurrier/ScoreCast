from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageDraw

from common.fonts import (
    get_4x5_width,
    print_3x5,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    gfx_5x7_width,
    print_gfx_5x7_centered,
)


BALL_BROWN = (139, 69, 19)
WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)


def ordinal_down(down):
    if down == 1:
        return "1st"
    if down == 2:
        return "2nd"
    if down == 3:
        return "3rd"
    if down == 4:
        return "4th"
    return "-"


@dataclass(frozen=True)
class FootballFocusStyle:
    team_color: Callable
    draw_team_logo: Callable
    draw_broadcast_logo: Callable
    show_ranks: bool = False


# =========================================================
# Display
# =========================================================

FOCUS_WIDTH = 384
FOCUS_HEIGHT = 32

BLACK = (0, 0, 0)
DIM_WHITE = (168, 168, 172)
MUTED = (118, 118, 124)
CENTER_LINE = (32, 32, 36)
CLOCK_AMBER = (255, 214, 70)
LOSING_SCORE = (118, 108, 48)

RAIL_WIDTH = 3
LOGO_SIZE = 30
LEFT_PANEL_RIGHT = 127
RIGHT_PANEL_LEFT = 256
FIELD_X = 132
FIELD_Y = 28


# =========================================================
# Game state helpers
# =========================================================

def _is_scheduled(game):
    status = str(
        getattr(game, "status", "")
    ).strip().upper()

    return status in {
        "STATUS_SCHEDULED",
        "SCHEDULED",
        "STATUS_PREVIEW",
        "PREVIEW",
        "STATUS_PRE_GAME",
        "PRE_GAME",
        "STATUS_PREGAME",
        "PREGAME",
    }


def _is_final(game):
    status = str(
        getattr(game, "status", "")
    ).strip().upper()

    return "FINAL" in status or status == "STATUS_FINAL"


def _is_halftime(game):
    status = str(
        getattr(game, "status", "")
    ).strip().upper()

    return "HALF" in status


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mix(a, b, t):
    return tuple(
        max(0, min(255, int(a[i] + (b[i] - a[i]) * t)))
        for i in range(3)
    )


def _panel_fill(color):
    return _mix(BLACK, color, 0.14)


def _well_fill(color):
    return _mix(BLACK, color, 0.08)


# =========================================================
# Text / score helpers
# =========================================================

def draw_focus_possession_football(draw, x, y):
    draw.line([(x + 4, y), (x + 6, y)], fill=BALL_BROWN)
    draw.line([(x + 2, y + 1), (x + 8, y + 1)], fill=BALL_BROWN)
    draw.line([(x + 1, y + 2), (x + 9, y + 2)], fill=BALL_BROWN)
    draw.line([(x, y + 3), (x + 10, y + 3)], fill=BALL_BROWN)
    draw.line([(x + 1, y + 4), (x + 9, y + 4)], fill=BALL_BROWN)
    draw.line([(x + 2, y + 5), (x + 8, y + 5)], fill=BALL_BROWN)
    draw.line([(x + 4, y + 6), (x + 6, y + 6)], fill=BALL_BROWN)

    draw.line([(x + 3, y + 3), (x + 7, y + 3)], fill=WHITE)
    draw.point((x + 4, y + 2), fill=WHITE)
    draw.point((x + 5, y + 2), fill=WHITE)
    draw.point((x + 6, y + 2), fill=WHITE)
    draw.point((x + 4, y + 4), fill=WHITE)
    draw.point((x + 5, y + 4), fill=WHITE)
    draw.point((x + 6, y + 4), fill=WHITE)


def _draw_scaled_gfx_text(
    image,
    *,
    text,
    x,
    y,
    color,
    scale=2,
    align="left",
):
    """
    Render the existing 5x7 font and enlarge it
    using nearest-neighbor scaling.

    Uses a transparent source so panel tints
    are not punched out by a black box.
    """

    text = str(text)

    if not text:
        return 0

    text_width = max(1, gfx_5x7_width(text))
    r, g, b = color

    source = Image.new(
        "RGBA",
        (text_width, 7),
        (0, 0, 0, 0),
    )
    source_draw = ImageDraw.Draw(source)
    print_gfx_5x7(source_draw, text, 0, 0, (r, g, b, 255))

    scaled_width = source.width * scale
    scaled_height = source.height * scale
    enlarged = source.resize(
        (scaled_width, scaled_height),
        resample=Image.Resampling.NEAREST,
    )

    if align == "center":
        paste_x = x - scaled_width // 2
    elif align == "right":
        paste_x = x - scaled_width
    else:
        paste_x = x

    image.paste(enlarged, (paste_x, y), enlarged)
    return scaled_width


def _rank_text(rank):
    if rank is None:
        return ""

    try:
        value = int(rank)
    except (TypeError, ValueError):
        return ""

    if value <= 0:
        return ""

    return f"#{value}"


def _draw_team_name(draw, *, style, team, x, y, align):
    team = str(team).upper()
    color = style.team_color(team)
    width = gfx_5x7_width(team)

    if align == "right":
        text_x = x - width
    elif align == "center":
        text_x = x - width // 2
    else:
        text_x = x

    print_gfx_5x7(draw, team, text_x, y, color)
    underline_y = y + 8
    draw.line(
        [(text_x, underline_y), (text_x + width - 1, underline_y)],
        fill=_mix(BLACK, color, 0.72),
    )
    return text_x, width


def _draw_side_chrome(draw, *, style, team, is_home):
    color = style.team_color(team)
    fill = _panel_fill(color)

    if is_home:
        panel = [RIGHT_PANEL_LEFT, 0, FOCUS_WIDTH - 1, FOCUS_HEIGHT - 1]
        rail = [
            FOCUS_WIDTH - RAIL_WIDTH,
            0,
            FOCUS_WIDTH - 1,
            FOCUS_HEIGHT - 1,
        ]
        divider_x = RIGHT_PANEL_LEFT
    else:
        panel = [0, 0, LEFT_PANEL_RIGHT, FOCUS_HEIGHT - 1]
        rail = [0, 0, RAIL_WIDTH - 1, FOCUS_HEIGHT - 1]
        divider_x = LEFT_PANEL_RIGHT

    draw.rectangle(panel, fill=fill)
    draw.rectangle(rail, fill=color)
    draw.line(
        [(divider_x, 0), (divider_x, FOCUS_HEIGHT - 1)],
        fill=CENTER_LINE,
    )


def _team_text_anchor(is_home):
    if is_home:
        logo_x = FOCUS_WIDTH - RAIL_WIDTH - 1 - LOGO_SIZE
        text_x = logo_x - 4
        return logo_x, text_x, "right"

    logo_x = RAIL_WIDTH + 1
    text_x = logo_x + LOGO_SIZE + 3
    return logo_x, text_x, "left"


def _draw_score_value(
    image,
    draw,
    *,
    score,
    x,
    y,
    align,
    color,
    team_color_value,
):
    text = str(score)
    glyph_w = max(1, gfx_5x7_width(text)) * 2
    well_w = glyph_w + 6
    well_h = 16

    if align == "right":
        well_x = x - well_w
        score_x = x - 2
    else:
        well_x = x
        score_x = x + 2

    draw.rectangle(
        [well_x, y - 1, well_x + well_w - 1, y - 1 + well_h - 1],
        fill=_well_fill(team_color_value),
    )

    _draw_scaled_gfx_text(
        image,
        text=text,
        x=score_x,
        y=y,
        color=color,
        scale=2,
        align=align,
    )


def _draw_team_column(
    image,
    draw,
    *,
    style,
    team,
    is_home,
    settings,
    score=None,
    record=None,
    has_possession=False,
    score_color=YELLOW,
    rank=None,
):
    team = str(team).upper()
    color = style.team_color(team)

    _draw_side_chrome(
        draw,
        style=style,
        team=team,
        is_home=is_home,
    )

    logo_x, text_x, align = _team_text_anchor(is_home)
    style.draw_team_logo(image, team, logo_x, 1, settings)

    rank_label = _rank_text(rank) if style.show_ranks else ""
    rank_width = get_4x5_width(rank_label) if rank_label else 0
    name_anchor = text_x

    if rank_label:
        if is_home:
            print_4x5(
                draw,
                rank_label,
                text_x - rank_width,
                3,
                YELLOW,
            )
            name_anchor = text_x - rank_width - 2
        else:
            print_4x5(draw, rank_label, text_x, 3, YELLOW)
            name_anchor = text_x + rank_width + 2

    name_x, name_w = _draw_team_name(
        draw,
        style=style,
        team=team,
        x=name_anchor,
        y=2,
        align=align,
    )

    if has_possession:
        if is_home:
            football_x = name_x - 14
        else:
            football_x = name_x + name_w + 3
        draw_focus_possession_football(draw, football_x, 2)

    if score is not None:
        _draw_score_value(
            image,
            draw,
            score=score,
            x=text_x,
            y=15,
            align=align,
            color=score_color,
            team_color_value=color,
        )
    elif record:
        if align == "right":
            print_4x5(
                draw,
                record,
                text_x - get_4x5_width(record),
                17,
                DIM_WHITE,
            )
        else:
            print_4x5(draw, record, text_x, 17, DIM_WHITE)


# =========================================================
# Exact ticker field tracker — enlarged
# =========================================================

def _draw_large_field_tracker(
    draw,
    x,
    y,
    yardline,
    possession_direction,
    possession,
    home_team,
    home_color,
    away_color,
    distance=None,
    in_red_zone=False,
):
    GRASS_A = (0, 118, 28)
    GRASS_B = (0, 92, 20)
    RED_ZONE = (86, 52, 12)
    LINE_COLOR = (186, 186, 186)
    HASH = (210, 210, 210)
    POST_YELLOW = (255, 205, 0)
    LACE_WHITE = (255, 255, 255)

    ez_width = 10
    playable_width = 100
    field_height = 4

    field_left = x
    field_right = x + ez_width + playable_width + ez_width - 1
    playable_left = x + ez_width
    playable_right = playable_left + playable_width - 1
    field_bottom = y + field_height - 1

    draw.rectangle(
        [field_left, y, playable_left - 1, field_bottom],
        fill=away_color,
    )
    draw.rectangle(
        [playable_right + 1, y, field_right, field_bottom],
        fill=home_color,
    )

    for stripe in range(10):
        shade = GRASS_A if stripe % 2 == 0 else GRASS_B
        left = playable_left + stripe * 10
        right = left + 9
        draw.rectangle([left, y, right, field_bottom], fill=shade)

    if in_red_zone:
        is_home_attacking = possession == home_team
        if is_home_attacking:
            zone_left = playable_left
            zone_right = playable_left + 19
        else:
            zone_left = playable_right - 19
            zone_right = playable_right
        draw.rectangle(
            [zone_left, y, zone_right, field_bottom],
            fill=RED_ZONE,
        )

    draw.line(
        [playable_left, y, playable_left, field_bottom],
        fill=LINE_COLOR,
    )
    draw.line(
        [playable_right, y, playable_right, field_bottom],
        fill=LINE_COLOR,
    )

    for mark in (10, 20, 30, 40, 50, 60, 70, 80, 90):
        mx = playable_left + mark
        if mark in (25, 50, 75):
            continue
        draw.point((mx, y), fill=HASH)
        draw.point((mx, field_bottom), fill=HASH)

    for mark in (25, 50, 75):
        mx = playable_left + mark
        draw.line(
            [mx, y, mx, field_bottom],
            fill=LINE_COLOR if mark != 50 else WHITE,
        )

    is_home_attacking = possession == home_team

    if is_home_attacking:
        if possession_direction == "OWN":
            absolute_yards = 100 - yardline
        else:
            absolute_yards = yardline
    else:
        if possession_direction == "OWN":
            absolute_yards = yardline
        else:
            absolute_yards = 100 - yardline

    absolute_yards = max(0, min(100, absolute_yards))
    pixel_offset = int(absolute_yards)
    scrimmage_x = playable_left + pixel_offset

    if distance is not None:
        try:
            distance_value = int(distance)
        except (TypeError, ValueError):
            distance_value = 0

        if distance_value > 0:
            first_down_pixels = max(1, int(round(distance_value)))
            if is_home_attacking:
                first_down_x = scrimmage_x - first_down_pixels
            else:
                first_down_x = scrimmage_x + first_down_pixels

            first_down_x = max(
                playable_left,
                min(playable_right, first_down_x),
            )
            draw.line(
                [first_down_x, y, first_down_x, field_bottom],
                fill=YELLOW,
            )

    draw.line(
        [scrimmage_x, y, scrimmage_x, field_bottom],
        fill=WHITE,
    )

    football_y = y - 3
    if possession == home_team:
        football_x = scrimmage_x + 3
    else:
        football_x = scrimmage_x - 3

    draw.line(
        [(football_x - 2, football_y), (football_x + 2, football_y)],
        fill=BALL_BROWN,
    )
    draw.line(
        [(football_x - 3, football_y + 1), (football_x + 3, football_y + 1)],
        fill=BALL_BROWN,
    )
    draw.line(
        [(football_x - 2, football_y + 2), (football_x + 2, football_y + 2)],
        fill=BALL_BROWN,
    )
    draw.point((football_x, football_y + 1), fill=LACE_WHITE)
    draw.point((football_x + 1, football_y + 1), fill=LACE_WHITE)

    post_y = y - 4

    def _goalpost(px):
        draw.line([(px, post_y), (px, post_y + 2)], fill=POST_YELLOW)
        draw.line([(px + 2, post_y), (px + 2, post_y + 2)], fill=POST_YELLOW)
        draw.line([(px, post_y + 2), (px + 2, post_y + 2)], fill=POST_YELLOW)
        draw.line([(px + 1, post_y + 3), (px + 1, post_y + 5)], fill=POST_YELLOW)

    _goalpost(x - 1)
    _goalpost(field_right - 1)


# =========================================================
# Pregame
# =========================================================

def _record_text(wins, losses):
    return f"{_safe_int(wins)}-{_safe_int(losses)}"


def _draw_scheduled(image, draw, game, settings, style):
    away = str(getattr(game, "away", "")).upper()
    home = str(getattr(game, "home", "")).upper()
    week = getattr(game, "week", "")
    date = str(getattr(game, "date", "") or "").strip()
    start_time = str(getattr(game, "start_time", "") or "").strip()
    broadcast = str(getattr(game, "broadcast", "") or "").strip()

    _draw_team_column(
        image,
        draw,
        style=style,
        team=away,
        is_home=False,
        settings=settings,
        record=_record_text(game.away_wins, game.away_losses),
        rank=getattr(game, "away_rank", None),
    )
    _draw_team_column(
        image,
        draw,
        style=style,
        team=home,
        is_home=True,
        settings=settings,
        record=_record_text(game.home_wins, game.home_losses),
        rank=getattr(game, "home_rank", None),
    )

    cx = FOCUS_WIDTH // 2

    top_parts = []
    if week:
        top_parts.append(f"WEEK {week}")
    if date:
        top_parts.append(date)
    top_text = "  ".join(top_parts)
    if top_text:
        print_4x5_centered(draw, top_text, cx, 2, DIM_WHITE)

    if start_time:
        print_gfx_5x7_centered(draw, start_time, cx, 11, WHITE)

    if broadcast:
        drawn = style.draw_broadcast_logo(
            image,
            broadcast,
            cx,
            25,
            settings,
        )
        if not drawn:
            print_3x5(
                draw,
                broadcast.upper(),
                cx - (len(broadcast) * 4) // 2,
                25,
                MUTED,
            )


# =========================================================
# Live scoreboard
# =========================================================

def _quarter_label(game):
    if _is_halftime(game):
        return "HALFTIME"

    quarter = _safe_int(getattr(game, "quarter", 0))
    if quarter > 4:
        extra = quarter - 4
        return "OT" if extra == 1 else f"{extra}OT"
    if quarter > 0:
        return f"Q{quarter}"
    return ""


def _in_red_zone(game):
    possession = str(getattr(game, "possession", "") or "").upper()
    side = str(getattr(game, "yardline_side", "") or "").upper()
    raw_number = getattr(game, "yardline_number", None)
    away = str(getattr(game, "away", "") or "").upper()
    home = str(getattr(game, "home", "") or "").upper()

    if not possession or raw_number is None:
        return False

    number = _safe_int(raw_number, -1)
    if number < 0:
        return False
    if possession == away:
        return side == home and number <= 20
    if possession == home:
        return side == away and number <= 20
    return False


def _draw_live_center(draw, game):
    cx = FOCUS_WIDTH // 2
    is_halftime = _is_halftime(game)
    label = _quarter_label(game)
    clock = str(getattr(game, "clock", "") or "").strip()

    if is_halftime:
        print_4x5_centered(draw, "HALFTIME", cx, 13, CLOCK_AMBER)
        return

    top_text = label
    if label and clock:
        top_text = f"{label} {clock}"
    elif clock:
        top_text = clock

    if top_text:
        print_gfx_5x7_centered(draw, top_text, cx, 4, CLOCK_AMBER)

    down = _safe_int(getattr(game, "down", 0))
    distance = _safe_int(getattr(game, "distance", 0))
    if down > 0:
        down_text = f"{ordinal_down(down)}&{distance}"
        color = YELLOW if _in_red_zone(game) else WHITE
        print_gfx_5x7_centered(draw, down_text, cx, 14, color)


def _draw_live(image, draw, game, settings, style):
    away = str(getattr(game, "away", "")).upper()
    home = str(getattr(game, "home", "")).upper()
    away_score = _safe_int(getattr(game, "away_score", 0))
    home_score = _safe_int(getattr(game, "home_score", 0))
    possession = str(getattr(game, "possession", "")).upper()
    is_halftime = _is_halftime(game)

    _draw_team_column(
        image,
        draw,
        style=style,
        team=away,
        is_home=False,
        settings=settings,
        score=away_score,
        has_possession=(possession == away and not is_halftime),
        rank=getattr(game, "away_rank", None),
    )
    _draw_team_column(
        image,
        draw,
        style=style,
        team=home,
        is_home=True,
        settings=settings,
        score=home_score,
        has_possession=(possession == home and not is_halftime),
        rank=getattr(game, "home_rank", None),
    )

    yardline = getattr(game, "yardline_number", None)
    if not is_halftime and yardline is not None:
        direction = (
            "OWN"
            if str(game.possession).upper()
            == str(game.yardline_side).upper()
            else "OPP"
        )
        _draw_large_field_tracker(
            draw,
            FIELD_X,
            FIELD_Y,
            _safe_int(yardline),
            direction,
            possession,
            home,
            style.team_color(home),
            style.team_color(away),
            game.distance,
            in_red_zone=_in_red_zone(game),
        )

    _draw_live_center(draw, game)


# =========================================================
# Final
# =========================================================

def _draw_final(image, draw, game, settings, style):
    away = str(getattr(game, "away", "")).upper()
    home = str(getattr(game, "home", "")).upper()
    away_score = _safe_int(getattr(game, "away_score", 0))
    home_score = _safe_int(getattr(game, "home_score", 0))

    away_color = YELLOW
    home_color = YELLOW
    if away_score > home_score:
        home_color = LOSING_SCORE
    elif home_score > away_score:
        away_color = LOSING_SCORE

    _draw_team_column(
        image,
        draw,
        style=style,
        team=away,
        is_home=False,
        settings=settings,
        score=away_score,
        score_color=away_color,
        rank=getattr(game, "away_rank", None),
    )
    _draw_team_column(
        image,
        draw,
        style=style,
        team=home,
        is_home=True,
        settings=settings,
        score=home_score,
        score_color=home_color,
        rank=getattr(game, "home_rank", None),
    )

    cx = FOCUS_WIDTH // 2
    print_gfx_5x7_centered(draw, "FINAL", cx, 12, WHITE)


# =========================================================
# Main renderer
# =========================================================

def render_football_focus(game, settings, style):
    """
    Render a full-screen 384x32 football focus scoreboard.
    """

    image = Image.new(
        "RGB",
        (FOCUS_WIDTH, FOCUS_HEIGHT),
        BLACK,
    )
    draw = ImageDraw.Draw(image)

    if _is_scheduled(game):
        _draw_scheduled(image, draw, game, settings, style)
        return image

    if _is_final(game):
        _draw_final(image, draw, game, settings, style)
        return image

    _draw_live(image, draw, game, settings, style)
    return image
