import time


class AlertEventStore:
    def __init__(self, max_age_seconds=3600):
        self.max_age_seconds = max_age_seconds
        self.seen = {}

    def is_new(self, event_id):
        self.cleanup()

        if event_id in self.seen:
            return False

        self.seen[event_id] = time.time()
        return True

    def cleanup(self):
        now = time.time()

        expired = [
            event_id
            for event_id, seen_at in self.seen.items()
            if now - seen_at > self.max_age_seconds
        ]

        for event_id in expired:
            del self.seen[event_id]