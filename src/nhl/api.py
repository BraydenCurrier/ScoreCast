from concurrent.futures import ThreadPoolExecutor
import json

import requests

from common.broadcast import format_broadcast as _get_broadcast
from common.espn_scoreboard import (
    competitor_stat_int,
    possession_abbr,
    power_play_abbr,
    safe_int,
    strength_label,
    team_abbr,
)
from common.http import failure_text, get_body
from common.timezone import format_local_date, format_local_time

from nhl.models import HockeyGame


NHL_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/hockey/nhl/scoreboard"
)
NHL_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/"
    "sports/hockey/nhl/summary"
)
NHL_SITUATION_URL = (
    "https://sports.core.api.espn.com/v2/sports/hockey/"
    "leagues/nhl/events/{event_id}/competitions/{event_id}/situation"
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


def _team_sides(payload):
    sides = {}
    competitions = ((payload.get("header") or {}).get("competitions") or [])
    if not competitions or not isinstance(competitions[0], dict):
        return sides
    for competitor in competitions[0].get("competitors") or []:
        if not isinstance(competitor, dict):
            continue
        team = competitor.get("team") or {}
        side = str(competitor.get("homeAway") or "").strip().lower()
        team_id = str(team.get("id") or "").strip()
        if side in {"away", "home"} and team_id:
            sides[team_id] = side
    return sides


def _parse_goalies(payload):
    found = {"away": ("", ""), "home": ("", "")}
    if not isinstance(payload, dict):
        return found

    sides = _team_sides(payload)

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


def _box_players(payload):
    found = {}
    for entry in ((payload.get("boxscore") or {}).get("players") or []):
        if not isinstance(entry, dict):
            continue
        for group in entry.get("statistics") or []:
            if not isinstance(group, dict):
                continue
            for athlete in group.get("athletes") or []:
                if not isinstance(athlete, dict):
                    continue
                person = athlete.get("athlete") or {}
                athlete_id = str(person.get("id") or "").strip()
                if not athlete_id or athlete_id in found:
                    continue
                position = person.get("position") or {}
                found[athlete_id] = (
                    str(person.get("jersey") or "").strip(),
                    str(position.get("abbreviation") or "").strip().upper(),
                )
    return found


def _in_play(entry):
    whereabouts = entry.get("whereabouts") if isinstance(entry, dict) else None
    name = str((whereabouts or {}).get("name") or "").upper()
    if not name:
        return True
    return "IN_PLAY" in name


def _line_bucket(position):
    if position == "G":
        return 2
    if position in {"D", "LD", "RD"}:
        return 1
    if position in {"LW", "C", "RW", "F", "W"}:
        return 0
    return 1


def _on_ice_lineups(payload):
    """Skaters on the ice: forwards, then defense. The goalie is named below."""
    if not isinstance(payload, dict):
        return (), ()
    sides = _team_sides(payload)
    players = _box_players(payload)
    found = {"away": (), "home": ()}
    for team in payload.get("onIce") or []:
        if not isinstance(team, dict):
            continue
        side = sides.get(str(team.get("teamId") or "").strip())
        if side not in found:
            continue
        grouped = {0: [], 1: [], 2: []}
        for entry in team.get("entries") or []:
            if not isinstance(entry, dict) or not _in_play(entry):
                continue
            athlete_id = str(
                entry.get("athleteid") or entry.get("athleteId") or ""
            ).strip()
            jersey, position = players.get(athlete_id, ("", ""))
            bucket = _line_bucket(position)
            if not jersey or bucket == 2:
                continue
            grouped[bucket].append(jersey)
        found[side] = tuple((grouped[0] + grouped[1])[:6])
    return found["away"], found["home"]


def _clock_seconds(value):
    if isinstance(value, dict):
        value = value.get("displayValue")
    parts = str(value or "").strip().split(":")
    if len(parts) < 2 or not all(part.isdigit() for part in parts):
        return None
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def _period_number(value):
    if isinstance(value, dict):
        value = value.get("number")
    number = safe_int(value, 0) or 0
    return number if number > 0 else 0


def _ot_length(period, clock):
    remaining = _clock_seconds(clock)
    if period > 3 and remaining is not None and remaining > 5 * 60:
        return 20 * 60
    return 5 * 60


def _period_length(period, ot_length):
    if period <= 3:
        return 20 * 60
    return ot_length


def _game_time(period, clock_seconds, *, elapsed, ot_length):
    period = _period_number(period)
    if period <= 0 or clock_seconds is None:
        return None
    total = sum(_period_length(p, ot_length) for p in range(1, period))
    if elapsed:
        return total + clock_seconds
    length = _period_length(period, ot_length)
    return total + max(0, length - clock_seconds)


class _BoxPenalty:
    def __init__(self, team, start, remaining, chunk, cancellable):
        self.team = team
        self.start = start
        self.remaining = remaining
        self.chunk = chunk
        self.cancellable = cancellable

    def left(self, now):
        return self.remaining - (now - self.start)


def _play_time(play, ot_length):
    return _game_time(
        _period_number(play.get("period")),
        _clock_seconds(play.get("clock")),
        elapsed=True,
        ot_length=ot_length,
    )


def _manpower_penalty(play):
    kind = play.get("type") if isinstance(play.get("type"), dict) else {}
    label = f"{kind.get('text') or ''} {kind.get('penaltyType') or ''}".lower()
    minutes = safe_int(kind.get("penaltyMinutes"), 0) or 0
    if "penalty shot" in label or "misconduct" in label or minutes >= 10 or minutes <= 0:
        return None
    team = str((play.get("team") or {}).get("id") or "").strip()
    if not team:
        return None
    if minutes >= 5:
        length = minutes * 60
        return team, length, length, False
    return team, minutes * 60, 120, True


def _is_power_play_goal(play):
    if not play.get("scoringPlay"):
        return False
    strength = play.get("strength") if isinstance(play.get("strength"), dict) else {}
    label = f"{strength.get('text') or ''} {strength.get('abbreviation') or ''}".lower()
    return "power" in label


def _cancel_penalty(penalties, team, when):
    running = [
        penalty
        for penalty in penalties
        if (
            penalty.team == team
            and penalty.cancellable
            and penalty.start <= when
            and penalty.left(when) > 0
        )
    ]
    if not running:
        return
    penalty = min(running, key=lambda item: item.left(when))
    elapsed = when - penalty.start
    left = penalty.left(when)
    into = elapsed % penalty.chunk
    left_in_chunk = penalty.chunk - into if into else penalty.chunk
    penalty.remaining = max(0, left - left_in_chunk)
    penalty.start = when


def _format_pp_clock(times):
    shown = []
    for seconds in sorted(seconds for seconds in times if seconds > 0)[:2]:
        whole = int(seconds)
        shown.append(f"{whole // 60}:{whole % 60:02d}")
    return "  ".join(shown)


def _summary_clock(payload):
    competitions = ((payload.get("header") or {}).get("competitions") or [])
    if not competitions or not isinstance(competitions[0], dict):
        return 0, ""
    status = competitions[0].get("status") or {}
    if not isinstance(status, dict):
        return 0, ""
    return _period_number(status.get("period")), str(status.get("displayClock") or "").strip()


def _best_clock(options):
    """The clock furthest into the game.

    A feed that still says the previous period ended is behind one that
    has the new period. Inside one period, less time remaining is later.
    A 0:00 reading is the horn, so it loses to a clock that is still running.
    """
    usable = []
    for period, clock in options:
        period = _period_number(period)
        if period and _clock_seconds(clock) is not None:
            usable.append((period, str(clock).strip()))
    if not usable:
        return 0, ""
    latest_period = max(period for period, _clock in usable)
    in_period = [item for item in usable if item[0] == latest_period]
    running = [
        ( _clock_seconds(clock), period, clock)
        for period, clock in in_period
        if _clock_seconds(clock)
    ]
    if running:
        _remaining, period, clock = min(running)
        return period, clock
    return in_period[0]


def _strength_label(play):
    strength = play.get("strength") if isinstance(play.get("strength"), dict) else {}
    return f"{strength.get('text') or ''} {strength.get('abbreviation') or ''}".lower()


def _latest_special_side(plays, sides, ot_length):
    """Advantage from the newest play that names a strength.

    A power-play goal is the end of that advantage, so it does not count
    as the power play still being on.
    """
    chosen = None
    chosen_at = None
    for play in plays:
        label = _strength_label(play).strip()
        if not label:
            continue
        moment = _play_time(play, ot_length)
        if moment is None:
            continue
        if chosen_at is None or moment >= chosen_at:
            chosen = play
            chosen_at = moment
    if not chosen:
        return ""
    label = _strength_label(chosen)
    side = sides.get(str((chosen.get("team") or {}).get("id") or ""), "")
    if "short" in label and side:
        return "home" if side == "away" else "away"
    if "power" in label and side and not chosen.get("scoringPlay"):
        return side
    return ""


def _skater_edge(away_lineup, home_lineup):
    away_count = len(tuple(away_lineup or ()))
    home_count = len(tuple(home_lineup or ()))
    if away_count < 3 or home_count < 3 or away_count == home_count:
        return "", ""
    if away_count > home_count:
        return "away", f"{away_count}-{home_count}"
    return "home", f"{away_count}-{home_count}"


def _apply_live_advantage(state, away_lineup, home_lineup, situation_flag):
    """Keep a reconstructed power play, or the live manpower if ESPN still has one."""
    advantage, clock, strength = state
    ice_side, ice_strength = _skater_edge(away_lineup, home_lineup)
    if advantage:
        if not strength and ice_side == advantage:
            strength = ice_strength
        return advantage, clock, strength
    if situation_flag and ice_side:
        return ice_side, "", ice_strength
    return "", "", ""


def _situation_flags(event_id):
    """ESPN's live power-play and empty-net flags."""
    event_id = str(event_id or "").strip()
    if not event_id:
        return False, False
    try:
        body = get_body(
            NHL_SITUATION_URL.format(event_id=event_id),
            HTTP_TIMEOUT,
        )
        payload = json.loads(body)
    except (requests.RequestException, ValueError, TypeError):
        return False, False
    if not isinstance(payload, dict):
        return False, False
    return bool(payload.get("powerPlay")), bool(payload.get("emptyNet"))


_PENALTY_LABELS = {
    "tripping": "TRIP",
    "hooking": "HOOK",
    "holding": "HOLD",
    "holding the stick": "HOLD",
    "interference": "INTERFER",
    "slashing": "SLASH",
    "roughing": "ROUGH",
    "cross-checking": "CROSS",
    "cross checking": "CROSS",
    "boarding": "BOARD",
    "elbowing": "ELBOW",
    "fighting": "FIGHT",
    "high-sticking": "HIGH STICK",
    "high sticking": "HIGH STICK",
    "delay of game": "DELAY",
    "too many men": "TOO MANY",
    "too many men on the ice": "TOO MANY",
    "unsportsmanlike conduct": "UNSPORT",
    "kneeing": "KNEE",
    "charging": "CHARGE",
    "embellishment": "EMBELL",
    "clipping": "CLIP",
    "checking from behind": "BEHIND",
    "illegal check to the head": "HEAD",
    "misconduct": "MISCONDUCT",
    "game misconduct": "MISCONDUCT",
}


def _athlete_name(play, index):
    people = play.get("participants") if isinstance(play, dict) else None
    if not isinstance(people, list) or index >= len(people):
        return ""
    person = people[index] if isinstance(people[index], dict) else {}
    athlete = person.get("athlete") if isinstance(person.get("athlete"), dict) else person
    display = str(athlete.get("displayName") or athlete.get("shortName") or "")
    parts = display.replace(".", " ").split()
    while parts and len(parts[0]) <= 1:
        parts = parts[1:]
    return parts[-1] if parts else ""


def _describe_play(play):
    """A short center line, or nothing for a faceoff or whistle."""
    if not isinstance(play, dict):
        return None
    kind = play.get("type") if isinstance(play.get("type"), dict) else {}
    label = str(kind.get("text") or "").strip().lower()
    if not label:
        return None
    if any(
        skip in label
        for skip in (
            "face off",
            "faceoff",
            "giveaway",
            "takeaway",
            "stoppage",
            "period start",
            "period end",
        )
    ):
        return None
    if kind.get("penaltyMinutes") or kind.get("penaltyType") or label in _PENALTY_LABELS:
        short = _PENALTY_LABELS.get(label) or label.upper()
        return _athlete_name(play, 0), short, False
    if play.get("scoringPlay") or label == "goal":
        return _athlete_name(play, 0), "GOAL", True
    if label == "shot":
        return _athlete_name(play, 1) or _athlete_name(play, 0), "SAVE", False
    if label == "missed":
        return _athlete_name(play, 0), "MISS", False
    if label == "hit":
        return _athlete_name(play, 0), "HIT", False
    if label == "blocked":
        return _athlete_name(play, 1) or _athlete_name(play, 0), "BLOCK", False
    return None


def _recent_play(plays):
    """The newest goal, save, miss, hit, block, or penalty."""
    if not isinstance(plays, list):
        return "", "", False
    for play in reversed(plays):
        described = _describe_play(play)
        if described:
            return described
    return "", "", False


def _power_play_state(payload, period, clock):
    """Who has the man advantage, and the penalty time still on the board."""
    if not isinstance(payload, dict):
        return "", "", ""
    period, clock = _best_clock((
        (period, clock),
        _summary_clock(payload),
    ))
    ot_length = _ot_length(_period_number(period), clock)
    now = _game_time(
        period,
        _clock_seconds(clock),
        elapsed=False,
        ot_length=ot_length,
    )
    if now is None:
        return "", "", ""

    sides = _team_sides(payload)
    penalties = []
    plays = [play for play in (payload.get("plays") or []) if isinstance(play, dict)]
    latest = None
    for play in plays:
        label = str((play.get("type") or {}).get("text") or "").lower()
        if "period end" in label or "period start" in label:
            continue
        moment = _play_time(play, ot_length)
        if moment is not None and (latest is None or moment > latest):
            latest = moment
    # The scoreboard clock can still be on the previous period when the
    # board wakes up. The play-by-play is already in the power play.
    if latest is not None and latest > now:
        now = latest
    events = []
    for play in plays:
        moment = _play_time(play, ot_length)
        if moment is None:
            continue
        if _manpower_penalty(play):
            events.append((moment, 0, play))
        elif _is_power_play_goal(play):
            events.append((moment, 1, play))
    events.sort(key=lambda item: (item[0], item[1]))

    for moment, kind, play in events:
        if moment > now:
            break
        if kind == 0:
            team, remaining, chunk, cancellable = _manpower_penalty(play)
            penalties.append(_BoxPenalty(team, moment, remaining, chunk, cancellable))
            continue
        scorer = str((play.get("team") or {}).get("id") or "").strip()
        for team_id in sides:
            if team_id != scorer:
                _cancel_penalty(penalties, team_id, moment)

    remaining = {"away": [], "home": []}
    for penalty in penalties:
        left = penalty.left(now)
        side = sides.get(penalty.team)
        if left > 0 and side in remaining:
            remaining[side].append(left)

    away = sorted((item for item in remaining["away"] if item > 0), reverse=True)
    home = sorted((item for item in remaining["home"] if item > 0), reverse=True)
    matched = min(len(away), len(home))
    away = away[matched:]
    home = home[matched:]
    if away and not home:
        short, advantage, times = len(away), "home", away
    elif home and not away:
        short, advantage, times = len(home), "away", home
    else:
        advantage = ""
        times = []
        short = 0

    if advantage:
        skaters = max(3, 5 - short)
        strength = f"5-{skaters}" if advantage == "away" else f"{skaters}-5"
        return advantage, _format_pp_clock(times), strength

    side = _latest_special_side(plays, sides, ot_length)
    if side:
        return side, "", ""
    return "", "", ""


def _box_shots(payload):
    """Shots on goal from the summary. The scoreboard does not carry them."""
    found = {"away": None, "home": None}
    if not isinstance(payload, dict):
        return None, None
    sides = _team_sides(payload)
    for entry in ((payload.get("boxscore") or {}).get("teams") or []):
        if not isinstance(entry, dict):
            continue
        side = sides.get(str((entry.get("team") or {}).get("id") or ""))
        if side not in found:
            continue
        for stat in entry.get("statistics") or []:
            if not isinstance(stat, dict):
                continue
            if str(stat.get("name") or "").lower() != "shotstotal":
                continue
            parsed = safe_int(stat.get("displayValue", stat.get("value")))
            if parsed is not None:
                found[side] = parsed
    return found["away"], found["home"]


def _load_goalies(event_id, period=0, clock=""):
    event_id = str(event_id or "").strip()
    empty = ("", "", "", "", (), (), "", "", "", "", "", False, False, None, None)
    if not event_id:
        return empty
    try:
        body = get_body(
            f"{NHL_SUMMARY_URL}?event={event_id}",
            HTTP_TIMEOUT,
        )
        payload = json.loads(body)
    except (requests.RequestException, ValueError, TypeError):
        return empty
    parsed = _parse_goalies(payload)
    away_name, away_pct = parsed["away"]
    home_name, home_pct = parsed["home"]
    away_lineup, home_lineup = _on_ice_lineups(payload)
    advantage, pp_clock, strength = _power_play_state(payload, period, clock)
    power_flag, empty_net = _situation_flags(event_id)
    ice_side, _ice_strength = _skater_edge(away_lineup, home_lineup)
    advantage, pp_clock, strength = _apply_live_advantage(
        (advantage, pp_clock, strength),
        away_lineup,
        home_lineup,
        power_flag if not advantage and ice_side else False,
    )
    play_name, play_label, play_goal = _recent_play(payload.get("plays"))
    away_shots, home_shots = _box_shots(payload)
    return (
        away_name,
        away_pct,
        home_name,
        home_pct,
        away_lineup,
        home_lineup,
        advantage,
        pp_clock,
        strength,
        play_name,
        play_label,
        play_goal,
        empty_net,
        away_shots,
        home_shots,
    )


def _attach_goalies(pending):
    if not pending:
        return
    workers = min(4, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        loaded = pool.map(
            lambda item: (item[0], _load_goalies(item[1], item[2], item[3])),
            pending,
        )
        for game, goalies in loaded:
            (
                game.away_goalie,
                game.away_save_pct,
                game.home_goalie,
                game.home_save_pct,
                game.away_lineup,
                game.home_lineup,
                advantage,
                pp_clock,
                strength,
                play_name,
                play_label,
                play_goal,
                empty_net,
                away_shots,
                home_shots,
            ) = goalies
            game.last_play_name = play_name
            game.last_play_label = play_label
            game.last_play_goal = bool(play_goal)
            game.empty_net = bool(empty_net)
            if away_shots is not None:
                game.away_sog = away_shots
            if home_shots is not None:
                game.home_sog = home_shots
            if advantage in {"away", "home"}:
                game.power_play = game.away if advantage == "away" else game.home
                game.power_play_clock = pp_clock
                if strength:
                    game.strength = strength


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
                event_id=str(event.get("id") or ""),
            )
        )
        if game_status != "Scheduled":
            pending_goalies.append((games[-1], event.get("id"), period, clock))

    _attach_goalies(pending_goalies)
    return games