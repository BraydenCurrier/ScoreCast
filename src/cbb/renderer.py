from common.broadcast import draw_broadcast_logo
from common.fonts import (
    get_3x5_width,
    gfx_5x7_width,
    print_3x5,
    print_3x5_right,
    print_4x5,
    print_4x5_centered,
    print_4x5_right,
    print_clock,
    print_gfx_5x7,
)
from common.logo_store import draw_logo, get_selected_logo_variant

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)
ORANGE = (255, 130, 40)

LOGO_SIZE = 30
CARD_WIDTH = 88
CARD_STRIP = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE

PAD_CX = CARD_WIDTH // 2
NAME_Y = 2
CLOCK_Y = 10
SCORE_Y = 18
PIP_Y = 28
RECORD_Y = 22

TIMEOUT_PIP_W = 3
TIMEOUT_PIP_H = 2
TIMEOUT_PIP_GAP = 1
TIMEOUT_MAX = 4


def _status(game):
    return str(game.status or "").strip().upper()


def is_scheduled(game):
    return _status(game) in {"SCHEDULED", "PRE", "PREVIEW", "STATUS_SCHEDULED"}


def is_halftime(game):
    return "HALFTIME" in _status(game) or "HALF-TIME" in _status(game)


def is_final(game):
    return "FINAL" in _status(game)


def quarter_label(game):
    quarter = int(game.quarter or 0)
    if quarter >= 6:
        return f"{quarter - 4}OT"
    if quarter == 5:
        return "OT"
    if quarter >= 1:
        return f"Q{quarter}"
    return ""


def final_label(game):
    if int(game.quarter or 0) >= 5:
        return "F-OT"
    return "FINAL"


def draw_team_logo(image, team_abbreviation, x_start, y_start, settings):
    """College basketball logo, then the school's football logo."""
    for league in ("cbb", "cfb"):
        variant = get_selected_logo_variant(settings, league, team_abbreviation)
        if draw_logo(
            destination=image,
            league=league,
            identifier=team_abbreviation,
            x=x_start,
            y=y_start,
            variant=variant,
        ):
            return True
    return False


def _draw_scores(draw, game, offset_x):
    away = str(game.away_score)
    home = str(game.home_score)
    print_gfx_5x7(draw, away, 2 + offset_x, SCORE_Y, YELLOW)
    print_gfx_5x7(
        draw,
        home,
        CARD_WIDTH - 2 - gfx_5x7_width(home) + offset_x,
        SCORE_Y,
        YELLOW,
    )


def _timeout_cluster_width(count):
    if count <= 0:
        return 0
    return count * TIMEOUT_PIP_W + (count - 1) * TIMEOUT_PIP_GAP


def _draw_timeouts(draw, x, y, remaining, *, align="left"):
    if remaining is None:
        return
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        return
    remaining = max(0, min(TIMEOUT_MAX, remaining))
    width = _timeout_cluster_width(TIMEOUT_MAX)
    start_x = x - width if align == "right" else x
    step = TIMEOUT_PIP_W + TIMEOUT_PIP_GAP
    used = (70, 70, 70)
    for index in range(TIMEOUT_MAX):
        bx = start_x + index * step
        box = [bx, y, bx + TIMEOUT_PIP_W - 1, y + TIMEOUT_PIP_H - 1]
        if index < remaining:
            draw.rectangle(box, fill=WHITE)
        else:
            draw.rectangle(box, outline=used)


def _draw_live_marks(draw, game, offset_x):
    bonus = str(game.bonus or "").upper()

    if bonus == str(game.away).upper():
        print_4x5(draw, "BN", 2 + offset_x, CLOCK_Y, ORANGE)

    if bonus == str(game.home).upper():
        print_4x5_right(
            draw,
            "BN",
            CARD_WIDTH - 2 + offset_x,
            CLOCK_Y,
            ORANGE,
        )

    _draw_timeouts(
        draw,
        2 + offset_x,
        PIP_Y,
        game.away_timeouts,
        align="left",
    )
    _draw_timeouts(
        draw,
        CARD_WIDTH - 2 + offset_x,
        PIP_Y,
        game.home_timeouts,
        align="right",
    )


def _draw_pregame(image, draw, game, offset_x, settings):
    time_width = get_3x5_width(game.start_time)
    print_3x5(
        draw,
        game.start_time,
        (CARD_WIDTH - time_width) // 2 + offset_x,
        NAME_Y,
        YELLOW,
    )
    print_4x5_centered(draw, game.date, PAD_CX + offset_x, 11, WHITE)
    print_3x5(
        draw,
        f"{int(game.away_wins or 0)}-{int(game.away_losses or 0)}",
        2 + offset_x,
        RECORD_Y,
        GREY,
    )
    print_3x5_right(
        draw,
        f"{int(game.home_wins or 0)}-{int(game.home_losses or 0)}",
        CARD_WIDTH - 2 + offset_x,
        RECORD_Y,
        GREY,
    )
    if game.broadcast:
        draw_broadcast_logo(image, game.broadcast, PAD_CX + offset_x, 24, settings)


def render_game_strip_onto(image, draw, game, offset_x, settings):
    draw_team_logo(image, game.away, offset_x, 1, settings)
    text_x = offset_x + LOGO_SIZE
    print_gfx_5x7(draw, game.away, 2 + text_x, NAME_Y, WHITE)
    print_gfx_5x7(
        draw,
        game.home,
        CARD_WIDTH - 2 - gfx_5x7_width(game.home) + text_x,
        NAME_Y,
        WHITE,
    )

    if is_scheduled(game):
        _draw_pregame(image, draw, game, text_x, settings)
    else:
        _draw_scores(draw, game, text_x)
        if is_final(game):
            print_4x5_centered(
                draw,
                final_label(game),
                PAD_CX + text_x,
                CLOCK_Y,
                YELLOW,
            )
        elif is_halftime(game):
            print_4x5_centered(draw, "HT", PAD_CX + text_x, CLOCK_Y, YELLOW)
        else:
            label = quarter_label(game)
            if label:
                print_4x5_centered(draw, label, PAD_CX + text_x, NAME_Y, YELLOW)
            if game.clock:
                print_clock(draw, game.clock, PAD_CX + text_x, CLOCK_Y, YELLOW)
            _draw_live_marks(draw, game, text_x)

    draw_team_logo(
        image,
        game.home,
        offset_x + LOGO_SIZE + CARD_WIDTH,
        1,
        settings,
    )
