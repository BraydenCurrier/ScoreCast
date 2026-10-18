import argparse
import io
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from updater.status import (
    ACTIVE_STATES,
    INTERRUPTED_MESSAGE,
    mark_start_requested,
    mark_updater_interrupted,
    read_status,
    reconcile_status,
    service_state_is_running,
    updater_lock_is_held,
    write_status,
)
from updater.updater import (
    UpdateError,
    fetch_repository,
    find_latest_tag,
    install_update,
    main,
    record_updater_failure,
)
from updater.validation import ValidationError, run_command


class StatusFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.status_file = root / "update-status.json"
        self.lock_file = root / "update.lock"
        self.addCleanup(self.temp.cleanup)
        for patcher in (
            mock.patch(
                "updater.status.STATUS_FILE",
                self.status_file,
            ),
            mock.patch(
                "updater.status.LOCK_FILE",
                self.lock_file,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class ServiceStateTests(unittest.TestCase):
    def test_oneshot_activating_counts_as_running(self):
        self.assertTrue(service_state_is_running("activating"))
        self.assertTrue(service_state_is_running("active"))
        self.assertTrue(service_state_is_running("deactivating"))
        self.assertFalse(service_state_is_running("inactive"))
        self.assertFalse(service_state_is_running("failed"))
        self.assertFalse(service_state_is_running(""))


class StaleStatusTests(StatusFixture):
    def test_stopped_updater_becomes_a_retryable_failure(self):
        write_status(
            "checking",
            "Connecting to GitHub.",
            "1.8.1",
            progress=5,
            step="Checking repository",
        )

        status = reconcile_status(service_running=False)

        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["message"], INTERRUPTED_MESSAGE)
        self.assertTrue(status["interrupted"])
        self.assertEqual(status["version"], "1.8.1")
        self.assertNotIn(status["state"], ACTIVE_STATES)

        again = reconcile_status(service_running=False)
        self.assertEqual(again["state"], "failed")
        self.assertEqual(again["message"], INTERRUPTED_MESSAGE)

    def test_live_service_keeps_the_saved_status(self):
        write_status(
            "checking",
            "Connecting to GitHub.",
            progress=5,
        )

        status = reconcile_status(service_running=True)

        self.assertEqual(status["state"], "checking")
        self.assertEqual(
            status["message"],
            "Connecting to GitHub.",
        )

    def test_held_lock_keeps_the_saved_status(self):
        write_status(
            "downloading",
            "Preparing GameLine Pro 1.9.0.",
            "1.9.0",
            progress=22,
        )
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_file.open("a+")
        self.addCleanup(handle.close)
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        status = reconcile_status(service_running=False)

        self.assertEqual(status["state"], "downloading")
        self.assertTrue(updater_lock_is_held())

    def test_new_request_is_not_marked_failed_during_startup(self):
        mark_start_requested("1.8.1")

        status = reconcile_status(service_running=False)

        self.assertEqual(status["state"], "checking")
        self.assertEqual(status["message"], "Starting the updater.")
        self.assertIn(status["state"], ACTIVE_STATES)

    def test_expired_start_request_can_be_retried(self):
        write_status(
            "checking",
            "Starting the updater.",
            "1.8.1",
            progress=1,
            step="Preparing update",
            start_requested_at="2020-01-01T00:00:00+00:00",
        )

        status = reconcile_status(service_running=False)

        self.assertEqual(status["state"], "failed")
        self.assertNotIn(status["state"], ACTIVE_STATES)

    def test_activating_service_survives_a_fresh_start_request(self):
        mark_start_requested("1.8.1")

        status = reconcile_status(service_running=True)

        self.assertEqual(status["state"], "checking")

    def test_terminal_status_is_left_alone(self):
        write_status(
            "complete",
            "GameLine Pro updated successfully to 1.8.1.",
            "1.8.1",
        )

        status = reconcile_status(service_running=False)

        self.assertEqual(status["state"], "complete")

    def test_unexpected_exit_records_failure_once(self):
        write_status(
            "installing",
            "Installing GameLine Pro dependencies.",
            "1.9.0",
            progress=58,
        )

        mark_updater_interrupted(
            "The updater stopped before it finished."
        )
        mark_updater_interrupted(
            "The updater stopped before it finished."
        )

        status = read_status()
        self.assertEqual(status["state"], "failed")
        self.assertIn("stopped", status["message"])

        write_status(
            "current",
            "GameLine Pro is already up to date.",
            "1.8.1",
        )
        mark_updater_interrupted("should not replace success")
        self.assertEqual(read_status()["state"], "current")

    def test_failure_writer_does_not_clobber_a_live_update(self):
        write_status(
            "checking",
            "Connecting to GitHub.",
            progress=5,
        )
        handle = self.lock_file.open("a+")
        self.addCleanup(handle.close)
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        record_updater_failure(
            "Another GameLine Pro update is already running."
        )

        self.assertEqual(read_status()["state"], "checking")


class GitFetchTests(StatusFixture):
    def _git(self, *arguments, cwd=None):
        completed = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=GameLine Pro Test",
                *arguments,
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
            )
            self.fail(f"git {' '.join(arguments)} failed: {detail}")

    def test_fetch_updates_a_local_repository(self):
        root = Path(self.temp.name)
        origin = root / "origin.git"
        work = root / "work"
        mirror = root / "repo.git"

        self._git("init", "--bare", str(origin))
        self._git("clone", str(origin), str(work))
        (work / "README").write_text("one\n", encoding="utf-8")
        self._git("add", "README", cwd=work)
        self._git("commit", "-m", "one", cwd=work)
        self._git("tag", "v1.2.3", cwd=work)
        self._git("push", "origin", "HEAD", cwd=work)
        self._git("push", "origin", "v1.2.3", cwd=work)
        self._git("clone", "--bare", str(origin), str(mirror))

        (work / "README").write_text("two\n", encoding="utf-8")
        self._git("commit", "-am", "two", cwd=work)
        self._git("tag", "v1.2.4", cwd=work)
        self._git("push", "origin", "HEAD", cwd=work)
        self._git("push", "origin", "v1.2.4", cwd=work)

        with mock.patch(
            "updater.updater.REPOSITORY_DIR",
            mirror,
        ):
            fetch_repository()
            self.assertEqual(find_latest_tag(), "v1.2.4")

        status = read_status()
        self.assertEqual(status["state"], "checking")
        self.assertIn("complete", status["message"].lower())

    def test_fetch_reports_git_failure(self):
        missing = Path(self.temp.name) / "missing"
        missing.mkdir()

        with mock.patch(
            "updater.updater.REPOSITORY_DIR",
            missing,
        ):
            with self.assertRaises(UpdateError) as caught:
                fetch_repository()

        self.assertIn("Git fetch failed", str(caught.exception))
        self.assertIn("not a git repository", str(caught.exception))

    def test_fetch_timeout_stops_the_child(self):
        hung_stderr = _HungStream()
        hung_stdout = _HungStream()
        process = mock.Mock()
        process.stderr = hung_stderr
        process.stdout = hung_stdout
        process.stdin = None
        process.pid = 4242
        process.returncode = None
        process.poll.return_value = None

        def stop(proc):
            proc.stderr.close()
            proc.stdout.close()
            proc.poll.return_value = -9
            proc.returncode = -9

        with (
            mock.patch(
                "updater.updater.FETCH_TIMEOUT_SECONDS",
                0.3,
            ),
            mock.patch(
                "updater.updater.subprocess.Popen",
                return_value=process,
            ) as popen,
            mock.patch(
                "updater.updater.stop_process",
                side_effect=stop,
            ) as stop_process,
        ):
            with self.assertRaises(UpdateError) as caught:
                fetch_repository()

        self.assertIn("timed out", str(caught.exception))
        stop_process.assert_called()
        command = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertIn("credential.interactive=never", command)
        self.assertIn("credential.helper=", command)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GIT_ASKPASS"], "/bin/false")

    def test_git_command_timeout_is_reported(self):
        with mock.patch(
            "updater.validation.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["git"],
                timeout=3,
            ),
        ):
            with self.assertRaises(ValidationError) as caught:
                run_command(
                    ["/usr/bin/git", "status"],
                    timeout=3,
                )

        self.assertIn("timed out", str(caught.exception))


class InstallFlowTests(StatusFixture):
    def test_successful_install_records_completion(self):
        with (
            mock.patch(
                "updater.updater.resolve_link",
                side_effect=[
                    Path("/opt/scorecast/releases/1.8.1"),
                    Path("/opt/scorecast/venvs/1.8.1"),
                ],
            ),
            mock.patch(
                "updater.updater.create_release",
                return_value=Path("/opt/scorecast/releases/1.9.0"),
            ),
            mock.patch(
                "updater.updater.create_release_venv",
                return_value=Path("/opt/scorecast/venvs/1.9.0"),
            ),
            mock.patch("updater.updater.stop_scorecast"),
            mock.patch("updater.updater.build_panel_shift"),
            mock.patch("updater.updater.validate_release"),
            mock.patch("updater.updater.replace_symlink"),
            mock.patch("updater.updater.restart_scorecast"),
            mock.patch("updater.updater.wait_for_service_health"),
        ):
            install_update("v1.9.0", "1.9.0")

        status = read_status()
        self.assertEqual(status["state"], "complete")
        self.assertIn("1.9.0", status["message"])
        self.assertEqual(status["version"], "1.9.0")

    def test_validation_failure_rolls_back(self):
        with (
            mock.patch(
                "updater.updater.resolve_link",
                side_effect=[
                    Path("/opt/scorecast/releases/1.8.1"),
                    Path("/opt/scorecast/venvs/1.8.1"),
                ],
            ),
            mock.patch(
                "updater.updater.create_release",
                return_value=Path("/opt/scorecast/releases/1.9.0"),
            ),
            mock.patch(
                "updater.updater.create_release_venv",
                return_value=Path("/opt/scorecast/venvs/1.9.0"),
            ),
            mock.patch("updater.updater.stop_scorecast"),
            mock.patch("updater.updater.build_panel_shift"),
            mock.patch("updater.updater.validate_release"),
            mock.patch("updater.updater.replace_symlink") as replace_symlink,
            mock.patch("updater.updater.restart_scorecast"),
            mock.patch(
                "updater.updater.wait_for_service_health",
                side_effect=[
                    ValidationError("dashboard did not return"),
                    None,
                ],
            ),
        ):
            with self.assertRaises(UpdateError):
                install_update("v1.9.0", "1.9.0")

        self.assertEqual(read_status()["state"], "rolled_back")
        self.assertGreaterEqual(replace_symlink.call_count, 2)

    def test_main_skips_install_when_already_current(self):
        with (
            mock.patch("updater.updater.require_root"),
            mock.patch("updater.updater.require_installation"),
            mock.patch(
                "updater.updater.acquire_lock",
                return_value=mock.Mock(),
            ),
            mock.patch(
                "updater.updater.check_for_update",
                return_value=("v1.8.1", "1.8.1", "1.8.1"),
            ),
            mock.patch("updater.updater.install_update") as install,
            mock.patch(
                "updater.updater.parse_arguments",
                return_value=argparse.Namespace(
                    check_only=False,
                ),
            ),
        ):
            self.assertEqual(main(), 0)

        install.assert_not_called()
        self.assertEqual(read_status()["state"], "current")

    def test_main_installs_a_newer_release(self):
        with (
            mock.patch("updater.updater.require_root"),
            mock.patch("updater.updater.require_installation"),
            mock.patch(
                "updater.updater.acquire_lock",
                return_value=mock.Mock(),
            ),
            mock.patch(
                "updater.updater.check_for_update",
                return_value=("v2.0.0", "2.0.0", "1.8.1"),
            ),
            mock.patch("updater.updater.install_update") as install,
            mock.patch(
                "updater.updater.parse_arguments",
                return_value=argparse.Namespace(
                    check_only=False,
                ),
            ),
        ):
            self.assertEqual(main(), 0)

        install.assert_called_once_with("v2.0.0", "2.0.0")


class _HungStream(io.TextIOBase):
    def __init__(self):
        self._closed = threading.Event()

    def read(self, size=-1):
        self._closed.wait(timeout=5)
        return ""

    def close(self):
        self._closed.set()
        super().close()
