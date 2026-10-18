from mlb.colors import YELLOW, WHITE, GREY, RED, team_color
from common.broadcast import draw_broadcast_logo
from common.logo_store import draw_logo, get_selected_logo_variant
from common.fonts import (
    print_3x5,
    get_3x5_width,
    print_3x5_right,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    draw_text_right,
    gfx_5x7_width,
)

LOGO_SIZE = 30
CARD_WIDTH = 64

PAD_CX = 32
NAME_Y = 2
CLOCK_Y = 10
SCORE_Y = 18
RECORD_Y = 22


def _status(game):
    return str(game.status or "").strip().upper()


def is_scheduled(game):
    return _status(game) in {
        "PREVIEW",
        "SCHEDULED",
        "PRE",
        "PRE-GAME",
        "PREGAME",
        "WARMUP",
    }


def is_final(game):
    status = _status(game)
    return (
        "FINAL" in status
        or status in {"GAME OVER", "COMPLETED EARLY"}
    )


def final_label(game):
    try:
        inning = int(game.inning or 0)
    except (TypeError, ValueError):
        inning = 0
    if inning > 9:
        return f"F-{inning}"
    return "FINAL"


def draw_base_diamond(draw, cx, cy, occupied, size=5):
    color = WHITE if occupied else GREY
    points = [
        (cx, cy - size),
        (cx + size, cy),
        (cx, cy + size),
        (cx - size, cy),
    ]

    if occupied:
        draw.polygon(points, fill=color)
    else:
        draw.line(points + [points[0]], fill=color)

def draw_outs(draw, x, y, outs):
    for i in range(3):
        cx = x + i * 5
        box = (cx, y, cx + 2, y + 2)

        if i < outs:
            draw.rectangle(box, fill=RED)
        else:
            draw.rectangle(box, outline=(70, 70, 70))

def draw_inning(draw, x, y, inning, top, color):
    if inning > 9:
        if top:
            draw.polygon([(x - 1, y), (x - 1, y + 2), (x, y + 2)], fill=color)
        else:
            draw.polygon([(x - 2, y), (x, y), (x - 1, y + 2)], fill=color)

        number_x = x + 2
    else:
        if top:
            draw.polygon([(x + 1, y), (x, y + 2), (x + 2, y + 2)], fill=color)
        else:
            draw.polygon([(x, y), (x + 2, y), (x + 1, y + 2)], fill=color)

        number_x = x + 4

    print_4x5(draw, inning, number_x, y, color)

def draw_team_logo(
    image,
    team_abbreviation,
    x_start,
    y_start,
    settings,
):
    variant = get_selected_logo_variant(
        settings,
        "mlb",
        team_abbreviation,
    )

    return draw_logo(
        destination=image,
        league="mlb",
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
        variant=variant,
    )

def _draw_pregame(image, draw, game, offset_x, settings):
    time_text = str(game.start_time or "")
    time_width = get_3x5_width(time_text)
    print_3x5(
        draw,
        time_text,
        (CARD_WIDTH - time_width) // 2 + offset_x,
        NAME_Y,
        YELLOW,
    )
    if game.date:
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
        draw_broadcast_logo(image, game.broadcast, 31 + offset_x, 24, settings)


def _draw_scores(draw, game, offset_x, y):
    away = str(game.away_score)
    home = str(game.home_score)
    print_gfx_5x7(draw, away, 2 + offset_x, y, YELLOW)
    print_gfx_5x7(
        draw,
        home,
        CARD_WIDTH - 2 - gfx_5x7_width(home) + offset_x,
        y,
        YELLOW,
    )


def render_baseball_game_onto(image, draw, game, offset_x, settings):
    print_gfx_5x7(draw, game.away, 3 + offset_x, NAME_Y, team_color(game.away))
    print_gfx_5x7(draw, game.home, 44 + offset_x, NAME_Y, team_color(game.home))

    if is_scheduled(game):
        _draw_pregame(image, draw, game, offset_x, settings)
        return

    if is_final(game):
        print_4x5_centered(
            draw,
            final_label(game),
            PAD_CX + offset_x,
            CLOCK_Y,
            YELLOW,
        )
        _draw_scores(draw, game, offset_x, SCORE_Y)
        return

    draw_inning(draw, 27 + offset_x, 19, game.inning, game.top_inning, YELLOW)

    draw_base_diamond(draw, 24 + offset_x, 14, game.third)
    draw_base_diamond(draw, 38 + offset_x, 14, game.first)
    draw_base_diamond(draw, 31 + offset_x, 7, game.second)

    if game.away_score < 10:
        print_gfx_5x7(draw, str(game.away_score), 9 + offset_x, 13, YELLOW)
    else:
        print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 13, YELLOW)

    if game.home_score < 10:
        draw_text_right(draw, game.home_score, 55 + offset_x, 13, YELLOW)
    else:
        draw_text_right(draw, game.home_score, 60 + offset_x, 13, YELLOW)

    draw_outs(draw, 25 + offset_x, 26, game.outs)

    print_3x5(draw, f"{game.away_wins}-{game.away_losses}", 2 + offset_x, 25, GREY)
    print_3x5_right(draw, f"{game.home_wins}-{game.home_losses}", 60 + offset_x, 25, GREY)

def render_game_strip_onto(image, draw, game, offset_x, settings):
    # away logo
    draw_team_logo(image, game.away, offset_x, 1, settings)

    # score card
    render_baseball_game_onto(image, draw, game, offset_x + LOGO_SIZE, settings)

    # home logo
    draw_team_logo(image, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1, settings)