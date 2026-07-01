from PIL import Image, ImageDraw

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from mlb.colors import YELLOW, WHITE, GREY, RED, team_color
from mlb import mlb_logos
from common.fonts import print_3x5, get_3x5_width, print_4x5, get_4x5_width, print_4x5_centered, print_gfx_5x7, gfx_5x7_width, draw_text_right

LOGO_SIZE = 30
CARD_WIDTH = 64
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE

def draw_base_diamond(draw, cx, cy, occupied):
    color = WHITE if occupied else GREY
    points = [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)]

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

def draw_team_logo(draw, team_abbreviation, x_start, y_start):
    """Stamps a pre-processed 16x16 team logo onto your matrix image frame"""
    # Look up array safely dynamically (e.g., "LAD", "NYY", "CHC")
    logo_data = getattr(mlb_logos, f"LOGO_{team_abbreviation}", None)
    
    if not logo_data:
        return  # Fall back smoothly if logo doesn't exist
        
    for y, row in enumerate(logo_data):
        for x, rgb_color in enumerate(row):
            # Treat (0, 0, 0) as transparent background so it doesn't draw black blocks
            if rgb_color != (0, 0, 0):
                draw.point((x_start + x, y_start + y), fill=rgb_color)

def render_baseball_game_onto(draw, game, offset_x):
    print_gfx_5x7(draw, game.away, 3 + offset_x, 2, team_color(game.away))

    if game.away_score < 10:
        print_gfx_5x7(draw, str(game.away_score), 9 + offset_x, 13, YELLOW)
    else:
        print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 13, YELLOW)

    print_gfx_5x7(draw, game.home, 44 + offset_x, 2, team_color(game.home))

    if game.home_score < 10:
        draw_text_right(draw, game.home_score, 55 + offset_x, 13, YELLOW)
    else:
        draw_text_right(draw, game.home_score, 60 + offset_x, 13, YELLOW)

    if game.status == "Preview":
        width = get_3x5_width(game.start_time)
        centered_x = (64 - width) // 2
        print_3x5(draw, game.start_time, centered_x + offset_x, 2, YELLOW)
    else:
        draw_inning(draw, 27 + offset_x, 19, game.inning, game.top_inning, YELLOW)

        draw_base_diamond(draw, 24 + offset_x, 14, game.third)
        draw_base_diamond(draw, 38 + offset_x, 14, game.first)
        draw_base_diamond(draw, 31 + offset_x, 7, game.second)

    draw_outs(draw, 25 + offset_x, 26, game.outs)

    print_3x5(draw, f"{game.away_wins}-{game.away_losses}", 2 + offset_x, 25, GREY)
    print_3x5(draw, f"{game.home_wins}-{game.home_losses}", 43 + offset_x, 25, GREY)

def render_game_strip_onto(draw, game, offset_x):
    # Away logo before the score card
    draw_team_logo(draw, game.away, offset_x, 1)

    # Existing 64px score card after away logo
    render_baseball_game_onto(draw, game, offset_x + LOGO_SIZE)

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