from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from updater.config import STATUS_FILE


def write_status(
    state: str,
    message: str,
    version: str = "",
    **extra: Any,
) -> None:
    """Write updater state atomically for the web dashboard."""
    data = {
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
