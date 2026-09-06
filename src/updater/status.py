from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from updater.config import STATUS_FILE

ACTIVE_STATES = {
    "checking",
    "downloading",
    "installing",
    "validating",
    "restarting",
    "rolling_back",
}

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

def write_status(
    state: str,
    message: str,
    version: str = "",
    **extra: Any,
) -> None:
    if state in {"failed", "rolled_back"} and "progress" not in extra:
        previous = read_status()
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

    """Write updater state atomically for the web dashboard."""
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
    default = {
        "progress": 0,
        "progress_kind": "steps",
        "step": "",
        "state": "idle",
        "message": "No update is currently running.",
        "version": "",
        "updated_at": "",
    }

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
