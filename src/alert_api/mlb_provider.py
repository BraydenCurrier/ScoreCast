import requests
from datetime import date

from alert_api.provider_base import AlertProvider
from alert_api.models import AlertEvent


class MLBProvider(AlertProvider):
    name = "mlb"

    def __init__(self):
        self.base_url = "https://statsapi.mlb.com/api/v1"
        self.live_base_url = "https://statsapi.mlb.com/api/v1.1"

    def get_today_game_pks(self):
        today = date.today().isoformat()

        url = f"{self.base_url}/schedule"
        params = {
            "sportId": 1,
            "date": today,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        game_pks = []

        for day in data.get("dates", []):
            for game in day.get("games", []):
                game_pks.append(game["gamePk"])

        return game_pks

    def poll(self):
        events = []

        for game_pk in self.get_today_game_pks():
            events.extend(self.poll_game(game_pk))

        return events

    def poll_game(self, game_pk):
        url = f"{self.live_base_url}/game/{game_pk}/feed/live"

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()

        game_data = data.get("gameData", {})
        live_data = data.get("liveData", {})

        teams = game_data.get("teams", {})
        away_team = teams.get("away", {}).get("abbreviation")
        home_team = teams.get("home", {}).get("abbreviation")

        linescore = live_data.get("linescore", {})
        away_score = linescore.get("teams", {}).get("away", {}).get("runs")
        home_score = linescore.get("teams", {}).get("home", {}).get("runs")

        status = linescore.get("inningState", "")
        inning = linescore.get("currentInningOrdinal", "")
        status_text = f"{status} {inning}".strip()

        plays = live_data.get("plays", {}).get("allPlays", [])

        events = []

        for play in plays:
            about = play.get("about", {})
            result = play.get("result", {})
            matchup = play.get("matchup", {})

            event_type = result.get("eventType")
            event = result.get("event", "")
            description = result.get("description", "")

            batter = matchup.get("batter", {}).get("fullName")
            half_inning = about.get("halfInning")

            batting_team = away_team if half_inning == "top" else home_team

            play_id = about.get("atBatIndex")
            if play_id is None:
                continue

            if event_type == "home_run":
                events.append(
                    AlertEvent(
                        event_id=f"mlb:{game_pk}:home_run:{play_id}",
                        event_type="home_run",
                        league="mlb",
                        team=batting_team,
                        player=batter,
                        message=f"{batter} home run",
                        detail=description,
                        away=away_team,
                        home=home_team,
                        away_score=away_score,
                        home_score=home_score,
                        status=status_text,
                        source=self.name,
                    )
                )

            elif result.get("rbi", 0) > 0 or "scores" in description.lower():
                events.append(
                    AlertEvent(
                        event_id=f"mlb:{game_pk}:run:{play_id}",
                        event_type="score",
                        league="mlb",
                        team=batting_team,
                        player=batter,
                        message=event or "Run scored",
                        detail=description,
                        away=away_team,
                        home=home_team,
                        away_score=away_score,
                        home_score=home_score,
                        status=status_text,
                        source=self.name,
                    )
                )

        return events