from dataclasses import dataclass, field
import time


@dataclass
class NotificationCard:
    provider: str    
    source: str     
    title: str
    body: str

    created_at: float = field(default_factory=time.time)
