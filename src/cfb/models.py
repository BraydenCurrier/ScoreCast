from dataclasses import dataclass
from typing import Optional


@dataclass
class CollegeFootballGame:
    away: str
    home: str
    status: str

    start_time: str

    away_score: int
    home_score: int

    away_wins: int
    away_losses: int
    home_wins: int
    home_losses: int

    quarter: int
    clock: str

    possession: str
    down: int
    distance: int

    # None means ESPN did not provide a usable field position.
    # Zero is a real, valid yard-line value and must remain distinguishable
    # from missing data.
    yardline_side: str
    yardline_number: Optional[int]

    away_rank: Optional[int]
    home_rank: Optional[int]

    broadcast: str = ""

    date: str = "5-6-26"
    week: int = 0

    event_id: str = ""

    # Alert metadata from ESPN's situation.lastPlay
    last_play_id: str = ""
    last_play_text: str = ""
    scoring_play: bool = False
    last_play_type: str = ""
    last_play_yardage: int = 0
    last_play_team: str = ""
    last_play_athlete_ids: tuple = ()
    last_play_athlete_names: tuple = ()
    away_timeouts: int | None = None
    home_timeouts: int | None = None
    short_down_text: str = ""
    play_under_review: bool = False
    away_rush_yards: int | None = None
    away_pass_yards: int | None = None
    away_turnovers: int | None = None
    home_rush_yards: int | None = None
    home_pass_yards: int | None = None
    home_turnovers: int | None = None