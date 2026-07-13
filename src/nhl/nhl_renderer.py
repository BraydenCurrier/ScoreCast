from common.fonts import print_3x5, get_3x5_width, print_4x5, get_4x5_width, print_4x5_centered, print_gfx_5x7, gfx_5x7_width, draw_text_right, print_clock
from nhl import nhl_logos

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

def draw_team_logo(draw, team_abbreviation, x_start, y_start):
    logo_data = getattr(nhl_logos, f"LOGO_{team_abbreviation}", None)
    
    if not logo_data:
        return  
        
    for y, row in enumerate(logo_data):
        for x, rgb_color in enumerate(row):
            if rgb_color != (0, 0, 0):
                draw.point((x_start + x, y_start + y), fill=rgb_color)

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


def render_game_strip_onto(draw, game, odds, offset_x):
    # away logo
    draw_team_logo(draw, game.away, offset_x, 1)

    # score card
    render_hockey_game_onto(draw, game, odds, offset_x + LOGO_SIZE)

    # home logo
    draw_team_logo(draw, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1)