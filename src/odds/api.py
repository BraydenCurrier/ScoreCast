import requests

from common.settings import get_settings
from odds.models import BettingOdds


BASE_URL = "https://api.the-odds-api.com/v4/sports"
CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


SPORT_KEYS = {
    "mlb": "baseball_mlb",
    "nfl": "americanfootball_nfl",
    "cfb": "americanfootball_ncaaf",
    "nba": "basketball_nba",
    "nhl": "icehockey_nhl",
}


def get_odds(sport):
    settings = get_settings()
    odds_settings = settings.get("odds", {})

    if not odds_settings.get("enabled", True):
        return []

    api_key = odds_settings.get("api_key", "").strip()

    if not api_key:
        return []

    sportsbook = odds_settings.get("sportsbook", "draftkings").strip()

    sport_key = SPORT_KEYS.get(sport)

    if sport_key is None:
        return []

    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
    }

    if sportsbook:
        params["bookmakers"] = sportsbook

    response = requests.get(
        f"{BASE_URL}/{sport_key}/odds",
        params=params,
        timeout=15,
        verify=CA_BUNDLE,
    )

    response.raise_for_status()

    data = response.json()
    odds = []

    for game in data:
        bookmakers = game.get("bookmakers", [])

        if not bookmakers:
            continue

        bookmaker = bookmakers[0]

        model = BettingOdds(
            away=game.get("away_team", ""),
            home=game.get("home_team", ""),
            sportsbook=bookmaker.get("title", ""),
        )

        markets = {}

        for market in bookmaker.get("markets", []):
            markets[market.get("key")] = market.get("outcomes", [])

        if "h2h" in markets:
            for outcome in markets["h2h"]:
                if outcome.get("name") == model.away:
                    model.moneyline_away = outcome.get("price")

                elif outcome.get("name") == model.home:
                    model.moneyline_home = outcome.get("price")

        if "spreads" in markets:
            for outcome in markets["spreads"]:
                if outcome.get("name") == model.away:
                    model.spread = outcome.get("point")
                    model.spread_price = outcome.get("price")
                    break

        if "totals" in markets:
            for outcome in markets["totals"]:
                if outcome.get("name") == "Over":
                    model.total = outcome.get("point")
                    model.over_price = outcome.get("price")

                elif outcome.get("name") == "Under":
                    model.under_price = outcome.get("price")

        odds.append(model)

    return odds