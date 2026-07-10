import threading
import time

from common.settings import get_settings
from notifications.rss_provider import fetch_rss_notifications

DEFAULT_MAX_AGE_SECONDS = 120 * 60


class NotificationManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._cards = []
        self._seen_ids = set()

    def _max_age_seconds(self, config):
        return int(config.get("max_age_seconds", DEFAULT_MAX_AGE_SECONDS))

    def _prune_locked(self, max_age_seconds, now=None):
        if now is None:
            now = time.time()

        self._cards = [
            card
            for card in self._cards
            if getattr(card, "created_at", 0) and now - card.created_at <= max_age_seconds
        ]

    def refresh(self):
        settings = get_settings()
        config = settings.get("notifications", {})
        max_age_seconds = self._max_age_seconds(config)
        now = time.time()

        with self._lock:
            self._prune_locked(max_age_seconds, now)

        if not config.get("enabled", True):
            return

        new_cards = []

        for source in config.get("sources", []):
            if source.get("provider") != "rss":
                continue

            try:
                cards = fetch_rss_notifications(
                    source.get("source", "RSS"),
                    source.get("url", ""),
                    self._seen_ids,
                    max_age_seconds=max_age_seconds,
                    now=now,
                )
                new_cards.extend(cards)
            except Exception as e:
                print("Notification source failed:", source.get("source"), e)

        max_cards = int(config.get("max_cards", 5))

        with self._lock:
            if new_cards:
                self._cards = (new_cards + self._cards)[:max_cards]

            self._prune_locked(max_age_seconds, now)

    def get_cards(self):
        settings = get_settings()
        max_age_seconds = self._max_age_seconds(settings.get("notifications", {}))

        with self._lock:
            self._prune_locked(max_age_seconds)
            return list(self._cards)
