from __future__ import annotations

import compileall
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from updater.config import (
    HEALTH_REQUEST_TIMEOUT_SECONDS,
    SERVICE_NAME,
    SETTINGS_DIR,
    STARTUP_TIMEOUT_SECONDS,
    WEB_HEALTH_URL,
)


class ValidationError(RuntimeError):
    """Raised when a release or running service fails validation."""


def run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        output = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Command exited with {result.returncode}"
        )

        raise ValidationError(
            f"{' '.join(command)} failed: {output}"
        )

    return result


def build_environment(
    release_path: Path,
) -> dict[str, str]:
    environment = os.environ.copy()

    environment.update({
        "SCORECAST_CONFIG_DIR": str(
            SETTINGS_DIR
        ),
        "PYTHONPATH": str(
            release_path / "src"
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })

    return environment


def validate_release(
    release_path: Path,
    python_path: Path,
) -> None:
    """Validate source files, imports, and persistent settings."""
    source_path = release_path / "src"
    main_path = source_path / "main.py"
    requirements_path = (
        release_path / "requirements.txt"
    )

    if not main_path.is_file():
        raise ValidationError(
            f"Missing entry point: {main_path}"
        )

    if not requirements_path.is_file():
        raise ValidationError(
            f"Missing requirements file: "
            f"{requirements_path}"
        )

    if not python_path.is_file():
        raise ValidationError(
            f"Missing Python interpreter: "
            f"{python_path}"
        )

    environment = build_environment(
        release_path
    )

    run_command(
        [
            str(python_path),
            "-m",
            "compileall",
            "-q",
            str(source_path),
        ],
        environment=environment,
        cwd=release_path,
    )

    validation_code = """
from common.settings import get_settings
from common.matrix import create_matrix
from web.app import app

settings = get_settings()

assert isinstance(settings, dict)
assert callable(create_matrix)
assert app is not None

print("Release validation successful")
"""

    run_command(
        [
            str(python_path),
            "-c",
            validation_code,
        ],
        environment=environment,
        cwd=release_path,
    )


def service_is_active() -> bool:
    result = subprocess.run(
        [
            "/usr/bin/systemctl",
            "is-active",
            "--quiet",
            SERVICE_NAME,
        ],
        check=False,
    )

    return result.returncode == 0


def web_dashboard_is_healthy() -> bool:
    try:
        request = urllib.request.Request(
            WEB_HEALTH_URL,
            headers={
                "User-Agent": (
                    "ScoreCast-Updater/1.0"
                ),
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=(
                HEALTH_REQUEST_TIMEOUT_SECONDS
            ),
        ) as response:
            return 200 <= response.status < 500

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ):
        return False


def wait_for_service_health() -> None:
    """
    Wait for both systemd and the dashboard to become available.
    """
    deadline = (
        time.monotonic()
        + STARTUP_TIMEOUT_SECONDS
    )

    while time.monotonic() < deadline:
        if (
            service_is_active()
            and web_dashboard_is_healthy()
        ):
            return

        time.sleep(1)

    if not service_is_active():
        raise ValidationError(
            "ScoreCast did not remain active "
            "after restarting."
        )

    raise ValidationError(
        "ScoreCast started, but the web dashboard "
        f"did not respond at {WEB_HEALTH_URL}."
    )
