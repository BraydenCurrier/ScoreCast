import re


BIG_PLAY_MIN_YARDS = 20

_SKIP_MARKERS = (
    "timeout",
    "delay of game",
    "two-minute",
    "two minute",
    "kneel",
    "spike",
    "no play",
    "penalty",
    "review",
    "challenge",
)

_SPECIAL_TEAMS_SKIP = (
    "kickoff",
    "punt",
    "extra point",
    "xp good",
    "xp is good",
)


def _blob(*parts):
    return " ".join(
        str(part or "").strip().lower()
        for part in parts
        if str(part or "").strip()
    )


def _yards_label(yardage):
    if yardage > 0:
        return f"{yardage} YD"

    return ""


def classify_nfl_big_play(
    *,
    play_type="",
    play_text="",
    yardage=0,
    scoring=False,
):
    blob = _blob(play_type, play_text)

    if not blob:
        return None

    if any(marker in blob for marker in _SKIP_MARKERS):
        return None

    if "incomplete" in blob and "intercept" not in blob:
        return None

    special_teams = any(
        marker in blob
        for marker in _SPECIAL_TEAMS_SKIP
    )
    explosive = (
        "touchdown" in blob
        or "fumble" in blob
        or "intercept" in blob
        or "return" in blob
    )

    if special_teams and not explosive and not scoring:
        return None

    yards = _yards_label(yardage)

    if "safety" in blob:
        return {
            "kind": "SAFETY",
            "headline": "SAFETY",
            "detail": "SAFETY",
            "chant": ("SAFETY",),
        }

    if (
        "touchdown" in blob
        or (
            scoring
            and "field goal" not in blob
            and "extra point" not in blob
            and "two-point" not in blob
            and "2-pt" not in blob
        )
    ):
        detail = " ".join(
            part
            for part in (yards, "TD")
            if part
        )
        return {
            "kind": "TOUCHDOWN",
            "headline": "TOUCHDOWN",
            "detail": detail or "TOUCHDOWN",
            "chant": ("TOUCH", "DOWN"),
        }

    if "intercept" in blob:
        return {
            "kind": "INTERCEPTION",
            "headline": "PICK",
            "detail": " ".join(
                part
                for part in (yards, "INT")
                if part
            ) or "INT",
            "chant": ("PICK",),
        }

    if re.search(r"\bsack", blob):
        return {
            "kind": "SACK",
            "headline": "SACK",
            "detail": "SACK",
            "chant": ("SACK",),
        }

    if "fumble" in blob:
        return {
            "kind": "FUMBLE",
            "headline": "FUMBLE",
            "detail": "FUMBLE",
            "chant": ("FUMBLE",),
        }

    if "field goal" in blob and (
        scoring
        or "good" in blob
        or "is good" in blob
    ):
        return {
            "kind": "FIELD_GOAL",
            "headline": "FIELD GOAL",
            "detail": " ".join(
                part
                for part in (yards, "FG")
                if part
            ) or "FIELD GOAL",
            "chant": ("FIELD", "GOAL"),
        }

    if (
        "two-point" in blob
        or "2-pt" in blob
        or "2pt" in blob
    ) and (
        scoring
        or "good" in blob
        or "succeed" in blob
        or "conversion" in blob
    ):
        return {
            "kind": "TWO_POINT",
            "headline": "2-PT",
            "detail": "2-PT CONV",
            "chant": ("TWO", "POINT"),
        }

    if yardage >= BIG_PLAY_MIN_YARDS:
        return {
            "kind": "BIG_PLAY",
            "headline": "BIG PLAY",
            "detail": f"{yardage} YD PLAY",
            "chant": ("BIG", "PLAY"),
        }

    return None


def last_name_for_alert(player):
    last = str((player or {}).get("last") or "").strip()

    if last:
        return last.upper()

    name = str((player or {}).get("name") or "").strip()
    parts = name.split()

    if parts:
        return parts[-1].upper()

    return "PLAYER"


def compact_play_text(play_text):
    text = re.sub(r"\s+", " ", str(play_text or "")).strip()

    if not text:
        return ""

    text = re.sub(r"\btouchdown\b", "TD", text, flags=re.I)
    text = re.sub(r"\byards?\b", "YD", text, flags=re.I)
    text = re.sub(r"\bintercepted\b", "INT", text, flags=re.I)
    text = re.sub(r"\binterception\b", "INT", text, flags=re.I)
    text = re.sub(r"\bfield goal\b", "FG", text, flags=re.I)
    text = re.sub(r"\bextra point\b", "XP", text, flags=re.I)
    text = re.sub(r"\btwo-point\b", "2PT", text, flags=re.I)
    text = re.sub(r"['’`,;()\[\]]+", "", text)
    text = re.sub(r"[^A-Za-z0-9 .:+%-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text.upper()


def player_in_last_play(player, game):
    if not player:
        return False

    espn_id = str(player.get("espn_id") or "").strip()
    play_ids = {
        str(athlete_id).strip()
        for athlete_id in getattr(game, "last_play_athlete_ids", ())
        if str(athlete_id).strip()
    }

    if espn_id and espn_id in play_ids:
        return True

    full_name = re.sub(
        r"\s+",
        " ",
        str(player.get("name") or ""),
    ).strip().lower()

    play_names = [
        re.sub(r"\s+", " ", str(name or "")).strip().lower()
        for name in getattr(game, "last_play_athlete_names", ())
        if str(name or "").strip()
    ]

    if full_name and full_name in play_names:
        return True

    play_text = str(
        getattr(game, "last_play_text", "") or ""
    ).upper()

    if not play_text:
        return False

    first = str(player.get("first") or "").strip()
    last = str(player.get("last") or "").strip()
    team = str(player.get("team") or "").upper()
    home = str(getattr(game, "home", "") or "").upper()
    away = str(getattr(game, "away", "") or "").upper()

    if team and team not in {home, away}:
        return False

    if first and last:
        short = f"{first[0]}.{last}".upper()
        if short in play_text.replace(" ", ""):
            return True
        if re.search(
            rf"\b{re.escape(first[0])}\.\s*{re.escape(last)}\b",
            play_text,
            re.IGNORECASE,
        ):
            return True

    if last and len(last) >= 5:
        if re.search(rf"\b{re.escape(last)}\b", play_text, re.IGNORECASE):
            return True

    return False
