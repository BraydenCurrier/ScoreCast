from dataclasses import dataclass, field
import time


@dataclass
class NotificationCard:
    provider: str      # twitter, rss, spotify, calendar
    source: str        # @AdamSchefter
    title: str
    body: str

    created_at: float = field(default_factory=time.time)
