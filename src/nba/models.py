from dataclasses import dataclass


@dataclass
class BasketballGame:
    away: str
    home: str

    status: str
    start_time: str
    date: str 

    away_score: int
    home_score: int

    away_wins: int = 0
    away_losses: int = 0
    home_wins: int = 0
    home_losses: int = 0

    quarter: int = 0
    clock: str = ""
