from common.fonts import (
    get_3x5_width,
    get_4x5_width,
    gfx_5x7_width,
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
)

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)

LOGO_SIZE = 30
CARD_WIDTH = 64
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE

NAME_LEFT_X = 2
NAME_RIGHT_X = 62
PAD_CENTER_X = 32
RECORD_Y = 26
LEAGUE_Y = 17
DATE_Y = 9
TIME_Y = 2
NAME_Y = 2
SCORE_Y = 13
STATUS_Y = 2
CLOCK_Y = 22


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


def _team_name_width(text):
    text = str(text or "").upper()

    if len(text) <= 3:
        return gfx_5x7_width(text)

    return get_4x5_width(text)


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


def _record_text(wins, draws, losses):
    return f"{int(wins or 0)}-{int(draws or 0)}-{int(losses or 0)}"


def _draw_centered_if_fits(
    draw,
    text,
    center_x,
    y,
    color,
    width_fn,
    left_limit,
    right_limit,
):
    text = str(text or "").strip()
    if not text:
        return False

    width = width_fn(text)
    start_x = center_x - width // 2
    end_x = start_x + width - 1

    if start_x < left_limit or end_x > right_limit:
        return False

    if width_fn is get_3x5_width:
        print_3x5(draw, text, start_x, y, color)
    else:
        print_4x5(draw, text, start_x, y, color)

    return True


def _draw_pregame_center_badge(image, draw, game, offset_x, settings):
    # Soccer W-D-L records are too wide to share a row with
    # league text or a broadcast logo. Keep this middle band
    # for the league only so nothing collides with the records.
    if game.league_short:
        print_4x5_centered(
            draw,
            game.league_short,
            PAD_CENTER_X + offset_x,
            LEAGUE_Y,
            GREY,
        )


def _draw_scores(draw, game, offset_x):
    away = str(game.away_score)
    home = str(game.home_score)

    print_gfx_5x7(
        draw,
        away,
        NAME_LEFT_X + 2 + offset_x,
        SCORE_Y,
        YELLOW,
    )
    home_width = gfx_5x7_width(home)
    print_gfx_5x7(
        draw,
        home,
        NAME_RIGHT_X - 2 - home_width + offset_x,
        SCORE_Y,
        YELLOW,
    )


def render_soccer_game_onto(image, draw, game, offset_x, settings):
    draw_team_name(
        draw,
        game.away,
        NAME_LEFT_X + offset_x,
        NAME_Y,
        WHITE,
    )
    draw_team_name(
        draw,
        game.home,
        NAME_RIGHT_X + offset_x,
        NAME_Y,
        WHITE,
        right=True,
    )

    away_name_end = NAME_LEFT_X + _team_name_width(game.away)
    home_name_start = NAME_RIGHT_X - _team_name_width(game.home)

    if is_scheduled(game):
        _draw_centered_if_fits(
            draw,
            game.start_time,
            PAD_CENTER_X + offset_x,
            TIME_Y,
            YELLOW,
            get_3x5_width,
            away_name_end + 2 + offset_x,
            home_name_start - 2 + offset_x,
        )

        if game.date:
            print_4x5_centered(
                draw,
                game.date,
                PAD_CENTER_X + offset_x,
                DATE_Y,
                WHITE,
            )

        _draw_pregame_center_badge(
            image,
            draw,
            game,
            offset_x,
            settings,
        )

        print_3x5(
            draw,
            _record_text(
                game.away_wins,
                game.away_draws,
                game.away_losses,
            ),
            NAME_LEFT_X + offset_x,
            RECORD_Y,
            GREY,
        )
        print_3x5_right(
            draw,
            _record_text(
                game.home_wins,
                game.home_draws,
                game.home_losses,
            ),
            NAME_RIGHT_X + offset_x,
            RECORD_Y,
            GREY,
        )
        return

    label = period_label(game)
    if label and game.status.upper() != "HALFTIME":
        _draw_centered_if_fits(
            draw,
            label,
            PAD_CENTER_X + offset_x,
            STATUS_Y,
            YELLOW,
            get_4x5_width,
            away_name_end + 2 + offset_x,
            home_name_start - 2 + offset_x,
        )

    _draw_scores(draw, game, offset_x)

    if is_final(game):
        return

    if game.status.upper() == "HALFTIME":
        print_4x5_centered(
            draw,
            "HT",
            PAD_CENTER_X + offset_x,
            CLOCK_Y,
            YELLOW,
        )
        return

    if game.clock:
        print_4x5_centered(
            draw,
            game.clock,
            PAD_CENTER_X + offset_x,
            CLOCK_Y,
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
