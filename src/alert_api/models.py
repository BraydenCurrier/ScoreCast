from dataclasses import dataclass, field
import time


@dataclass
class AlertEvent:
    event_id: str
    event_type: str
    league: str

    team: str | None = None
    player: str | None = None

    message: str = ""
    detail: str | None = None

    away: str | None = None
    home: str | None = None
    away_score: int | None = None
    home_score: int | None = None
    status: str | None = None

    source: str = "unknown"
    created_at: float = field(default_factory=time.time)