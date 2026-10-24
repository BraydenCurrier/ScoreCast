import json
import re

import requests

from common.broadcast import format_broadcast as _get_broadcast
from common.espn_scoreboard import (
    bonus_side,
    possession_abbr,
    safe_int,
    team_abbr,
    timeouts_remaining,
)
from common.http import failure_text, get_body
from common.timezone import format_local_date, format_local_time

from nba.models import BasketballGame


NBA_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/"
    "basketball/nba/scoreboard"
)


HTTP_TIMEOUT = (3.05, 10)
LIVE_TIMEOUT = (3.05, 6)

CORE_SITUATION_URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/"
    "leagues/nba/events/{event_id}/competitions/{event_id}/situation"
)


def fetch_nba_scoreboard():
    try:
        body = get_body(
            NBA_SCOREBOARD_URL,
            HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            "NBA ESPN request failed: "
            f"{failure_text(exc)[:300]}"
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "NBA ESPN endpoint returned invalid JSON: "
            f"{body[:300]}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Unexpected NBA ESPN response type: "
            f"{type(data).__name__}"
        )

    return data


def _team_id_from_ref(node):
    if isinstance(node, dict):
        if node.get("id") not in (None, ""):
            return str(node.get("id")).strip()
        node = node.get("$ref") or ""
    match = re.search(r"/teams/(\d+)(?:\?|$)", str(node or ""))
    return match.group(1) if match else ""


def _abbr_for_team_id(team_id, home, away):
    for competitor in (home, away):
        if not isinstance(competitor, dict):
            continue
        ids = {
            str(competitor.get("id") or ""),
            str((competitor.get("team") or {}).get("id") or ""),
        }
        if team_id and team_id in ids:
            return team_abbr(competitor)
    return ""


def _side_in_bonus(fouls):
    if not isinstance(fouls, dict):
        return False
    state = str(fouls.get("bonusState") or "").strip().upper()
    return bool(state) and state not in {"NONE", "NO", "FALSE"}


def _fetch_json(url):
    body = get_body(url, LIVE_TIMEOUT)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("Unexpected NBA situation response")
    return data


def _details_from_payload(situation, play, home, away):
    """Timeouts, bonus, and ball possession from the core situation feed."""
    situation = situation if isinstance(situation, dict) else {}
    play = play if isinstance(play, dict) else {}
    possession = _abbr_for_team_id(
        _team_id_from_ref(play.get("possessionTeam")),
        home,
        away,
    )
    if not possession:
        possession = possession_abbr(situation, home, away)
    return {
        "possession": possession,
        "away_timeouts": timeouts_remaining(situation, "away", cap=7),
        "home_timeouts": timeouts_remaining(situation, "home", cap=7),
        "away_in_bonus": _side_in_bonus(situation.get("awayFouls")),
        "home_in_bonus": _side_in_bonus(situation.get("homeFouls")),
    }


def _live_details(event_id, home, away):
    event_id = str(event_id or "").strip()
    if not event_id:
        return {}
    try:
        situation = _fetch_json(
            CORE_SITUATION_URL.format(event_id=event_id)
        )
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return {}

    play = {}
    last = situation.get("lastPlay")
    ref = last.get("$ref") if isinstance(last, dict) else ""
    if ref:
        try:
            play = _fetch_json(ref)
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            play = {}
    return _details_from_payload(situation, play, home, away)


def _bonus_flags(situation):
    """Each team can be in the bonus at the same time."""
    if not isinstance(situation, dict):
        return False, False

    def _on(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value or "").strip().lower() in {"1", "true", "yes", "y"}

    away = _on(situation.get("awayInBonus"))
    home = _on(situation.get("homeInBonus"))
    named = str(situation.get("inBonus") or "").strip().lower()
    if named in {"away", "visitor"}:
        away = True
    elif named == "home":
        home = True
    elif named == "both":
        away = True
        home = True
    away = away or _side_in_bonus(situation.get("awayFouls"))
    home = home or _side_in_bonus(situation.get("homeFouls"))
    return away, home


def _points_leader(competitor):
    for group in competitor.get("leaders") or []:
        if str(group.get("name") or "").strip().lower() != "points":
            continue
        people = group.get("leaders") or []
        if not people or not isinstance(people[0], dict):
            return "", ""
        person = people[0]
        athlete = person.get("athlete") or {}
        name = str(
            athlete.get("shortName")
            or athlete.get("displayName")
            or ""
        ).strip()
        points = str(person.get("displayValue") or "").strip().split()
        return name, points[0] if points else ""
    return "", ""


def _quarter_scores(competitor):
    scores = []
    for item in competitor.get("linescores") or []:
        if not isinstance(item, dict):
            continue
        value = safe_int(item.get("value", item.get("displayValue")))
        if value is None:
            continue
        scores.append(value)
    return tuple(scores)


def _last_play(situation, home, away):
    play = {}
    if isinstance(situation, dict):
        raw = situation.get("lastPlay")
        if isinstance(raw, dict):
            play = raw

    text = str(play.get("text") or "").strip()
    kind = str((play.get("type") or {}).get("text") or "").strip()
    team_id = str((play.get("team") or {}).get("id") or "").strip()
    team = ""
    for competitor in (home, away):
        ids = {
            str(competitor.get("id") or ""),
            str((competitor.get("team") or {}).get("id") or ""),
        }
        if team_id and team_id in ids:
            team = team_abbr(competitor)
            break

    athlete = ""
    involved = play.get("athletesInvolved") or []
    if involved and isinstance(involved[0], dict):
        athlete = str(
            involved[0].get("shortName")
            or involved[0].get("fullName")
            or ""
        ).strip()

    points = safe_int(play.get("scoreValue"), 0) or 0
    return text, kind, team, athlete, points


def get_record(team):
    records = team.get("records", [])

    if not records:
        return 0, 0

    summary = records[0].get(
        "summary",
        "0-0",
    )

    try:
        wins, losses = summary.split("-")
        return int(wins), int(losses)
    except (TypeError, ValueError):
        return 0, 0


def get_today_games():
    data = fetch_nba_scoreboard()

    games = []

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

        away_wins, away_losses = get_record(away)
        home_wins, home_losses = get_record(home)
        away_leader, away_leader_points = _points_leader(away)
        home_leader, home_leader_points = _points_leader(home)
        (
            last_play_text,
            last_play_type,
            last_play_team,
            last_play_athlete,
            last_play_points,
        ) = _last_play(situation, home, away)
        away_in_bonus, home_in_bonus = _bonus_flags(situation)
        possession = possession_abbr(situation, home, away)
        away_timeouts = timeouts_remaining(situation, "away", cap=7)
        home_timeouts = timeouts_remaining(situation, "home", cap=7)

        status = competition["status"]
        status_type = status.get("type") or {}
        state = str(status_type.get("state") or "").lower()
        detail = " ".join(
            [
                str(status_type.get("name") or ""),
                str(status_type.get("description") or ""),
                str(status_type.get("detail") or ""),
                str(status_type.get("shortDetail") or ""),
            ]
        ).lower()

        quarter = int(status.get("period") or 0)
        clock = str(status.get("displayClock") or "").strip()
        if clock in {"0.0", "0:00", "0"}:
            clock = ""

        if state == "in":
            details = _live_details(event.get("id"), home, away)
            if details.get("possession"):
                possession = details["possession"]
            if details.get("away_timeouts") is not None:
                away_timeouts = details["away_timeouts"]
            if details.get("home_timeouts") is not None:
                home_timeouts = details["home_timeouts"]
            away_in_bonus = away_in_bonus or details.get("away_in_bonus", False)
            home_in_bonus = home_in_bonus or details.get("home_in_bonus", False)

        if state == "pre":
            game_status = "Scheduled"
            quarter = 0
            clock = ""
        elif "halftime" in detail or "half-time" in detail:
            game_status = "Halftime"
            clock = ""
        elif state == "in":
            game_status = "Live"
        else:
            game_status = "Final"
            clock = ""
            if quarter < 4:
                quarter = 4

        games.append(
            BasketballGame(
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

                home_wins=home_wins,
                home_losses=home_losses,

                quarter=quarter,
                clock=clock,
                possession=possession,
                away_timeouts=away_timeouts,
                home_timeouts=home_timeouts,
                away_in_bonus=away_in_bonus,
                home_in_bonus=home_in_bonus,
                bonus=bonus_side(
                    situation,
                    home_team,
                    away_team,
                ),
                event_id=str(event.get("id") or ""),
                away_leader=away_leader,
                away_leader_points=away_leader_points,
                home_leader=home_leader,
                home_leader_points=home_leader_points,
                last_play_text=last_play_text,
                last_play_type=last_play_type,
                last_play_team=last_play_team,
                last_play_athlete=last_play_athlete,
                last_play_points=last_play_points,
                away_quarters=_quarter_scores(away),
                home_quarters=_quarter_scores(home),
            )
        )

    return games