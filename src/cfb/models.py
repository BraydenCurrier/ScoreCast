from dataclasses import dataclass

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

    yardline_side: str
    yardline_number: int

    away_rank: int
    home_rank: int

    date: str = "5-6-26"
    week: int = 0
