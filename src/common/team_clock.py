"""One clock theme for every team the board already knows.

Pro teams use their scoreboard colors. College teams use the same
school colors as the ticker. Soccer clubs take a color from the logo.
The picture stays dark so the clock can sit on top of it.
"""

from __future__ import annotations

from functools import lru_cache


LEAGUES = (
    ("featured", "Featured"),
    ("nfl", "NFL"),
    ("nba", "NBA"),
    ("mlb", "MLB"),
    ("nhl", "NHL"),
    ("cfb", "College Football"),
    ("cbb", "College Basketball"),
    ("soccer", "Soccer"),
)

LEAGUE_LABELS = dict(LEAGUES)

NBA_NAMES = {
    "ATL": "Atlanta Hawks",
    "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GS": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NO": "New Orleans Pelicans",
    "NY": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SA": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTAH": "Utah Jazz",
    "WSH": "Washington Wizards",
}

NHL_NAMES = {
    "ANA": "Anaheim Ducks",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CAR": "Carolina Hurricanes",
    "CBJ": "Columbus Blue Jackets",
    "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LA": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NJ": "New Jersey Devils",
    "NSH": "Nashville Predators",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SEA": "Seattle Kraken",
    "SJ": "San Jose Sharks",
    "STL": "St. Louis Blues",
    "TB": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WPG": "Winnipeg Jets",
    "WSH": "Washington Capitals",
}

# The Rams scoreboard color is stored under the shorter abbreviation.
_NFL_COLOR_ALIAS = {"LAR": "LA"}

# Second uniform color. The clock uses this beside the main color.
NBA_ALTERNATES = {
    "ATL": (255, 184, 28),
    "BKN": (255, 255, 255),
    "BOS": (186, 148, 80),
    "CHA": (29, 17, 96),
    "CHI": (255, 255, 255),
    "CLE": (255, 184, 28),
    "DAL": (188, 192, 196),
    "DEN": (13, 34, 64),
    "DET": (0, 43, 92),
    "GS": (255, 199, 44),
    "HOU": (196, 206, 211),
    "IND": (0, 45, 98),
    "LAC": (29, 66, 138),
    "LAL": (85, 37, 130),
    "MEM": (255, 187, 0),
    "MIA": (244, 184, 0),
    "MIL": (238, 220, 180),
    "MIN": (120, 190, 33),
    "NO": (180, 151, 90),
    "NY": (245, 132, 38),
    "OKC": (240, 90, 30),
    "ORL": (196, 206, 211),
    "PHI": (237, 23, 76),
    "PHX": (29, 17, 96),
    "POR": (255, 255, 255),
    "SAC": (188, 190, 192),
    "SA": (0, 0, 0),
    "TOR": (196, 206, 212),
    "UTAH": (0, 43, 92),
    "WSH": (0, 43, 92),
}

MLB_ALTERNATES = {
    "ARI": (0, 163, 174),
    "ATL": (19, 39, 79),
    "ATH": (255, 184, 28),
    "BAL": (0, 0, 0),
    "BOS": (15, 34, 64),
    "CHC": (204, 52, 51),
    "CWS": (0, 0, 0),
    "CIN": (255, 255, 255),
    "CLE": (12, 35, 64),
    "COL": (196, 206, 212),
    "DET": (12, 35, 64),
    "HOU": (0, 45, 98),
    "KC": (255, 196, 37),
    "LAA": (0, 50, 99),
    "LAD": (255, 255, 255),
    "MIA": (255, 102, 0),
    "MIL": (19, 41, 75),
    "MIN": (0, 43, 92),
    "NYM": (255, 88, 0),
    "NYY": (255, 255, 255),
    "PHI": (35, 70, 145),
    "PIT": (255, 255, 255),
    "SD": (252, 210, 80),
    "SEA": (12, 44, 86),
    "SF": (0, 0, 0),
    "STL": (252, 194, 0),
    "TB": (9, 44, 92),
    "TEX": (200, 16, 46),
    "TOR": (255, 255, 255),
    "WSH": (20, 40, 84),
}

NHL_ALTERNATES = {
    "ANA": (180, 151, 90),
    "BOS": (0, 0, 0),
    "BUF": (255, 184, 28),
    "CAR": (255, 255, 255),
    "CBJ": (200, 16, 46),
    "CGY": (250, 190, 20),
    "CHI": (0, 133, 66),
    "COL": (35, 97, 146),
    "DAL": (196, 206, 212),
    "DET": (255, 255, 255),
    "EDM": (4, 30, 66),
    "FLA": (200, 160, 60),
    "LA": (0, 0, 0),
    "MIN": (166, 25, 46),
    "MTL": (0, 30, 98),
    "NJ": (255, 255, 255),
    "NSH": (4, 30, 66),
    "NYI": (0, 48, 135),
    "NYR": (206, 17, 38),
    "OTT": (200, 160, 50),
    "PHI": (255, 255, 255),
    "PIT": (255, 255, 255),
    "SEA": (224, 58, 62),
    "SJ": (255, 102, 0),
    "STL": (252, 181, 20),
    "TB": (255, 255, 255),
    "TOR": (255, 255, 255),
    "UTA": (0, 0, 0),
    "VAN": (10, 134, 61),
    "VGK": (185, 30, 45),
    "WPG": (196, 206, 212),
    "WSH": (4, 30, 66),
}


def league_label(league):
    return LEAGUE_LABELS.get(str(league or "").strip().lower(), "")


def theme_for_id(theme_id):
    text = str(theme_id or "").strip()
    if not text.startswith("team_"):
        return None
    parts = text.split("_", 2)
    if len(parts) != 3:
        return None
    return theme_for(parts[1], parts[2])


def theme_for(league, abbreviation):
    league = str(league or "").strip().lower()
    abbreviation = str(abbreviation or "").strip().upper()
    if league not in LEAGUE_LABELS or league == "featured":
        return None
    if abbreviation not in abbreviations(league):
        return None
    primary, accent = colors(league, abbreviation)
    return {
        "id": f"team_{league}_{abbreviation}",
        "name": display_name(league, abbreviation),
        "scene": "team",
        "league": league,
        "abbreviation": abbreviation,
        "primary": [int(primary[0]), int(primary[1]), int(primary[2])],
        "accent": [int(accent[0]), int(accent[1]), int(accent[2])],
    }


def themes_for_league(league):
    league = str(league or "").strip().lower()
    found = []
    for abbreviation in abbreviations(league):
        theme = theme_for(league, abbreviation)
        if theme is not None:
            found.append(theme)
    found.sort(key=lambda theme: (theme["name"].lower(), theme["abbreviation"]))
    return found


def favorite_themes(settings):
    raw = (settings or {}).get("favorite_teams") or {}
    if not isinstance(raw, dict):
        return []
    found = []
    seen = set()
    for league, teams in raw.items():
        if isinstance(teams, str):
            teams = [teams]
        if not isinstance(teams, list):
            continue
        for abbreviation in teams:
            theme = theme_for(league, abbreviation)
            if theme is None or theme["id"] in seen:
                continue
            seen.add(theme["id"])
            found.append(theme)
    found.sort(key=lambda theme: theme["name"].lower())
    return found


def logo_source(league, abbreviation, settings=None):
    """(league, abbreviation, variant) for the logo this theme should show."""
    league = str(league or "").strip().lower()
    abbreviation = str(abbreviation or "").strip().upper()
    if not league or not abbreviation:
        return None
    from common.logo_store import get_logo_variants, get_selected_logo_variant

    search = [league]
    if league == "cbb":
        search.append("cfb")
    for item in search:
        try:
            variants = get_logo_variants(item, abbreviation)
        except ValueError:
            continue
        if not variants:
            continue
        variant = "current" if "current" in variants else variants[0]
        if settings:
            chosen = get_selected_logo_variant(
                settings,
                item,
                abbreviation,
                available=variants,
            )
            if chosen in variants:
                variant = chosen
        return item, abbreviation, variant
    return None


def display_name(league, abbreviation):
    league = str(league or "").strip().lower()
    abbreviation = str(abbreviation or "").strip().upper()
    if league == "nfl":
        from alerts.teams import NFL_TEAM_ALERTS

        team = NFL_TEAM_ALERTS.get(abbreviation)
        if team is not None:
            return team.name
    elif league == "mlb":
        from alerts.teams import MLB_TEAM_NAMES

        return MLB_TEAM_NAMES.get(abbreviation, abbreviation)
    elif league == "nba":
        return NBA_NAMES.get(abbreviation, abbreviation)
    elif league == "nhl":
        return NHL_NAMES.get(abbreviation, abbreviation)
    return abbreviation


@lru_cache(maxsize=8)
def abbreviations(league):
    league = str(league or "").strip().lower()
    if league == "cbb":
        from cfb.colors import TEAM_COLORS

        return frozenset(TEAM_COLORS)
    if league not in LEAGUE_LABELS or league == "featured":
        return frozenset()
    try:
        from common.logo_store import get_teams_with_logos

        return frozenset(
            str(team).strip().upper()
            for team in get_teams_with_logos(league)
            if str(team).strip()
        )
    except (ValueError, OSError):
        return frozenset()


def colors(league, abbreviation):
    """Main color and the team's alternate color."""
    league = str(league or "").strip().lower()
    abbreviation = str(abbreviation or "").strip().upper()
    primary = _primary(league, abbreviation)
    alternate = _known_alternate(league, abbreviation)
    if alternate is None:
        alternate = _sampled_alternate(league, abbreviation, tuple(primary)) or None
    if not alternate:
        alternate = _fallback_alternate(primary)
    return primary, alternate


def _primary(league, abbreviation):
    if league == "nfl":
        from alerts.teams import NFL_TEAM_ALERTS

        team = NFL_TEAM_ALERTS.get(abbreviation)
        if team is not None:
            return team.primary
        from nfl.colors import team_color

        return team_color(_NFL_COLOR_ALIAS.get(abbreviation, abbreviation))
    if league == "nba":
        from nba.colors import team_color

        return team_color(abbreviation)
    if league == "mlb":
        from mlb.colors import team_color

        return team_color(abbreviation)
    if league == "nhl":
        from nhl.colors import team_color

        return team_color(abbreviation)
    if league in {"cfb", "cbb"}:
        from cfb.colors import team_color

        return team_color(abbreviation)
    if league == "soccer":
        return _soccer_color(abbreviation)
    return (32, 48, 80)


def _known_alternate(league, abbreviation):
    if league == "nfl":
        from alerts.teams import NFL_TEAM_ALERTS

        team = NFL_TEAM_ALERTS.get(abbreviation)
        if team is not None:
            return team.accent
        return None
    tables = {
        "nba": NBA_ALTERNATES,
        "mlb": MLB_ALTERNATES,
        "nhl": NHL_ALTERNATES,
    }
    table = tables.get(league)
    if table is None:
        return None
    return table.get(abbreviation)


@lru_cache(maxsize=1024)
def _sampled_alternate(league, abbreviation, primary):
    """A second color taken from the logo, when the uniform table has none."""
    source = logo_source(league, abbreviation)
    if source is None:
        return ()
    logo_league, team, variant = source
    try:
        from common.logo_store import load_logo

        image = load_logo(logo_league, team, variant)
    except (FileNotFoundError, ValueError, OSError):
        return ()
    totals = {}
    counts = {}
    for red, green, blue, alpha in image.getdata():
        if alpha < 80 or red + green + blue < 45:
            continue
        key = (red // 28, green // 28, blue // 28)
        count = counts.get(key, 0) + 1
        counts[key] = count
        bucket = totals.get(key)
        if bucket is None:
            totals[key] = [red, green, blue]
        else:
            bucket[0] += red
            bucket[1] += green
            bucket[2] += blue
    ranked = sorted(counts, key=counts.get, reverse=True)
    found_colors = []
    for key in ranked:
        count = counts[key]
        found = tuple(channel // count for channel in totals[key])
        if _color_gap(found, primary) < 120 or _same_family(found, primary):
            continue
        found_colors.append(found)
    colorful = [
        color for color in found_colors
        if max(color) - min(color) > 28 and min(color) < 215
    ]
    if colorful:
        return colorful[0]
    if found_colors:
        return found_colors[0]
    return ()


def _color_gap(left, right):
    return sum(abs(int(left[index]) - int(right[index])) for index in range(3))


def _same_family(left, right):
    """True when the second color is just a lighter or darker copy."""
    def chroma(color):
        peak = max(int(channel) for channel in color) or 1
        return tuple(int(channel) / peak for channel in color)

    distance = sum(
        abs(left_channel - right_channel)
        for left_channel, right_channel in zip(chroma(left), chroma(right))
    )
    return distance < 0.5


def _fallback_alternate(primary):
    """White is the usual second uniform when a logo has only one color."""
    red, green, blue = (int(primary[0]), int(primary[1]), int(primary[2]))
    if min(red, green, blue) > 210:
        return (24, 28, 36)
    return (255, 255, 255)


@lru_cache(maxsize=256)
def _soccer_color(abbreviation):
    from common.logo_store import bundled_logo_path

    path = bundled_logo_path("soccer", abbreviation)
    if path is None:
        return (32, 64, 120)
    try:
        from PIL import Image

        image = Image.open(path).convert("RGBA")
    except (OSError, ValueError):
        return (32, 64, 120)
    pixels = list(image.getdata())
    step = max(1, len(pixels) // 400)
    best = None
    best_score = -1
    for index in range(0, len(pixels), step):
        red, green, blue, alpha = pixels[index]
        if alpha < 80:
            continue
        luminance = red + green + blue
        if luminance < 40 or luminance > 720:
            continue
        saturation = max(red, green, blue) - min(red, green, blue)
        score = saturation * 2 + (255 - abs(luminance - 380) // 3)
        if score > best_score:
            best_score = score
            best = (red, green, blue)
    return best or (32, 64, 120)
