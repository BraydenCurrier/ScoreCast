from common.fonts import print_3x5, get_3x5_width, print_4x5, get_4x5_width, print_4x5_centered, print_gfx_5x7, gfx_5x7_width, draw_text_right, print_clock
from common.logo_store import draw_logo, get_selected_logo_variant

WHITE = (255, 255, 255)
YELLOW = (255, 235, 0)
GREY = (80, 80, 80)
GREEN = (0, 220, 80)

LOGO_SIZE = 30
CARD_WIDTH = 64
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE

def is_live(game):
    return game.status.upper() in ["LIVE", "IN PROGRESS"]


def is_final(game):
    return "FINAL" in game.status.upper()


def draw_text_right(draw, text, right_x, y, color):
    width = len(str(text)) * 6 - 1
    print_gfx_5x7(draw, str(text), right_x - width, y, color)

def draw_team_logo(
    image,
    team_abbreviation,
    x_start,
    y_start,
    settings,
):
    variant = get_selected_logo_variant(
        settings,
        "nhl",
        team_abbreviation,
    )

    return draw_logo(
        destination=image,
        league="nhl",
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
        variant=variant,
    )

def render_hockey_game_onto(draw, game, odds, offset_x):
    # away team
    print_gfx_5x7(draw, game.away, 3 + offset_x, 2, WHITE)

    # home team
    draw_text_right(draw, game.home, 61 + offset_x, 2, WHITE)

    # records
    print_3x5(draw, f"{game.away_wins}-{game.away_losses}", 2 + offset_x, 25, GREY)
    print_3x5(draw, f"{game.home_wins}-{game.home_losses}", 43 + offset_x, 25, GREY)

    if game.status == "Scheduled":
        width = get_3x5_width(game.start_time)
        centered_x = (64 - width) // 2
        print_3x5(draw, game.start_time, centered_x + offset_x, 2, YELLOW)
        print_4x5_centered(draw, game.date, 32 + offset_x, 14, WHITE)
    else:
        # period and clock
        print_4x5_centered(draw, "P" + str(game.period), 32 + offset_x, 2, YELLOW)
        print_clock(draw, game.clock, 32 + offset_x, 14, YELLOW)

        # score centered
        if game.away_score < 10:
            print_gfx_5x7(draw, str(game.away_score), 9 + offset_x, 13, YELLOW)
        else:
            print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 13, YELLOW)

        if game.home_score < 10:
            draw_text_right(draw, game.home_score, 55 + offset_x, 13, YELLOW)
        else:
            draw_text_right(draw, game.home_score, 60 + offset_x, 13, YELLOW)


def render_game_strip_onto(image, draw, game, odds, offset_x, settings):
    # away logo
    draw_team_logo(image, game.away, offset_x, 1, settings)

    # score card
    render_hockey_game_onto(draw, game, odds, offset_x + LOGO_SIZE)

    # home logo
    draw_team_logo(image, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1, settings)