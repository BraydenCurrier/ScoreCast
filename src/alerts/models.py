from dataclasses import dataclass


@dataclass(frozen=True)
class PossessionAlert:
    game_id: str
    league: str
    alert_type: str
    team: str
    opponent: str
    headline: str
    detail: str
    possession_label: str
    chant: tuple[str, ...]
    primary: tuple[int, int, int]
    accent: tuple[int, int, int]
    down: int
    distance: int
    yardline_side: str
    yardline_number: int
    quarter: int
    clock: str
    created_at: float
    chant_frame_seconds: float
    details_frame_seconds: float
    is_player_alert: bool = False
    play_text: str = ""
    player_name: str = ""
    away: str = ""
    home: str = ""
    away_score: int = 0
    home_score: int = 0

    @property
    def total_duration(self) -> float:
        return max(1.0, self.details_frame_seconds)