from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(
    os.getenv(
        "SCORECAST_INSTALL_DIR",
        "/opt/scorecast",
    )
)

REPOSITORY_DIR = BASE_DIR / "repo.git"
RELEASES_DIR = BASE_DIR / "releases"
VENVS_DIR = BASE_DIR / "venvs"

CURRENT_LINK = BASE_DIR / "current"
PREVIOUS_LINK = BASE_DIR / "previous"

CURRENT_VENV_LINK = BASE_DIR / "current-venv"
PREVIOUS_VENV_LINK = BASE_DIR / "previous-venv"

STATUS_FILE = BASE_DIR / "update-status.json"
LOCK_FILE = BASE_DIR / "update.lock"

SETTINGS_DIR = Path(
    os.getenv(
        "SCORECAST_CONFIG_DIR",
        "/var/lib/scorecast",
    )
)

SERVICE_NAME = os.getenv(
    "SCORECAST_SERVICE_NAME",
    "scorecast",
)

WEB_HEALTH_URL = os.getenv(
    "SCORECAST_HEALTH_URL",
    "http://127.0.0.1:8080/",
)

SYSTEM_PYTHON = Path(
    os.getenv(
        "SCORECAST_SYSTEM_PYTHON",
        "/usr/bin/python3",
    )
)

STARTUP_TIMEOUT_SECONDS = int(
    os.getenv(
        "SCORECAST_UPDATE_STARTUP_TIMEOUT",
        "30",
    )
)

HEALTH_REQUEST_TIMEOUT_SECONDS = float(
    os.getenv(
        "SCORECAST_HEALTH_REQUEST_TIMEOUT",
        "3",
    )
)
