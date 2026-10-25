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
CORE_ROSTER_URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
    "events/{event_id}/competitions/{event_id}/competitors/{team_id}/roster"
)
CORE_PLAYER_STATS_URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
    "events/{event_id}/competitions/{event_id}/competitors/{team_id}/"
    "roster/{athlete_id}/statistics/0"
)

# Last player who appeared in a play, kept when the newest play names nobody.
_recent_players = {}


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


def _ref_id(ref, kind):
    match = re.search(rf"/{kind}/(\d+)", str(ref or ""))
    return match.group(1) if match else ""


def _leading_name(text):
    """Player name at the start of an ESPN play description."""
    stop = {
        "makes", "misses", "made", "missed", "enters", "leaves",
        "personal", "loose", "shooting", "offensive", "defensive",
        "blocks", "steals", "steal", "turnover", "foul", "flagrant",
        "technical", "lost", "bad", "out", "of", "vs", "alley",
        "with", "traveling", "kicked", "double", "hanging",
        "running", "driving", "cutting", "floating", "pullup",
        "step", "steps", "hook", "layup", "dunk", "tip", "rebound",
        "timeout", "full", "challenge", "review", "end", "quarter",
        "period", "game", "second", "seconds", "ejected", "flopping",
        "palming", "inbound", "shot", "clock", "violation", "charge",
        "goaltending", "delay", "gains", "possession", "away", "from",
        "play",
    }
    words = []
    for word in str(text or "").split():
        cleaned = word.strip(".,()[]{}:")
        if not cleaned:
            continue
        if not words and not cleaned[0].isalpha():
            return ""
        if cleaned.lower() in stop or cleaned[0].isdigit():
            break
        words.append(cleaned)
    return " ".join(words).strip()


def _core_play_player(play, home, away):
    if not isinstance(play, dict):
        return None
    participants = [
        item for item in (play.get("participants") or [])
        if isinstance(item, dict)
    ]
    person = next(
        (item for item in participants if item.get("type") != "subout"),
        None,
    )
    if person is None:
        return None
    athlete = person.get("athlete") if isinstance(person.get("athlete"), dict) else {}
    stats = person.get("statistics") if isinstance(person.get("statistics"), dict) else {}
    team = play.get("team") if isinstance(play.get("team"), dict) else {}
    athlete_id = _ref_id(athlete.get("$ref"), "athletes")
    team_id = (
        _ref_id(stats.get("$ref"), "competitors")
        or _ref_id(team.get("$ref"), "teams")
    )
    if not athlete_id or not team_id:
        return None
    return {
        "athlete_id": athlete_id,
        "team_id": team_id,
        "name": _leading_name(play.get("text")),
        "team": _abbr_for_team_id(team_id, home, away),
        "text": str(play.get("text") or "").strip(),
        "kind": str((play.get("type") or {}).get("text") or "").strip(),
        "points": safe_int(play.get("scoreValue"), 0) or 0,
    }


def _recent_plays(event_id):
    """The newest plays, oldest first. The last item is the current play."""
    url = (
        "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/"
        f"events/{event_id}/competitions/{event_id}/plays?limit=8"
    )
    page = _fetch_json(url)
    page_count = safe_int(page.get("pageCount"), 1) or 1
    if page_count > 1:
        page = _fetch_json(f"{url}&page={page_count}")
    return [
        item for item in (page.get("items") or [])
        if isinstance(item, dict)
    ]


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

    plays = []
    try:
        plays = _recent_plays(event_id)
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        plays = []

    play = plays[-1] if plays else {}
    if not play:
        last = situation.get("lastPlay")
        ref = last.get("$ref") if isinstance(last, dict) else ""
        if ref:
            try:
                play = _fetch_json(ref)
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                play = {}
            if play:
                plays = [play]

    details = _details_from_payload(situation, play, home, away)
    if play.get("text"):
        details["latest_text"] = str(play.get("text") or "").strip()
        details["latest_kind"] = str((play.get("type") or {}).get("text") or "").strip()
        details["latest_points"] = safe_int(play.get("scoreValue"), 0) or 0
    for candidate in reversed(plays):
        player = _core_play_player(candidate, home, away)
        if player and player.get("name"):
            details["core_play"] = player
            break
    return details


def _on_court_numbers(roster):
    """Jerseys for the five players marked active on the floor."""
    numbers = []
    entries = roster.get("entries") if isinstance(roster, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("active") or entry.get("didNotPlay"):
            continue
        jersey = str(entry.get("jersey") or "").strip()
        if not jersey:
            continue
        numbers.append(jersey)
        if len(numbers) == 5:
            break
    return tuple(numbers)


def _competitor_team_id(competitor):
    team = competitor.get("team") if isinstance(competitor, dict) else None
    team = team if isinstance(team, dict) else {}
    return str(team.get("id") or competitor.get("id") or "").strip()


def _on_court(event_id, competitor):
    event_id = str(event_id or "").strip()
    team_id = _competitor_team_id(competitor)
    if not event_id or not team_id:
        return ()
    try:
        roster = _fetch_json(
            CORE_ROSTER_URL.format(event_id=event_id, team_id=team_id)
        )
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return ()
    return _on_court_numbers(roster)


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
    athlete_id = ""
    involved = play.get("athletesInvolved") or []
    if involved and isinstance(involved[0], dict):
        athlete = str(
            involved[0].get("shortName")
            or involved[0].get("fullName")
            or ""
        ).strip()
        athlete_id = str(involved[0].get("id") or "").strip()
        if not team_id:
            team_id = str((involved[0].get("team") or {}).get("id") or "").strip()

    points = safe_int(play.get("scoreValue"), 0) or 0
    return text, kind, team, athlete, points, athlete_id, team_id


def _stat_display(categories, abbreviation):
    wanted = str(abbreviation or "").upper()
    for category in categories or []:
        if not isinstance(category, dict):
            continue
        for stat in category.get("stats") or []:
            if not isinstance(stat, dict):
                continue
            if str(stat.get("abbreviation") or "").upper() != wanted:
                continue
            return str(stat.get("displayValue") or "").strip()
    return ""


def _player_line_from_stats(payload):
    splits = payload.get("splits") if isinstance(payload, dict) else None
    categories = splits.get("categories") if isinstance(splits, dict) else None
    return {
        "points": _stat_display(categories, "PTS"),
        "rebounds": _stat_display(categories, "REB"),
        "assists": _stat_display(categories, "AST"),
    }


def _fetch_player_line(event_id, team_id, athlete_id):
    try:
        payload = _fetch_json(
            CORE_PLAYER_STATS_URL.format(
                event_id=event_id,
                team_id=team_id,
                athlete_id=athlete_id,
            )
        )
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return None
    line = _player_line_from_stats(payload)
    if not any(line.values()):
        return None
    return line


def _tracked_player(event_id, athlete_id, team_id, name, team_abbr_name):
    """Stats for the newest play that named a player."""
    event_id = str(event_id or "").strip()
    cached = _recent_players.get(event_id)
    athlete_id = str(athlete_id or "").strip()
    team_id = str(team_id or "").strip()
    name = str(name or "").strip()
    if athlete_id and team_id:
        chosen = {
            "id": athlete_id,
            "team_id": team_id,
            "name": name or (cached or {}).get("name", ""),
            "team": team_abbr_name or (cached or {}).get("team", ""),
        }
    elif cached:
        chosen = cached
    else:
        return None

    line = _fetch_player_line(event_id, chosen["team_id"], chosen["id"])
    if line is None:
        return cached
    chosen = {
        **chosen,
        "points": line["points"],
        "rebounds": line["rebounds"],
        "assists": line["assists"],
    }
    _recent_players[event_id] = chosen
    return chosen


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
            last_play_athlete_id,
            last_play_team_id,
        ) = _last_play(situation, home, away)
        away_in_bonus, home_in_bonus = _bonus_flags(situation)
        possession = possession_abbr(situation, home, away)
        away_timeouts = timeouts_remaining(situation, "away", cap=7)
        home_timeouts = timeouts_remaining(situation, "home", cap=7)
        away_lineup = ()
        home_lineup = ()
        play_player = ""
        play_player_team = ""
        play_player_points = ""
        play_player_rebounds = ""
        play_player_assists = ""

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
            away_lineup = _on_court(event.get("id"), away)
            home_lineup = _on_court(event.get("id"), home)
            if details.get("latest_text"):
                last_play_text = details["latest_text"]
                last_play_type = details.get("latest_kind") or last_play_type
                last_play_points = details.get("latest_points", last_play_points)
            core_play = details.get("core_play") or {}
            if core_play.get("athlete_id"):
                last_play_athlete_id = core_play["athlete_id"]
            if core_play.get("team_id"):
                last_play_team_id = core_play["team_id"]
            if (
                core_play.get("name")
                and core_play.get("text") == details.get("latest_text")
            ):
                last_play_athlete = core_play["name"]
                if core_play.get("team"):
                    last_play_team = core_play["team"]
            tracked = _tracked_player(
                event.get("id"),
                last_play_athlete_id,
                last_play_team_id,
                core_play.get("name") or last_play_athlete,
                core_play.get("team") or last_play_team,
            )
            if tracked:
                play_player = tracked.get("name", "")
                play_player_team = tracked.get("team", "")
                play_player_points = tracked.get("points", "")
                play_player_rebounds = tracked.get("rebounds", "")
                play_player_assists = tracked.get("assists", "")

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
                play_player=play_player,
                play_player_team=play_player_team,
                play_player_points=play_player_points,
                play_player_rebounds=play_player_rebounds,
                play_player_assists=play_player_assists,
                away_quarters=_quarter_scores(away),
                home_quarters=_quarter_scores(home),
                away_lineup=away_lineup,
                home_lineup=home_lineup,
            )
        )

    return games