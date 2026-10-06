from __future__ import annotations

import time
from datetime import date
from typing import Any

import requests

from mlb.api import MLB_SCHEDULE_URL, CA_BUNDLE, HTTP_TIMEOUT, get_team_abbr
from mlb.api import _session as mlb_session


def _abbr(team: dict) -> str:
    try:
        return get_team_abbr(team)
    except Exception:
        return str(team.get("abbreviation") or team.get("name") or "?")[:3].upper()

from bets.providers.base import EventInfo, EventSnapshot, PlayerInfo


SNAP_TTL = 25.0
EVENTS_TTL = 45.0

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, loader):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


def _get(url: str, params: dict | None = None) -> dict:
    response = mlb_session.get(
        url,
        params=params,
        timeout=HTTP_TIMEOUT,
        verify=CA_BUNDLE,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected MLB response.")
    return data


def _status_label(detailed: str, abstract: str) -> str:
    text = f"{detailed} {abstract}".lower()
    if "final" in text:
        return "Final"
    if "progress" in text or "live" in text or abstract.lower() == "live":
        return "Live"
    return "Scheduled"


class MlbProvider:
    league = "mlb"

    def list_events(self) -> list[EventInfo]:
        def load():
            payload = _get(
                MLB_SCHEDULE_URL,
                {
                    "sportId": 1,
                    "date": date.today().isoformat(),
                    "hydrate": "linescore,team",
                },
            )
            events = []
            for day in payload.get("dates") or []:
                for game in day.get("games") or []:
                    status = game.get("status") or {}
                    teams = game.get("teams") or {}
                    away = (teams.get("away") or {}).get("team") or {}
                    home = (teams.get("home") or {}).get("team") or {}
                    linescore = game.get("linescore") or {}
                    away_abbr = _abbr(away)
                    home_abbr = _abbr(home)
                    events.append(
                        EventInfo(
                            league="mlb",
                            event_id=str(game.get("gamePk") or ""),
                            label=f"{away_abbr} @ {home_abbr}",
                            away=away_abbr,
                            home=home_abbr,
                            status=_status_label(
                                str(status.get("detailedState") or ""),
                                str(status.get("abstractGameState") or ""),
                            ),
                            start_time=str(game.get("gameDate") or ""),
                            date=str(game.get("officialDate") or ""),
                            away_score=int((teams.get("away") or {}).get("score") or 0),
                            home_score=int((teams.get("home") or {}).get("score") or 0),
                            period=str(linescore.get("currentInning") or ""),
                            clock="Top" if linescore.get("isTopInning") else "Bot",
                        )
                    )
            return events

        try:
            return _cached("events:mlb", EVENTS_TTL, load)
        except (OSError, ValueError, requests.RequestException):
            return []

    def list_players(self, event_id: str) -> list[PlayerInfo]:
        snapshot_payload = self._feed(event_id)
        players: dict[str, PlayerInfo] = {}
        box = ((snapshot_payload.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
        for side in ("away", "home"):
            team = box.get(side) or {}
            abbr = _abbr((team.get("team") or {"name": side}))
            for person in (team.get("players") or {}).values():
                info = person.get("person") or {}
                player_id = str(info.get("id") or "").strip()
                name = str(info.get("fullName") or info.get("boxscoreName") or "").strip()
                if player_id and name:
                    players[player_id] = PlayerInfo(
                        player_id=player_id,
                        name=name,
                        team=abbr,
                        position=str((person.get("position") or {}).get("abbreviation") or ""),
                    )
        return sorted(players.values(), key=lambda item: item.name)

    def _feed(self, event_id: str) -> dict:
        url = f"https://statsapi.mlb.com/api/v1.1/game/{event_id}/feed/live"

        def load():
            return _get(
                url,
                {
                    "fields": (
                        "gameData,status,detailedState,abstractGameState,"
                        "liveData,boxscore,teams,away,home,team,id,name,"
                        "players,person,fullName,boxscoreName,position,"
                        "abbreviation,stats,batting,pitching,hits,atBats,"
                        "runs,rbi,homeRuns,baseOnBalls,totalBases,strikeOuts,"
                        "doubles,triples,linescore,currentInning,isTopInning,"
                        "teams,away,home,runs"
                    )
                },
            )

        return _cached(f"mlbfeed:{event_id}", SNAP_TTL, load)

    def snapshot(self, event_id: str) -> EventSnapshot | None:
        try:
            payload = self._feed(event_id)
        except Exception:
            return None
        game_data = payload.get("gameData") or {}
        status = _status_label(
            str((game_data.get("status") or {}).get("detailedState") or ""),
            str((game_data.get("status") or {}).get("abstractGameState") or ""),
        )
        linescore = (payload.get("liveData") or {}).get("linescore") or {}
        teams = linescore.get("teams") or {}
        box = ((payload.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
        away_team = _abbr(((box.get("away") or {}).get("team") or {"name": "AWAY"}))
        home_team = _abbr(((box.get("home") or {}).get("team") or {"name": "HOME"}))
        player_stats: dict[str, dict[str, float]] = {}
        inning = int(linescore.get("currentInning") or 0)
        remaining = None
        if status == "Scheduled":
            remaining = 1.0
        elif status == "Final":
            remaining = 0.0
        elif inning:
            remaining = max(0.0, min(1.0, 1.0 - (inning - 1) / 9.0))

        for side in ("away", "home"):
            for person in ((box.get(side) or {}).get("players") or {}).values():
                info = person.get("person") or {}
                player_id = str(info.get("id") or "").strip()
                if not player_id:
                    continue
                batting = ((person.get("stats") or {}).get("batting") or {})
                pitching = ((person.get("stats") or {}).get("pitching") or {})
                doubles = float(batting.get("doubles") or 0)
                triples = float(batting.get("triples") or 0)
                hr = float(batting.get("homeRuns") or 0)
                hits = float(batting.get("hits") or 0)
                total_bases = batting.get("totalBases")
                if total_bases is None:
                    singles = max(0.0, hits - doubles - triples - hr)
                    total_bases = singles + 2 * doubles + 3 * triples + 4 * hr
                mapped = {
                    "hits": hits,
                    "total_bases": float(total_bases or 0),
                    "home_runs": hr,
                    "runs": float(batting.get("runs") or 0),
                    "rbi": float(batting.get("rbi") or 0),
                    "batter_bb": float(batting.get("baseOnBalls") or 0),
                    "batter_k": float(batting.get("strikeOuts") or 0),
                    "pitcher_k": float(pitching.get("strikeOuts") or 0),
                    "pitcher_bb": float(pitching.get("baseOnBalls") or 0),
                    "pitcher_hits": float(pitching.get("hits") or 0),
                }
                player_stats[player_id] = mapped

        return EventSnapshot(
            league="mlb",
            event_id=str(event_id),
            status=status,
            away=away_team,
            home=home_team,
            away_score=int((teams.get("away") or {}).get("runs") or 0),
            home_score=int((teams.get("home") or {}).get("runs") or 0),
            period=str(linescore.get("currentInning") or ""),
            clock="Top" if linescore.get("isTopInning") else "Bot",
            remaining_fraction=remaining,
            player_stats=player_stats,
            fetched_at=time.time(),
        )
