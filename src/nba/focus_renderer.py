from PIL import Image, ImageDraw

from common.broadcast import draw_broadcast_logo
from common.football_focus import (
    SCORE_SLIDE,
    _draw_score_glyphs,
    _draw_score_slide,
    _score_slide_state,
)
from common.fonts import (
    get_3x5_width,
    get_4x5_width,
    gfx_5x7_width,
    print_3x5,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    print_gfx_5x7_centered,
)
from common.settings import get_developer_settings
from nba.colors import team_color
from nba.nba_renderer import draw_team_logo, final_label, is_final, is_halftime, is_scheduled, quarter_label


FOCUS_WIDTH = 384
FOCUS_HEIGHT = 32
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
DIM_WHITE = (168, 168, 172)
CENTER_LINE = (32, 32, 36)
CLOCK_AMBER = (255, 214, 70)
LOSING_SCORE = (118, 108, 48)
BONUS_ORANGE = (255, 130, 40)
BONUS_OFF = (96, 96, 102)
BALL_ORANGE = (230, 108, 20)
BALL_SEAM = (118, 40, 10)
BALL_LIGHT = (255, 206, 120)
BALL_SHADE = (176, 72, 12)

RAIL_WIDTH = 3
LOGO_SIZE = 30
LEFT_PANEL_RIGHT = 127
RIGHT_PANEL_LEFT = 256
CENTER_LIMIT = 118
SCORE_Y = 12

TIMEOUT_PIP_W = 4
TIMEOUT_PIP_H = 4
TIMEOUT_PIP_GAP = 2
TIMEOUT_MAX = 7
STATUS_Y = 24
BALL_SIZE = 9


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


def _last_name(value):
    parts = str(value or "").replace(".", " ").upper().split()
    return parts[-1] if parts else ""


def play_line(text, kind, athlete):
    """Short center label for one ESPN play description."""
    kind_u = str(kind or "").upper()
    text_l = str(text or "").lower()
    name = _last_name(athlete)

    if "TIMEOUT" in kind_u or "timeout" in text_l:
        return "TIMEOUT"
    if "CHALLENGE" in kind_u or "challenge" in text_l:
        return "CHALLENGE"
    if "FOUL" in kind_u or "foul" in text_l:
        return f"{name} FOUL".strip()
    if "FREE THROW" in kind_u or "free throw" in text_l:
        made = "make" in text_l
        missed = "miss" in text_l
        mark = "FT" if made or not missed else "FT MISS"
        return f"{name} {mark}".strip()
    if "three" in text_l:
        verb = "3PT" if "make" in text_l else "MISS 3"
        return f"{name} {verb}".strip()
    if "make" in text_l or "made" in text_l:
        return f"{name} MAKE".strip()
    if "miss" in text_l:
        return f"{name} MISS".strip()
    if "rebound" in text_l:
        return f"{name} REB".strip()
    if "steal" in text_l:
        return f"{name} STL".strip()
    if "turnover" in text_l:
        return f"{name} TO".strip()
    if "block" in text_l:
        return f"{name} BLK".strip()
    return name


def _fit_gfx(text, max_width):
    text = str(text or "").upper().strip()
    while text and gfx_5x7_width(text) > max_width:
        text = text[:-1].rstrip()
    return text


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


def _timeout_width():
    return TIMEOUT_MAX * TIMEOUT_PIP_W + (TIMEOUT_MAX - 1) * TIMEOUT_PIP_GAP


def _draw_timeouts(draw, x, y, remaining):
    remaining = max(0, min(TIMEOUT_MAX, _safe_int(remaining, 0)))
    step = TIMEOUT_PIP_W + TIMEOUT_PIP_GAP
    for index in range(TIMEOUT_MAX):
        bx = x + index * step
        box = [bx, y, bx + TIMEOUT_PIP_W - 1, y + TIMEOUT_PIP_H - 1]
        if index < remaining:
            draw.rectangle(box, fill=WHITE)
        else:
            draw.rectangle(box, outline=(78, 78, 84))


def _draw_basketball(draw, x, y):
    """Round 9px ball. Seams stay one pixel wide so the silhouette holds."""
    rows = (
        "  #*###  ",
        " ###+### ",
        "#+##+##+#",
        "#+##+##+#",
        "#+##+##+#",
        "#+##+##+#",
        "#+##+##+#",
        " ###+#o# ",
        "  #####  ",
    )
    fills = {
        "#": BALL_ORANGE,
        "+": BALL_SEAM,
        "*": BALL_LIGHT,
        "o": BALL_SHADE,
    }
    for row, pattern in enumerate(rows):
        for col, mark in enumerate(pattern):
            color = fills.get(mark)
            if color:
                draw.point((x + col, y + row), fill=color)


def _team_in_bonus(game, team, is_home):
    if str(getattr(game, "bonus", "") or "").upper() == team:
        return True
    flag = "home_in_bonus" if is_home else "away_in_bonus"
    return bool(getattr(game, flag, False))


def _draw_status_row(draw, text_x, *, align_right, timeouts, in_bonus):
    label = "BONUS"
    label_w = get_4x5_width(label)
    label_color = BONUS_ORANGE if in_bonus else BONUS_OFF
    gap = 4
    pip_y = STATUS_Y + 1
    if timeouts is None:
        label_x = text_x - label_w if align_right else text_x
        print_4x5(draw, label, label_x, STATUS_Y, label_color)
        return

    pip_w = _timeout_width()
    if align_right:
        pip_x = text_x - pip_w
        label_x = pip_x - gap - label_w
    else:
        pip_x = text_x
        label_x = pip_x + pip_w + gap
    _draw_timeouts(draw, pip_x, pip_y, timeouts)
    print_4x5(draw, label, label_x, STATUS_Y, label_color)


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
    show_possession=False,
    show_status=False,
    in_bonus=False,
    timeouts=None,
    game_id="",
):
    team = str(team).upper()
    color = team_color(team)
    _draw_side_chrome(draw, team, is_home)
    logo_x, text_x, align_right = _anchors(is_home)
    draw_team_logo(image, team, logo_x, 1, settings)

    record = (
        f"{_safe_int(game.home_wins)}-{_safe_int(game.home_losses)}"
        if is_home
        else f"{_safe_int(game.away_wins)}-{_safe_int(game.away_losses)}"
    )
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

    if show_possession:
        if align_right:
            _draw_basketball(draw, abbr_x - 2 - BALL_SIZE, 1)
        else:
            _draw_basketball(draw, abbr_x + abbr_width + 2, 1)

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

    if show_status:
        _draw_status_row(
            draw,
            text_x,
            align_right=align_right,
            timeouts=timeouts,
            in_bonus=in_bonus,
        )


def _period_text(game):
    if is_halftime(game):
        return "HALFTIME"
    label = quarter_label(game)
    clock = str(getattr(game, "clock", "") or "").strip()
    if is_final(game):
        return final_label(game)
    if label and clock:
        return f"{label} {clock}"
    return label or clock


def _quarter_text(values):
    numbers = [str(_safe_int(value)) for value in values or ()]
    while len(numbers) > 1 and get_3x5_width(" ".join(numbers)) > CENTER_LIMIT:
        numbers = numbers[1:]
    return " ".join(numbers)


def _draw_quarter_rows(draw, game, y):
    away = _quarter_text(getattr(game, "away_quarters", ()))
    home = _quarter_text(getattr(game, "home_quarters", ()))
    if not away and not home:
        return
    cx = FOCUS_WIDTH // 2
    if away:
        width = get_3x5_width(away)
        print_3x5(draw, away, cx - width // 2, y, team_color(game.away))
    if home:
        width = get_3x5_width(home)
        print_3x5(draw, home, cx - width // 2, y + 6, team_color(game.home))


def _draw_scheduled(image, draw, game, settings):
    _draw_team_column(
        image, draw, game, game.away, False, settings,
    )
    _draw_team_column(
        image, draw, game, game.home, True, settings,
    )
    cx = FOCUS_WIDTH // 2
    date = str(getattr(game, "date", "") or "").strip()
    if date:
        print_4x5_centered(draw, date, cx, 2, DIM_WHITE)
    start = str(getattr(game, "start_time", "") or "").strip()
    if start:
        print_gfx_5x7_centered(draw, start, cx, 11, WHITE)
    broadcast = str(getattr(game, "broadcast", "") or "").strip()
    if broadcast and not draw_broadcast_logo(image, broadcast, cx, 25, settings):
        print_4x5_centered(draw, broadcast, cx, 24, DIM_WHITE)


def _draw_live_or_final(image, draw, game, settings):
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

    possession = str(getattr(game, "possession", "") or "").upper()
    live = not final and not is_scheduled(game)
    game_id = "nba:" + (
        str(getattr(game, "event_id", "") or "")
        or f"{game.away}@{game.home}"
    )
    _draw_team_column(
        image,
        draw,
        game,
        game.away,
        False,
        settings,
        score=away_score,
        score_color=away_color,
        show_possession=live and possession == str(game.away).upper(),
        show_status=live,
        in_bonus=_team_in_bonus(game, str(game.away).upper(), False),
        timeouts=getattr(game, "away_timeouts", None) if live else None,
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
        show_possession=live and possession == str(game.home).upper(),
        show_status=live,
        in_bonus=_team_in_bonus(game, str(game.home).upper(), True),
        timeouts=getattr(game, "home_timeouts", None) if live else None,
        game_id=game_id,
    )

    cx = FOCUS_WIDTH // 2
    period = _period_text(game)
    if period:
        color = WHITE if final or is_halftime(game) else CLOCK_AMBER
        print_gfx_5x7_centered(draw, _fit_gfx(period, CENTER_LIMIT), cx, 1, color)

    if live and not is_halftime(game):
        label = play_line(
            getattr(game, "last_play_text", ""),
            getattr(game, "last_play_type", ""),
            getattr(game, "last_play_athlete", ""),
        )
        label = _fit_gfx(label, CENTER_LIMIT)
        if label:
            play_color = YELLOW if _safe_int(getattr(game, "last_play_points", 0)) > 0 else WHITE
            print_gfx_5x7_centered(draw, label, cx, 10, play_color)

    quarter_y = 12 if final or is_halftime(game) else 20
    _draw_quarter_rows(draw, game, quarter_y)


def render_nba_focus(game, settings):
    image = Image.new("RGB", (FOCUS_WIDTH, FOCUS_HEIGHT), BLACK)
    draw = ImageDraw.Draw(image)
    if is_scheduled(game):
        _draw_scheduled(image, draw, game, settings)
    else:
        _draw_live_or_final(image, draw, game, settings)
    return image
