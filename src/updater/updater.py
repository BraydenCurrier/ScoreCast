from __future__ import annotations

import time
import threading
import queue
import uuid

import atexit
import argparse
import fcntl
import os
import re
import shutil
import signal
import subprocess
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
    RGB_MATRIX_DIR,
    SERVICE_NAME,
    SYSTEM_PYTHON,
    VENVS_DIR,
)
from updater.status import (
    mark_updater_interrupted,
    updater_lock_is_held,
    write_status,
)
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

FETCH_TIMEOUT_SECONDS = 120
GIT_COMMAND_TIMEOUT_SECONDS = 60


class UpdateError(RuntimeError):
    """Raised when GameLine Pro cannot be updated safely."""


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
            "Another GameLine Pro update is "
            "already running."
        ) from error

    lock_file.write(
        f"{os.getpid()}\n"
    )
    lock_file.flush()

    return lock_file


def git_environment() -> dict[str, str]:
    """Run Git without prompts and fail a stalled HTTP transfer."""
    environment = os.environ.copy()
    environment.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
        "GCM_INTERACTIVE": "never",
        "GIT_HTTP_LOW_SPEED_LIMIT": "1000",
        "GIT_HTTP_LOW_SPEED_TIME": "30",
    })
    environment.setdefault(
        "GIT_SSH_COMMAND",
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    )
    return environment


def run_git(*arguments: str) -> str:
    result = run_command(
        [
            "/usr/bin/git",
            "-c",
            "credential.interactive=never",
            "-c",
            "credential.helper=",
            f"--git-dir={REPOSITORY_DIR}",
            *arguments,
        ],
        environment=git_environment(),
        timeout=GIT_COMMAND_TIMEOUT_SECONDS,
    )

    return result.stdout.strip()


def stop_process(process: subprocess.Popen) -> None:
    """Stop a Git child and the process group it leads."""
    if process.poll() is not None:
        _close_process_streams(process)
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    _close_process_streams(process)


def _close_process_streams(process: subprocess.Popen) -> None:
    for stream in (process.stdout, process.stderr, process.stdin):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


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


def _record_fetch_progress(
    line: str,
    last_write: float,
) -> float:
    match = re.search(
        r"(Receiving objects|Resolving deltas):\s*(\d+)%",
        line,
    )

    if (
        not match
        or time.monotonic() - last_write < 0.2
    ):
        return last_write

    fraction = int(match.group(2)) / 100

    if match.group(1) == "Receiving objects":
        progress = 5 + int(fraction * 12)
    else:
        progress = 17 + int(fraction * 3)

    write_status(
        "checking",
        line.strip(),
        progress=progress,
        step="Checking repository",
        progress_kind="transfer",
    )
    return time.monotonic()


def fetch_repository() -> None:
    write_status(
        "checking",
        "Connecting to GitHub.",
        progress=5,
        step="Checking repository",
    )

    log("Fetching branches and tags.")

    command = [
        "/usr/bin/git",
        "-c",
        "credential.interactive=never",
        "-c",
        "credential.helper=",
        f"--git-dir={REPOSITORY_DIR}",
        "fetch",
        "--progress",
        "--prune",
        "--tags",
        "origin",
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=git_environment(),
        start_new_session=True,
    )

    output: list[str] = []
    stdout_chunks: list[str] = []
    progress_queue: queue.Queue = queue.Queue()

    def read_stderr() -> None:
        try:
            while True:
                char = process.stderr.read(1)
                if char == "":
                    break
                progress_queue.put(char)
        except Exception:
            pass
        finally:
            progress_queue.put(None)

    def read_stdout() -> None:
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                stdout_chunks.append(chunk)
        except Exception:
            pass

    stderr_thread = threading.Thread(
        target=read_stderr,
        daemon=True,
    )
    stdout_thread = threading.Thread(
        target=read_stdout,
        daemon=True,
    )
    stderr_thread.start()
    stdout_thread.start()

    line = ""
    last_write = 0.0
    timed_out = False
    returncode = 1
    deadline = time.monotonic() + FETCH_TIMEOUT_SECONDS

    try:
        while True:
            if time.monotonic() >= deadline:
                timed_out = True
                stop_process(process)
                break

            try:
                char = progress_queue.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None:
                    try:
                        char = progress_queue.get(timeout=1)
                    except queue.Empty:
                        break
                else:
                    continue

            if char is None:
                break

            if char in ("\r", "\n"):
                if line:
                    output.append(line)
                    if len(output) > 40:
                        output.pop(0)
                    last_write = _record_fetch_progress(
                        line,
                        last_write,
                    )
                line = ""
            else:
                line += char

        if line:
            output.append(line)

        if not timed_out:
            if process.poll() is None:
                try:
                    returncode = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_process(process)
                    timed_out = True
                    returncode = process.returncode or 1
            else:
                returncode = process.returncode or 0
    finally:
        if process.poll() is None:
            stop_process(process)
        else:
            _close_process_streams(process)
        stderr_thread.join(timeout=2)
        stdout_thread.join(timeout=2)

    if timed_out:
        raise UpdateError(
            "GitHub fetch timed out after "
            f"{FETCH_TIMEOUT_SECONDS} seconds."
        )

    if returncode != 0:
        stdout = "".join(stdout_chunks).strip()
        detail = (
            "\n".join(output[-8:])
            or stdout
            or str(returncode)
        )
        raise UpdateError(
            f"Git fetch failed: {detail}"
        )

    write_status(
        "checking",
        "Repository check complete.",
        progress=20,
        step="Checking repository",
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
        f"Preparing GameLine Pro {version}.",
        version,
        progress=22,
        step="Preparing release",
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

    write_status(
        "downloading",
        "Release files ready.",
        version,
        progress=35,
        step="Preparing release",
    )

    return release_path


def build_panel_shift(release_path: Path) -> None:
    script = release_path / "scripts" / "build_panel_shift.sh"
    if not script.is_file():
        log("Panel scroll helper source is missing; continuing.")
        return

    log("Building the panel scroll helper.")
    completed = subprocess.run(
        ["bash", str(script), str(release_path)],
        check=False,
    )
    if completed.returncode != 0:
        log(
            "Panel scroll helper did not build; "
            "the ticker will redraw each column."
        )


RGBMATRIX_IMPORT = (
    "from rgbmatrix import RGBMatrix, RGBMatrixOptions"
)

VENV_RUNTIME_CHECK = """
from rgbmatrix import RGBMatrix, RGBMatrixOptions
import requests
from PIL import Image, ImageDraw
import flask
requests.Session()
Image.new("RGB", (8, 8))
"""


def rgbmatrix_binding_is_healthy(python_path: Path) -> bool:
    """True only if the hzeller LED binding can actually be imported."""
    check = subprocess.run(
        [str(python_path), "-c", RGBMATRIX_IMPORT],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        return False

    locate = subprocess.run(
        [
            str(python_path),
            "-c",
            (
                "import pathlib, rgbmatrix; "
                "print(pathlib.Path(rgbmatrix.__file__)"
                ".resolve().parent / 'core.so')"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if locate.returncode != 0:
        return False

    core_so = Path(locate.stdout.strip())
    return core_so.is_file() and core_so.stat().st_size > 10_000


def venv_runtime_is_healthy(python_path: Path) -> bool:
    """True if LED, Pillow, and requests can all load from this interpreter."""
    if not python_path.is_file():
        return False
    if not rgbmatrix_binding_is_healthy(python_path):
        return False
    check = subprocess.run(
        [str(python_path), "-c", VENV_RUNTIME_CHECK],
        capture_output=True,
        text=True,
        check=False,
    )
    return check.returncode == 0


def _site_packages(python_path: Path) -> Path:
    result = run_command(
        [
            str(python_path),
            "-c",
            (
                "import site; "
                "print(site.getsitepackages()[0])"
            ),
        ]
    )
    return Path(result.stdout.strip())


def _rgbmatrix_package(python_path: Path) -> Path:
    result = run_command(
        [
            str(python_path),
            "-c",
            (
                "import pathlib, rgbmatrix; "
                "print(pathlib.Path(rgbmatrix.__file__)"
                ".resolve().parent)"
            ),
        ]
    )
    return Path(result.stdout.strip())


def copy_directory_verified(source: Path, target: Path) -> None:
    """Copy a package directory and require every file to keep its size."""
    if target.exists():
        shutil.rmtree(target)

    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts:
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination, follow_symlinks=True)
        if destination.stat().st_size != path.stat().st_size:
            raise RuntimeError(
                f"Incomplete copy of {relative}: "
                f"{destination.stat().st_size} bytes, "
                f"expected {path.stat().st_size}."
            )


def pip_install(python_path: Path, *arguments: str) -> None:
    run_command(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            *arguments,
        ]
    )


def install_rgbmatrix_binding(
    python_path: Path,
    source_python: Path,
) -> None:
    """
    Install the hzeller LED binding into a new venv.

    Prefer a size-checked copy of a working local build, then fall back
    to pip installing the packaged tree under /opt/rpi-rgb-led-matrix.
    """
    if rgbmatrix_binding_is_healthy(source_python):
        copy_directory_verified(
            _rgbmatrix_package(source_python),
            _site_packages(python_path) / "rgbmatrix",
        )
        if rgbmatrix_binding_is_healthy(python_path):
            return

    if RGB_MATRIX_DIR.is_dir():
        log(
            "Building the RGB matrix Python binding "
            f"from {RGB_MATRIX_DIR}."
        )
        pip_install(python_path, str(RGB_MATRIX_DIR))

    if not rgbmatrix_binding_is_healthy(python_path):
        raise UpdateError(
            "The RGB matrix Python binding "
            "did not install completely."
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
        if venv_runtime_is_healthy(python_path):
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
        (
            f"Creating environment for "
            f"GameLine Pro {version}."
        ),
        version,
        progress=40,
        step="Creating environment",
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

    write_status(
        "installing",
        "Installing Python tooling.",
        version,
        progress=48,
        step="Installing dependencies",
    )

    write_status(
        "installing",
        "Installing GameLine Pro dependencies.",
        version,
        progress=58,
        step="Installing dependencies",
    )

    requirements_path = (
        release_path / "requirements.txt"
    )

    log(
        f"Installing dependencies for "
        f"{version}."
    )

    pip_install(
        python_path,
        "--upgrade",
        "pip",
        "setuptools",
        "wheel",
    )
    pip_install(
        python_path,
        "-r",
        str(requirements_path),
    )

    current_python = (
        CURRENT_VENV_LINK
        / "bin"
        / "python"
    )

    write_status(
        "installing",
        "Preparing RGB matrix support.",
        version,
        progress=70,
        step="Installing dependencies",
    )

    log("Installing the RGB matrix Python binding.")
    install_rgbmatrix_binding(
        python_path,
        current_python,
    )
    os.sync()

    if not venv_runtime_is_healthy(python_path):
        shutil.rmtree(venv_path, ignore_errors=True)
        raise UpdateError(
            f"Python environment for {version} "
            "did not install completely."
        )

    write_status(
        "installing",
        "Dependencies installed.",
        version,
        progress=78,
        step="Installing dependencies",
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


def stop_scorecast() -> None:
    log("Stopping GameLine Pro for environment install.")
    run_command([
        "/usr/bin/systemctl",
        "stop",
        SERVICE_NAME,
    ])


def restart_scorecast() -> None:
    log("Restarting GameLine Pro.")

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

    write_status(
        "rolling_back",
        "Restoring the previous release.",
        attempted_version,
        progress=95,
        step="Restoring previous release",
    )

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

    try:
        stop_scorecast()
        venv_path = create_release_venv(
            release_path,
            version,
        )
    except (UpdateError, ValidationError) as error:
        restart_scorecast()
        raise UpdateError(
            f"Python environment for {version} "
            f"failed to install: {error}"
        ) from error

    python_path = (
        venv_path / "bin" / "python"
    )
    build_panel_shift(release_path)

    write_status(
        "validating",
        f"Validating GameLine Pro {version}.",
        version,
        progress=80,
        step="Validating release",
    )

    log(
        f"Validating release {version}."
    )

    validate_release(
        release_path,
        python_path,
    )

    write_status(
        "validating",
        "Release validation passed.",
        version,
        progress=90,
        step="Validating release",
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
        f"Restarting GameLine Pro {version}.",
        version,
        progress=95,
        step="Restarting display",
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
            "GameLine Pro updated successfully "
            f"to {version}."
        ),
        version,
    )

    log(
        f"GameLine Pro {version} installed "
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
            "Update GameLine Pro from tagged "
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
        write_status(
            "checking",
            "Starting update.",
            progress=0,
            step="Preparing update",
            run_id=uuid.uuid4().hex,
        )

        (
            latest_tag,
            latest_version,
            current_version,
        ) = check_for_update()

        if latest_version == current_version:
            write_status(
                "current",
                (
                    "GameLine Pro is already "
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
                    f"GameLine Pro {latest_version} "
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


def record_updater_failure(message: str) -> None:
    """Persist a failure without clobbering a different live update."""
    if updater_lock_is_held():
        log(
            "Leaving the running update status unchanged."
        )
        return

    try:
        write_status(
            "failed",
            message,
        )
    except OSError:
        pass


def _exit_after_interruption(signum: int, _frame) -> None:
    mark_updater_interrupted(
        "The updater was interrupted before it finished."
    )
    raise SystemExit(128 + signum)


def _exit_after_unexpected_stop() -> None:
    mark_updater_interrupted(
        "The updater stopped before it finished."
    )


if __name__ == "__main__":
    signal.signal(
        signal.SIGTERM,
        _exit_after_interruption,
    )
    signal.signal(
        signal.SIGINT,
        _exit_after_interruption,
    )
    atexit.register(
        _exit_after_unexpected_stop
    )

    try:
        raise SystemExit(
            main()
        )

    except Exception as error:
        message = str(error)

        log(
            f"ERROR: {message}"
        )
        record_updater_failure(message)
        raise SystemExit(1)
