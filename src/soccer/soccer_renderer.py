from common.fonts import (
    get_3x5_width,
    get_4x5_width,
    print_3x5,
    print_3x5_right,
    print_4x5,
    print_4x5_centered,
    print_gfx_5x7,
    draw_text_right,
)
from common.logo_store import (
    draw_logo,
    get_selected_logo_variant,
    load_logo,
)

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)

LOGO_SIZE = 30
CARD_WIDTH = 64
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE


def is_live(game):
    return game.status.upper() in {
        "LIVE",
        "HALFTIME",
        "EXTRA TIME",
        "PENALTIES",
    }


def is_final(game):
    return game.status.upper() == "FINAL"


def is_scheduled(game):
    return game.status.upper() == "SCHEDULED"


def period_label(game):
    status = game.status.upper()

    if status == "HALFTIME":
        return "HT"
    if status == "EXTRA TIME":
        return "ET"
    if status == "PENALTIES":
        return "PK"
    if status == "FINAL":
        return "FT"
    if status == "LIVE":
        if game.period <= 1:
            return "1H"
        if game.period == 2:
            return "2H"
        return "ET"

    return ""


def draw_team_name(draw, text, x, y, color, right=False):
    text = str(text or "").upper()

    if len(text) <= 3:
        if right:
            draw_text_right(draw, text, x, y, color)
        else:
            print_gfx_5x7(draw, text, x, y, color)
        return

    width = get_4x5_width(text)

    if right:
        print_4x5(draw, text, x - width, y + 1, color)
    else:
        print_4x5(draw, text, x, y + 1, color)


def draw_team_logo(image, team_abbreviation, x_start, y_start, settings):
    variant = get_selected_logo_variant(
        settings,
        "soccer",
        team_abbreviation,
    )

    return draw_logo(
        destination=image,
        league="soccer",
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
        variant=variant,
    )


def draw_broadcast_logo(image, broadcast, x, y, settings):
    if not broadcast:
        return False

    identifier = str(broadcast).split(",")[0].strip()
    identifier = identifier.replace("+", "_PLUS")
    identifier = identifier.replace(" ", "_")

    if not identifier:
        return False

    variant = get_selected_logo_variant(
        settings,
        "broadcast",
        identifier,
    )

    try:
        logo = load_logo(
            league="broadcast",
            identifier=identifier,
            variant=variant,
        )
    except (
        FileNotFoundError,
        ValueError,
        OSError,
    ):
        return False

    return draw_logo(
        destination=image,
        league="broadcast",
        identifier=identifier,
        x=x - logo.width // 2,
        y=y - logo.height // 2,
        variant=variant,
    )


def render_soccer_game_onto(image, draw, game, offset_x, settings):
    draw_team_name(
        draw,
        game.away,
        3 + offset_x,
        2,
        WHITE,
    )
    draw_team_name(
        draw,
        game.home,
        61 + offset_x,
        2,
        WHITE,
        right=True,
    )

    if is_scheduled(game):
        width = get_3x5_width(game.start_time)
        centered_x = (64 - width) // 2
        print_3x5(
            draw,
            game.start_time,
            centered_x + offset_x,
            2,
            YELLOW,
        )
        print_4x5_centered(
            draw,
            game.date,
            32 + offset_x,
            11,
            WHITE,
        )

        print_3x5(
            draw,
            f"{game.away_wins}-{game.away_draws}-{game.away_losses}",
            2 + offset_x,
            22,
            GREY,
        )
        print_3x5_right(
            draw,
            f"{game.home_wins}-{game.home_draws}-{game.home_losses}",
            60 + offset_x,
            22,
            GREY,
        )

        if game.broadcast:
            drew_logo = draw_broadcast_logo(
                image,
                game.broadcast,
                31 + offset_x,
                24,
                settings,
            )
            if not drew_logo and game.league_short:
                print_4x5_centered(
                    draw,
                    game.league_short,
                    32 + offset_x,
                    22,
                    GREY,
                )
        elif game.league_short:
            print_4x5_centered(
                draw,
                game.league_short,
                32 + offset_x,
                22,
                GREY,
            )
        return

    print_4x5_centered(
        draw,
        period_label(game),
        32 + offset_x,
        2,
        YELLOW,
    )

    if game.away_score < 10:
        print_gfx_5x7(
            draw,
            str(game.away_score),
            9 + offset_x,
            13,
            YELLOW,
        )
    else:
        print_gfx_5x7(
            draw,
            str(game.away_score),
            5 + offset_x,
            13,
            YELLOW,
        )

    if game.home_score < 10:
        draw_text_right(
            draw,
            game.home_score,
            55 + offset_x,
            13,
            YELLOW,
        )
    else:
        draw_text_right(
            draw,
            game.home_score,
            60 + offset_x,
            13,
            YELLOW,
        )

    if is_final(game):
        return

    if game.status.upper() == "HALFTIME":
        print_4x5_centered(
            draw,
            "HT",
            32 + offset_x,
            22,
            YELLOW,
        )
        return

    if game.clock:
        print_4x5_centered(
            draw,
            game.clock,
            32 + offset_x,
            22,
            YELLOW,
        )


def render_game_strip_onto(image, draw, game, offset_x, settings):
    draw_team_logo(image, game.away, offset_x, 1, settings)
    render_soccer_game_onto(
        image,
        draw,
        game,
        offset_x + LOGO_SIZE,
        settings,
    )
    draw_team_logo(
        image,
        game.home,
        offset_x + LOGO_SIZE + CARD_WIDTH,
        1,
        settings,
    )
