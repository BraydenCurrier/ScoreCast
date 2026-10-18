from __future__ import annotations

from typing import Any


CLASS_TO_SPORT = {
    "FootballGame": "nfl",
    "CfbGame": "cfb",
    "CollegeFootballGame": "cfb",
    "BasketballGame": "nba",
    "HockeyGame": "nhl",
    "SoccerGame": "soccer",
    "GolfTournament": "pga",
    "StockQuote": "stocks",
    "FantasyMatchup": "fantasy",
    "BaseballGame": "mlb",
    "BetTicket": "bets",
}


def is_stock_id(game_id: str) -> bool:
    return str(game_id).startswith("stocks:")


def sport_for_game(game: Any) -> str:
    return CLASS_TO_SPORT.get(game.__class__.__name__, "mlb")


def game_id(game: Any) -> str:
    class_name = game.__class__.__name__

    if class_name == "BetTicket":
        return str(getattr(game, "ticket_id", "") or "")

    sport = sport_for_game(game)

    if sport == "stocks":
        symbol = str(
            getattr(game, "symbol", "")
            or getattr(game, "away", "")
            or ""
        ).strip().upper()
        return f"stocks:{symbol}" if symbol else "stocks:"

    if sport == "fantasy":
        league_id = str(getattr(game, "league_id", "") or "").strip()
        week = str(getattr(game, "week", "") or "").strip()
        matchup_id = str(getattr(game, "matchup_id", "") or "").strip()
        if league_id and week and matchup_id:
            return f"fantasy:{league_id}:{week}:{matchup_id}"

    event_id = str(
        getattr(game, "event_id", "")
        or getattr(game, "game_pk", "")
        or ""
    ).strip()
    if event_id:
        return f"{sport}:{event_id}"

    away = str(getattr(game, "away", "") or "").strip().upper()
    home = str(getattr(game, "home", "") or "").strip().upper()
    return f"{sport}:{away}@{home}"


def selected_sports_ids(settings: dict[str, Any]) -> set[str]:
    if "selected_games" in settings:
        values = settings.get("selected_games") or []
        if isinstance(values, str):
            values = [values]
        return {
            str(item).strip()
            for item in values
            if str(item).strip() and not is_stock_id(str(item))
        }

    hidden = {
        str(item)
        for item in (settings.get("hidden_games") or [])
    }
    order = settings.get("game_order") or []
    if isinstance(order, str):
        order = [order]
    return {
        str(item).strip()
        for item in order
        if (
            str(item).strip()
            and not is_stock_id(str(item))
            and str(item) not in hidden
        )
    }


def game_is_shown(game: Any, settings: dict[str, Any]) -> bool:
    identifier = game_id(game)
    if is_stock_id(identifier):
        hidden = {
            str(item)
            for item in (settings.get("hidden_games") or [])
        }
        return identifier not in hidden
    return identifier in selected_sports_ids(settings)
