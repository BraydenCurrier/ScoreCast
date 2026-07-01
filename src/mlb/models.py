from dataclasses import dataclass

@dataclass
class BaseballGame:
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

    inning: int
    top_inning: bool

    first: bool
    second: bool
    third: bool

    outs: int
