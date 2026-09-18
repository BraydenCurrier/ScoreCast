from datetime import datetime

from common.timezone import get_local_timezone

import requests

from mlb.models import BaseballGame, MlbScoringPlay

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

HTTP_TIMEOUT = (3.05, 10)

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


def _batter_last_name(play):
    matchup = play.get("matchup") or {}
    batter = matchup.get("batter") or {}
    full_name = str(batter.get("fullName") or "").strip()

    if not full_name:
        return ""

    return full_name.split()[-1]


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

    return _parse_schedule(data)


def get_alert_games():
    data = _fetch_schedule(
        "linescore,team,scoringplays"
    )

    return _parse_schedule(
        data,
        include_scoring_plays=True,
    )
