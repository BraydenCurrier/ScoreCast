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


@dataclass(frozen=True)
class MlbPitch:
    px: float
    pz: float
    result: str
    strike_zone_top: float = 3.5
    strike_zone_bottom: float = 1.5
    speed: float = 0.0
    pitch_type: str = ""
    pitch_name: str = ""


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
    balls: int = 0
    strikes: int = 0
    batter: str = ""
    pitcher: str = ""
    pitches: tuple = field(default_factory=tuple)
    strike_zone_top: float = 3.5
    strike_zone_bottom: float = 1.5
    pitcher_pitches: int = 0
    batter_stat: str = ""
