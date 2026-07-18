from dataclasses import dataclass
from typing import Dict, Tuple


RGBColor = Tuple[int, int, int]


@dataclass(frozen=True)
class NFLTeamAlert:
    abbreviation: str
    name: str
    possession_label: str
    chant: tuple[str, ...]
    primary: RGBColor
    accent: RGBColor


NFL_TEAM_ALERTS: Dict[str, NFLTeamAlert] = {
    "ARI": NFLTeamAlert(
        abbreviation="ARI",
        name="Arizona Cardinals",
        possession_label="CARDINALS BALL",
        chant=("RISE", "UP", "RED SEA"),
        primary=(151, 35, 63),
        accent=(255, 255, 255),
    ),

    "ATL": NFLTeamAlert(
        abbreviation="ATL",
        name="Atlanta Falcons",
        possession_label="FALCONS BALL",
        chant=("RISE", "UP"),
        primary=(167, 25, 48),
        accent=(255, 255, 255),
    ),

    "BAL": NFLTeamAlert(
        abbreviation="BAL",
        name="Baltimore Ravens",
        possession_label="RAVENS BALL",
        chant=("RAVENS", "FLOCK"),
        primary=(36, 23, 115),
        accent=(241, 198, 83),
    ),

    "BUF": NFLTeamAlert(
        abbreviation="BUF",
        name="Buffalo Bills",
        possession_label="BILLS BALL",
        chant=("GO", "BILLS"),
        primary=(0, 51, 141),
        accent=(198, 12, 48),
    ),

    "CAR": NFLTeamAlert(
        abbreviation="CAR",
        name="Carolina Panthers",
        possession_label="PANTHERS BALL",
        chant=("KEEP", "POUNDING"),
        primary=(0, 133, 202),
        accent=(255, 255, 255),
    ),

    "CHI": NFLTeamAlert(
        abbreviation="CHI",
        name="Chicago Bears",
        possession_label="BEARS BALL",
        chant=("BEAR", "DOWN"),
        primary=(11, 22, 42),
        accent=(200, 56, 3),
    ),

    "CIN": NFLTeamAlert(
        abbreviation="CIN",
        name="Cincinnati Bengals",
        possession_label="BENGALS BALL",
        chant=("WHO", "DEY"),
        primary=(251, 79, 20),
        accent=(0, 0, 0),
    ),

    "CLE": NFLTeamAlert(
        abbreviation="CLE",
        name="Cleveland Browns",
        possession_label="BROWNS BALL",
        chant=("DAWG", "POUND"),
        primary=(49, 29, 0),
        accent=(255, 60, 0),
    ),

    "DAL": NFLTeamAlert(
        abbreviation="DAL",
        name="Dallas Cowboys",
        possession_label="COWBOYS BALL",
        chant=("HOW BOUT", "THEM", "COWBOYS"),
        primary=(0, 53, 148),
        accent=(255, 255, 255),
    ),

    "DEN": NFLTeamAlert(
        abbreviation="DEN",
        name="Denver Broncos",
        possession_label="BRONCOS BALL",
        chant=("BRONCOS", "COUNTRY"),
        primary=(251, 79, 20),
        accent=(0, 34, 68),
    ),

    "DET": NFLTeamAlert(
        abbreviation="DET",
        name="Detroit Lions",
        possession_label="LIONS BALL",
        chant=("ONE", "PRIDE"),
        primary=(0, 118, 182),
        accent=(176, 183, 188),
    ),

    "GB": NFLTeamAlert(
        abbreviation="GB",
        name="Green Bay Packers",
        possession_label="PACKERS BALL",
        chant=("GO", "PACK", "GO"),
        primary=(24, 48, 40),
        accent=(255, 184, 28),
    ),

    "HOU": NFLTeamAlert(
        abbreviation="HOU",
        name="Houston Texans",
        possession_label="TEXANS BALL",
        chant=("GO", "TEXANS"),
        primary=(3, 32, 47),
        accent=(167, 25, 48),
    ),

    "IND": NFLTeamAlert(
        abbreviation="IND",
        name="Indianapolis Colts",
        possession_label="COLTS BALL",
        chant=("FOR", "THE SHOE"),
        primary=(0, 44, 95),
        accent=(255, 255, 255),
    ),

    "JAX": NFLTeamAlert(
        abbreviation="JAX",
        name="Jacksonville Jaguars",
        possession_label="JAGS BALL",
        chant=("DUUUVAL",),
        primary=(0, 103, 120),
        accent=(215, 162, 42),
    ),

    "KC": NFLTeamAlert(
        abbreviation="KC",
        name="Kansas City Chiefs",
        possession_label="CHIEFS BALL",
        chant=("CHIEFS", "KINGDOM"),
        primary=(227, 24, 55),
        accent=(255, 184, 28),
    ),

    "LV": NFLTeamAlert(
        abbreviation="LV",
        name="Las Vegas Raiders",
        possession_label="RAIDERS BALL",
        chant=("JUST", "WIN", "BABY"),
        primary=(0, 0, 0),
        accent=(165, 172, 175),
    ),

    "LAC": NFLTeamAlert(
        abbreviation="LAC",
        name="Los Angeles Chargers",
        possession_label="CHARGERS BALL",
        chant=("BOLT", "UP"),
        primary=(0, 128, 198),
        accent=(255, 194, 14),
    ),

    "LAR": NFLTeamAlert(
        abbreviation="LAR",
        name="Los Angeles Rams",
        possession_label="RAMS BALL",
        chant=("WHOSE HOUSE", "RAMS HOUSE"),
        primary=(0, 53, 148),
        accent=(255, 163, 0),
    ),

    "MIA": NFLTeamAlert(
        abbreviation="MIA",
        name="Miami Dolphins",
        possession_label="DOLPHINS BALL",
        chant=("FINS", "UP"),
        primary=(0, 142, 151),
        accent=(252, 76, 2),
    ),

    "MIN": NFLTeamAlert(
        abbreviation="MIN",
        name="Minnesota Vikings",
        possession_label="VIKINGS BALL",
        chant=("SKOL", "SKOL", "SKOL"),
        primary=(79, 38, 131),
        accent=(255, 198, 47),
    ),

    "NE": NFLTeamAlert(
        abbreviation="NE",
        name="New England Patriots",
        possession_label="PATRIOTS BALL",
        chant=("LETS", "GO", "PATS"),
        primary=(0, 34, 68),
        accent=(198, 12, 48),
    ),

    "NO": NFLTeamAlert(
        abbreviation="NO",
        name="New Orleans Saints",
        possession_label="SAINTS BALL",
        chant=("WHO", "DAT"),
        primary=(16, 16, 16),
        accent=(211, 188, 141),
    ),

    "NYG": NFLTeamAlert(
        abbreviation="NYG",
        name="New York Giants",
        possession_label="GIANTS BALL",
        chant=("BIG", "BLUE"),
        primary=(1, 35, 82),
        accent=(163, 13, 45),
    ),

    "NYJ": NFLTeamAlert(
        abbreviation="NYJ",
        name="New York Jets",
        possession_label="JETS BALL",
        chant=("J", "E", "T", "S", "JETS"),
        primary=(18, 87, 64),
        accent=(255, 255, 255),
    ),

    "PHI": NFLTeamAlert(
        abbreviation="PHI",
        name="Philadelphia Eagles",
        possession_label="EAGLES BALL",
        chant=("FLY", "EAGLES", "FLY"),
        primary=(0, 76, 84),
        accent=(165, 172, 175),
    ),

    "PIT": NFLTeamAlert(
        abbreviation="PIT",
        name="Pittsburgh Steelers",
        possession_label="STEELERS BALL",
        chant=("HERE", "WE GO", "STEELERS"),
        primary=(16, 16, 16),
        accent=(255, 182, 18),
    ),

    "SF": NFLTeamAlert(
        abbreviation="SF",
        name="San Francisco 49ers",
        possession_label="49ERS BALL",
        chant=("BANG BANG", "NINER GANG"),
        primary=(170, 0, 0),
        accent=(173, 153, 93),
    ),

    "SEA": NFLTeamAlert(
        abbreviation="SEA",
        name="Seattle Seahawks",
        possession_label="SEAHAWKS BALL",
        chant=("GO", "HAWKS"),
        primary=(0, 34, 68),
        accent=(105, 190, 40),
    ),

    "TB": NFLTeamAlert(
        abbreviation="TB",
        name="Tampa Bay Buccaneers",
        possession_label="BUCS BALL",
        chant=("FIRE", "THE CANNONS"),
        primary=(213, 10, 10),
        accent=(255, 121, 0),
    ),

    "TEN": NFLTeamAlert(
        abbreviation="TEN",
        name="Tennessee Titans",
        possession_label="TITANS BALL",
        chant=("TITAN", "UP"),
        primary=(12, 35, 64),
        accent=(75, 146, 219),
    ),

    "WSH": NFLTeamAlert(
        abbreviation="WSH",
        name="Washington Commanders",
        possession_label="COMMANDERS BALL",
        chant=("HAIL", "TO THE", "COMMANDERS"),
        primary=(90, 20, 20),
        accent=(255, 182, 18),
    ),
}


def get_team_alert(abbreviation):
    return NFL_TEAM_ALERTS.get(str(abbreviation).upper())