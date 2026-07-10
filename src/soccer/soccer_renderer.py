from common.fonts import print_3x5, get_3x5_width, print_4x5, get_4x5_width, print_4x5_centered, print_gfx_5x7, gfx_5x7_width, draw_text_right
from soccer import soccer_logos

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
    """Stamps a pre-processed 16x16 team logo onto your matrix image frame"""
    # Look up array safely dynamically (e.g., "LAD", "NYY", "CHC")
    logo_data = getattr(soccer_logos, f"FLAG_{team_abbreviation}", None)
    
    if not logo_data:
        return  # Fall back smoothly if logo doesn't exist
        
    for y, row in enumerate(logo_data):
        for x, rgb_color in enumerate(row):
            # Treat (0, 0, 0) as transparent background so it doesn't draw black blocks
            if rgb_color != (0, 0, 0):
                draw.point((x_start + x, y_start + y), fill=rgb_color)

def render_soccer_game_onto(draw, game, odds, offset_x):
    # Team Away
    print_gfx_5x7(draw, game.away, 3 + offset_x, 2, WHITE)

    # Team Home
    print_gfx_5x7(draw, game.home, 44 + offset_x, 2, WHITE)

    # Preview or Live/Final
    if game.status == "SCHEDULED":
        width = get_3x5_width(game.start_time)
        centered_x = (64 - width) // 2
        print_3x5(draw, game.start_time, centered_x + offset_x, 2, YELLOW)
        print_4x5_centered(draw, game.date, 32 + offset_x, 14, WHITE)
    else:
        print_4x5_centered(draw, game.status, 32 + offset_x, 2, YELLOW)

        if game.home_score < 10:
            draw_text_right(draw, game.home_score, 55 + offset_x, 13, YELLOW)
        else:
            draw_text_right(draw, game.home_score, 60 + offset_x, 13, YELLOW)

        if game.away_score < 10:
            print_gfx_5x7(draw, str(game.away_score), 9 + offset_x, 13, YELLOW)
        else:
            print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 13, YELLOW)

    stage_name = game.stage.replace("-", " ").upper()
    print_4x5_centered(draw, stage_name, 32 + offset_x, 24, WHITE)

def render_game_strip_onto(draw, game, odds, offset_x):
    # Away logo before the score card
    draw_team_logo(draw, game.away, offset_x, 1)

    # Existing 64px score card after away logo
    render_soccer_game_onto(draw, game, odds, offset_x + LOGO_SIZE)

    # Home logo after the score card
    draw_team_logo(draw, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1)

def render_scrolling_games(games, current_game, scroll_x):
    image = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    if not games:
        draw.text((3, 12), "NO GAMES", fill=WHITE)
        return image

    next_game = current_game + 1
    if next_game >= len(games):
        next_game = 0

    render_game_strip_onto(draw, games[current_game], int(scroll_x))
    render_game_strip_onto(draw, games[next_game], int(scroll_x) + GAME_WIDTH + GAME_GAP)

    return image