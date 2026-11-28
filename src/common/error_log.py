"""Errors the app can show without a terminal.

Each entry keeps a stable code, a short explanation, and the technical
detail. Repeats of the same failure update the last entry instead of
filling the file.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()
_last_write = {}
_hooks_installed = False
_MAX_ENTRIES = 200
_DETAIL_LIMIT = 1200

_CATALOG = {
    "SPORT-MLB": "Baseball scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-NFL": "Football scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-CFB": "College football scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-NBA": "Basketball scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-CBB": "College basketball scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-NHL": "Hockey scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-SOCCER": "Soccer scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-PGA": "Golf scores could not be loaded. The board is still showing the last scores it had.",
    "SPORT-STOCKS": "Stock quotes could not be loaded. The board is still showing the last quotes it had.",
    "SPORT-FANTASY": "Fantasy scores could not be loaded. The board is still showing the last scores it had.",
    "GAMES-REFRESH": "Scores could not be refreshed. The board kept the scores it already had.",
    "REFRESH-WORKER": "The score refresh stopped early. The board kept the scores it already had.",
    "CARD-DRAW": "A score card could not be drawn. That game shows an error card instead.",
    "TICKER-REBUILD": "The scrolling board could not be rebuilt.",
    "DISPLAY-DRAW": "The board could not update the picture it is showing.",
    "MESSAGE-DRAW": "A custom message could not be drawn on the board.",
    "BETS-REFRESH": "Tracked bets could not be refreshed.",
    "BET-STORE": "Saved bets could not be opened.",
    "PLAYERS-REFRESH": "Player cards could not be refreshed.",
    "MODE-SELECT": "A display mode could not update the games on the board.",
    "SETTINGS-LOAD": "Saved settings could not be read. The app is using defaults until they can be saved again.",
    "TIMEZONE": "The display timezone could not be updated.",
    "WEB-BIND": "The app could not open its page on that port.",
    "WEB-ERROR": "A page in the app hit an unexpected error.",
    "APP-CRASH": "The app hit an unexpected error.",
}


def _log_path(path=None):
    if path is not None:
        return Path(path)
    override = os.environ.get("SCORECAST_ERROR_LOG", "").strip()
    if override:
        return Path(override)
    from common.settings import SETTINGS_DIR
    return Path(SETTINGS_DIR) / "error_log.json"


def _detail_text(error):
    if error is None:
        return ""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error)
    text = " ".join(text.split())
    if len(text) > _DETAIL_LIMIT:
        text = text[: _DETAIL_LIMIT - 1] + "…"
    return text


def _reason(detail):
    text = detail.lower()
    if any(token in text for token in ("timed out", "timeout", "read timed out")):
        return "The score feed did not answer in time. Check the Wi-Fi connection."
    if any(
        token in text
        for token in (
            "name or service not known",
            "temporary failure in name resolution",
            "failed to resolve",
            "nodename nor servname",
        )
    ):
        return "The board could not look up the score feed. Wi-Fi may be connected without internet."
    if any(
        token in text
        for token in (
            "connection refused",
            "network is unreachable",
            "connectionerror",
            "max retries exceeded",
            "network unreachable",
        )
    ):
        return "The board could not reach the score feed. Check that Wi-Fi has internet."
    if "429" in text or "too many requests" in text:
        return "The score feed asked the board to slow down. It will try again."
    if any(token in text for token in ("401", "403", "unauthorized", "forbidden")):
        return "The score feed refused the request."
    if "404" in text:
        return "The score feed did not have the data the board asked for."
    if any(token in text for token in ("500", "502", "503", "504")):
        return "The score feed had a problem on its side. The board will try again."
    if "json" in text and any(token in text for token in ("decode", "expecting", "invalid")):
        return "The score feed sent a response the app could not read."
    if "permission denied" in text:
        return "The app was not allowed to read or write a file it needs."
    return ""


def describe(code, detail=""):
    """Plain explanation for an error code and its technical detail."""
    lead = _CATALOG.get(
        str(code or "").strip().upper(),
        "Something went wrong. The details below are what the app recorded.",
    )
    reason = _reason(detail or "")
    if reason:
        return f"{lead} {reason}"
    return lead


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S%z")


def _clock():
    try:
        from common.timezone import get_local_timezone
        return datetime.now(get_local_timezone())
    except Exception:
        return datetime.now().astimezone()


def _read_entries(path):
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    entries = loaded.get("entries") if isinstance(loaded, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _write_entries(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"entries": entries}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def record_error(code, error, *, summary="", source="", path=None, min_interval=30):
    """Save an error. Same code and detail repeats are counted together."""
    try:
        code = str(code or "APP-CRASH").strip().upper()[:40]
        detail = _detail_text(error)
        if not detail and not summary:
            return None
        target = _log_path(path)
        signature = (str(target), code, detail)
        now_m = time.monotonic()
        with _lock:
            last = _last_write.get(signature)
            if min_interval and last is not None and now_m - last < min_interval:
                return None
            _last_write[signature] = now_m

        moment = _clock()
        shown = summary or describe(code, detail)
        with _lock:
            entries = _read_entries(target)
            if (
                entries
                and entries[-1].get("code") == code
                and entries[-1].get("detail") == detail
            ):
                current = entries[-1]
                current["count"] = int(current.get("count") or 1) + 1
                current["last_at"] = _stamp(moment)
                current["summary"] = shown
            else:
                entries.append({
                    "at": _stamp(moment),
                    "last_at": _stamp(moment),
                    "count": 1,
                    "code": code,
                    "summary": shown,
                    "detail": detail,
                    "source": str(source or "")[:80],
                })
            if len(entries) > _MAX_ENTRIES:
                entries = entries[-_MAX_ENTRIES:]
            _write_entries(target, entries)
            return dict(entries[-1])
    except Exception:
        return None


def recent_errors(limit=100, path=None):
    target = _log_path(path)
    with _lock:
        entries = _read_entries(target)
    if limit is not None:
        entries = entries[-int(limit):]
    return list(reversed(entries))


def clear_errors(path=None):
    target = _log_path(path)
    with _lock:
        _last_write.clear()
        try:
            _write_entries(target, [])
        except OSError:
            return False
    return True


def report_text(entries=None, path=None):
    """Plain text a person can copy and send."""
    if entries is None:
        entries = recent_errors(path=path)
    lines = ["GameLine error log"]
    if not entries:
        lines.append("No errors recorded.")
        return "\n".join(lines)
    for entry in entries:
        count = int(entry.get("count") or 1)
        when = entry.get("last_at") or entry.get("at") or ""
        times = f" ({count} times)" if count > 1 else ""
        lines.append("")
        lines.append(f"{entry.get('code') or 'APP-CRASH'}{times}")
        lines.append(when)
        lines.append(entry.get("summary") or "")
        detail = entry.get("detail") or ""
        if detail:
            lines.append(detail)
    return "\n".join(lines).rstrip() + "\n"


def install_excepthook():
    """Record crashes that escape a thread."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    previous = sys.excepthook

    def _hook(exc_type, exc, tb):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            record_error("APP-CRASH", exc, source="app")
        previous(exc_type, exc, tb)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        previous_thread = threading.excepthook

        def _thread_hook(args):
            exc_type = args.exc_type
            if exc_type and not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
                name = args.thread.name if args.thread is not None else "thread"
                record_error("APP-CRASH", args.exc_value, source=name)
            previous_thread(args)

        threading.excepthook = _thread_hook
