import threading
import time

from alerts.manager import possession_alert_manager
from common.settings import get_settings
from nfl.api import get_today_games


DEFAULT_POLL_INTERVAL = 3.0
MINIMUM_POLL_INTERVAL = 2.0
MAXIMUM_POLL_INTERVAL = 30.0

_error_lock = threading.Lock()
_last_error_message = ""
_last_error_logged_at = 0.0


def _safe_poll_interval(settings):
    alerts_settings = settings.get("alerts", {})

    raw_value = alerts_settings.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_POLL_INTERVAL

    return max(MINIMUM_POLL_INTERVAL, min(MAXIMUM_POLL_INTERVAL, value))


def _log_error_throttled(error):
    global _last_error_message
    global _last_error_logged_at

    now = time.monotonic()
    message = f"{type(error).__name__}: {error}"

    with _error_lock:
        should_log = (message != _last_error_message or now - _last_error_logged_at >= 60.0)

        if not should_log:
            return

        _last_error_message = message
        _last_error_logged_at = now

    print("Possession watcher failed:", message, flush=True)


def possession_watch_loop(stop_event):
    if stop_event is None:
        stop_event = threading.Event()

    while not stop_event.is_set():
        loop_started_at = time.monotonic()

        try:
            settings = get_settings()

            games = get_today_games()

            possession_alert_manager.process_games(games=games, settings=settings, now=time.monotonic())

        except Exception as error:
            _log_error_throttled(error)

        try:
            settings = get_settings()
            poll_interval = _safe_poll_interval(settings)
        except Exception:
            poll_interval = DEFAULT_POLL_INTERVAL

        elapsed = (time.monotonic() - loop_started_at)

        sleep_seconds = max(0.1, poll_interval - elapsed)

        stop_event.wait(sleep_seconds)