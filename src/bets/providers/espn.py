from __future__ import annotations

import json
import time
from typing import Any

from common.http import get_body

from bets.providers.base import EventInfo, EventSnapshot, PlayerInfo


HTTP_TIMEOUT = (3.05, 10)
SUMMARY_TTL = 25.0
EVENTS_TTL = 45.0
ROSTER_TTL = 30 * 60

ESPN_PATHS = {
    "nfl": "football/nfl",
    "cfb": "football/college-football",
    "nba": "basketball/nba",
    "nhl": "hockey/nhl",
}

GAME_MINUTES = {
    "nfl": 60.0,
    "cfb": 60.0,
    "nba": 48.0,
    "nhl": 60.0,
}

QUARTERS = {
    "nfl": (4, 15.0),
    "cfb": (4, 15.0),
    "nba": (4, 12.0),
    "nhl": (3, 20.0),
}

STAT_KEYS = {
    "pass_yds": ("passingYards",),
    "pass_td": ("passingTouchdowns",),
    "pass_comp": ("completions",),
    "pass_att": ("passingAttempts",),
    "pass_int": ("interceptions",),
    "rush_yds": ("rushingYards",),
    "rush_att": ("rushingAttempts",),
    "rush_td": ("rushingTouchdowns",),
    "rec_yds": ("receivingYards",),
    "receptions": ("receptions",),
    "rec_td": ("receivingTouchdowns",),
    "points": ("points",),
    "rebounds": ("rebounds",),
    "assists": ("assists",),
    "threes": ("threePointFieldGoalsMade",),
    "steals": ("steals",),
    "blocks": ("blocks",),
    "turnovers": ("turnovers",),
    "goals": ("goals",),
    "hockey_assists": ("assists",),
    "hockey_points": ("points",),
    "shots": ("shots", "shotsOnGoal"),
    "saves": ("saves",),
}


_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, loader):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


def _fetch_json(url: str) -> dict:
    body = get_body(url, HTTP_TIMEOUT)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("Unexpected ESPN response.")
    return data


def _parse_clock(clock: str) -> float:
    text = str(clock or "").strip()
    if not text or text in {"0:00", "00:00"}:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return max(0.0, int(parts[0]) + int(parts[1]) / 60.0)
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return 0.0


def remaining_fraction(league: str, status: str, period: str, clock: str) -> float | None:
    state = str(status or "").lower()
    if state in {"scheduled", "pre"}:
        return 1.0
    if state in {"final", "post"}:
        return 0.0
    periods, minutes = QUARTERS.get(league, (4, 15.0))
    try:
        current = int(float(period or 0))
    except (TypeError, ValueError):
        current = 1
    current = max(1, current)
    leftover_periods = max(0, periods - current)
    clock_minutes = _parse_clock(clock)
    remaining = leftover_periods * minutes + clock_minutes
    total = periods * minutes
    if total <= 0:
        return None
    return max(0.0, min(1.0, remaining / total))


def _event_status(competition: dict) -> tuple[str, str, str]:
    status = (competition.get("status") or {})
    type_info = status.get("type") or {}
    state = str(type_info.get("state") or "").lower()
    period = str(status.get("period") or "")
    clock = str(status.get("displayClock") or "")
    if state == "pre":
        return "Scheduled", "0", ""
    if state == "in":
        return "Live", period, clock
    return "Final", period, ""


def _competitors(competition: dict) -> tuple[dict, dict]:
    competitors = competition.get("competitors") or []
    away = next((item for item in competitors if item.get("homeAway") == "away"), {})
    home = next((item for item in competitors if item.get("homeAway") == "home"), {})
    return away, home


def _abbr(competitor: dict) -> str:
    team = competitor.get("team") or {}
    return str(team.get("abbreviation") or team.get("shortDisplayName") or "")[:8].upper()


def _score(competitor: dict) -> int:
    try:
        return int(competitor.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _parse_stat_token(raw) -> float:
    text = str(raw or "0").strip()
    if not text or text in {"-", "--"}:
        return 0.0
    if "/" in text:
        text = text.split("/", 1)[0]
    if "-" in text and not text.startswith("-"):
        text = text.split("-", 1)[0]
    try:
        return float(text)
    except ValueError:
        return 0.0


def _stats_from_boxscore(boxscore: dict) -> dict[str, dict[str, float]]:
    players: dict[str, dict[str, float]] = {}
    for team_block in boxscore.get("players") or []:
        team = str((team_block.get("team") or {}).get("abbreviation") or "").upper()
        for group in team_block.get("statistics") or []:
            keys = [str(key) for key in (group.get("keys") or [])]
            for athlete in group.get("athletes") or []:
                person = athlete.get("athlete") or {}
                player_id = str(person.get("id") or "").strip()
                if not player_id:
                    continue
                values = athlete.get("stats") or []
                mapped = players.setdefault(player_id, {"_team": team})  # type: ignore
                mapped["_team"] = team
                for index, key in enumerate(keys):
                    if index >= len(values):
                        break
                    amount = _parse_stat_token(values[index])
                    if key == "completions/passingAttempts":
                        mapped["completions"] = _parse_stat_token(str(values[index]).split("/")[0])
                        mapped["passingAttempts"] = _parse_stat_token(
                            str(values[index]).split("/")[-1]
                        )
                        continue
                    mapped[key] = amount
                    if "-" in key and key.split("-", 1)[0] in {
                        "threePointFieldGoalsMade",
                        "fieldGoalsMade",
                        "sacks",
                    }:
                        mapped[key.split("-", 1)[0]] = amount
    return players


def _player_market_value(stats: dict[str, float], market: str) -> float | None:
    if market == "rush_rec_yds":
        return stats.get("rushingYards", 0) + stats.get("receivingYards", 0)
    if market == "anytime_td":
        return stats.get("rushingTouchdowns", 0) + stats.get("receivingTouchdowns", 0)
    if market == "pra":
        return stats.get("points", 0) + stats.get("rebounds", 0) + stats.get("assists", 0)
    if market == "pr":
        return stats.get("points", 0) + stats.get("rebounds", 0)
    if market == "pa":
        return stats.get("points", 0) + stats.get("assists", 0)
    if market == "ra":
        return stats.get("rebounds", 0) + stats.get("assists", 0)
    for key in STAT_KEYS.get(market, ()):
        if key in stats:
            return float(stats[key])
    return None


class EspnProvider:
    def __init__(self, league: str):
        if league not in ESPN_PATHS:
            raise ValueError(league)
        self.league = league
        self.path = ESPN_PATHS[league]

    def _scoreboard_url(self) -> str:
        return (
            "https://site.api.espn.com/apis/site/v2/sports/"
            f"{self.path}/scoreboard"
        )

    def _summary_url(self, event_id: str) -> str:
        return (
            "https://site.api.espn.com/apis/site/v2/sports/"
            f"{self.path}/summary?event={event_id}"
        )

    def _roster_url(self, team_id: str) -> str:
        return (
            "https://site.api.espn.com/apis/site/v2/sports/"
            f"{self.path}/teams/{team_id}/roster"
        )

    def list_events(self) -> list[EventInfo]:
        def load():
            data = _fetch_json(self._scoreboard_url())
            events = []
            for event in data.get("events") or []:
                competitions = event.get("competitions") or []
                if not competitions:
                    continue
                competition = competitions[0]
                away, home = _competitors(competition)
                status, period, clock = _event_status(competition)
                events.append(
                    EventInfo(
                        league=self.league,
                        event_id=str(event.get("id") or ""),
                        label=str(event.get("shortName") or event.get("name") or ""),
                        away=_abbr(away),
                        home=_abbr(home),
                        status=status,
                        start_time=str(event.get("date") or ""),
                        date=str(event.get("date") or "")[:10],
                        away_score=_score(away),
                        home_score=_score(home),
                        period=period,
                        clock=clock,
                    )
                )
            return events

        return _cached(f"events:{self.league}", EVENTS_TTL, load)

    def list_players(self, event_id: str) -> list[PlayerInfo]:
        snapshot = self.snapshot(event_id)
        if snapshot and snapshot.player_stats:
            # Live/final box score names are incomplete without roster merge.
            pass

        def load_header():
            return _fetch_json(self._summary_url(event_id))

        summary = _cached(f"summary:{self.league}:{event_id}", SUMMARY_TTL, load_header)
        players: dict[str, PlayerInfo] = {}
        box_players = (summary.get("boxscore") or {}).get("players") or []
        for team_block in box_players:
            team = str((team_block.get("team") or {}).get("abbreviation") or "").upper()
            for group in team_block.get("statistics") or []:
                for athlete in group.get("athletes") or []:
                    person = athlete.get("athlete") or {}
                    player_id = str(person.get("id") or "").strip()
                    name = str(person.get("displayName") or "").strip()
                    if player_id and name:
                        players[player_id] = PlayerInfo(
                            player_id=player_id,
                            name=name,
                            team=team,
                            position=str((person.get("position") or {}).get("abbreviation") or ""),
                        )

        header = summary.get("header") or {}
        competitions = header.get("competitions") or []
        if competitions:
            for competitor in competitions[0].get("competitors") or []:
                team = competitor.get("team") or {}
                team_id = str(team.get("id") or "")
                abbr = str(team.get("abbreviation") or "").upper()
                if not team_id:
                    continue

                def load_roster(url=self._roster_url(team_id)):
                    return _fetch_json(url)

                try:
                    roster = _cached(f"roster:{self.league}:{team_id}", ROSTER_TTL, load_roster)
                except Exception:
                    continue
                for group in roster.get("athletes") or []:
                    for item in group.get("items") or []:
                        player_id = str(item.get("id") or "").strip()
                        name = str(item.get("displayName") or "").strip()
                        if not player_id or not name:
                            continue
                        position = item.get("position") or {}
                        players[player_id] = PlayerInfo(
                            player_id=player_id,
                            name=name,
                            team=abbr,
                            position=str(position.get("abbreviation") or ""),
                        )

        return sorted(players.values(), key=lambda item: item.name)

    def snapshot(self, event_id: str) -> EventSnapshot | None:
        def load():
            return _fetch_json(self._summary_url(event_id))

        try:
            summary = _cached(f"summary:{self.league}:{event_id}", SUMMARY_TTL, load)
        except Exception:
            return None

        header = summary.get("header") or {}
        competitions = header.get("competitions") or []
        if not competitions:
            return None
        competition = competitions[0]
        away, home = _competitors(competition)
        status, period, clock = _event_status(competition)
        stats = _stats_from_boxscore(summary.get("boxscore") or {})
        player_stats: dict[str, dict[str, float]] = {}
        for player_id, raw in stats.items():
            mapped: dict[str, float] = {}
            for market in (
                "pass_yds", "pass_td", "pass_comp", "pass_att", "pass_int",
                "rush_yds", "rush_att", "rush_td", "rec_yds", "receptions",
                "rec_td", "rush_rec_yds", "anytime_td", "points", "rebounds",
                "assists", "threes", "steals", "blocks", "turnovers", "pra",
                "pr", "pa", "ra", "goals", "hockey_assists", "hockey_points",
                "shots", "saves",
            ):
                value = _player_market_value(raw, market)
                if value is not None:
                    mapped[market] = value
            if mapped:
                player_stats[player_id] = mapped

        return EventSnapshot(
            league=self.league,
            event_id=str(event_id),
            status=status,
            away=_abbr(away),
            home=_abbr(home),
            away_score=_score(away),
            home_score=_score(home),
            period=period,
            clock=clock,
            remaining_fraction=remaining_fraction(self.league, status, period, clock),
            player_stats=player_stats,
            fetched_at=time.time(),
        )
