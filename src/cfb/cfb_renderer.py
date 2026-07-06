from PIL import Image, ImageDraw

from common.config import PANEL_WIDTH, PANEL_HEIGHT
from common.fonts import print_3x5, get_3x5_width, print_3x5_right, print_4x5, get_4x5_width, print_4x5_centered, print_4x5_right, print_clock, print_gfx_5x7, gfx_5x7_width, draw_text_right
from cfb.colors import RED, WHITE, GREY, YELLOW, GRASS_GREEN, BALL_BROWN, team_color
from cfb import cfb_logos

LOGO_SIZE = 30      # Keep the anchor point starting exactly at 30
CARD_WIDTH = 76     # Widen the inner scorecard canvas by 12px (6px left, 6px right)
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

    # If ball is on opponent 20 or closer
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


def draw_possession_arrow(draw, x, y, direction, color):
    if direction == "left":
        points = [
            (x, y + 3),
            (x + 5, y),
            (x + 5, y + 6),
        ]
    else:
        points = [
            (x + 5, y + 3),
            (x, y),
            (x, y + 6),
        ]

    draw.polygon(points, fill=color)


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


def draw_border(draw, game):
    color = RED if in_redzone(game) else GREY
    draw.rectangle((0, 0, PANEL_WIDTH - 1, PANEL_HEIGHT - 1), outline=color)

def draw_possession_football(draw, x, y):
    # Row 0 (Top profile):   . X X X .
    draw.line([(x + 1, y), (x + 3, y)], fill=BALL_BROWN)
    
    # Row 1 (Middle laces): X X W X X  (W = White Lace)
    draw.point((x, y + 1), fill=BALL_BROWN)
    draw.point((x + 1, y + 1), fill=BALL_BROWN)
    draw.point((x + 2, y + 1), fill=WHITE)  # Center lace
    draw.point((x + 3, y + 1), fill=BALL_BROWN)
    draw.point((x + 4, y + 1), fill=BALL_BROWN)
    
    # Row 2 (Bottom profile): . X X X .
    draw.line([(x + 1, y + 2), (x + 3, y + 2)], fill=BALL_BROWN)

def draw_team_logo(draw, team_abbreviation, x_start, y_start):
    """Stamps a pre-processed 16x16 team logo onto your matrix image frame"""
    logo_data = getattr(cfb_logos, f"LOGO_{team_abbreviation}", None)
    
    if not logo_data:
        return  # Fall back smoothly if logo doesn't exist
        
    for y, row in enumerate(logo_data):
        for x, rgb_color in enumerate(row):
            # Treat (0, 0, 0) as transparent background so it doesn't draw black blocks
            if rgb_color != (0, 0, 0):
                draw.point((x_start + x, y_start + y), fill=rgb_color)
            
def draw_field_tracker(draw, x,  y, yardline, possession_direction, possession, home_team, home_color):
    """Draws a scaled football field tracker with home_color endzones, 
    goal posts, a line of scrimmage, and a mini 5x3 football tracker.
    """
    # 🎨 Colors
    GRASS = (0, 180, 30)
    LINE_COLOR = (200, 200, 200)
    BALL_COLOR = (255, 220, 0)       # Line of Scrimmage
    POST_YELLOW = (255, 205, 0)      # Goal post yellow
    BALL_BROWN = (139, 69, 19)       # Football leather
    LACE_WHITE = (255, 255, 255)     # Football laces
    
    # Field Dimensions   
    ez_width = 3
    playable_width = 50
    field_height = 6    
    
    # 1. Draw Background Turf & Endzones
    # Left Endzone
    draw.rectangle([x, y, x + ez_width - 1, y + field_height - 1], fill=home_color)
    # Playable Grass
    draw.rectangle([x + ez_width, y, x + ez_width + playable_width - 1, y + field_height - 1], fill=GRASS)
    # Right Endzone
    draw.rectangle([x + ez_width + playable_width, y, x + ez_width + playable_width + ez_width - 1, y + field_height - 1], fill=home_color)
    
    # 2. Draw Major Field Lines & White Goal Lines
    # Left Goal Line (The first column of green grass turned white)
    left_goal_x = x + ez_width
    draw.line([left_goal_x, y, left_goal_x, y + field_height - 1], fill=LINE_COLOR)
    
    # Right Goal Line (The last column of green grass turned white)
    right_goal_x = x + ez_width + playable_width - 1
    draw.line([right_goal_x, y, right_goal_x, y + field_height - 1], fill=LINE_COLOR)

    # 2. Draw Major Field Lines (50, 20s)
    draw.line([x + ez_width + 25, y, x + ez_width + 25, y + field_height - 1], fill=LINE_COLOR)
    draw.point((x + ez_width + 10, y), fill=LINE_COLOR)
    draw.point((x + ez_width + playable_width - 10, y), fill=LINE_COLOR)

    # ==========================================
    # 5. Calculate Absolute Yards Based on Fixed Directions
    # ==========================================
    is_home_attacking = (possession == home_team)
    
    if is_home_attacking:
        # Home always drives Right to Left
        if possession_direction == "OWN":
            absolute_yards = 100 - yardline
        else:
            absolute_yards = yardline
            
        pixel_offset = int(absolute_yards / 2)
        scrimmage_x = x + ez_width + pixel_offset
        
        # 6. Draw Line of Scrimmage Indicator
        draw.line([scrimmage_x, y, scrimmage_x, y + field_height - 1], fill=BALL_COLOR)
        
        # 7. Draw Football ABOVE Field (Pointing Left: Tip at LOS, Laces on TOP)
        fx = scrimmage_x
        fy = y - 3
        
        # Row 0
        draw.line([(fx + 1, fy), (fx + 3, fy)], fill=BALL_BROWN)
    
        # Row 1 (Middle laces): X X W X X  (W = White Lace)
        draw.point((fx, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 1, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 2, fy + 1), fill=LACE_WHITE)  # Center lace
        draw.point((fx + 3, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 4, fy + 1), fill=BALL_BROWN)
    
        # Row 2 (Bottom profile): . X X X .
        draw.line([(fx + 1, fy + 2), (fx + 3, fy + 2)], fill=BALL_BROWN)

    else:
        # Away always drives Left to Right
        if possession_direction == "OWN":
            absolute_yards = yardline
        else:
            absolute_yards = 100 - yardline
            
        pixel_offset = int(absolute_yards / 2)
        scrimmage_x = x + ez_width + pixel_offset
        
        # 6. Draw Line of Scrimmage Indicator
        draw.line([scrimmage_x, y, scrimmage_x, y + field_height - 1], fill=BALL_COLOR)
        
        # 7. Draw Football ABOVE Field (Pointing Right: Tip at LOS, Laces on TOP)
        fx = scrimmage_x - 4
        fy = y - 3
        
        draw.line([(fx + 1, fy), (fx + 3, fy)], fill=BALL_BROWN)
    
        # Row 1 (Middle laces): X X W X X  (W = White Lace)
        draw.point((fx, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 1, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 2, fy + 1), fill=LACE_WHITE)  # Center lace
        draw.point((fx + 3, fy + 1), fill=BALL_BROWN)
        draw.point((fx + 4, fy + 1), fill=BALL_BROWN)
    
        # Row 2 (Bottom profile): . X X X .
        draw.line([(fx + 1, fy + 2), (fx + 3, fy + 2)], fill=BALL_BROWN)

    # 3. Draw Left Field Goal Post (Back of Left Endzone)
    lx = x - 1
    y = y - 4  
    draw.line([(lx, y), (lx, y + 2)], fill=POST_YELLOW)          
    draw.line([(lx + 2, y), (lx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(lx, y + 2), (lx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(lx + 1, y + 3), (lx + 1, y + 5)], fill=POST_YELLOW) 

    # 4. Draw Right Field Goal Post (Back of Right Endzone)
    rx = x + ez_width + playable_width + ez_width - 2
    draw.line([(rx, y), (rx, y + 2)], fill=POST_YELLOW)          
    draw.line([(rx + 2, y), (rx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(rx, y + 2), (rx + 2, y + 2)], fill=POST_YELLOW)  
    draw.line([(rx + 1, y + 3), (rx + 1, y + 5)], fill=POST_YELLOW) 


def render_football_game_onto(draw, game, offset_x):

    away_color = team_color(game.away)
    home_color = team_color(game.home)

    # 1. Teams: Expanded canvas lets us pull Away further left (2px) 
    # and push Home further right (52px) to clear 4-letter abbreviations
    print_gfx_5x7(draw, game.away, 2 + offset_x, 2, away_color)
    draw_text_right(draw, game.home, 73 + offset_x, 2, home_color)

    # Ranks
    if(game.away_rank != None):
        print_4x5(draw, "#" + str(game.away_rank), 2 + offset_x, 10, YELLOW)
    if(game.home_rank != None):
        print_4x5_right(draw, "#" + str(game.home_rank), 73 + offset_x, 10, YELLOW)

    # The absolute horizontal center of our 76px card is now 38
    if(game.status == "STATUS_SCHEDULED"):
        # Central pre-game elements anchored cleanly on the 38px midpoint
        print_4x5_centered(draw, game.start_time, 38 + offset_x, 2, WHITE)
        weekNumber = "Week " + str(game.week)
        print_4x5_centered(draw, weekNumber, 38 + offset_x, 11, WHITE)
        print_4x5_centered(draw, game.date, 38 + offset_x, 20, WHITE)
    else:
        # Live quarter text tracking (Using standard print_4x5 requires offsetting left slightly from center)
        print_4x5(draw, "Q" + str(game.quarter), 33 + offset_x, 2, WHITE)

        # Game clock anchored on yellow digits
        print_clock(draw, game.clock, 39 + offset_x, 8, YELLOW)

        # Down & Distance centered perfectly on 38
        downAndDistance = ordinal_down(game.down) + "&" + str(game.distance) 
        print_4x5_centered(draw, downAndDistance, 38 + offset_x, 14, WHITE)

        # Possession Mini-Football: Positioned symmetrically around the top quarter text
        if game.possession == game.away:
            draw_possession_football(draw, 25 + offset_x, 3)
        else:
            draw_possession_football(draw, 46 + offset_x, 3)
        
        # Yardline text centered on 38
        yard = game.yardline_side + " " + str(game.yardline_number)
        print_4x5_centered(draw, yard, 38 + offset_x, 20, WHITE)

    # 2. Score Alignment
    # Away score stays aligned left next to the away abbreviation
    if game.away_score < 10:
        print_gfx_5x7(draw, str(game.away_score), 8 + offset_x, 16, YELLOW)
    else:
        print_gfx_5x7(draw, str(game.away_score), 5 + offset_x, 16, YELLOW)

    # Home score utilizes right-alignment anchor points shifted out to match the new 76px boundary
    if game.home_score < 10:
        draw_text_right(draw, game.home_score, 67 + offset_x, 16, YELLOW)
    else:
        draw_text_right(draw, game.home_score, 71 + offset_x, 16, YELLOW)

    # 3. Football Field Tracker placement (Centered on the bottom row)
    # Stretches across the core of the canvas from pixel 10 to pixel 66
    if game.possession == game.yardline_side:
        draw_field_tracker(draw, 10 + offset_x, 29, game.yardline_number, "OWN", game.possession, game.home, home_color)
    else:
        draw_field_tracker(draw, 10 + offset_x, 29, game.yardline_number, "OPP", game.possession, game.home, home_color)

def render_game_strip_onto(draw, game, offset_x):
    # Away logo at absolute start
    draw_team_logo(draw, game.away, offset_x, 1)

    # Score card starts exactly 30px inward
    render_football_game_onto(draw, game, offset_x + LOGO_SIZE)

    # Home logo follows directly after the new 76px scorecard (30 + 76 = 106)
    draw_team_logo(draw, game.home, offset_x + LOGO_SIZE + CARD_WIDTH, 1)