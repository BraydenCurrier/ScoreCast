from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.settings import SETTINGS_DIR, ensure_settings_directory

from bets.catalog import KIND_PARLAY, KIND_SINGLE, OPEN_STATUSES, STATUS_PENDING
from bets.odds import parse_american_odds, parse_stake


DB_PATH = SETTINGS_DIR / "bets.sqlite"

_lock = threading.RLock()
_initialized = False


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    ensure_settings_directory()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=8,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_store() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        connection = _connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sportsbook TEXT,
                    stake REAL,
                    odds_american INTEGER,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    settled_at TEXT,
                    manual_result INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_bets_user
                    ON bets(user_id, archived, status);

                CREATE TABLE IF NOT EXISTS legs (
                    id TEXT PRIMARY KEY,
                    bet_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    league TEXT NOT NULL,
                    market TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    line REAL,
                    odds_american INTEGER,
                    event_id TEXT,
                    event_label TEXT,
                    player_id TEXT,
                    player_name TEXT,
                    team TEXT,
                    opponent TEXT,
                    home_team TEXT,
                    away_team TEXT,
                    status TEXT NOT NULL,
                    current_value REAL,
                    final_value REAL,
                    game_status TEXT,
                    period TEXT,
                    clock TEXT,
                    stale INTEGER NOT NULL DEFAULT 0,
                    settle_source TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(bet_id) REFERENCES bets(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_legs_bet ON legs(bet_id, position);
                CREATE INDEX IF NOT EXISTS idx_legs_event ON legs(league, event_id);
                CREATE INDEX IF NOT EXISTS idx_legs_status ON legs(status);

                CREATE TABLE IF NOT EXISTS notices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    bet_id TEXT,
                    leg_id TEXT,
                    notice_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    shown INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_notices_open
                    ON notices(shown, created_at);
                """
            )
        finally:
            connection.close()
        _initialized = True


def _rows(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _fetch_legs(connection: sqlite3.Connection, bet_id: str) -> list[dict[str, Any]]:
    return _rows(
        connection.execute(
            """
            SELECT * FROM legs
            WHERE bet_id = ?
            ORDER BY position ASC
            """,
            (bet_id,),
        ).fetchall()
    )


def _attach_legs(
    connection: sqlite3.Connection,
    bets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not bets:
        return []
    ids = [bet["id"] for bet in bets]
    placeholders = ",".join("?" for _ in ids)
    legs = _rows(
        connection.execute(
            f"""
            SELECT * FROM legs
            WHERE bet_id IN ({placeholders})
            ORDER BY position ASC
            """,
            ids,
        ).fetchall()
    )
    by_bet: dict[str, list] = {bet_id: [] for bet_id in ids}
    for leg in legs:
        by_bet.setdefault(leg["bet_id"], []).append(leg)
    for bet in bets:
        bet["legs"] = by_bet.get(bet["id"], [])
    return bets


def get_bet(bet_id: str, user_id: str) -> dict[str, Any] | None:
    init_store()
    with _lock:
        connection = _connect()
        try:
            row = connection.execute(
                "SELECT * FROM bets WHERE id = ? AND user_id = ?",
                (bet_id, user_id),
            ).fetchone()
            if row is None:
                return None
            bet = dict(row)
            bet["legs"] = _fetch_legs(connection, bet_id)
            return bet
        finally:
            connection.close()


def list_bets(
    user_id: str,
    *,
    status: str | None = None,
    archived: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    init_store()
    clauses = ["user_id = ?", "archived = ?"]
    params: list[Any] = [user_id, 1 if archived else 0]
    if status == "open":
        clauses.append(
            "status IN (" + ",".join("?" for _ in OPEN_STATUSES) + ")"
        )
        params.extend(sorted(OPEN_STATUSES))
    elif status == "settled":
        clauses.append("status NOT IN (" + ",".join("?" for _ in OPEN_STATUSES) + ")")
        params.extend(sorted(OPEN_STATUSES))
    elif status:
        clauses.append("status = ?")
        params.append(status)

    sql = (
        "SELECT * FROM bets WHERE "
        + " AND ".join(clauses)
        + " ORDER BY datetime(created_at) DESC LIMIT ?"
    )
    params.append(int(limit))

    with _lock:
        connection = _connect()
        try:
            bets = _rows(connection.execute(sql, params).fetchall())
            return _attach_legs(connection, bets)
        finally:
            connection.close()


def list_open_bets() -> list[dict[str, Any]]:
    init_store()
    with _lock:
        connection = _connect()
        try:
            bets = _rows(
                connection.execute(
                    """
                    SELECT * FROM bets
                    WHERE archived = 0
                      AND status IN ({})
                    ORDER BY datetime(created_at) ASC
                    """.format(
                        ",".join("?" for _ in OPEN_STATUSES)
                    ),
                    tuple(sorted(OPEN_STATUSES)),
                ).fetchall()
            )
            return _attach_legs(connection, bets)
        finally:
            connection.close()


def list_user_history(user_id: str) -> list[dict[str, Any]]:
    return list_bets(user_id, archived=False, limit=1000)


def _new_id() -> str:
    return uuid.uuid4().hex


def create_bet(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    init_store()
    kind = str(payload.get("kind") or KIND_SINGLE).lower()
    if kind not in {KIND_SINGLE, KIND_PARLAY}:
        raise ValueError("Bet type must be single or parlay.")

    legs = list(payload.get("legs") or [])
    if kind == KIND_SINGLE and len(legs) != 1:
        raise ValueError("A single bet needs exactly one leg.")
    if kind == KIND_PARLAY and len(legs) < 2:
        raise ValueError("A parlay needs at least two legs.")
    if len(legs) > 12:
        raise ValueError("Parlays are limited to 12 legs.")

    stake = parse_stake(payload.get("stake"))
    odds = None
    if payload.get("odds_american") not in (None, ""):
        odds = parse_american_odds(payload.get("odds_american"))

    now = utc_now()
    bet_id = _new_id()
    with _lock:
        connection = _connect()
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                INSERT INTO bets (
                    id, user_id, kind, status, sportsbook, stake,
                    odds_american, notes, created_at, updated_at,
                    settled_at, manual_result, archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 0)
                """,
                (
                    bet_id,
                    user_id,
                    kind,
                    STATUS_PENDING,
                    str(payload.get("sportsbook") or "").strip()[:40] or None,
                    stake,
                    odds,
                    str(payload.get("notes") or "").strip()[:280] or None,
                    now,
                    now,
                ),
            )
            for index, leg in enumerate(legs):
                _insert_leg(connection, bet_id, index, leg, now)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
    saved = get_bet(bet_id, user_id)
    if saved is None:
        raise RuntimeError("Bet was not saved.")
    return saved


def _leg_team(leg: dict[str, Any], direction: str) -> str | None:
    team = str(leg.get("team") or "").strip().upper()[:8] or None
    if team:
        return team
    home = str(leg.get("home_team") or "").strip().upper()[:8] or None
    away = str(leg.get("away_team") or "").strip().upper()[:8] or None
    if "away" in direction:
        return away
    if "home" in direction:
        return home
    return None


def _insert_leg(
    connection: sqlite3.Connection,
    bet_id: str,
    position: int,
    leg: dict[str, Any],
    now: str,
) -> None:
    from bets.catalog import LEAGUES, directions_for, market_for

    league = str(leg.get("league") or "").lower().strip()
    if league not in LEAGUES:
        raise ValueError("Choose a supported league.")
    market = market_for(str(leg.get("market") or ""))
    direction = str(leg.get("direction") or "").strip()
    allowed = {item[0] for item in directions_for(market.key)}
    if direction not in allowed:
        raise ValueError("That outcome is not valid for this market.")

    line = leg.get("line")
    if line in (None, ""):
        if market.key in {"moneyline"}:
            line_value = None
        else:
            raise ValueError("Enter a line.")
    else:
        try:
            line_value = float(line)
        except (TypeError, ValueError) as error:
            raise ValueError("Line must be a number.") from error
        if abs(line_value) > 10000:
            raise ValueError("Line is out of range.")

    odds = None
    if leg.get("odds_american") not in (None, ""):
        odds = parse_american_odds(leg.get("odds_american"))

    event_id = str(leg.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("Choose a game.")

    if market.scope == "player":
        player_id = str(leg.get("player_id") or "").strip()
        player_name = str(leg.get("player_name") or "").strip()
        if not player_id or not player_name:
            raise ValueError("Choose a player.")
    else:
        player_id = None
        player_name = None

    connection.execute(
        """
        INSERT INTO legs (
            id, bet_id, position, league, market, direction, line,
            odds_american, event_id, event_label, player_id, player_name,
            team, opponent, home_team, away_team, status, current_value,
            final_value, game_status, period, clock, stale, settle_source,
            last_error, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  NULL, NULL, ?, '', '', 0, NULL, NULL, ?)
        """,
        (
            _new_id(),
            bet_id,
            position,
            league,
            market.key,
            direction,
            line_value,
            odds,
            event_id,
            str(leg.get("event_label") or "").strip()[:80],
            player_id,
            player_name,
            _leg_team(leg, direction),
            str(leg.get("opponent") or "").strip().upper()[:8] or None,
            str(leg.get("home_team") or "").strip().upper()[:8] or None,
            str(leg.get("away_team") or "").strip().upper()[:8] or None,
            STATUS_PENDING,
            str(leg.get("game_status") or "Scheduled")[:40],
            now,
        ),
    )


def update_leg_progress(leg_id: str, fields: dict[str, Any]) -> None:
    init_store()
    if not fields:
        return
    allowed = {
        "status", "current_value", "final_value", "game_status",
        "period", "clock", "stale", "settle_source", "last_error",
        "updated_at",
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        return
    if "updated_at" not in fields:
        assignments.append("updated_at = ?")
        values.append(utc_now())
    values.append(leg_id)
    with _lock:
        connection = _connect()
        try:
            connection.execute(
                f"UPDATE legs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        finally:
            connection.close()


def update_bet_fields(bet_id: str, user_id: str | None, fields: dict[str, Any]) -> None:
    init_store()
    allowed = {
        "status", "odds_american", "stake", "notes", "sportsbook",
        "settled_at", "manual_result", "archived", "updated_at",
    }
    assignments = []
    values = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        return
    if "updated_at" not in fields:
        assignments.append("updated_at = ?")
        values.append(utc_now())
    sql = f"UPDATE bets SET {', '.join(assignments)} WHERE id = ?"
    values.append(bet_id)
    if user_id:
        sql += " AND user_id = ?"
        values.append(user_id)
    with _lock:
        connection = _connect()
        try:
            connection.execute(sql, values)
        finally:
            connection.close()


def delete_bet(bet_id: str, user_id: str) -> bool:
    init_store()
    with _lock:
        connection = _connect()
        try:
            cursor = connection.execute(
                "DELETE FROM bets WHERE id = ? AND user_id = ?",
                (bet_id, user_id),
            )
            return cursor.rowcount > 0
        finally:
            connection.close()


def add_notice(
    user_id: str,
    notice_type: str,
    title: str,
    detail: str = "",
    bet_id: str | None = None,
    leg_id: str | None = None,
) -> None:
    init_store()
    with _lock:
        connection = _connect()
        try:
            connection.execute(
                """
                INSERT INTO notices (
                    id, user_id, bet_id, leg_id, notice_type, title,
                    detail, created_at, shown
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    _new_id(),
                    user_id,
                    bet_id,
                    leg_id,
                    notice_type,
                    title[:40],
                    (detail or "")[:80],
                    utc_now(),
                ),
            )
        finally:
            connection.close()


def next_notice() -> dict[str, Any] | None:
    init_store()
    with _lock:
        connection = _connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM notices
                WHERE shown = 0
                ORDER BY datetime(created_at) ASC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()


def mark_notice_shown(notice_id: str) -> None:
    init_store()
    with _lock:
        connection = _connect()
        try:
            connection.execute(
                "UPDATE notices SET shown = 1 WHERE id = ?",
                (notice_id,),
            )
        finally:
            connection.close()


def export_snapshot() -> str:
    return json.dumps({"db": str(DB_PATH), "time": utc_now()})
