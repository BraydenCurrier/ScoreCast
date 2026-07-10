from datetime import datetime, timedelta
import threading

from odds.api import get_odds


class OddsManager:

    REFRESH_INTERVAL = timedelta(minutes=15)

    def __init__(self):
        self._lock = threading.RLock()

        self._cache = {}

        self._last_refresh = {}

    def refresh(self, sport):

        now = datetime.now()

        with self._lock:

            if (
                sport in self._last_refresh
                and now - self._last_refresh[sport] < self.REFRESH_INTERVAL
            ):
                return

            odds = get_odds(sport)

            sport_cache = {}

            for game in odds:

                sport_cache[
                    f"{game.away}@{game.home}"
                ] = game

            self._cache[sport] = sport_cache

            self._last_refresh[sport] = now

    def get(self, sport, away, home):

        with self._lock:

            return (
                self._cache
                .get(sport, {})
                .get(f"{away}@{home}")
            )

    def refresh_all(self):

        for sport in (

            "mlb",
            "nfl",
            "cfb",
            "nba",
            "nhl",

        ):

            try:
                self.refresh(sport)

            except Exception as e:
                print("Odds refresh failed:", sport, e)