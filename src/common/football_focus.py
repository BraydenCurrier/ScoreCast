from dataclasses import dataclass
from typing import Callable
import re
import time

from PIL import Image, ImageDraw

from common.fonts import (
    get_4x5_width,
    print_3x5,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    gfx_5x7_width,
    print_gfx_5x7_centered,
    print_gfx_7x11,
    gfx_7x11_width,
)
from common.settings import get_developer_settings


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
RECORD_GAP = 4
STAT_INSET = 6
FOUL_ORANGE = (255, 130, 40)
SCORE_Y = 14
SCORE_H = 11
SCORE_SLIDE = True
SCORE_SLIDE_SECONDS = 0.5
TIMEOUT_Y = 29
CLOCK_Y = 1
DOWN_Y = 9
LAST_PLAY_Y = 18
SCORING_Y = 14


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


# =========================================================
# Text / score helpers
# =========================================================

TIMEOUT_PIP_W = 5
TIMEOUT_PIP_H = 2
TIMEOUT_PIP_GAP = 2
TIMEOUT_COUNT = 3


def _timeouts_cluster_width():
    return (
        TIMEOUT_COUNT * TIMEOUT_PIP_W
        + (TIMEOUT_COUNT - 1) * TIMEOUT_PIP_GAP
    )


def _draw_timeouts(draw, x, y, remaining, *, align="left"):
    if remaining is None:
        return
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        return
    remaining = max(0, min(TIMEOUT_COUNT, remaining))
    width = _timeouts_cluster_width()
    start_x = x - width if align == "right" else x
    used_outline = (70, 70, 70)
    step = TIMEOUT_PIP_W + TIMEOUT_PIP_GAP
    for i in range(TIMEOUT_COUNT):
        bx = start_x + i * step
        box = [
            bx,
            y,
            bx + TIMEOUT_PIP_W - 1,
            y + TIMEOUT_PIP_H - 1,
        ]
        if i < remaining:
            draw.rectangle(box, fill=WHITE)
        else:
            draw.rectangle(box, outline=used_outline)


def _draw_possession_arrow(draw, *, x, y, color, point_inward):
    width = 6
    height = 7
    top = y
    bottom = y + height - 1
    mid_y = y + height // 2
    if point_inward == "right":
        tip = (x + width - 1, mid_y)
        base = [(x, top), (x, bottom)]
    else:
        tip = (x, mid_y)
        base = [(x + width - 1, top), (x + width - 1, bottom)]
    draw.polygon([tip, *base], fill=color)


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


def _team_text_anchor(is_home, inner_pad=2):
    if is_home:
        logo_x = FOCUS_WIDTH - RAIL_WIDTH - inner_pad - LOGO_SIZE
        text_x = RIGHT_PANEL_LEFT + inner_pad
        return logo_x, text_x, "left"

    logo_x = RAIL_WIDTH + inner_pad
    text_x = LEFT_PANEL_RIGHT - inner_pad
    return logo_x, text_x, "right"


_score_slides = {}
_SCORE_SLIDE_GAP = 0.12


def _slide_ease(progress):
    progress = max(0.0, min(1.0, progress))
    return 1.0 - (1.0 - progress) ** 3


def _score_slide_state(game_id, is_home, score):
    key = (str(game_id or ""), "home" if is_home else "away")
    now = time.monotonic()
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0

    state = _score_slides.get(key)
    if state is None:
        _score_slides[key] = {
            "shown": score,
            "target": score,
            "from": score,
            "to": score,
            "start": now,
            "playing": False,
            "primed": False,
            "last_seen": now,
        }
        return score, None, 1.0

    gap = now - state["last_seen"]
    state["last_seen"] = now

    if not state["primed"]:
        state["shown"] = score
        state["target"] = score
        state["from"] = score
        state["to"] = score
        state["playing"] = False
        state["primed"] = True
        return score, None, 1.0

    if score != state["target"]:
        state["target"] = score

    became_visible = gap > _SCORE_SLIDE_GAP
    needs_slide = state["target"] != state["shown"]

    if became_visible:
        if needs_slide:
            state["playing"] = True
            state["from"] = state["shown"]
            state["to"] = state["target"]
            state["start"] = now
        else:
            state["playing"] = False
    elif needs_slide and not state["playing"]:
        state["playing"] = True
        state["from"] = state["shown"]
        state["to"] = state["target"]
        state["start"] = now

    if not state["playing"]:
        return state["shown"], None, 1.0

    elapsed = now - state["start"]
    if elapsed >= SCORE_SLIDE_SECONDS:
        state["shown"] = state["to"]
        state["playing"] = False
        if state["target"] != state["shown"]:
            state["playing"] = True
            state["from"] = state["shown"]
            state["to"] = state["target"]
            state["start"] = now
            return state["from"], state["to"], 0.0
        return state["shown"], None, 1.0

    progress = _slide_ease(elapsed / SCORE_SLIDE_SECONDS)
    return state["from"], state["to"], progress


def _draw_score_glyphs(draw, text, x, y, color, align):
    text = str(text)
    width = gfx_7x11_width(text)
    glyph_x = x - width if align == "right" else x
    print_gfx_7x11(draw, text, glyph_x, y, color)
    return width


def _draw_score_slide(image, *, old, new, progress, text_x, y, color, align):
    old_text = str(old)
    new_text = str(new)
    old_w = gfx_7x11_width(old_text)
    new_w = gfx_7x11_width(new_text)
    clip_w = max(old_w, new_w, 1)
    clip_h = SCORE_H
    if align == "right":
        clip_x = text_x - clip_w
    else:
        clip_x = text_x
    clip_x = max(0, clip_x)
    clip_y = y
    box = (
        clip_x,
        clip_y,
        min(FOCUS_WIDTH, clip_x + clip_w),
        min(FOCUS_HEIGHT, clip_y + clip_h),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    clip = image.crop(box)
    clip_draw = ImageDraw.Draw(clip)
    offset = int(round(progress * clip_h))
    old_x = clip_w - old_w if align == "right" else 0
    new_x = clip_w - new_w if align == "right" else 0
    print_gfx_7x11(clip_draw, old_text, old_x, -offset, color)
    print_gfx_7x11(clip_draw, new_text, new_x, clip_h - offset, color)
    image.paste(clip, (box[0], box[1]))


def _draw_team_stats(
    draw,
    *,
    logo_x,
    is_home,
    rush,
    passing,
    turnovers,
    record_width=0,
):
    lines = []
    if rush is not None:
        lines.append(("RUSH", str(rush)))
    if passing is not None:
        lines.append(("PASS", str(passing)))
    if turnovers is not None:
        lines.append(("TO", str(turnovers)))
    if not lines:
        return

    line_h = 5
    line_gap = 2
    total_h = len(lines) * line_h + (len(lines) - 1) * line_gap
    start_y = (FOCUS_HEIGHT - total_h) // 2
    label_gap = 3

    if is_home:
        record_left = logo_x - RECORD_GAP - record_width
        stats_right = record_left - STAT_INSET
    else:
        record_right = logo_x + LOGO_SIZE + RECORD_GAP + record_width
        stats_left = record_right + STAT_INSET

    for index, (label, value) in enumerate(lines):
        y = start_y + index * (line_h + line_gap)
        label_w = get_4x5_width(label)
        value_w = get_4x5_width(value)
        if is_home:
            label_x = stats_right - label_w
            value_x = label_x - label_gap - value_w
        else:
            label_x = stats_left
            value_x = label_x + label_w + label_gap
        print_4x5(draw, label, label_x, y, MUTED)
        print_4x5(draw, value, value_x, y, WHITE)


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
    timeouts=None,
    rush=None,
    passing=None,
    turnovers=None,
    game_id="",
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
    if rank_label:
        rank_width = get_4x5_width(rank_label)
        if is_home:
            print_4x5(
                draw,
                rank_label,
                logo_x - 2 - rank_width,
                3,
                YELLOW,
            )
        else:
            print_4x5(draw, rank_label, logo_x + LOGO_SIZE + 2, 3, YELLOW)

    record_width = 0
    if record:
        record_width = get_4x5_width(record)
        if is_home:
            record_x = logo_x - RECORD_GAP - record_width
        else:
            record_x = logo_x + LOGO_SIZE + RECORD_GAP
        print_4x5(draw, record, record_x, 13, DIM_WHITE)

    _draw_team_stats(
        draw,
        logo_x=logo_x,
        is_home=is_home,
        rush=rush,
        passing=passing,
        turnovers=turnovers,
        record_width=record_width,
    )

    name_x, name_w = _draw_team_name(
        draw,
        style=style,
        team=team,
        x=text_x,
        y=2,
        align=align,
    )

    if has_possession:
        if is_home:
            _draw_possession_arrow(
                draw,
                x=name_x + name_w + 2,
                y=2,
                color=WHITE,
                point_inward="left",
            )
        else:
            _draw_possession_arrow(
                draw,
                x=name_x - 8,
                y=2,
                color=WHITE,
                point_inward="right",
            )

    if score is not None:
        if get_developer_settings().get("score_slide", SCORE_SLIDE):
            old_score, new_score, progress = _score_slide_state(
                game_id,
                is_home,
                score,
            )
            if new_score is None or progress >= 1:
                _draw_score_glyphs(
                    draw,
                    old_score,
                    text_x,
                    SCORE_Y,
                    score_color,
                    align,
                )
            else:
                _draw_score_slide(
                    image,
                    old=old_score,
                    new=new_score,
                    progress=progress,
                    text_x=text_x,
                    y=SCORE_Y,
                    color=score_color,
                    align=align,
                )
        else:
            _draw_score_glyphs(
                draw,
                score,
                text_x,
                SCORE_Y,
                score_color,
                align,
            )
        if timeouts is not None:
            _draw_timeouts(
                draw,
                text_x,
                TIMEOUT_Y,
                timeouts,
                align=align,
            )


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


def _format_yardline(game):
    raw_number = getattr(game, "yardline_number", None)
    if raw_number is None:
        return ""
    try:
        number = int(raw_number)
    except (TypeError, ValueError):
        return ""
    if number <= 0 or number > 50:
        return ""
    if number == 50:
        return "50"
    side = str(getattr(game, "yardline_side", "") or "").upper().strip()
    if side:
        return f"{side} {number}"
    return str(number)


def _athlete_last_name(value):
    name = str(value or "").replace(".", " ").upper().strip()
    parts = [part for part in name.split() if part]
    return parts[-1] if parts else ""


def _play_blob(game):
    return (
        f"{getattr(game, 'last_play_type', '')} "
        f"{getattr(game, 'last_play_text', '')}"
    ).lower()


def _situation_label(game):
    short = str(getattr(game, "short_down_text", "") or "").lower()
    if "kickoff" in short:
        return "KICKOFF"
    if "fair catch" in short:
        return "FAIR CATCH"
    if "extra point" in short:
        return "XP"
    if "two-point" in short or "2-pt" in short or "2pt" in short:
        return "2PT"
    if "field goal" in short:
        return "FG"

    if _safe_int(getattr(game, "down", 0)) > 0:
        return ""

    blob = _play_blob(game)
    if "kickoff" in blob:
        return "KICKOFF"
    if "fair catch" in blob:
        return "FAIR CATCH"
    if "extra point" in blob:
        return "XP"
    if "two-point" in blob or "2-pt" in blob or "2pt" in blob:
        return "2PT"
    return ""


def _down_label(game):
    special = _situation_label(game)
    if special:
        return special

    down = _safe_int(getattr(game, "down", 0))
    distance = _safe_int(getattr(game, "distance", 0))
    if down <= 0:
        return ""

    short = str(getattr(game, "short_down_text", "") or "").upper()
    if "GOAL" in short:
        return f"{ordinal_down(down)}&G"
    return f"{ordinal_down(down)}&{distance}"


def _yds(yards):
    return f"{yards} YDS"


_PENALTY_KINDS = (
    ("defensive pass interference", "DPI"),
    ("offensive pass interference", "OPI"),
    ("pass interference", "PI"),
    ("roughing the passer", "RTP"),
    ("roughing the kicker", "RTK"),
    ("running into the kicker", "KICKER"),
    ("unnecessary roughness", "UNR"),
    ("personal foul", "PF"),
    ("false start", "FALSE START"),
    ("defensive holding", "HOLD"),
    ("offensive holding", "HOLD"),
    ("holding", "HOLD"),
    ("offsides", "OFFSIDE"),
    ("offside", "OFFSIDE"),
    ("encroachment", "ENCROACH"),
    ("neutral zone infraction", "NZI"),
    ("delay of game", "DELAY"),
    ("too many men", "12 MEN"),
    ("illegal formation", "FORMATION"),
    ("illegal shift", "SHIFT"),
    ("illegal motion", "MOTION"),
    ("illegal contact", "CONTACT"),
    ("illegal block", "BLOCK"),
    ("face mask", "FACE MASK"),
    ("unsportsmanlike", "UNS"),
    ("taunting", "TAUNT"),
    ("chop block", "CHOP"),
    ("clipping", "CLIP"),
    ("intentional grounding", "GROUNDING"),
    ("illegal forward pass", "ILL PASS"),
    ("kick catch interference", "KCI"),
    ("ineligible", "INELIG"),
)


def _penalty_yards(blob, yards):
    if yards:
        return abs(yards)
    match = re.search(r"(\d+)\s*yards?", blob)
    if match:
        return int(match.group(1))
    return 0


def _penalty_label(blob, yards):
    if "offset" in blob:
        return "OFFSETTING"
    infraction = "PENALTY"
    for needle, label in _PENALTY_KINDS:
        if needle in blob:
            infraction = label
            break
    if "declined" in blob:
        return f"{infraction} DECLINED"
    yds = _penalty_yards(blob, yards)
    if yds:
        return f"{infraction} {_yds(yds)}"
    return infraction


def _last_play_label(game):
    play_type = str(getattr(game, "last_play_type", "") or "")
    play_text = str(getattr(game, "last_play_text", "") or "")
    blob = f"{play_type} {play_text}".lower().strip()
    if not blob:
        return ""

    yards = _safe_int(getattr(game, "last_play_yardage", 0))
    if "penalty" in blob:
        return _penalty_label(blob, yards)

    skip = (
        "timeout",
        "two-minute",
        "two minute",
        "kneel",
        "spike",
        "no play",
    )
    if any(marker in blob for marker in skip):
        return ""

    scoring = bool(getattr(game, "scoring_play", False))

    if "safety" in blob:
        return "SAFETY"
    if "touchdown" in blob or (
        scoring
        and "field goal" not in blob
        and "extra point" not in blob
        and "two-point" not in blob
        and "2-pt" not in blob
    ):
        if "intercept" in blob:
            return "INT TD"
        if "fumble" in blob:
            return "FUM TD"
        if "punt" in blob or "kickoff" in blob or "return" in blob:
            return "RET TD"
        if "pass" in blob:
            return "PASS TD"
        if "rush" in blob:
            return "RUSH TD"
        return "TD"
    if "intercept" in blob:
        return "INT"
    if "sack" in blob:
        return "SACK"
    if "fumble" in blob:
        return "FUMBLE"
    if "field goal" in blob:
        if "block" in blob:
            return "FG BLK"
        if any(token in blob for token in ("no good", "miss", "wide", "short")):
            return "FG MISS"
        if scoring or " is good" in blob or blob.endswith("good"):
            return "FG GOOD"
        return "FG"
    if "extra point" in blob:
        if any(token in blob for token in ("no good", "miss", "block")):
            return "XP MISS"
        if scoring or "good" in blob:
            return "XP GOOD"
        return "XP"
    if "two-point" in blob or "2-pt" in blob or "2pt" in blob:
        if "fail" in blob or "no good" in blob:
            return "2PT FAIL"
        if scoring or "good" in blob or "succeed" in blob:
            return "2PT GOOD"
        return "2PT"
    if "punt" in blob:
        return f"PUNT {_yds(yards)}" if yards else "PUNT"
    if "kickoff" in blob:
        return "KICKOFF"
    if "incomplete" in blob:
        return "INC"

    kind = play_type.upper()
    if "PASS" in kind or "pass" in blob:
        return f"PASS {_yds(yards)}" if yards else "PASS"
    if "RUSH" in kind or "rush" in blob:
        return f"RUSH {_yds(yards)}"
    return ""


def _last_play_detail(game):
    label = _last_play_label(game)
    if not label:
        return ""

    names = getattr(game, "last_play_athlete_names", ()) or ()
    last = _athlete_last_name(names[0]) if names else ""
    if not last:
        return label

    while last and get_4x5_width(f"{label} {last}") > 118:
        last = last[:-1]
    if not last:
        return label
    return f"{label} {last}"


def _draw_live_center(draw, game):
    cx = FOCUS_WIDTH // 2
    is_halftime = _is_halftime(game)
    label = _quarter_label(game)
    clock = str(getattr(game, "clock", "") or "").strip()

    if is_halftime:
        print_4x5_centered(draw, "HALFTIME", cx, 13, CLOCK_AMBER)
        return

    reviewing = bool(getattr(game, "play_under_review", False))
    top_text = label
    if label and clock:
        top_text = f"{label} {clock}"
    elif clock:
        top_text = clock

    scoring = bool(getattr(game, "scoring_play", False))
    play_label = _last_play_label(game)
    down_text = _down_label(game)
    yard_text = _format_yardline(game)
    detail = ""
    if not scoring:
        detail = _last_play_detail(game)
        if detail == down_text:
            detail = ""

    if reviewing:
        print_gfx_5x7_centered(draw, "REVIEW", cx, CLOCK_Y, FOUL_ORANGE)
    elif top_text:
        print_gfx_5x7_centered(draw, top_text, cx, CLOCK_Y, CLOCK_AMBER)

    color = YELLOW if scoring or _in_red_zone(game) else WHITE
    flash_on = True
    if scoring:
        flash_on = (time.monotonic() % 1.0) < 0.65

    down_y = SCORING_Y if scoring else DOWN_Y

    if scoring and play_label:
        if flash_on:
            print_gfx_5x7_centered(draw, play_label, cx, SCORING_Y, YELLOW)
    elif down_text and yard_text:
        gap = 6
        down_width = gfx_5x7_width(down_text)
        yard_width = gfx_5x7_width(yard_text)
        start_x = cx - (down_width + gap + yard_width) // 2
        print_gfx_5x7(draw, down_text, start_x, down_y, color)
        print_gfx_5x7(
            draw,
            yard_text,
            start_x + down_width + gap,
            down_y,
            color,
        )
    elif down_text:
        print_gfx_5x7_centered(draw, down_text, cx, down_y, color)
    elif yard_text:
        print_gfx_5x7_centered(draw, yard_text, cx, down_y, color)

    if detail:
        print_4x5_centered(draw, detail, cx, LAST_PLAY_Y, DIM_WHITE)


def _draw_live(image, draw, game, settings, style):
    away = str(getattr(game, "away", "")).upper()
    home = str(getattr(game, "home", "")).upper()
    away_score = _safe_int(getattr(game, "away_score", 0))
    home_score = _safe_int(getattr(game, "home_score", 0))
    possession = str(getattr(game, "possession", "")).upper()
    is_halftime = _is_halftime(game)
    event_id = str(getattr(game, "event_id", "") or "") or (
        f"{away}@{home}"
    )

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
        timeouts=getattr(game, "away_timeouts", None),
        record=_record_text(game.away_wins, game.away_losses),
        rush=getattr(game, "away_rush_yards", None),
        passing=getattr(game, "away_pass_yards", None),
        turnovers=getattr(game, "away_turnovers", None),
        game_id=event_id,
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
        timeouts=getattr(game, "home_timeouts", None),
        record=_record_text(game.home_wins, game.home_losses),
        rush=getattr(game, "home_rush_yards", None),
        passing=getattr(game, "home_pass_yards", None),
        turnovers=getattr(game, "home_turnovers", None),
        game_id=event_id,
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

    event_id = str(getattr(game, "event_id", "") or "") or (
        f"{away}@{home}"
    )

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
        record=_record_text(game.away_wins, game.away_losses),
        rush=getattr(game, "away_rush_yards", None),
        passing=getattr(game, "away_pass_yards", None),
        turnovers=getattr(game, "away_turnovers", None),
        game_id=event_id,
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
        record=_record_text(game.home_wins, game.home_losses),
        rush=getattr(game, "home_rush_yards", None),
        passing=getattr(game, "home_pass_yards", None),
        turnovers=getattr(game, "home_turnovers", None),
        game_id=event_id,
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
