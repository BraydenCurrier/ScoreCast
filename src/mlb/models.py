from dataclasses import dataclass, field


@dataclass(frozen=True)
class MlbScoringPlay:
    play_id: str
    event: str
    event_type: str
    description: str
    rbi: int
    inning: int
    half: str
    batter: str
    batting_team: str

    @property
    def is_home_run(self) -> bool:
        event_type = str(self.event_type or "").lower()
        event = str(self.event or "").lower()

        return (
            event_type == "home_run"
            or event == "home run"
        )


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
    game_pk: str = ""
    scoring_plays: tuple = field(default_factory=tuple)
