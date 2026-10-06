from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import unicodedata

from common.timezone import get_local_timezone

import requests

from mlb.models import BaseballGame, MlbPitch, MlbScoringPlay

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)
LIVE_FEED_TIMEOUT = (2.05, 6)

LIVE_FEED_FIELDS = (
    "liveData,plays,currentPlay,matchup,batter,pitcher,fullName,"
    "lastName,boxscoreName,id,"
    "playEvents,details,isPitch,call,description,code,"
    "pitchData,coordinates,pX,pZ,strikeZoneTop,strikeZoneBottom,startSpeed,"
    "type,"
    "boxscore,teams,home,away,players,stats,pitching,batting,"
    "seasonStats,numberOfPitches,pitchesThrown,atBats,hits,avg"
)

_session = requests.Session()
_session.headers.update({
    "User-Agent": "P4SportsTicker/1.0",
    "Accept": "application/json",
})

# lookup table to convert team id's to abbreviations
TEAM_ABBR = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "ATH",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


def get_team_abbr(team):
    return TEAM_ABBR.get(team["id"], team["name"][:3].upper())


def format_local_time(utc_time_str):
    utc_dt = datetime.fromisoformat(
        utc_time_str.replace("Z", "+00:00")
    )

    local_dt = utc_dt.astimezone(
        get_local_timezone()
    )

    return local_dt.strftime("%-I:%M")


def get_record(team_data):
    record = team_data.get("leagueRecord", {})

    return {
        "wins": record.get("wins", 0),
        "losses": record.get("losses", 0),
    }


_NAME_SUFFIXES = {
    "JR": "JR",
    "JR.": "JR",
    "JUNIOR": "JR",
    "SR": "SR",
    "SR.": "SR",
    "SENIOR": "SR",
    "II": "II",
    "III": "III",
    "IV": "IV",
    "V": "V",
}


def _last_name_from_full(full_name):
    parts = [
        part
        for part in str(full_name or "").replace(",", " ").split()
        if part
    ]
    if not parts:
        return ""

    suffix_key = parts[-1].upper()
    suffix = _NAME_SUFFIXES.get(suffix_key)
    if suffix and len(parts) >= 2:
        last = parts[-2]
        return f"{last} {suffix}"

    return parts[-1]


def _person_last_name(person):
    if not isinstance(person, dict):
        return ""

    last_name = str(person.get("lastName") or "").strip()
    full_name = str(
        person.get("fullName")
        or person.get("boxscoreName")
        or ""
    ).strip()

    display = ""
    if last_name:
        display = _last_name_from_full(last_name)
        if display.replace(".", "").upper() in _NAME_SUFFIXES:
            display = ""

    if not display:
        display = _last_name_from_full(full_name)

    folded = unicodedata.normalize("NFKD", str(display))
    ascii_name = "".join(
        char for char in folded if not unicodedata.combining(char)
    )
    return ascii_name.replace(".", "").upper()


def _batter_last_name(play):
    matchup = play.get("matchup") or {}
    return _person_last_name(matchup.get("batter"))


def _parse_scoring_plays(game, away, home):
    plays = []

    for index, play in enumerate(game.get("scoringPlays") or []):
        if not isinstance(play, dict):
            continue

        result = play.get("result") or {}
        about = play.get("about") or {}
        event = str(result.get("event") or "").strip()
        event_type = str(result.get("eventType") or "").strip()
        description = str(result.get("description") or "").strip()
        half = str(about.get("halfInning") or "").strip().lower()
        inning = int(about.get("inning") or 0)
        rbi = int(result.get("rbi") or 0)
        batting_team = away if half == "top" else home
        play_id = (
            f"{inning}:{half}:{event}:{rbi}:"
            f"{result.get('awayScore')}:"
            f"{result.get('homeScore')}:"
            f"{description}"
        )

        plays.append(
            MlbScoringPlay(
                play_id=play_id or f"play-{index}",
                event=event,
                event_type=event_type,
                description=description,
                rbi=rbi,
                inning=inning,
                half=half,
                batter=_batter_last_name(play),
                batting_team=str(batting_team or "").upper(),
            )
        )

    return tuple(plays)


def _pitch_result(event):
    details = event.get("details") or {}
    call = details.get("call") or {}
    if not isinstance(call, dict):
        call = {}

    code = str(
        call.get("code")
        or details.get("code")
        or ""
    ).upper()
    description = str(details.get("description") or "").lower()

    if code == "B" or (
        "ball" in description
        and "in play" not in description
        and "foul" not in description
    ):
        return "ball"

    if code in {"F", "L"} or "foul" in description:
        return "foul"

    if (
        code in {"X", "E", "D", "H"}
        or description.startswith("in play")
    ):
        return "in_play"

    return "strike"


def _boxscore_player(payload, person_id):
    if not person_id:
        return {}

    key = f"ID{person_id}"
    teams = (
        ((payload.get("liveData") or {}).get("boxscore") or {})
        .get("teams")
        or {}
    )

    for side in ("home", "away"):
        players = (teams.get(side) or {}).get("players") or {}
        person = players.get(key)
        if isinstance(person, dict):
            return person

    return {}


def _pitcher_pitch_count(payload, pitcher_id):
    pitching = (
        (_boxscore_player(payload, pitcher_id).get("stats") or {})
        .get("pitching")
        or {}
    )
    for field in ("numberOfPitches", "pitchesThrown"):
        try:
            value = int(pitching.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _batter_stat_line(payload, batter_id):
    player = _boxscore_player(payload, batter_id)
    game_batting = (player.get("stats") or {}).get("batting") or {}
    season_batting = (player.get("seasonStats") or {}).get("batting") or {}

    try:
        at_bats = int(game_batting.get("atBats") or 0)
    except (TypeError, ValueError):
        at_bats = 0
    try:
        hits = int(game_batting.get("hits") or 0)
    except (TypeError, ValueError):
        hits = 0

    if at_bats > 0:
        return f"{hits}-{at_bats}"

    avg = str(
        season_batting.get("avg")
        or game_batting.get("avg")
        or ""
    ).strip()
    if avg.startswith("0.") and len(avg) > 2:
        avg = avg[1:]
    return avg


def _parse_current_at_bat(payload):
    current_play = (
        ((payload.get("liveData") or {}).get("plays") or {})
        .get("currentPlay")
        or {}
    )
    matchup = current_play.get("matchup") or {}
    batter_person = matchup.get("batter") if isinstance(matchup.get("batter"), dict) else {}
    pitcher_person = matchup.get("pitcher") if isinstance(matchup.get("pitcher"), dict) else {}
    batter = _person_last_name(batter_person)
    pitcher = _person_last_name(pitcher_person)
    pitcher_pitches = _pitcher_pitch_count(payload, pitcher_person.get("id"))
    batter_stat = _batter_stat_line(payload, batter_person.get("id"))
    pitches = []
    zone_top = 3.5
    zone_bottom = 1.5

    for event in current_play.get("playEvents") or []:
        if not isinstance(event, dict):
            continue
        if not event.get("isPitch"):
            continue

        pitch_data = event.get("pitchData") or {}
        coordinates = pitch_data.get("coordinates") or {}
        px = coordinates.get("pX")
        pz = coordinates.get("pZ")

        if px is None or pz is None:
            continue

        top = float(pitch_data.get("strikeZoneTop") or zone_top)
        bottom = float(pitch_data.get("strikeZoneBottom") or zone_bottom)
        zone_top = top
        zone_bottom = bottom

        try:
            speed = float(pitch_data.get("startSpeed") or 0)
        except (TypeError, ValueError):
            speed = 0.0
        type_info = (event.get("details") or {}).get("type") or {}
        if not isinstance(type_info, dict):
            type_info = {}
        pitch_type = str(type_info.get("code") or "").upper()
        pitch_name = str(type_info.get("description") or "").strip()

        pitches.append(
            MlbPitch(
                px=float(px),
                pz=float(pz),
                result=_pitch_result(event),
                strike_zone_top=top,
                strike_zone_bottom=bottom,
                speed=speed,
                pitch_type=pitch_type,
                pitch_name=pitch_name,
            )
        )

    return {
        "batter": batter,
        "pitcher": pitcher,
        "pitcher_pitches": pitcher_pitches,
        "batter_stat": batter_stat,
        "pitches": tuple(pitches),
        "strike_zone_top": zone_top,
        "strike_zone_bottom": zone_bottom,
    }


def fetch_current_at_bat(game_pk):
    pk = str(game_pk or "").strip()
    if not pk:
        return {}

    try:
        response = _session.get(
            MLB_LIVE_FEED_URL.format(game_pk=pk),
            params={"fields": LIVE_FEED_FIELDS},
            timeout=LIVE_FEED_TIMEOUT,
            verify=CA_BUNDLE,
        )
        response.raise_for_status()
        return _parse_current_at_bat(response.json())
    except (OSError, ValueError, requests.RequestException):
        return {}


def _enrich_live_at_bats(games):
    live_games = [
        game
        for game in games
        if str(game.status).lower() == "live"
        and game.game_pk
    ]

    if not live_games:
        return games

    updates = {}
    workers = min(6, len(live_games))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_current_at_bat, game.game_pk): game.game_pk
            for game in live_games
        }

        for future in as_completed(futures):
            game_pk = futures[future]
            try:
                payload = future.result()
            except Exception:
                payload = {}

            if payload:
                updates[game_pk] = payload

    for game in games:
        payload = updates.get(game.game_pk)
        if not payload:
            continue

        if payload.get("batter"):
            game.batter = payload["batter"]
        if payload.get("pitcher"):
            game.pitcher = payload["pitcher"]
        game.pitcher_pitches = int(payload.get("pitcher_pitches") or 0)
        game.batter_stat = str(payload.get("batter_stat") or "")
        game.pitches = payload.get("pitches") or ()
        game.strike_zone_top = float(
            payload.get("strike_zone_top") or game.strike_zone_top
        )
        game.strike_zone_bottom = float(
            payload.get("strike_zone_bottom") or game.strike_zone_bottom
        )

    return games


def _parse_game(game, include_scoring_plays=False):
    linescore = game.get("linescore", {})

    away_data = game["teams"]["away"]
    home_data = game["teams"]["home"]

    away_team = away_data["team"]
    home_team = home_data["team"]

    away_record = get_record(away_data)
    home_record = get_record(home_data)
    away = get_team_abbr(away_team)
    home = get_team_abbr(home_team)
    scoring_plays = ()
    offense = linescore.get("offense") or {}
    defense = linescore.get("defense") or {}

    if include_scoring_plays:
        scoring_plays = _parse_scoring_plays(
            game,
            away,
            home,
        )

    return BaseballGame(
        away=away,
        home=home,
        status=game["status"]["abstractGameState"],
        start_time=format_local_time(game["gameDate"]),
        away_score=away_data.get("score", 0) or 0,
        home_score=home_data.get("score", 0) or 0,
        away_wins=away_record["wins"],
        away_losses=away_record["losses"],
        home_wins=home_record["wins"],
        home_losses=home_record["losses"],
        inning=linescore.get("currentInning", 0) or 0,
        top_inning=linescore.get("inningHalf") == "Top",
        first=bool(linescore.get("offense", {}).get("first")),
        second=bool(linescore.get("offense", {}).get("second")),
        third=bool(linescore.get("offense", {}).get("third")),
        outs=linescore.get("outs", 0) or 0,
        game_pk=str(game.get("gamePk") or ""),
        scoring_plays=scoring_plays,
        balls=int(linescore.get("balls", 0) or 0),
        strikes=int(linescore.get("strikes", 0) or 0),
        batter=_person_last_name(offense.get("batter")),
        pitcher=_person_last_name(defense.get("pitcher")),
    )


def _fetch_schedule(hydrate):
    today = datetime.now(
        get_local_timezone()
    ).strftime("%Y-%m-%d")

    params = {
        "sportId": 1,
        "date": today,
        "hydrate": hydrate,
    }

    response = _session.get(
        MLB_SCHEDULE_URL,
        params=params,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    return response.json()


def _parse_schedule(data, include_scoring_plays=False):
    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            try:
                games.append(
                    _parse_game(
                        game,
                        include_scoring_plays=(
                            include_scoring_plays
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

    return games


def get_today_games():
    data = _fetch_schedule(
        "probablePitcher,linescore,team"
    )

    return _enrich_live_at_bats(_parse_schedule(data))


def get_alert_games():
    data = _fetch_schedule(
        "linescore,team,scoringplays"
    )

    return _parse_schedule(
        data,
        include_scoring_plays=True,
    )
