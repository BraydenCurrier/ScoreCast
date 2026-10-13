from dataclasses import dataclass


@dataclass(frozen=True)
class GolfPlayer:
    name: str
    position: str
    score: str
    score_value: int
    marker: str
    finished_round: bool
    awaiting_tee: bool = False


@dataclass(frozen=True)
class GolfTournament:
    event_id: str
    name: str
    status: str
    logo_url: str
    players: tuple[GolfPlayer, ...]
    when: str = ""
