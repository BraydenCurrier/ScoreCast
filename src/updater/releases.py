"""Cached lookup of the newest ScoreCast release and its description."""

from __future__ import annotations

import subprocess
import threading
import time
from urllib.parse import quote

import requests

from updater.config import REPOSITORY_DIR
from updater.updater import version_key


REFRESH_SECONDS = 10 * 60
FAILURE_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 4
MAX_TAG_PAGES = 3
MAX_DESCRIPTION_CHARS = 4000

GITHUB_API = "https://api.github.com"
_REMOTE_MARKERS = (
    "https://github.com/",
    "http://github.com/",
    "git@github.com:",
    "ssh://git@github.com/",
)

_cache_guard = threading.Lock()
_refresh_guard = threading.Lock()
_cache: dict | None = None


def clear_release_cache() -> None:
    global _cache
    with _cache_guard:
        _cache = None


def latest_release_info(current_version: str) -> dict:
    """Return whether a newer tagged release exists, plus its description."""
    cached = _cached_info(current_version)
    if cached is not None:
        return cached

    with _refresh_guard:
        cached = _cached_info(current_version)
        if cached is not None:
            return cached

        try:
            info = _fetch_release(current_version)
            ok = True
        except (
            OSError,
            subprocess.TimeoutExpired,
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ):
            info = None
            ok = False

        return _store(current_version, info, ok)


def parse_github_remote(url: str) -> tuple[str, str] | None:
    remote = url.strip()
    if remote.endswith(".git"):
        remote = remote[:-4]

    for marker in _REMOTE_MARKERS:
        if remote.startswith(marker):
            path = remote[len(marker):].strip("/")
            owner, separator, repo = path.partition("/")
            if separator and owner and repo and "/" not in repo:
                return owner, repo
            return None

    return None


def select_latest_tag(names: list[str]) -> str | None:
    valid = [
        name.strip()
        for name in names
        if version_key(name.strip()) != (-1, -1, -1)
    ]
    if not valid:
        return None
    return max(valid, key=version_key)


def split_message(message: str) -> tuple[str, str]:
    text = message.replace("\r\n", "\n").strip()
    if not text:
        return "", ""
    title, _separator, body = text.partition("\n")
    return title.strip(), body.strip()


def notes_from_payloads(
    tag: str,
    release_payload: dict | None,
    commit_payload: dict | None,
) -> tuple[str, str]:
    release_body = ""
    release_name = ""
    if isinstance(release_payload, dict):
        release_body = str(release_payload.get("body") or "").strip()
        release_name = str(release_payload.get("name") or "").strip()

    if release_body:
        if release_name and not _is_version_label(release_name, tag):
            return release_name, _clip(release_body)
        title, body = split_message(release_body)
        return title, _clip(body)

    message = ""
    if isinstance(commit_payload, dict):
        commit = commit_payload.get("commit") or {}
        if isinstance(commit, dict):
            message = str(commit.get("message") or "")

    title, body = split_message(message)
    if not title:
        title = "A new version is ready to install."
    return title, _clip(body)


def _fetch_release(current_version: str) -> dict:
    repository = github_repository()
    if repository is None:
        return _empty(current_version)

    owner, repo = repository
    names = _tag_names(owner, repo)
    latest_tag = select_latest_tag(names)
    if latest_tag is None:
        return _empty(current_version)

    latest_version = latest_tag.removeprefix("v")
    current_key = version_key(current_version)
    newer = (
        current_key != (-1, -1, -1)
        and version_key(latest_tag) > current_key
    )
    if not newer:
        info = _empty(current_version)
        info["latest_version"] = latest_version
        return info

    encoded = quote(latest_tag, safe="")
    release_payload = _get_json(
        f"{GITHUB_API}/repos/{owner}/{repo}/releases/tags/{encoded}"
    )
    commit_payload = None
    if not _release_has_body(release_payload):
        commit_payload = _get_json(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits/{encoded}"
        )

    title, description = notes_from_payloads(
        latest_tag,
        release_payload,
        commit_payload,
    )
    return {
        "update_available": True,
        "latest_version": latest_version,
        "current_version": current_version,
        "title": title,
        "description": description,
    }


def github_repository() -> tuple[str, str] | None:
    if not REPOSITORY_DIR.exists():
        return None

    result = subprocess.run(
        [
            "/usr/bin/git",
            f"--git-dir={REPOSITORY_DIR}",
            "remote",
            "get-url",
            "origin",
        ],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return None
    return parse_github_remote(result.stdout.strip())


def _tag_names(owner: str, repo: str) -> list[str]:
    names: list[str] = []
    url = (
        f"{GITHUB_API}/repos/{owner}/{repo}/tags"
        "?per_page=100"
    )
    for _page in range(MAX_TAG_PAGES):
        payload, next_url = _get_json_page(url)
        if not isinstance(payload, list):
            break
        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        if not next_url:
            break
        url = next_url
    return names


def _get_json(url: str):
    payload, _next = _get_json_page(url)
    return payload


def _get_json_page(url: str):
    response = requests.get(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ScoreCast",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    return response.json(), _next_link(response.headers.get("Link", ""))


def _next_link(header: str) -> str | None:
    for part in header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">")
        if start != -1 and end > start:
            return section[start + 1:end]
    return None


def _release_has_body(payload) -> bool:
    return (
        isinstance(payload, dict)
        and bool(str(payload.get("body") or "").strip())
    )


def _is_version_label(name: str, tag: str) -> bool:
    plain = tag.removeprefix("v")
    return name.strip() in {tag, plain, f"v{plain}"}


def _clip(text: str) -> str:
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[:MAX_DESCRIPTION_CHARS].rstrip() + "…"


def _empty(current_version: str) -> dict:
    return {
        "update_available": False,
        "latest_version": None,
        "current_version": current_version,
        "title": "",
        "description": "",
    }


def _cached_info(current_version: str) -> dict | None:
    now = time.monotonic()
    with _cache_guard:
        cached = _cache
        if not cached or cached["current_version"] != current_version:
            return None
        limit = REFRESH_SECONDS if cached["ok"] else FAILURE_SECONDS
        if now - cached["fetched_at"] >= limit:
            return None
        return dict(cached["info"])


def _store(current_version: str, info: dict | None, ok: bool) -> dict:
    global _cache
    with _cache_guard:
        previous = _cache
        if (
            not ok
            and previous
            and previous["current_version"] == current_version
            and previous["ok"]
        ):
            kept = dict(previous["info"])
            _cache = {
                "current_version": current_version,
                "fetched_at": time.monotonic(),
                "ok": False,
                "info": kept,
            }
            return dict(kept)

        stored = info or _empty(current_version)
        _cache = {
            "current_version": current_version,
            "fetched_at": time.monotonic(),
            "ok": ok,
            "info": stored,
        }
        return dict(stored)
