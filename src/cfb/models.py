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
