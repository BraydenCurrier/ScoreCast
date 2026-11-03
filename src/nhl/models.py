from dataclasses import dataclass


@dataclass
class HockeyGame:
    away: str
    home: str

    status: str
    start_time: str
    date: str

    away_score: int
    home_score: int

    away_wins: int = 0
    away_losses: int = 0
    away_ot_losses: int = 0

    home_wins: int = 0
    home_losses: int = 0
    home_ot_losses: int = 0

    period: int = 0
    clock: str = ""

    broadcast: str = ""

    intermission: bool = False
    shootout: bool = False
    overtime: bool = False

    away_sog: int | None = None
    home_sog: int | None = None
    possession: str = ""
    power_play: str = ""
    power_play_clock: str = ""
    strength: str = ""
    away_so_goals: int | None = None
    home_so_goals: int | None = None
    away_goalie: str = ""
    home_goalie: str = ""
    away_save_pct: str = ""
    home_save_pct: str = ""
    away_lineup: tuple = ()
    home_lineup: tuple = ()
    event_id: str = ""
    last_play_name: str = ""
    last_play_label: str = ""
    last_play_goal: bool = False
    empty_net: bool = False
