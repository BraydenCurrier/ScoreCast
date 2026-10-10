from dataclasses import dataclass


@dataclass
class SoccerGame:
    away: str
    home: str

    status: str
    start_time: str
    date: str

    away_score: int
    home_score: int

    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0

    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0

    period: int = 0
    clock: str = ""
    broadcast: str = ""

    league_id: str = ""
    league_name: str = ""
    league_short: str = ""
    event_id: str = ""

    extra_time: bool = False
    penalties: bool = False
    away_reds: int = 0
    home_reds: int = 0
    away_pk: int | None = None
    home_pk: int | None = None
    away_agg: int | None = None
    home_agg: int | None = None
