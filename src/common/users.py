from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from common.settings import SETTINGS_DIR, ensure_settings_directory


BOOTSTRAP_PASSWORD = "ticker123"
USERS_FILE = SETTINGS_DIR / "users.json"
WEB_SECRET_FILE = SETTINGS_DIR / "web-secret"

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
MIN_PASSWORD_LENGTH = 8
MAX_PROFILES = 20
PASSWORD_HASH_ITERATIONS = 260_000

_users_lock = threading.RLock()
_cached_store: dict[str, Any] | None = None
_cached_mtime_ns: int | None = None


class UserError(ValueError):
    """Raised when a profile cannot be created or updated."""


class UserStoreError(RuntimeError):
    """Raised when the on-disk profile store cannot be read safely."""


def get_or_create_web_secret() -> str:
    ensure_settings_directory()

    try:
        existing = WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass

    secret = secrets.token_hex(32)

    try:
        WEB_SECRET_FILE.write_text(secret + "\n", encoding="utf-8")
        os.chmod(WEB_SECRET_FILE, 0o600)
    except OSError:
        pass

    return secret


def _write_json_atomic(path, data: dict[str, Any]) -> None:
    ensure_settings_directory()

    temporary_path = path.with_name(f".{path.name}.tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _load_store() -> dict[str, Any]:
    try:
        with USERS_FILE.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    except FileNotFoundError:
        return {"users": []}
    except (OSError, json.JSONDecodeError) as error:
        raise UserStoreError(
            "The profiles file is unreadable. "
            "Fix or restore users.json before signing in."
        ) from error

    if not isinstance(loaded, dict):
        raise UserStoreError(
            "The profiles file is invalid. "
            "Fix or restore users.json before signing in."
        )

    users = loaded.get("users", [])
    if not isinstance(users, list):
        raise UserStoreError(
            "The profiles file is invalid. "
            "Fix or restore users.json before signing in."
        )

    return {"users": users}


def _save_store(store: dict[str, Any]) -> None:
    global _cached_store, _cached_mtime_ns

    _write_json_atomic(USERS_FILE, store)
    _cached_store = store

    try:
        _cached_mtime_ns = USERS_FILE.stat().st_mtime_ns
    except OSError:
        _cached_mtime_ns = None


def _get_store() -> dict[str, Any]:
    global _cached_store, _cached_mtime_ns

    try:
        current_mtime_ns = USERS_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        _cached_store = {"users": []}
        _cached_mtime_ns = None
        return _cached_store

    if (
        _cached_store is not None
        and _cached_mtime_ns == current_mtime_ns
    ):
        return _cached_store

    store = _load_store()
    _cached_store = store
    _cached_mtime_ns = current_mtime_ns
    return store


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user.get("id", "")),
        "username": str(user.get("username", "")),
        "role": str(user.get("role", "user")),
        "created_at": str(user.get("created_at", "")),
    }


def list_users() -> list[dict[str, Any]]:
    with _users_lock:
        store = _get_store()
        return [_public_user(user) for user in store["users"]]


def has_users() -> bool:
    with _users_lock:
        return bool(_get_store()["users"])


def get_user_by_id(user_id: str | None) -> dict[str, Any] | None:
    if not user_id:
        return None

    with _users_lock:
        store = _get_store()
        for user in store["users"]:
            if str(user.get("id", "")) == str(user_id):
                return _public_user(user)

    return None


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def _check_password(stored_hash: str, password: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = str(stored_hash).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False

        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(expected.hex(), digest_hex)


def normalize_username(username: str) -> str:
    return str(username or "").strip()


def validate_username(username: str) -> str:
    cleaned = normalize_username(username)

    if not USERNAME_PATTERN.fullmatch(cleaned):
        raise UserError(
            "Usernames must be 3 to 32 characters and use only letters, numbers, and underscores."
        )

    return cleaned


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(
            f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters."
        )

    if len(password) > 128:
        raise UserError("Passwords must be 128 characters or fewer.")

    return password


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    cleaned_username = normalize_username(username)
    lookup = cleaned_username.casefold()

    if not cleaned_username or not password:
        return None

    with _users_lock:
        store = _get_store()

        for user in store["users"]:
            stored_name = str(user.get("username", ""))
            if stored_name.casefold() != lookup:
                continue

            if _check_password(str(user.get("password_hash", "")), password):
                return _public_user(user)

            return None

    return None


def create_user(
    username: str,
    password: str,
    *,
    role: str = "user",
) -> dict[str, Any]:
    cleaned_username = validate_username(username)
    cleaned_password = validate_password(password)

    if role not in {"root", "user"}:
        raise UserError("Invalid profile role.")

    with _users_lock:
        store = _get_store()
        users = store["users"]

        if len(users) >= MAX_PROFILES:
            raise UserError("The maximum number of profiles has been reached.")

        if any(
            str(user.get("username", "")).casefold() == cleaned_username.casefold()
            for user in users
        ):
            raise UserError("That username is already taken.")

        if not users:
            role = "root"
        elif role == "root":
            raise UserError("Only the original account can be the root user.")

        user = {
            "id": secrets.token_hex(16),
            "username": cleaned_username,
            "password_hash": _hash_password(cleaned_password),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        users.append(user)
        _save_store(store)
        return _public_user(user)


def delete_user(user_id: str, *, actor_id: str) -> None:
    with _users_lock:
        store = _get_store()
        users = store["users"]

        target = next(
            (user for user in users if str(user.get("id", "")) == str(user_id)),
            None,
        )

        if target is None:
            raise UserError("That profile was not found.")

        if str(target.get("id", "")) == str(actor_id):
            raise UserError("You cannot delete the account you are using.")

        if str(target.get("role", "")) == "root":
            raise UserError("The root profile cannot be deleted.")

        store["users"] = [
            user for user in users if str(user.get("id", "")) != str(user_id)
        ]
        _save_store(store)
