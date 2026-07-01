from dataclasses import dataclass

@dataclass
class SoccerGame:
    away: str
    home: str

    away_score: int
    home_score: int

    status: str          # e.g. "45'", "HT", "FT", "3:00 PM"
    start_time: str      # e.g. "3:00 PM"
    date: str            # e.g. "JUN 22"

    minute: int
    stoppage: str

    tournament: str      # e.g. "FIFA WORLD CUP"
    stage: str           # e.g. "GROUP A", "ROUND OF 16", "FINAL"