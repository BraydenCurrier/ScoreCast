from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json

import requests

from common.espn_scoreboard import (
    competitor_stat_int,
    possession_abbr,
    power_play_abbr,
    safe_int,
    strength_label,
    team_abbr,
)
from common.http import failure_text, get_body
from common.timezone import get_local_timezone

from nhl.models import HockeyGame


NHL_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/hockey/nhl/scoreboard"
)
NHL_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/hockey/nhl/summary"
)


HTTP_TIMEOUT = (3.05, 10)


def fetch_nhl_scoreboard():
    try:
        body = get_body(
            NHL_SCOREBOARD_URL,
            HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "NHL ESPN request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "NHL ESPN endpoint returned invalid JSON: "
            f"{body[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Unexpected NHL ESPN response type: "
            f"{type(data).__name__}"
        )

    return data


def format_local_time(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        get_local_timezone()
    )

    return local_dt.strftime("%-I:%M")


def format_local_date(date_string):
    utc_dt = datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        get_local_timezone()
    )

    return local_dt.strftime("%b %-d")


def get_record(team):
    records = team.get("records", [])

    if not records:
        return 0, 0, 0

    summary = records[0].get("summary", "0-0-0")
    parts = summary.split("-")

    wins = int(parts[0]) if len(parts) > 0 else 0
    losses = int(parts[1]) if len(parts) > 1 else 0
    ot_losses = int(parts[2]) if len(parts) > 2 else 0

    return wins, losses, ot_losses


def get_period_status(status):
    state = status["type"]["state"]
    name = status["type"].get("name", "")
    detail = status["type"].get("detail", "")
    short_detail = status["type"].get(
        "shortDetail",
        "",
    )

    period = status.get("period", 0)
    clock = status.get("displayClock", "")

    intermission = False
    overtime = False
    shootout = False

    if state == "pre":
        game_status = "Scheduled"
        period = 0
        clock = ""

    elif state == "in":
        game_status = "Live"

        text = (
            f"{name} {detail} {short_detail}"
        ).lower()

        if "intermission" in text:
            game_status = "Intermission"
            intermission = True

        if (
            period > 3
            or "overtime" in text
            or " ot" in text
        ):
            game_status = "Overtime"
            overtime = True

        if "shootout" in text:
            game_status = "Shootout"
            shootout = True

    else:
        game_status = "Final"

        text = (
            f"{name} {detail} {short_detail}"
        ).lower()

        if "shootout" in text:
            shootout = True

        if (
            "overtime" in text
            or " ot" in text
        ):
            overtime = True

    return (
        game_status,
        period,
        clock,
        intermission,
        overtime,
        shootout,
    )

from common.broadcast import format_broadcast as _get_broadcast


def _toi_seconds(text):
    parts = str(text or "").strip().split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return 0


def _goalie_name(athlete):
    last = str((athlete or {}).get("lastName") or "").strip()
    if last:
        return last.upper()

    short = str((athlete or {}).get("shortName") or "").strip()
    parts = short.replace(".", " ").split()
    if len(parts) >= 2 and len(parts[0]) == 1:
        return " ".join(parts[1:]).upper()
    return short.upper()


def _save_pct(raw, shots_against):
    if shots_against <= 0:
        return ""
    text = str(raw or "").strip()
    if not text or text in {"-", "—"}:
        return ""
    if text.startswith("."):
        return text
    try:
        value = float(text)
    except ValueError:
        return ""
    if value > 1.5:
        value = value / 100.0
    rendered = f"{value:.3f}"
    if rendered.startswith("0"):
        return rendered[1:]
    return rendered


def _parse_goalies(payload):
    found = {"away": ("", ""), "home": ("", "")}
    if not isinstance(payload, dict):
        return found

    sides = {}
    competitions = ((payload.get("header") or {}).get("competitions") or [])
    if competitions:
        for competitor in competitions[0].get("competitors") or []:
            team = competitor.get("team") or {}
            side = str(competitor.get("homeAway") or "").strip().lower()
            team_id = str(team.get("id") or "")
            if side in found and team_id:
                sides[team_id] = side

    for entry in ((payload.get("boxscore") or {}).get("players") or []):
        if not isinstance(entry, dict):
            continue
        team_id = str((entry.get("team") or {}).get("id") or "")
        side = sides.get(team_id)
        if side not in found:
            continue
        for group in entry.get("statistics") or []:
            if not isinstance(group, dict) or group.get("name") != "goalies":
                continue
            keys = group.get("keys") or []
            chosen = None
            for athlete in group.get("athletes") or []:
                if not isinstance(athlete, dict):
                    continue
                stats = athlete.get("stats") or []
                values = {
                    keys[index]: stats[index]
                    for index in range(min(len(keys), len(stats)))
                }
                if chosen is None or _toi_seconds(values.get("timeOnIce")) > 0:
                    chosen = values | {"athlete": athlete.get("athlete") or {}}
            if not chosen:
                continue
            shots = safe_int(chosen.get("shotsAgainst"), 0) or 0
            found[side] = (
                _goalie_name(chosen.get("athlete")),
                _save_pct(chosen.get("savePct"), shots),
            )
    return found


def _load_goalies(event_id):
    event_id = str(event_id or "").strip()
    if not event_id:
        return "", "", "", ""
    try:
        body = get_body(
            f"{NHL_SUMMARY_URL}?event={event_id}",
            HTTP_TIMEOUT,
        )
        payload = json.loads(body)
    except (requests.RequestException, ValueError, TypeError):
        return "", "", "", ""
    parsed = _parse_goalies(payload)
    away_name, away_pct = parsed["away"]
    home_name, home_pct = parsed["home"]
    return away_name, away_pct, home_name, home_pct


def _attach_goalies(pending):
    if not pending:
        return
    workers = min(4, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = pool.map(
            lambda item: (item[0], _load_goalies(item[1])),
            pending,
        )
        for game, goalies in loaded:
            (
                game.away_goalie,
                game.away_save_pct,
                game.home_goalie,
                game.home_save_pct,
            ) = goalies


def get_today_games():
    data = fetch_nhl_scoreboard()
    games = []
    pending_goalies = []

    for event in data.get("events", []):
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        away = next(
            competitor
            for competitor in competitors
            if competitor["homeAway"] == "away"
        )

        home = next(
            competitor
            for competitor in competitors
            if competitor["homeAway"] == "home"
        )

        away_team = team_abbr(away)
        home_team = team_abbr(home)
        situation = competition.get("situation") or {}

        (
            away_wins,
            away_losses,
            away_ot_losses,
        ) = get_record(away)

        (
            home_wins,
            home_losses,
            home_ot_losses,
        ) = get_record(home)

        status = competition["status"]

        (
            game_status,
            period,
            clock,
            intermission,
            overtime,
            shootout,
        ) = get_period_status(status)

        games.append(
            HockeyGame(
                away=away_team,
                home=home_team,

                status=game_status,
                start_time=format_local_time(
                    event["date"]
                ),
                date=format_local_date(
                    event["date"]
                ),

                broadcast=_get_broadcast(
                    event,
                    competition,
                ),

                away_score=int(
                    away.get("score", 0)
                ),
                home_score=int(
                    home.get("score", 0)
                ),

                away_wins=away_wins,
                away_losses=away_losses,
                away_ot_losses=away_ot_losses,

                home_wins=home_wins,
                home_losses=home_losses,
                home_ot_losses=home_ot_losses,

                period=period,
                clock=clock,

                intermission=intermission,
                overtime=overtime,
                shootout=shootout,

                away_sog=competitor_stat_int(
                    away,
                    "shotsOnGoal",
                    "sog",
                    "shots",
                ),
                home_sog=competitor_stat_int(
                    home,
                    "shotsOnGoal",
                    "sog",
                    "shots",
                ),
                possession=possession_abbr(
                    situation,
                    home,
                    away,
                ),
                power_play=power_play_abbr(
                    situation,
                    home,
                    away,
                ),
                strength=strength_label(situation),
                away_so_goals=safe_int(
                    away.get("shootoutScore"),
                ),
                home_so_goals=safe_int(
                    home.get("shootoutScore"),
                ),
            )
        )
        if game_status != "Scheduled":
            pending_goalies.append((games[-1], event.get("id")))

    _attach_goalies(pending_goalies)
    return games