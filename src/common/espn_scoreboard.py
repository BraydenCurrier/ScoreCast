from __future__ import annotations

from typing import Any


def safe_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "home", "away"}


def competitor_stat_int(competitor: dict[str, Any], *names: str):
    wanted = {str(name).strip().lower() for name in names if name}
    for stat in competitor.get("statistics") or []:
        if not isinstance(stat, dict):
            continue
        name = str(stat.get("name") or "").strip().lower()
        abbr = str(stat.get("abbreviation") or "").strip().lower()
        if name not in wanted and abbr not in wanted:
            continue
        parsed = safe_int(
            stat.get("displayValue", stat.get("value")),
        )
        if parsed is not None:
            return parsed
    return None


def team_abbr(competitor: dict[str, Any]) -> str:
    team = competitor.get("team") or {}
    abbreviation = team.get("abbreviation")
    if abbreviation:
        return str(abbreviation).upper()
    name = str(team.get("name") or team.get("shortDisplayName") or "")
    return name[:3].upper()


def possession_abbr(
    situation: dict[str, Any] | None,
    home: dict[str, Any],
    away: dict[str, Any],
) -> str:
    if not isinstance(situation, dict):
        return ""

    possession_id = str(situation.get("possession") or "").strip()
    if not possession_id:
        return ""

    for competitor in (home, away):
        ids = {
            str(competitor.get("id") or ""),
            str((competitor.get("team") or {}).get("id") or ""),
        }
        if possession_id in ids:
            return team_abbr(competitor)

    return ""


def timeouts_remaining(situation: dict[str, Any] | None, side: str, cap: int = 7):
    if not isinstance(situation, dict):
        return None
    key = "homeTimeouts" if side == "home" else "awayTimeouts"
    raw = situation.get(key)
    if raw in (None, ""):
        blob = situation.get("timeouts")
        if isinstance(blob, dict):
            raw = blob.get(side)
    parsed = safe_int(raw)
    if parsed is None:
        return None
    return max(0, min(cap, parsed))


def bonus_side(
    situation: dict[str, Any] | None,
    home_abbr: str,
    away_abbr: str,
) -> str:
    if not isinstance(situation, dict):
        return ""

    if _truthy(situation.get("awayInBonus")):
        return away_abbr
    if _truthy(situation.get("homeInBonus")):
        return home_abbr

    in_bonus = situation.get("inBonus")
    if isinstance(in_bonus, str):
        text = in_bonus.strip().lower()
        if text in {"away", "visitor"}:
            return away_abbr
        if text == "home":
            return home_abbr
    return ""


def power_play_abbr(
    situation: dict[str, Any] | None,
    home: dict[str, Any],
    away: dict[str, Any],
) -> str:
    if not isinstance(situation, dict):
        return ""

    home_abbr = team_abbr(home)
    away_abbr = team_abbr(away)
    home_ids = {
        str(home.get("id") or ""),
        str((home.get("team") or {}).get("id") or ""),
        "home",
    }
    away_ids = {
        str(away.get("id") or ""),
        str((away.get("team") or {}).get("id") or ""),
        "away",
    }

    strength = str(situation.get("strength") or "").lower()
    if "even" in strength:
        return ""

    for key in (
        "onPowerPlay",
        "powerPlayTeam",
        "manAdvantage",
        "powerPlayAdvantage",
    ):
        value = situation.get(key)
        if value in (None, "", False):
            continue
        token = str(value).strip()
        if token in home_ids:
            return home_abbr
        if token in away_ids:
            return away_abbr

    away_skaters = safe_int(
        situation.get("awayStrength", situation.get("awayOnIce")),
    )
    home_skaters = safe_int(
        situation.get("homeStrength", situation.get("homeOnIce")),
    )
    if (
        away_skaters is not None
        and home_skaters is not None
        and away_skaters != home_skaters
    ):
        return home_abbr if home_skaters > away_skaters else away_abbr

    if not (
        _truthy(situation.get("isPowerPlay"))
        or _truthy(situation.get("powerPlay"))
        or "power" in strength
    ):
        return ""

    last_play = situation.get("lastPlay") or {}
    play_text = " ".join(
        [
            str(last_play.get("text") or ""),
            str((last_play.get("type") or {}).get("text") or ""),
        ]
    ).lower()
    if "power play" not in play_text and "pp " not in play_text:
        return ""

    team_id = str((last_play.get("team") or {}).get("id") or "")
    if team_id in home_ids:
        return home_abbr
    if team_id in away_ids:
        return away_abbr
    return ""


def strength_label(situation: dict[str, Any] | None) -> str:
    if not isinstance(situation, dict):
        return ""
    away_skaters = safe_int(
        situation.get("awayStrength", situation.get("awayOnIce")),
    )
    home_skaters = safe_int(
        situation.get("homeStrength", situation.get("homeOnIce")),
    )
    if (
        away_skaters is not None
        and home_skaters is not None
        and away_skaters != home_skaters
    ):
        return f"{away_skaters}-{home_skaters}"
    return ""
