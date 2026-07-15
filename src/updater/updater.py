from __future__ import annotations

import argparse
import fcntl
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from updater.config import (
    BASE_DIR,
    CURRENT_LINK,
    CURRENT_VENV_LINK,
    LOCK_FILE,
    PREVIOUS_LINK,
    PREVIOUS_VENV_LINK,
    RELEASES_DIR,
    REPOSITORY_DIR,
    SERVICE_NAME,
    SETTINGS_DIR,
    SYSTEM_PYTHON,
    VENVS_DIR,
)
from updater.status import write_status
from updater.validation import (
    ValidationError,
    run_command,
    validate_release,
    wait_for_service_health,
)


VERSION_PATTERN = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)"
    r"(?:[-+].*)?$"
)


class UpdateError(RuntimeError):
    """Raised when ScoreCast cannot be updated safely."""


def log(message: str) -> None:
    print(
        f"[scorecast-update] {message}",
        flush=True,
    )


def require_root() -> None:
    if os.geteuid() != 0:
        raise UpdateError(
            "The updater must run as root."
        )


def require_installation() -> None:
    required_paths = [
        REPOSITORY_DIR,
        RELEASES_DIR,
        CURRENT_LINK,
    ]

    for path in required_paths:
        if not path.exists():
            raise UpdateError(
                f"Required path is missing: {path}"
            )

    if not SYSTEM_PYTHON.is_file():
        raise UpdateError(
            f"System Python is missing: "
            f"{SYSTEM_PYTHON}"
        )


def acquire_lock():
    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    lock_file = LOCK_FILE.open(
        "w",
        encoding="utf-8",
    )

    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError as error:
        lock_file.close()

        raise UpdateError(
            "Another ScoreCast update is "
            "already running."
        ) from error

    lock_file.write(
        f"{os.getpid()}\n"
    )
    lock_file.flush()

    return lock_file


def run_git(*arguments: str) -> str:
    result = run_command(
        [
            "/usr/bin/git",
            f"--git-dir={REPOSITORY_DIR}",
            *arguments,
        ]
    )

    return result.stdout.strip()


def version_key(tag: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.match(
        tag.strip()
    )

    if not match:
        return (-1, -1, -1)

    return tuple(
        int(part)
        for part in match.groups()
    )


def fetch_repository() -> None:
    write_status(
        "checking",
        "Checking GitHub for updates.",
    )

    log("Fetching branches and tags.")

    run_git(
        "fetch",
        "--prune",
        "--tags",
        "origin",
    )


def find_latest_tag() -> str:
    output = run_git(
        "tag",
        "--list",
        "v*",
    )

    tags = [
        tag.strip()
        for tag in output.splitlines()
        if VERSION_PATTERN.match(
            tag.strip()
        )
    ]

    if not tags:
        raise UpdateError(
            "No semantic-version release tags "
            "were found."
        )

    return max(
        tags,
        key=version_key,
    )


def resolve_link(path: Path) -> Path | None:
    if not path.is_symlink():
        return None

    try:
        return path.resolve(
            strict=True
        )
    except FileNotFoundError:
        return None


def release_version(path: Path | None) -> str:
    if path is None:
        return ""

    return path.name


def remove_existing_worktree(
    release_path: Path,
) -> None:
    if not release_path.exists():
        return

    log(
        f"Removing incomplete release "
        f"{release_path.name}."
    )

    result = subprocess.run(
        [
            "/usr/bin/git",
            f"--git-dir={REPOSITORY_DIR}",
            "worktree",
            "remove",
            "--force",
            str(release_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if (
        result.returncode != 0
        and release_path.exists()
    ):
        shutil.rmtree(
            release_path
        )

    run_git(
        "worktree",
        "prune",
    )


def create_release(
    tag: str,
    version: str,
) -> Path:
    release_path = (
        RELEASES_DIR / version
    )

    if release_path.exists():
        main_file = (
            release_path
            / "src"
            / "main.py"
        )

        requirements_file = (
            release_path
            / "requirements.txt"
        )

        if (
            main_file.is_file()
            and requirements_file.is_file()
        ):
            log(
                f"Release {version} already "
                "exists locally."
            )
            return release_path

        remove_existing_worktree(
            release_path
        )

    write_status(
        "downloading",
        f"Downloading ScoreCast {version}.",
        version,
    )

    log(
        f"Checking out {tag}."
    )

    run_git(
        "worktree",
        "add",
        "--detach",
        str(release_path),
        tag,
    )

    return release_path


def copy_rgbmatrix_binding(
    source_python: Path,
    target_python: Path,
) -> None:
    """
    Copy the working local rgbmatrix binding into a new release venv.

    The hzeller binding is often installed outside normal PyPI handling,
    so it may not be visible inside a newly created virtual environment.
    """
    source_result = run_command(
        [
            str(source_python),
            "-c",
            (
                "import pathlib, rgbmatrix; "
                "print(pathlib.Path(rgbmatrix.__file__)"
                ".resolve().parent)"
            ),
        ]
    )

    source_package = Path(
        source_result.stdout.strip()
    )

    target_result = run_command(
        [
            str(target_python),
            "-c",
            (
                "import site; "
                "print(site.getsitepackages()[0])"
            ),
        ]
    )

    target_site_packages = Path(
        target_result.stdout.strip()
    )

    target_package = (
        target_site_packages / "rgbmatrix"
    )

    if target_package.exists():
        shutil.rmtree(target_package)

    shutil.copytree(
        source_package,
        target_package,
    )

def create_release_venv(
    release_path: Path,
    version: str,
) -> Path:
    venv_path = VENVS_DIR / version
    python_path = (
        venv_path / "bin" / "python"
    )

    if python_path.is_file():
        rgbmatrix_check = subprocess.run(
            [
                str(python_path),
                "-c",
                "import rgbmatrix",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if rgbmatrix_check.returncode == 0:
            log(
                f"Virtual environment for "
                f"{version} already exists."
            )
            return venv_path

        log(
            f"Existing environment for {version} "
            "is incomplete; rebuilding it."
        )

        shutil.rmtree(
            venv_path
        )

    if venv_path.exists():
        shutil.rmtree(
            venv_path
        )

    VENVS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_status(
        "installing",
        f"Creating environment for "
        f"ScoreCast {version}.",
        version,
    )

    log(
        f"Creating virtual environment "
        f"for {version}."
    )

    run_command(
        [
            str(SYSTEM_PYTHON),
            "-m",
            "venv",
            "--system-site-packages",
            str(venv_path),
        ]
    )

    pip_path = (
        venv_path / "bin" / "pip"
    )

    requirements_path = (
        release_path / "requirements.txt"
    )

    log(
        f"Installing dependencies for "
        f"{version}."
    )

    run_command(
        [
            str(pip_path),
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )

    run_command(
        [
            str(pip_path),
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements_path),
        ]
    )

    current_python = (
        CURRENT_VENV_LINK
        / "bin"
        / "python"
    )

    log(
        "Copying RGB matrix Python binding."
    )

    copy_rgbmatrix_binding(
        current_python,
        python_path,
    )

    return venv_path


def replace_symlink(
    link_path: Path,
    target_path: Path,
) -> None:
    temporary_link = link_path.with_name(
        f".{link_path.name}.new"
    )

    try:
        temporary_link.unlink(
            missing_ok=True
        )

        temporary_link.symlink_to(
            target_path,
            target_is_directory=True,
        )

        os.replace(
            temporary_link,
            link_path,
        )

    finally:
        try:
            temporary_link.unlink(
                missing_ok=True
            )
        except OSError:
            pass


def restart_scorecast() -> None:
    log("Restarting ScoreCast.")

    run_command([
        "/usr/bin/systemctl",
        "restart",
        SERVICE_NAME,
    ])


def rollback(
    old_release: Path,
    old_venv: Path,
    attempted_version: str,
    reason: str,
) -> None:
    log(
        f"Update failed: {reason}"
    )
    log("Rolling back.")

    replace_symlink(
        CURRENT_LINK,
        old_release,
    )

    replace_symlink(
        CURRENT_VENV_LINK,
        old_venv,
    )

    restart_scorecast()

    try:
        wait_for_service_health()
    except ValidationError as error:
        write_status(
            "failed",
            (
                "Update and automatic rollback "
                f"both failed: {error}"
            ),
            attempted_version,
        )

        raise UpdateError(
            "Automatic rollback failed."
        ) from error

    write_status(
        "rolled_back",
        (
            "Update failed. The previous "
            "release was restored."
        ),
        attempted_version,
        error=reason,
    )

    raise UpdateError(
        "Update failed and was rolled back."
    )


def install_update(
    latest_tag: str,
    version: str,
) -> None:
    old_release = resolve_link(
        CURRENT_LINK
    )

    old_venv = resolve_link(
        CURRENT_VENV_LINK
    )

    if old_release is None:
        raise UpdateError(
            "The current release link is invalid."
        )

    if old_venv is None:
        raise UpdateError(
            "The current virtual-environment "
            "link is invalid."
        )

    release_path = create_release(
        latest_tag,
        version,
    )

    venv_path = create_release_venv(
        release_path,
        version,
    )

    python_path = (
        venv_path / "bin" / "python"
    )

    write_status(
        "validating",
        f"Validating ScoreCast {version}.",
        version,
    )

    log(
        f"Validating release {version}."
    )

    validate_release(
        release_path,
        python_path,
    )

    replace_symlink(
        PREVIOUS_LINK,
        old_release,
    )

    replace_symlink(
        PREVIOUS_VENV_LINK,
        old_venv,
    )

    replace_symlink(
        CURRENT_LINK,
        release_path,
    )

    replace_symlink(
        CURRENT_VENV_LINK,
        venv_path,
    )

    write_status(
        "restarting",
        f"Restarting ScoreCast {version}.",
        version,
    )

    try:
        restart_scorecast()
        wait_for_service_health()

    except (
        ValidationError,
        UpdateError,
    ) as error:
        rollback(
            old_release,
            old_venv,
            version,
            str(error),
        )

    write_status(
        "complete",
        (
            "ScoreCast updated successfully "
            f"to {version}."
        ),
        version,
    )

    log(
        f"ScoreCast {version} installed "
        "successfully."
    )


def check_for_update() -> tuple[str, str, str]:
    fetch_repository()

    latest_tag = find_latest_tag()
    latest_version = latest_tag.removeprefix("v")

    current_release = resolve_link(
        CURRENT_LINK
    )

    current_version = release_version(
        current_release
    )

    log(
        f"Current version: "
        f"{current_version or 'unknown'}"
    )
    log(
        f"Latest version: {latest_version}"
    )

    return (
        latest_tag,
        latest_version,
        current_version,
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update ScoreCast from tagged "
            "GitHub releases."
        )
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Check for an update without "
            "installing it."
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    require_root()
    require_installation()

    lock_handle = acquire_lock()

    try:
        (
            latest_tag,
            latest_version,
            current_version,
        ) = check_for_update()

        if latest_version == current_version:
            write_status(
                "current",
                (
                    "ScoreCast is already "
                    "up to date."
                ),
                latest_version,
            )

            log("Already up to date.")
            return 0

        if arguments.check_only:
            write_status(
                "available",
                (
                    f"ScoreCast {latest_version} "
                    "is available."
                ),
                latest_version,
                current_version=current_version,
            )

            log(
                f"Update {latest_version} "
                "is available."
            )
            return 0

        install_update(
            latest_tag,
            latest_version,
        )

        return 0

    finally:
        lock_handle.close()


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except (
        UpdateError,
        ValidationError,
        subprocess.SubprocessError,
        OSError,
    ) as error:
        message = str(error)

        log(
            f"ERROR: {message}"
        )

        try:
            write_status(
                "failed",
                message,
            )
        except OSError:
            pass

        raise SystemExit(1)
