YELLOW = (255, 235, 0)
WHITE = (255, 255, 255)
GREY = (80, 80, 80)
RED = (255, 0, 0)
GRASS_GREEN = (0, 220, 40)
BALL_BROWN = (139, 69, 19)

TEAM_COLORS = {
    # AFC East
    "BUF": (0, 110, 255),   # Bills Electric Blue
    "MIA": (0, 225, 200),   # Dolphins Aqua Neon
    "NE":  (255, 15, 50),   # Patriots High-Output Red
    "NYJ": (0, 210, 80),    # Jets Bright Gotham Green

    # AFC North
    "BAL": (160, 40, 255),  # Ravens Piercing Purple
    "CIN": (255, 90, 0),    # Bengals Fiery Tiger Orange
    "CLE": (255, 75, 0),    # Browns Saturated Orange (Avoids muddy brown)
    "PIT": (255, 215, 0),   # Steelers Max-Punch Gold

    # AFC South
    "HOU": (255, 10, 30),   # Texans Battle Red
    "IND": (0, 120, 255),   # Colts Horseshoe Royal Blue
    "JAX": (0, 210, 210),   # Jaguars Vivid Teal
    "TEN": (0, 160, 255),   # Titans Bright Titans Blue

    # AFC West
    "DEN": (255, 85, 0),    # Broncos Mile High Orange
    "KC":  (255, 0, 10),    # Chiefs Pure Saturated Red
    "LV":  (220, 220, 225), # Raiders Bright Vegas Silver (Swapped for black)
    "LAC": (0, 150, 255),   # Chargers Neon Powder Blue

    # NFC East
    "DAL": (150, 180, 220), # Cowboys Star Silver-Blue
    "NYG": (0, 90, 255),    # Giants Big Blue
    "PHI": (0, 180, 120),   # Eagles Bright Midnight Teal
    "WSH": (255, 190, 0),   # Commanders Gold (Better contrast than dark burgundy)

    # NFC North
    "CHI": (255, 80, 0),    # Bears Saturated Orange
    "DET": (0, 160, 255),   # Lions Vibrant Honolulu Blue
    "GB":  (255, 210, 0),   # Packers Bright Cheese Gold
    "MIN": (150, 50, 255),  # Vikings Saturated Purple

    # NFC South
    "ATL": (255, 10, 30),   # Falcons High-Output Red (Swapped for black)
    "CAR": (0, 180, 255),   # Panthers Electric Process Blue
    "NO":  (230, 185, 85),  # Saints Crisp Metallic Gold
    "TB":  (255, 15, 40),   # Buccaneers Saturated Crimson Red

    # NFC West
    "ARI": (255, 10, 40),   # Cardinals Saturated Cardinal Red
    "LA":  (255, 210, 0),   # Rams Electric Royal Gold
    "SF":  (255, 25, 30),   # 49ers High-Output Red
    "SEA": (0, 255, 50)     # Seahawks Electric Action Green
}

def team_color(team):
    return TEAM_COLORS.get(team, WHITE)