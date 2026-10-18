from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from typing import Any

from updater.config import LOCK_FILE, STATUS_FILE

ACTIVE_STATES = {
    "checking",
    "downloading",
    "installing",
    "validating",
    "restarting",
    "rolling_back",
}

# Type=oneshot stays "activating" for the whole run. "active" alone
# would treat a live updater as already stopped.
RUNNING_SERVICE_STATES = {
    "active",
    "activating",
    "deactivating",
    "reloading",
}

# Time for systemd to launch the updater after the dashboard requests it.
START_REQUEST_GRACE_SECONDS = 10

INTERRUPTED_MESSAGE = (
    "The updater stopped before it finished. "
    "You can try again."
)

DEFAULT_PROGRESS = {
    "checking": 5,
    "downloading": 20,
    "installing": 40,
    "validating": 80,
    "restarting": 95,
    "rolling_back": 95,
    "complete": 100,
    "current": 100,
    "available": 100,
}

def _status_lock_path():
    return STATUS_FILE.with_name(
        f".{STATUS_FILE.name}.lock"
    )


def _lock_status_file(*, exclusive: bool = True):
    """Lock status updates so a stale read cannot clobber a newer write."""
    _status_lock_path().parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    handle = _status_lock_path().open(
        "a+",
        encoding="utf-8",
    )
    fcntl.flock(
        handle.fileno(),
        fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
    )
    return handle


def _unlock_status_file(handle) -> None:
    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_UN,
        )
    finally:
        handle.close()


def service_state_is_running(active_state: str) -> bool:
    """True while systemd still considers the updater unit in progress."""
    return (
        str(active_state).strip().lower()
        in RUNNING_SERVICE_STATES
    )


def updater_lock_is_held() -> bool:
    """True when an updater process holds the install lock."""
    try:
        LOCK_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        handle = LOCK_FILE.open("a+")
    except OSError:
        return False

    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        return True
    except OSError:
        return False
    else:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_UN,
        )
        return False
    finally:
        handle.close()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def within_start_grace(
    status: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """
    True just after the dashboard asks systemd to start.

    The unit can still be inactive for a moment, and the updater
    has not taken the lock yet. That window must not be stored
    as a failure.
    """
    requested = _parse_timestamp(
        status.get("start_requested_at")
    )
    if requested is None:
        return False

    current = now or datetime.now(timezone.utc)
    age = (current - requested).total_seconds()
    return 0 <= age < START_REQUEST_GRACE_SECONDS


def write_status(
    state: str,
    message: str,
    version: str = "",
    **extra: Any,
) -> None:
    """Write updater state atomically for the web dashboard."""
    handle = _lock_status_file()
    try:
        _write_status_unlocked(
            state,
            message,
            version,
            **extra,
        )
    finally:
        _unlock_status_file(handle)


def _write_status_unlocked(
    state: str,
    message: str,
    version: str = "",
    **extra: Any,
) -> None:
    if state in {"failed", "rolled_back"} and "progress" not in extra:
        previous = _read_status_unlocked()
        progress = previous.get("progress", 0)
    else:
        progress = extra.pop(
            "progress",
            DEFAULT_PROGRESS.get(state, 0),
        )

    progress = max(
        0,
        min(100, int(progress)),
    )

    if state in {
        "failed",
        "rolled_back",
    }:
        progress = min(progress, 99)

    data = {
        "progress": progress,
        "progress_kind": extra.pop(
            "progress_kind",
            "steps",
        ),
        "step": extra.pop(
            "step",
            "",
        ),
        "state": state,
        "message": message,
        "version": version,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        **extra,
    }

    STATUS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = STATUS_FILE.with_name(
        f".{STATUS_FILE.name}.tmp"
    )

    try:
        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(
            temporary_path,
            STATUS_FILE,
        )

    finally:
        try:
            temporary_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass


def read_status() -> dict[str, Any]:
    """Read the current update state."""
    handle = _lock_status_file(exclusive=False)
    try:
        return _read_status_unlocked()
    finally:
        _unlock_status_file(handle)


def _default_status() -> dict[str, Any]:
    return {
        "progress": 0,
        "progress_kind": "steps",
        "step": "",
        "state": "idle",
        "message": "No update is currently running.",
        "version": "",
        "updated_at": "",
    }


def _read_status_unlocked() -> dict[str, Any]:
    default = _default_status()

    try:
        with STATUS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            return default

        return {
            **default,
            **loaded,
        }

    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ):
        return default


def _state_of(status: dict[str, Any]) -> str:
    return str(
        status.get("state", "")
    ).strip().lower()


def updater_is_alive(
    status: dict[str, Any],
    *,
    service_running: bool,
) -> bool:
    if service_running or updater_lock_is_held():
        return True
    return within_start_grace(status)


def reconcile_status(
    *,
    service_running: bool,
) -> dict[str, Any]:
    """
    Turn a leftover active status into a failure once the updater is gone.

    A just-requested start is left alone until systemd or the lock
    shows the new run, so the dashboard does not fail it early.
    """
    handle = _lock_status_file()
    try:
        status = _read_status_unlocked()
        state = _state_of(status)

        if state not in ACTIVE_STATES:
            return status

        if updater_is_alive(
            status,
            service_running=service_running,
        ):
            return status

        _write_status_unlocked(
            "failed",
            INTERRUPTED_MESSAGE,
            str(status.get("version") or ""),
            progress=int(status.get("progress") or 0),
            step=str(status.get("step") or ""),
            error="interrupted",
            interrupted=True,
        )
        return _read_status_unlocked()
    finally:
        _unlock_status_file(handle)


def mark_start_requested(
    version: str = "",
) -> dict[str, Any]:
    """Record a dashboard start before systemd reports the unit."""
    write_status(
        "checking",
        "Starting the updater.",
        version,
        progress=1,
        step="Preparing update",
        start_requested_at=datetime.now(
            timezone.utc
        ).isoformat(),
    )
    return read_status()


def mark_updater_interrupted(message: str) -> None:
    """Record failure when the updater exits mid-run."""
    handle = _lock_status_file()
    try:
        status = _read_status_unlocked()
        if _state_of(status) not in ACTIVE_STATES:
            return

        _write_status_unlocked(
            "failed",
            message,
            str(status.get("version") or ""),
            error="interrupted",
            interrupted=True,
        )
    finally:
        _unlock_status_file(handle)


def is_update_in_progress() -> bool:
    status = read_status()

    if _state_of(status) not in ACTIVE_STATES:
        return False

    return updater_is_alive(
        status,
        service_running=False,
    )
