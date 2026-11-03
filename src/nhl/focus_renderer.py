import time

from PIL import Image, ImageDraw

from common.broadcast import draw_broadcast_logo
from common.football_focus import (
    SCORE_SLIDE,
    _draw_score_glyphs,
    _draw_score_slide,
    _score_slide_state,
)
from common.fonts import (
    get_4x5_width,
    gfx_5x7_width,
    gfx_7x11_width,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    print_gfx_5x7_centered,
)
from common.settings import get_developer_settings
from nhl.colors import team_color
from nhl.nhl_renderer import (
    draw_team_logo,
    final_label,
    is_final,
    is_intermission,
    is_scheduled,
    is_shootout,
    period_label,
)


FOCUS_WIDTH = 384
FOCUS_HEIGHT = 32
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
DIM_WHITE = (168, 168, 172)
CENTER_LINE = (32, 32, 36)
CLOCK_AMBER = (255, 214, 70)
LOSING_SCORE = (118, 108, 48)
PP_ORANGE = (255, 130, 40)

RAIL_WIDTH = 3
LOGO_SIZE = 30
LEFT_PANEL_RIGHT = 127
RIGHT_PANEL_LEFT = 256
CENTER_LIMIT = 118
SCORE_Y = 12
META_Y = 25
META_GAP = 3
PUCK_W = 7
PUCK_H = 5


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


def _ink_on_black(color):
    brightness = (color[0] * 30 + color[1] * 59 + color[2] * 11) // 100
    if brightness >= 110:
        return color
    return _mix(color, WHITE, 0.5)


def _fit_gfx(text, max_width):
    text = str(text or "").upper().strip()
    while text and gfx_5x7_width(text) > max_width:
        text = text[:-1].rstrip()
    return text


def _fit_4x5(text, max_width):
    text = str(text or "").upper().strip()
    while text and get_4x5_width(text) > max_width:
        text = text[:-1].rstrip()
    return text


def _so_pair(game):
    away = getattr(game, "away_so_goals", None)
    home = getattr(game, "home_so_goals", None)
    if away is None or home is None:
        return None
    try:
        return int(away), int(home)
    except (TypeError, ValueError):
        return None


def _period_name(game):
    if is_shootout(game):
        return "SO"
    period = _safe_int(getattr(game, "period", 0))
    if getattr(game, "overtime", False) or period > 3:
        extra = max(1, period - 3)
        return "OT" if extra <= 1 else f"{extra}OT"
    return period_label(game)


def _ended_period(game):
    period = _safe_int(getattr(game, "period", 0))
    names = {1: "1ST", 2: "2ND", 3: "3RD"}
    if period in names:
        return f"END {names[period]}"
    if period > 3:
        extra = period - 3
        return "END OT" if extra <= 1 else f"END {extra}OT"
    return ""


def _strength_text(game):
    raw = str(getattr(game, "strength", "") or "").strip()
    parts = raw.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0])} ON {int(parts[1])}"
    if str(getattr(game, "power_play", "") or "").strip():
        return "POWER PLAY"
    return ""


def _center_play(game):
    """Last name plus the event, trimmed so the event word stays whole."""
    name = " ".join(str(getattr(game, "last_play_name", "") or "").upper().split())
    label = " ".join(str(getattr(game, "last_play_label", "") or "").upper().split())
    if not label:
        return ""
    text = f"{name} {label}".strip() if name else label
    while name and gfx_5x7_width(text) > CENTER_LIMIT:
        name = name[:-1].rstrip()
        text = f"{name} {label}".strip() if name else label
    return _fit_gfx(text, CENTER_LIMIT)


def _power_line(game):
    situation = _strength_text(game)
    clock = str(getattr(game, "power_play_clock", "") or "").strip()
    if situation and clock:
        return f"{situation}  {clock}"
    if clock:
        return f"PP {clock}"
    return situation


def _clock_line(game):
    if is_final(game):
        return final_label(game), WHITE
    if is_intermission(game):
        return "INTERMISSION", WHITE
    if is_shootout(game):
        return "SHOOTOUT", WHITE
    label = _period_name(game)
    clock = str(getattr(game, "clock", "") or "").strip()
    if label and clock:
        return f"{label} {clock}", CLOCK_AMBER
    return label or clock, CLOCK_AMBER


def _draw_side_chrome(draw, team, is_home):
    color = team_color(team)
    fill = _mix(BLACK, color, 0.14)
    if is_home:
        draw.rectangle(
            [RIGHT_PANEL_LEFT, 0, FOCUS_WIDTH - 1, FOCUS_HEIGHT - 1],
            fill=fill,
        )
        draw.rectangle(
            [FOCUS_WIDTH - RAIL_WIDTH, 0, FOCUS_WIDTH - 1, FOCUS_HEIGHT - 1],
            fill=color,
        )
        draw.line(
            [(RIGHT_PANEL_LEFT, 0), (RIGHT_PANEL_LEFT, FOCUS_HEIGHT - 1)],
            fill=CENTER_LINE,
        )
        return
    draw.rectangle([0, 0, LEFT_PANEL_RIGHT, FOCUS_HEIGHT - 1], fill=fill)
    draw.rectangle([0, 0, RAIL_WIDTH - 1, FOCUS_HEIGHT - 1], fill=color)
    draw.line(
        [(LEFT_PANEL_RIGHT, 0), (LEFT_PANEL_RIGHT, FOCUS_HEIGHT - 1)],
        fill=CENTER_LINE,
    )


def _anchors(is_home):
    if is_home:
        logo_x = FOCUS_WIDTH - RAIL_WIDTH - 2 - LOGO_SIZE
        text_x = RIGHT_PANEL_LEFT + 2
        return logo_x, text_x, False
    logo_x = RAIL_WIDTH + 2
    text_x = LEFT_PANEL_RIGHT - 2
    return logo_x, text_x, True


def _draw_puck(draw, x, y):
    rows = (
        " ##### ",
        "#######",
        "#######",
        "#######",
        " ##### ",
    )
    for row, pattern in enumerate(rows):
        for col, mark in enumerate(pattern):
            if mark == "#":
                draw.point((x + col, y + row), fill=WHITE)


def _meta_parts(name, pct, max_width, name_color):
    name = " ".join(str(name or "").upper().replace(".", " ").split())
    pct = str(pct or "").strip()
    shown = name

    def parts_for(shown_name, keep_pct):
        parts = []
        if shown_name:
            parts.append((shown_name, name_color))
        if keep_pct and pct:
            parts.append((pct, DIM_WHITE))
        return parts

    def width(parts):
        if not parts:
            return 0
        return (
            sum(get_4x5_width(text) for text, _color in parts)
            + META_GAP * (len(parts) - 1)
        )

    parts = parts_for(shown, True)
    while shown and width(parts) > max_width:
        shown = shown[:-1].rstrip()
        parts = parts_for(shown, True)
    if width(parts) > max_width:
        parts = parts_for(shown, False)
    if shown and len(shown) < 2 and len(name) > 2:
        parts = [part for part in parts if part[0] != shown]
    return parts


def _draw_meta(draw, parts, left, right):
    """Goalie line, centered on the same span as the on-ice numbers."""
    if not parts or right - left < 8:
        return
    width = (
        sum(get_4x5_width(text) for text, _color in parts)
        + META_GAP * (len(parts) - 1)
    )
    x = left + max(0, (right - left - width) // 2)
    for text, color in parts:
        print_4x5(draw, text, x, META_Y, color)
        x += get_4x5_width(text) + META_GAP


def _draw_pp_by_abbr(draw, abbr_x, abbr_width, align_right):
    """Small orange PP on the team row, beside the abbreviation."""
    width = get_4x5_width("PP")
    gap = 2
    if align_right:
        x = abbr_x - gap - width
    else:
        x = abbr_x + abbr_width + gap
    print_4x5(draw, "PP", x, 3, PP_ORANGE)
    return x, width


def _draw_shots_under_score(draw, shots, text_x, align_right):
    text = str(shots)
    width = get_4x5_width(text)
    x = text_x - width if align_right else text_x
    print_4x5(draw, text, x, META_Y, WHITE)


def _jersey_numbers(numbers):
    chosen = []
    for number in numbers or ():
        text = str(number).strip()
        if text:
            chosen.append(text)
        if len(chosen) == 6:
            break
    return chosen


def _draw_jersey_row(draw, numbers, left, right, y, color):
    """On-ice numbers, centered in the open gap beside the score."""
    nums = _jersey_numbers(numbers)
    if not nums or right - left < 8:
        return

    def span(gap):
        return sum(get_4x5_width(number) for number in nums) + gap * (len(nums) - 1)

    while len(nums) > 1 and span(2) > right - left:
        nums.pop()
    gap = 4 if span(4) <= right - left else 2
    row_w = span(gap)
    x = left + max(0, (right - left - row_w) // 2)
    label = "ON ICE"
    label_w = get_4x5_width(label)
    label_x = x + (row_w - label_w) // 2
    label_x = max(left, min(label_x, right - label_w))
    print_4x5(draw, label, label_x, y - 6, DIM_WHITE)
    for number in nums:
        print_4x5(draw, number, x, y + 1, color)
        x += get_4x5_width(number) + gap


def _draw_team_column(
    image,
    draw,
    game,
    team,
    is_home,
    settings,
    *,
    score=None,
    score_color=YELLOW,
    show_puck=False,
    on_pp=False,
    goalie="",
    save_pct="",
    lineup=(),
    shots=None,
    game_id="",
):
    team = str(team).upper()
    color = team_color(team)
    _draw_side_chrome(draw, team, is_home)
    logo_x, text_x, align_right = _anchors(is_home)
    draw_team_logo(image, team, logo_x, 1, settings)

    if is_home:
        wins = _safe_int(game.home_wins)
        losses = _safe_int(game.home_losses)
        ot_losses = _safe_int(getattr(game, "home_ot_losses", 0))
    else:
        wins = _safe_int(game.away_wins)
        losses = _safe_int(game.away_losses)
        ot_losses = _safe_int(getattr(game, "away_ot_losses", 0))
    record = f"{wins}-{losses}-{ot_losses}"
    record_width = get_4x5_width(record)
    if is_home:
        record_x = logo_x - 4 - record_width
    else:
        record_x = logo_x + LOGO_SIZE + 4
    print_4x5(draw, record, record_x, 4, DIM_WHITE)

    abbr_width = gfx_5x7_width(team)
    abbr_x = text_x - abbr_width if align_right else text_x
    print_gfx_5x7(draw, team, abbr_x, 2, color)
    draw.line(
        [(abbr_x, 10), (abbr_x + abbr_width - 1, 10)],
        fill=_mix(BLACK, color, 0.72),
    )

    pp_x = pp_width = None
    if on_pp:
        pp_x, pp_width = _draw_pp_by_abbr(draw, abbr_x, abbr_width, align_right)

    if show_puck:
        if align_right:
            anchor = abbr_x if pp_x is None else pp_x
            puck_x = anchor - 2 - PUCK_W
            blocked = puck_x < record_x + record_width + 2
        else:
            anchor = abbr_x + abbr_width if pp_x is None else pp_x + pp_width
            puck_x = anchor + 2
            blocked = puck_x + PUCK_W > record_x - 2
        if not blocked and puck_x >= RAIL_WIDTH:
            _draw_puck(draw, puck_x, 3)

    if score is not None:
        align = "right" if align_right else "left"
        if get_developer_settings(settings).get("score_slide", SCORE_SLIDE):
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

    gap_left = gap_right = 0
    if score is not None:
        score_width = gfx_7x11_width(str(score))
        if align_right:
            gap_left = logo_x + LOGO_SIZE + 3
            gap_right = text_x - score_width - 3
        else:
            gap_left = text_x + score_width + 3
            gap_right = logo_x - 3
        if shots is not None:
            shot_width = get_4x5_width(str(shots))
            if align_right:
                gap_right = min(gap_right, text_x - shot_width - 2)
            else:
                gap_left = max(gap_left, text_x + shot_width + 2)

    if lineup and score is not None:
        _draw_jersey_row(
            draw,
            lineup,
            gap_left,
            gap_right,
            16,
            _ink_on_black(color),
        )

    if goalie or save_pct:
        parts = _meta_parts(
            goalie,
            save_pct,
            max(0, gap_right - gap_left),
            _ink_on_black(color),
        )
        _draw_meta(draw, parts, gap_left, gap_right)

    if score is not None and shots is not None:
        _draw_shots_under_score(draw, shots, text_x, align_right)


def _team_shots(game, is_home):
    value = getattr(game, "home_sog" if is_home else "away_sog", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


GOAL_CELEBRATION_SECONDS = 3.2
_GOAL_TRAVEL_SECONDS = 1.15
_goal_celebrations = {}

ICE = (232, 240, 248)
PUCK_BLACK = (8, 8, 10)
GOAL_POST = (186, 28, 36)
NET_WHITE = (198, 208, 216)
NET_MESH = (126, 138, 150)
SIREN_OFF = (78, 14, 20)
SIREN_ON = (255, 40, 46)


def _goal_celebration(game, now):
    """Play once when a new goal shows up. The goal already on screen is skipped."""
    if is_scheduled(game):
        return None
    now = time.monotonic() if now is None else now
    name = " ".join(str(getattr(game, "last_play_name", "") or "").upper().split())
    is_goal = bool(getattr(game, "last_play_goal", False))
    signature = (
        _safe_int(getattr(game, "away_score", 0)),
        _safe_int(getattr(game, "home_score", 0)),
        name if is_goal else "",
    )
    key = _focus_id(game)
    state = _goal_celebrations.get(key)
    if state is None:
        _goal_celebrations[key] = {"signature": signature, "start": None}
        return None
    if state["signature"] != signature:
        state["signature"] = signature
        state["start"] = now if is_goal else None
    if not is_goal or state.get("start") is None:
        return None
    elapsed = now - state["start"]
    if elapsed < 0 or elapsed >= GOAL_CELEBRATION_SECONDS:
        return None
    return elapsed, name or "GOAL"


def _draw_siren(draw, center, on):
    color = SIREN_ON if on else SIREN_OFF
    top = 9
    for dx in range(-3, 4):
        draw.point((center + dx, top + 3), fill=color)
    for dx in range(-2, 3):
        draw.point((center + dx, top + 2), fill=color)
    for dx in range(-1, 2):
        draw.point((center + dx, top + 1), fill=color)
    draw.point((center, top), fill=color)
    if on:
        draw.point((center - 6, top + 2), fill=SIREN_ON)
        draw.point((center + 6, top + 2), fill=SIREN_ON)
        draw.point((center - 5, top), fill=SIREN_ON)
        draw.point((center + 5, top), fill=SIREN_ON)


def _draw_black_puck(draw, x, y):
    rows = (" ### ", "#####", " ### ")
    for dy, pattern in enumerate(rows):
        for dx, mark in enumerate(pattern):
            if mark == "#":
                draw.point((x + dx, y + dy), fill=PUCK_BLACK)


def _draw_goal_celebration(draw, name, elapsed):
    """Scorer on top, then the puck rides the ice into the net and the lamp lights."""
    left = LEFT_PANEL_RIGHT + 2
    right = RIGHT_PANEL_LEFT - 2
    post_l = 190
    post_r = 242
    cross_y = 15
    base_y = 28
    cx = (post_l + post_r) // 2

    draw.rectangle([left, base_y, right, FOCUS_HEIGHT - 1], fill=ICE)
    draw.rectangle([post_l + 2, cross_y + 2, post_r - 2, base_y - 1], fill=NET_WHITE)
    for x in range(post_l + 4, post_r - 2, 4):
        draw.line([(x, cross_y + 2), (x, base_y - 1)], fill=NET_MESH)
    for y in range(cross_y + 4, base_y, 4):
        draw.line([(post_l + 2, y), (post_r - 2, y)], fill=NET_MESH)
    draw.rectangle([post_l, cross_y, post_r, cross_y + 1], fill=GOAL_POST)
    draw.rectangle([post_l, cross_y, post_l + 1, base_y], fill=GOAL_POST)
    draw.rectangle([post_r - 1, cross_y, post_r, base_y], fill=GOAL_POST)

    travel = _GOAL_TRAVEL_SECONDS
    enter = 0.32
    start_x = left + 2
    mouth_x = post_l - 6
    inside_x = post_l + 8
    if elapsed < travel:
        puck_x = start_x + (mouth_x - start_x) * (elapsed / travel)
    else:
        tucked = min(1.0, (elapsed - travel) / enter)
        puck_x = mouth_x + (inside_x - mouth_x) * tucked
    _draw_black_puck(draw, int(puck_x), base_y - 2)

    arrived = elapsed >= travel
    flashing = arrived and int((elapsed - travel) / 0.16) % 2 == 0
    _draw_siren(draw, cx, flashing)

    who = _fit_gfx(name or "GOAL", CENTER_LIMIT)
    if who:
        print_gfx_5x7_centered(draw, who, FOCUS_WIDTH // 2, 0, YELLOW)


def _draw_center(draw, game, now=None):
    celebration = _goal_celebration(game, now)
    if celebration:
        _draw_goal_celebration(draw, celebration[1], celebration[0])
        return

    cx = FOCUS_WIDTH // 2
    headline, headline_color = _clock_line(game)
    headline = _fit_gfx(headline, CENTER_LIMIT)
    if headline:
        print_gfx_5x7_centered(draw, headline, cx, 1, headline_color)

    if is_shootout(game):
        tally = _so_pair(game)
        if tally is not None:
            print_gfx_5x7_centered(
                draw,
                f"{tally[0]}-{tally[1]}",
                cx,
                12,
                YELLOW,
            )
        return

    if is_intermission(game):
        strength = _fit_gfx(_power_line(game), CENTER_LIMIT)
        if strength:
            print_gfx_5x7_centered(draw, strength, cx, 12, PP_ORANGE)
        else:
            ended = _fit_gfx(_ended_period(game), CENTER_LIMIT)
            if ended:
                print_gfx_5x7_centered(draw, ended, cx, 12, DIM_WHITE)
        return

    if is_final(game):
        return

    strength = _fit_gfx(_power_line(game), CENTER_LIMIT)
    if strength:
        print_gfx_5x7_centered(draw, strength, cx, 12, PP_ORANGE)
        return

    if getattr(game, "empty_net", False):
        print_gfx_5x7_centered(draw, "EMPTY NET", cx, 12, WHITE)
        return

    play = _center_play(game)
    if play:
        color = YELLOW if getattr(game, "last_play_goal", False) else WHITE
        print_gfx_5x7_centered(draw, play, cx, 12, color)


def _draw_scheduled(image, draw, game, settings):
    _draw_team_column(image, draw, game, game.away, False, settings)
    _draw_team_column(image, draw, game, game.home, True, settings)
    cx = FOCUS_WIDTH // 2
    date = str(getattr(game, "date", "") or "").strip()
    if date:
        print_4x5_centered(draw, date, cx, 2, DIM_WHITE)
    start = str(getattr(game, "start_time", "") or "").strip()
    if start:
        print_gfx_5x7_centered(draw, start, cx, 12, WHITE)
    broadcast = str(getattr(game, "broadcast", "") or "").strip()
    if broadcast and not draw_broadcast_logo(image, broadcast, cx, 25, settings):
        print_4x5_centered(draw, broadcast, cx, 24, DIM_WHITE)


def _focus_id(game):
    event_id = str(getattr(game, "event_id", "") or "")
    return "nhl:" + (event_id or f"{game.away}@{game.home}")


def _draw_live_or_final(image, draw, game, settings, now=None):
    away_score = _safe_int(game.away_score)
    home_score = _safe_int(game.home_score)
    final = is_final(game)
    away_color = YELLOW
    home_color = YELLOW
    if final and away_score != home_score:
        if away_score < home_score:
            away_color = LOSING_SCORE
        else:
            home_color = LOSING_SCORE

    playing = not final and not is_scheduled(game)
    show_puck = (
        playing
        and not is_intermission(game)
        and not is_shootout(game)
    )
    show_pp = playing and not is_shootout(game)
    possession = str(getattr(game, "possession", "") or "").upper()
    power_play = str(getattr(game, "power_play", "") or "").upper()
    game_id = _focus_id(game)

    _draw_team_column(
        image,
        draw,
        game,
        game.away,
        False,
        settings,
        score=away_score,
        score_color=away_color,
        show_puck=show_puck and possession == str(game.away).upper(),
        on_pp=show_pp and power_play == str(game.away).upper(),
        goalie=getattr(game, "away_goalie", ""),
        save_pct=getattr(game, "away_save_pct", ""),
        lineup=getattr(game, "away_lineup", ()) if playing else (),
        shots=_team_shots(game, False),
        game_id=game_id,
    )
    _draw_team_column(
        image,
        draw,
        game,
        game.home,
        True,
        settings,
        score=home_score,
        score_color=home_color,
        show_puck=show_puck and possession == str(game.home).upper(),
        on_pp=show_pp and power_play == str(game.home).upper(),
        goalie=getattr(game, "home_goalie", ""),
        save_pct=getattr(game, "home_save_pct", ""),
        lineup=getattr(game, "home_lineup", ()) if playing else (),
        shots=_team_shots(game, True),
        game_id=game_id,
    )
    _draw_center(draw, game, now)


def render_nhl_focus(game, settings, now=None):
    image = Image.new("RGB", (FOCUS_WIDTH, FOCUS_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    if is_scheduled(game):
        _draw_scheduled(image, draw, game, settings)
    else:
        _draw_live_or_final(image, draw, game, settings, now)
    return image
