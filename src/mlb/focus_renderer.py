from PIL import Image, ImageDraw

from common.fonts import (
    get_4x5_width,
    gfx_5x7_width,
    gfx_7x11_width,
    print_4x5,
    print_4x5_centered,
    print_4x5_right,
    print_gfx_5x7,
    print_gfx_5x7_centered,
    print_gfx_7x11,
)
from mlb.colors import WHITE, YELLOW, team_color
from mlb.mlb_renderer import (
    draw_base_diamond,
    draw_inning,
    draw_outs,
    draw_team_logo,
)


FOCUS_WIDTH = 384
FOCUS_HEIGHT = 32
BLACK = (0, 0, 0)
DIM_WHITE = (168, 168, 172)
CENTER_LINE = (32, 32, 36)
ZONE_FILL = (14, 14, 18)
ZONE_LINE = (92, 92, 98)
BALL_COLOR = (150, 150, 156)
FOUL_COLOR = (255, 130, 40)
IN_PLAY_COLOR = WHITE
SPEED_SLOW = (70, 150, 255)
SPEED_HOT = (255, 36, 36)

RAIL_WIDTH = 3
LOGO_SIZE = 30
LEFT_PANEL_RIGHT = 118
RIGHT_PANEL_LEFT = 266

PLATE_WIDTH_FT = 17.0 / 12.0
CHASE_FT = 0.85

PITCH_TYPE_NAMES = {
    "FF": "FOUR-SEAM",
    "FA": "FASTBALL",
    "FT": "TWO-SEAM",
    "SI": "SINKER",
    "FC": "CUTTER",
    "SL": "SLIDER",
    "ST": "SWEEPER",
    "SV": "SLURVE",
    "CH": "CHANGEUP",
    "CU": "CURVE",
    "CS": "CURVE",
    "KC": "KN-CURVE",
    "KN": "KNUCKLE",
    "FS": "SPLITTER",
    "FO": "FORKBALL",
    "SC": "SCREWBALL",
    "EP": "EEPHUS",
}


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


def _is_scheduled(game):
    status = str(getattr(game, "status", "")).strip().lower()
    return status in {"preview", "scheduled", "pre-game", "pregame"}


def _is_final(game):
    status = str(getattr(game, "status", "")).strip().lower()
    return "final" in status


def _last_name(value, max_width):
    name = str(value or "").replace(".", "").upper().strip()
    while name and get_4x5_width(name) > max_width:
        name = name[:-1]
    return name


def _pitch_type_label(pitch, max_width):
    code = str(getattr(pitch, "pitch_type", "") or "").upper().strip()
    label = PITCH_TYPE_NAMES.get(code, "")
    if not label:
        label = str(getattr(pitch, "pitch_name", "") or "").upper().strip()
        label = label.replace(" FASTBALL", "").replace("  ", " ")
    if not label:
        label = code
    while label and get_4x5_width(label) > max_width:
        label = label[:-1]
    return label


def _speed_color(mph):
    stops = (
        (80, SPEED_SLOW),
        (88, (200, 210, 255)),
        (92, WHITE),
        (95, YELLOW),
        (98, FOUL_COLOR),
        (102, SPEED_HOT),
    )
    if mph <= stops[0][0]:
        return stops[0][1]
    for index in range(1, len(stops)):
        low_mph, low_color = stops[index - 1]
        high_mph, high_color = stops[index]
        if mph <= high_mph:
            t = (mph - low_mph) / (high_mph - low_mph)
            return _mix(low_color, high_color, t)
    return stops[-1][1]


def _pitch_color(result):
    if result == "ball":
        return BALL_COLOR
    if result == "foul":
        return FOUL_COLOR
    if result == "in_play":
        return IN_PLAY_COLOR
    return YELLOW


def _draw_side_chrome(draw, team, is_home):
    color = team_color(team)
    fill = _mix(BLACK, color, 0.12)

    if is_home:
        draw.rectangle(
            [RIGHT_PANEL_LEFT, 0, FOCUS_WIDTH - 1, FOCUS_HEIGHT - 1],
            fill=fill,
        )
        draw.rectangle(
            [
                FOCUS_WIDTH - RAIL_WIDTH,
                0,
                FOCUS_WIDTH - 1,
                FOCUS_HEIGHT - 1,
            ],
            fill=color,
        )
        draw.line(
            [(RIGHT_PANEL_LEFT, 0), (RIGHT_PANEL_LEFT, FOCUS_HEIGHT - 1)],
            fill=CENTER_LINE,
        )
        return

    draw.rectangle(
        [0, 0, LEFT_PANEL_RIGHT, FOCUS_HEIGHT - 1],
        fill=fill,
    )
    draw.rectangle(
        [0, 0, RAIL_WIDTH - 1, FOCUS_HEIGHT - 1],
        fill=color,
    )
    draw.line(
        [(LEFT_PANEL_RIGHT, 0), (LEFT_PANEL_RIGHT, FOCUS_HEIGHT - 1)],
        fill=CENTER_LINE,
    )


NAME_STAT_GAP = 4
STAT_COLOR = WHITE
SCORE_Y = 14
PLAYER_Y = 25


def _player_max_width(is_home, score=None, inner_pad=2, gap=3):
    if is_home:
        logo_x = FOCUS_WIDTH - RAIL_WIDTH - inner_pad - LOGO_SIZE
        text_x = RIGHT_PANEL_LEFT + inner_pad
        reserved = 0
        if score is not None:
            reserved = gfx_7x11_width(str(score)) + gap
        return max(0, logo_x - NAME_STAT_GAP - (text_x + reserved))

    logo_x = RAIL_WIDTH + inner_pad
    text_x = LEFT_PANEL_RIGHT - inner_pad
    reserved = 0
    if score is not None:
        reserved = gfx_7x11_width(str(score)) + gap
    return max(0, (text_x - reserved) - NAME_STAT_GAP - (logo_x + LOGO_SIZE + NAME_STAT_GAP))


def _fit_name_stat(name, stat, max_width):
    stat = str(stat or "").strip().upper()
    stat_width = get_4x5_width(stat) if stat else 0
    name_budget = max_width
    if stat_width:
        name_budget = max(0, max_width - stat_width - NAME_STAT_GAP)
    name = _last_name(name, name_budget)
    return name, stat


def _player_for_side(game, is_home, score=None):
    batting_home = not bool(game.top_inning)
    max_width = _player_max_width(is_home, score)
    if is_home == batting_home:
        return _fit_name_stat(
            getattr(game, "batter", ""),
            getattr(game, "batter_stat", ""),
            max_width,
        )

    pitches = _safe_int(getattr(game, "pitcher_pitches", 0))
    return _fit_name_stat(
        getattr(game, "pitcher", ""),
        pitches if pitches > 0 else "",
        max_width,
    )


def _team_record(game, is_home):
    if is_home:
        wins = _safe_int(getattr(game, "home_wins", 0))
        losses = _safe_int(getattr(game, "home_losses", 0))
    else:
        wins = _safe_int(getattr(game, "away_wins", 0))
        losses = _safe_int(getattr(game, "away_losses", 0))
    return f"{wins}-{losses}"


def _draw_team_column(
    image,
    draw,
    game,
    team,
    is_home,
    settings,
    *,
    score=None,
    record=None,
    player=None,
):
    team = str(team).upper()
    color = team_color(team)
    _draw_side_chrome(draw, team, is_home)

    inner_pad = 2

    if is_home:
        logo_x = FOCUS_WIDTH - RAIL_WIDTH - inner_pad - LOGO_SIZE
        text_x = RIGHT_PANEL_LEFT + inner_pad
        align_right = False
    else:
        logo_x = RAIL_WIDTH + inner_pad
        text_x = LEFT_PANEL_RIGHT - inner_pad
        align_right = True

    draw_team_logo(image, team, logo_x, 1, settings)

    if record:
        record_width = get_4x5_width(record)
        if is_home:
            record_x = logo_x - NAME_STAT_GAP - record_width
        else:
            record_x = logo_x + LOGO_SIZE + NAME_STAT_GAP
        print_4x5(draw, record, record_x, 13, DIM_WHITE)

    abbr_width = gfx_5x7_width(team)
    abbr_x = text_x - abbr_width if align_right else text_x
    print_gfx_5x7(draw, team, abbr_x, 2, color)
    draw.line(
        [(abbr_x, 10), (abbr_x + abbr_width - 1, 10)],
        fill=_mix(BLACK, color, 0.72),
    )

    if score is not None:
        text = str(score)
        score_width = gfx_7x11_width(text)
        score_x = text_x - score_width if align_right else text_x
        print_gfx_7x11(draw, text, score_x, SCORE_Y, YELLOW)

    if player:
        name, stat = player
        name_width = get_4x5_width(name) if name else 0
        stat_width = get_4x5_width(stat) if stat else 0
        gap = NAME_STAT_GAP if name and stat else 0
        total_width = name_width + gap + stat_width
        if align_right:
            start_x = logo_x + LOGO_SIZE + NAME_STAT_GAP
        else:
            start_x = logo_x - NAME_STAT_GAP - total_width
        if name:
            print_4x5(draw, name, start_x, PLAYER_Y, DIM_WHITE)
        if stat:
            print_4x5(
                draw,
                stat,
                start_x + name_width + gap,
                PLAYER_Y,
                STAT_COLOR,
            )


def _draw_bases(draw, game, cx, size=8):
    draw_base_diamond(draw, cx - 12, 21, bool(game.third), size=size)
    draw_base_diamond(draw, cx + 12, 21, bool(game.first), size=size)
    draw_base_diamond(draw, cx, 9, bool(game.second), size=size)


def _draw_situation(draw, game, cx):
    balls = max(0, min(4, _safe_int(getattr(game, "balls", 0))))
    strikes = max(0, min(3, _safe_int(getattr(game, "strikes", 0))))
    count = f"{balls}-{strikes}"
    print_4x5_centered(draw, count, cx, 4, YELLOW)
    draw_inning(
        draw,
        cx - 5,
        14,
        _safe_int(game.inning),
        bool(game.top_inning),
        YELLOW,
    )
    draw_outs(draw, cx - 6, 24, _safe_int(game.outs))


def _draw_strike_zone(draw, game, left, top, box_w=21, box_h=26):
    right = left + box_w - 1
    bottom = top + box_h - 1
    pitches = list(getattr(game, "pitches", ()) or ())
    zone_top = float(getattr(game, "strike_zone_top", 3.5) or 3.5)
    zone_bottom = float(getattr(game, "strike_zone_bottom", 1.5) or 1.5)

    if pitches:
        zone_top = float(pitches[-1].strike_zone_top or zone_top)
        zone_bottom = float(pitches[-1].strike_zone_bottom or zone_bottom)

    xmin = -PLATE_WIDTH_FT / 2 - CHASE_FT
    xmax = PLATE_WIDTH_FT / 2 + CHASE_FT
    zmin = zone_bottom - CHASE_FT
    zmax = zone_top + CHASE_FT
    if zmax <= zmin:
        zmin = 1.0
        zmax = 4.0

    def _map_point(px, pz):
        # Mirror Statcast pX so the board matches the
        # camera: outside-right pitches sit on the right.
        px = -float(px)
        px = max(xmin, min(xmax, px))
        pz = max(zmin, min(zmax, float(pz)))
        x = left + int(round((px - xmin) / (xmax - xmin) * (box_w - 1)))
        y = bottom - int(round((pz - zmin) / (zmax - zmin) * (box_h - 1)))
        return x, y

    inner_x1, inner_y1 = _map_point(-PLATE_WIDTH_FT / 2, zone_top)
    inner_x2, inner_y2 = _map_point(PLATE_WIDTH_FT / 2, zone_bottom)
    inner_left = min(inner_x1, inner_x2)
    inner_right = max(inner_x1, inner_x2)
    inner_top = min(inner_y1, inner_y2)
    inner_bottom = max(inner_y1, inner_y2)

    draw.rectangle([left, top, right, bottom], fill=ZONE_FILL)
    draw.rectangle(
        [inner_left, inner_top, inner_right, inner_bottom],
        outline=ZONE_LINE,
    )
    plate_cx = (inner_left + inner_right) // 2
    draw.line(
        [(plate_cx - 2, inner_bottom), (plate_cx + 2, inner_bottom)],
        fill=WHITE,
    )

    for index, pitch in enumerate(pitches):
        x, y = _map_point(pitch.px, pitch.pz)
        color = _pitch_color(pitch.result)
        latest = index == len(pitches) - 1
        if latest:
            draw.rectangle([x - 1, y - 1, x + 1, y + 1], fill=color)
            draw.point((x, y), fill=WHITE)
        else:
            draw.rectangle([x, y, x + 1, y + 1], fill=color)

    return box_w


def _draw_latest_pitch(draw, game, right_x, max_width=50):
    pitches = list(getattr(game, "pitches", ()) or ())
    if not pitches:
        return

    pitch = pitches[-1]
    try:
        speed = int(round(float(getattr(pitch, "speed", 0) or 0)))
    except (TypeError, ValueError):
        speed = 0
    ptype = _pitch_type_label(pitch, max_width)

    if speed > 0:
        speed_text = str(speed)
        unit = "MPH"
        speed_width = get_4x5_width(speed_text)
        unit_width = get_4x5_width(unit)
        gap = 2
        start_x = right_x - (speed_width + gap + unit_width)
        print_4x5(draw, speed_text, start_x, 8, _speed_color(speed))
        print_4x5(
            draw,
            unit,
            start_x + speed_width + gap,
            8,
            DIM_WHITE,
        )
    if ptype:
        print_4x5_right(draw, ptype, right_x, 16, DIM_WHITE)


def _draw_scheduled(image, draw, game, settings):
    away = str(game.away).upper()
    home = str(game.home).upper()

    _draw_team_column(
        image,
        draw,
        game,
        away,
        False,
        settings,
        record=_team_record(game, False),
    )
    _draw_team_column(
        image,
        draw,
        game,
        home,
        True,
        settings,
        record=_team_record(game, True),
    )

    start_time = str(getattr(game, "start_time", "") or "").strip()
    if start_time:
        print_gfx_5x7_centered(draw, start_time, FOCUS_WIDTH // 2, 12, YELLOW)


def _draw_final(image, draw, game, settings):
    _draw_team_column(
        image,
        draw,
        game,
        game.away,
        False,
        settings,
        score=_safe_int(game.away_score),
        record=_team_record(game, False),
    )
    _draw_team_column(
        image,
        draw,
        game,
        game.home,
        True,
        settings,
        score=_safe_int(game.home_score),
        record=_team_record(game, True),
    )
    print_gfx_5x7_centered(draw, "FINAL", FOCUS_WIDTH // 2, 12, WHITE)


def _draw_live(image, draw, game, settings):
    _draw_team_column(
        image,
        draw,
        game,
        game.away,
        False,
        settings,
        score=_safe_int(game.away_score),
        record=_team_record(game, False),
        player=_player_for_side(
            game,
            False,
            _safe_int(game.away_score),
        ),
    )
    _draw_team_column(
        image,
        draw,
        game,
        game.home,
        True,
        settings,
        score=_safe_int(game.home_score),
        record=_team_record(game, True),
        player=_player_for_side(
            game,
            True,
            _safe_int(game.home_score),
        ),
    )

    center_left = LEFT_PANEL_RIGHT + 1
    center_right = RIGHT_PANEL_LEFT - 1
    zone_w = 21
    pitch_w = 50
    pitch_gap = 2
    situation_w = 14
    bases_w = 40
    cluster_gap = 10
    content_w = (
        pitch_w
        + pitch_gap
        + zone_w
        + situation_w
        + bases_w
        + cluster_gap * 2
    )
    span = center_right - center_left + 1
    group_left = center_left + max(0, (span - content_w) // 2)
    zone_left = group_left + pitch_w + pitch_gap
    situation_cx = zone_left + zone_w + cluster_gap + situation_w // 2
    bases_cx = (
        zone_left
        + zone_w
        + cluster_gap
        + situation_w
        + cluster_gap
        + bases_w // 2
        - 6
    )

    _draw_latest_pitch(draw, game, zone_left - pitch_gap - 1, pitch_w)
    _draw_strike_zone(draw, game, zone_left, 3, box_w=zone_w)
    _draw_situation(draw, game, situation_cx)
    _draw_bases(draw, game, bases_cx)


def render_mlb_focus(game, settings):
    image = Image.new("RGB", (FOCUS_WIDTH, FOCUS_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)

    if _is_scheduled(game):
        _draw_scheduled(image, draw, game, settings)
        return image

    if _is_final(game):
        _draw_final(image, draw, game, settings)
        return image

    _draw_live(image, draw, game, settings)
    return image
