from dataclasses import dataclass


@dataclass
class FantasyMatchup:
    away: str
    home: str

    status: str
    start_time: str
    date: str

    away_score: float
    home_score: float

    league_id: str
    league_name: str

    away_roster_id: int
    home_roster_id: int

    week: int
    matchup_id: int

    away_projected: float = 0.0
    home_projected: float = 0.0

    away_owner: str = ""
    home_owner: str = ""

    away_abbrev: str = ""
    home_abbrev: str = ""
    away_logo: str = ""
    home_logo: str = ""

    away_wins: int = -1
    away_losses: int = -1
    away_ties: int = 0
    home_wins: int = -1
    home_losses: int = -1
    home_ties: int = 0