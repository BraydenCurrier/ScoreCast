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