import copy
import threading
import time

from alerts.manager import possession_alert_manager
from common.settings import get_settings
from nfl.api import (
    get_today_games as get_nfl_games,
)
from cfb.api import (
    get_today_games as get_cfb_games,
)
from mlb.api import (
    get_alert_games as get_mlb_alert_games,
)


DEFAULT_POLL_INTERVAL = 3.0
MINIMUM_POLL_INTERVAL = 2.0
MAXIMUM_POLL_INTERVAL = 30.0

_error_lock = threading.Lock()
_last_error_message = ""
_last_error_logged_at = 0.0


def _alerts_enabled(settings):
    alerts_settings = settings.get("alerts", {})

    if not isinstance(alerts_settings, dict):
        return False

    return bool(alerts_settings.get("enabled", False))


def _baseline_settings(settings):
    """Settings for one catch-up pass that records state and emits nothing.

    While alerts are off the watcher does not poll. The first poll after
    they are turned on must absorb the current score, possession, red zone,
    and completed games the way the old disabled polls did, without
    replaying those events. confirmations_required of 1 adopts the current
    possession in that single sample.
    """
    baseline = copy.deepcopy(settings)
    alerts_settings = baseline.get("alerts")

    if not isinstance(alerts_settings, dict):
        alerts_settings = {}
        baseline["alerts"] = alerts_settings

    alerts_settings["enabled"] = False
    alerts_settings["confirmations_required"] = 1

    return baseline


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

    # True after a loop that skipped fetches because alerts were off.
    # The next enabled poll syncs state before it is allowed to alert.
    skipped_while_disabled = False

    while not stop_event.is_set():
        loop_started_at = time.monotonic()

        try:
            settings = get_settings()

            # Pause all possession-alert API requests
            # while the display is software-powered off.
            if not settings.get("display_enabled", True):
                stop_event.wait(0.5)
                continue

            if not _alerts_enabled(settings):
                skipped_while_disabled = True
            else:
                games = []

                try:
                    nfl_games = (
                        get_nfl_games()
                        or []
                    )

                    games.extend(
                        nfl_games
                    )

                except Exception as error:
                    _log_error_throttled(
                        RuntimeError(
                            f"NFL alerts: {error}"
                        )
                    )

                try:
                    cfb_games = (
                        get_cfb_games(
                            conference_groups=["80"],
                        )
                        or []
                    )

                    games.extend(
                        cfb_games
                    )

                except Exception as error:
                    _log_error_throttled(
                        RuntimeError(
                            f"CFB alerts: {error}"
                        )
                    )

                try:
                    mlb_games = (
                        get_mlb_alert_games()
                        or []
                    )

                    games.extend(
                        mlb_games
                    )

                except Exception as error:
                    _log_error_throttled(
                        RuntimeError(
                            f"MLB alerts: {error}"
                        )
                    )

                now = time.monotonic()

                if skipped_while_disabled:
                    possession_alert_manager.process_games(
                        games=games,
                        settings=_baseline_settings(settings),
                        now=now,
                    )

                possession_alert_manager.process_games(
                    games=games,
                    settings=settings,
                    now=now,
                )

                skipped_while_disabled = False

        except Exception as error:
            _log_error_throttled(error)

        try:
            settings = get_settings()
            poll_interval = _safe_poll_interval(settings)
        except Exception:
            poll_interval = DEFAULT_POLL_INTERVAL

        elapsed = time.monotonic() - loop_started_at
        sleep_seconds = max(0.1, poll_interval - elapsed)

        stop_event.wait(sleep_seconds)