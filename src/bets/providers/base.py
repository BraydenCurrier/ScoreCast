from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EventInfo:
    league: str
    event_id: str
    label: str
    away: str
    home: str
    status: str
    start_time: str
    date: str = ""
    away_score: int = 0
    home_score: int = 0
    period: str = ""
    clock: str = ""


@dataclass(frozen=True)
class PlayerInfo:
    player_id: str
    name: str
    team: str
    position: str = ""


@dataclass
class EventSnapshot:
    league: str
    event_id: str
    status: str
    away: str
    home: str
    away_score: int = 0
    home_score: int = 0
    period: str = ""
    clock: str = ""
    remaining_fraction: float | None = None
    player_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    fetched_at: float = 0.0
    stale: bool = False


class LeagueProvider(Protocol):
    league: str

    def list_events(self) -> list[EventInfo]:
        ...

    def list_players(self, event_id: str) -> list[PlayerInfo]:
        ...

    def snapshot(self, event_id: str) -> EventSnapshot | None:
        ...
