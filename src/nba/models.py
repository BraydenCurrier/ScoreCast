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

    broadcast: str = ""

    quarter: int = 0
    clock: str = ""

    possession: str = ""
    away_timeouts: int | None = None
    home_timeouts: int | None = None
    bonus: str = ""
    away_in_bonus: bool = False
    home_in_bonus: bool = False
    event_id: str = ""

    away_leader: str = ""
    away_leader_points: str = ""
    home_leader: str = ""
    home_leader_points: str = ""

    last_play_text: str = ""
    last_play_type: str = ""
    last_play_team: str = ""
    last_play_athlete: str = ""
    last_play_points: int = 0
    play_player: str = ""
    play_player_team: str = ""
    play_player_points: str = ""
    play_player_rebounds: str = ""
    play_player_assists: str = ""

    away_quarters: tuple = ()
    home_quarters: tuple = ()
    away_lineup: tuple = ()
    home_lineup: tuple = ()
