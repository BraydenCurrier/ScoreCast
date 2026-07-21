from PIL import Image, ImageDraw

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import print_3x5, get_3x5_width, print_3x5_right, print_4x5, get_4x5_width, print_4x5_centered, print_4x5_right, print_clock, print_gfx_5x7, gfx_5x7_width, draw_text_right
from cfb.colors import RED, WHITE, GREY, YELLOW, GRASS_GREEN, BALL_BROWN, team_color
from common.logo_store import draw_logo

LOGO_SIZE = 30     
# changed score card width to accomadate longer 4 character team abbreviations
CARD_WIDTH = 76   
GAME_GAP = 5
GAME_WIDTH = LOGO_SIZE + CARD_WIDTH + LOGO_SIZE 

def game_id(game):
    return f"{game.away}@{game.home}"

def is_live(game):
    return game.status.lower() in ["live", "in progress", "halftime"]

def is_final(game):
    return "final" in game.status.lower()

def is_preview(game):
    return not is_live(game) and not is_final(game)


def in_redzone(game):
    if not is_live(game):
        return False

    if game.possession == "":
        return False

    # determine if a team is inside the opponents 20 (redzone)
    if game.possession == game.away:
        return game.yardline_side == game.home and game.yardline_number <= 20

    if game.possession == game.home:
        return game.yardline_side == game.away and game.yardline_number <= 20

    return False


def draw_5x7_right(draw, text, right_x, y, color):
    text = str(text)
    width = len(text) * 6 - 1
    print_gfx_5x7(draw, text, right_x - width, y, color)


def draw_3x5_center(draw, text, center_x, y, color):
    width = get_3x5_width(text)
    print_3x5(draw, text, center_x - width // 2, y, color)

def ordinal_down(down):
    if down == 1:
        return "1st"
    if down == 2:
        return "2nd"
    if down == 3:
        return "3rd"
    if down == 4:
        return "4th"
    return "-"

def draw_possession_football(draw, x, y):
    # top
    draw.line([(x + 1, y), (x + 3, y)], fill=BALL_BROWN)
    
    # middle with lace
    draw.point((x, y + 1), fill=BALL_BROWN)
    draw.point((x + 1, y + 1), fill=BALL_BROWN)
    draw.point((x + 2, y + 1), fill=WHITE)  # lace
    draw.point((x + 3, y + 1), fill=BALL_BROWN)
    draw.point((x + 4, y + 1), fill=BALL_BROWN)
    
    # bottom
    draw.line([(x + 1, y + 2), (x + 3, y + 2)], fill=BALL_BROWN)

def draw_team_logo(
    image,
    team_abbreviation,
    x_start,
    y_start,
):
    return draw_logo(
        destination=image,
        league="cfb",
        identifier=team_abbreviation,
        x=x_start,
        y=y_start,
    )
            
def draw_field_tracker(draw, x,  y, yardline, possession_direction, possession, home_team, home_color):
    GRASS = (0, 180, 30)
    LINE_COLOR = (200, 200, 200)
    BALL_COLOR = (255, 220, 0)       
    POST_YELLOW = (255, 205, 0)      
    BALL_BROWN = (139, 69, 19)       
    LACE_WHITE = (255, 255, 255)
    
    # field dimensions   
    ez_width = 3
    playable_width = 50
    field_height = 6    
    
    # left endzone
    draw.rectangle([x, y, x + ez_width - 1, y + field_height - 1], fill=home_color)
    # field
    draw.rectangle([x + ez_width, y, x + ez_width + playable_width - 1, y + field_height - 1], fill=GRASS)
    # right endzone
    draw.rectangle([x + ez_width + playable_width, y, x + ez_width + playable_width + ez_width - 1, y + field_height - 1], fill=home_color)
    
    # left goal line
    left_goal_x = x + ez_width
    draw.line([left_goal_x, y, left_goal_x, y + field_height - 1], fill=LINE_COLOR)
    
    # right goal line
    right_goal_x = x + ez_width + playable_width - 1
    draw.line([right_goal_x, y, right_goal_x, y + field_height - 1], fill=LINE_COLOR)

    # yard lines
    draw.line([x + ez_width + 25, y, x + ez_width + 25, y + field_height - 1], fill=LINE_COLOR)
    draw.point((x + ez_width + 10, y), fill=LINE_COLOR)
    draw.point((x + ez_width + playable_width - 10, y), fill=LINE_COLOR)

    is_home_attacking = (possession == home_team)
    
    if is_home_attacking:
        if possession_direction == "OWN":
            absolute_yards = 100 - yardline
        else:
            absolute_yards = yardline
            
        pixel_offset = int(absolute_yards / 2)
        scrimmage_x = x + ez_width + pixel_offset
        
        # line of scrimmage
        draw.line([scrimmage_x, y, scrimmage_x, y + field_height - 1], fill=BALL_COLOR)
        
        # draw football
        fx = scrimmage_x
        fy = y - 3
        
        draw_possession_football(draw, fx - 4, fy)

    else:
        if possession_direction == "OWN":
            absolute_yards = yardline
        else:
            absolute_yards = 100 - yardline
            
        pixel_offset = int(absolute_yards / 2)
        scrimmage_x = x + ez_width + pixel_offset
        
        # line of scrimmage
        draw.line([scrimmage_x, y, scrimmage_x, y + field_height - 1], fill=BALL_COLOR)
        
        # draw football
        fx = scrimmage_x - 4
        fy = y - 3
        
        draw_possession_football(draw, fx - 4, fy)

    # draw left field goal
    lx = x - 1
    y = y - 4  
    draw.line([(lx, y), (lx, y + 2)], fill=POST_YELLOW)          
    draw.line([(lx + 2, y), (lx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(lx, y + 2), (lx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(lx + 1, y + 3), (lx + 1, y + 5)], fill=POST_YELLOW) 

    # draw right field goal
    rx = x + ez_width + playable_width + ez_width - 2
    draw.line([(rx, y), (rx, y + 2)], fill=POST_YELLOW)          
    draw.line([(rx + 2, y), (rx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(rx, y + 2), (rx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(rx + 1, y + 3), (rx + 1, y + 5)], fill=POST_YELLOW) 


def render_football_game_onto(draw, game, offset_x):

    away_color = team_color(game.away)
    home_color = team_color(game.home)

    # print team abbreviations
    print_gfx_5x7(draw, game.away, 2 + offset_x, 2, away_color)
    draw_text_right(draw, game.home, 73 + offset_x, 2, home_color)

    # print ranks
    if(game.away_rank != None):
        print_4x5(draw, "#" + str(game.away_rank), 2 + offset_x, 10, YELLOW)
    if(game.home_rank != None):
        print_4x5_right(draw, "#" + str(game.home_rank), 73 + offset_x, 10, YELLOW)

    if(game.status == "STATUS_SCHEDULED"):
        # print scheduled game time, week number, and date
        print_4x5_centered(draw, game.start_time, 38 + offset_x, 2, WHITE)
        weekNumber = "Week " + str(game.week)
        print_4x5_centered(draw, weekNumber, 38 + offset_x, 11, WHITE)
        print_4x5_centered(draw, game.date, 38 + offset_x, 20, WHITE)
    else:
        # print quarter and game clock
        print_4x5(draw, "Q" + str(game.quarter), 33 + offset_x, 2, WHITE)
        print_clock(draw, game.clock, 39 + offset_x, 8, YELLOW)

        # print down and distance 
        downAndDistance = ordinal_down(game.down) + "&" + str(game.distance) 
        print_4x5_centered(draw, downAndDistance, 38 + offset_x, 14, WHITE)

        # print possession football
        if game.possession == game.away:
            draw_possession_football(draw, 25 + offset_x, 3)
        else:
            draw_possession_football(draw, 46 + offset_x, 3)
        
        # print yardline side and number
        yard = game.yardline_side + " " + str(game.yardline_number)
        print_4x5_centered(draw, yard, 38 + offset_x, 20, WHITE)

        # print scores centered
        if game.away_score < 10:
            print_gfx_5x7(draw, str(game.away_score), 8 + offset_x, 16, YELLOW)
        else:
            print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 16, YELLOW)

        if game.home_score < 10:
            draw_text_right(draw, game.home_score, 67 + offset_x, 16, YELLOW)
        else:
            draw_text_right(draw, game.home_score, 71 + offset_x, 16, YELLOW)

        if game.possession == game.yardline_side:
            draw_field_tracker(draw, 10 + offset_x, 29, game.yardline_number, "OWN", game.possession, game.home, home_color)
        else:
            draw_field_tracker(draw, 10 + offset_x, 29, game.yardline_number, "OPP", game.possession, game.home, home_color)

def render_game_strip_onto(image, draw, game, offset_x):
    # away logo
    draw_team_logo(image, game.away, offset_x, 1)

    # score card
    render_football_game_onto(draw, game, offset_x + LOGO_SIZE)

    # home logo
    draw_team_logo(image, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1)