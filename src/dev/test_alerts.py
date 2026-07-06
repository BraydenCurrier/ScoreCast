import os
import sys
import time

# Allow running this file directly from project root
PROJECT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from common.matrix import create_matrix
from alerts.models import Alert
from alerts.manager import AlertManager
from alerts.display import AlertDisplay


FRAME_DELAY = 1 / 60
ALERT_DURATION = 4


def make_test_alerts():
    return [

        #
        # NFL
        #
        Alert(
            alert_id="nfl_td",
            alert_type="touchdown",
            league="nfl",
            team="KC",
            player="Patrick Mahomes",
            message="Mahomes to Kelce TD",
            away="KC",
            home="BUF",
            away_score=24,
            home_score=17,
            status="Q4 2:14",
            detail="Chiefs take the lead"
        ),

        Alert(
            alert_id="nfl_fg",
            alert_type="score",
            league="nfl",
            team="BUF",
            player=None,
            message="Tyler Bass 42 yd FG",
            away="KC",
            home="BUF",
            away_score=24,
            home_score=20,
            status="Q4 1:32",
            detail="Bills within four"
        ),

        Alert(
            alert_id="nfl_safety",
            alert_type="score",
            league="nfl",
            team="PIT",
            player=None,
            message="Safety",
            away="BAL",
            home="PIT",
            away_score=10,
            home_score=2,
            status="Q1 11:47",
            detail="First points of the game"
        ),

        #
        # CFB
        #
        Alert(
            alert_id="cfb_td",
            alert_type="touchdown",
            league="cfb",
            team="SCAR",
            player="LaNorris Sellers",
            message="Sellers 18 yd rush",
            away="SCAR",
            home="UGA",
            away_score=21,
            home_score=17,
            status="3Q 8:41",
            detail="#12 South Carolina leads"
        ),

        Alert(
            alert_id="cfb_upset",
            alert_type="score",
            league="cfb",
            team="SCAR",
            player=None,
            message="Upset Alert",
            away="SCAR",
            home="UGA",
            away_score=28,
            home_score=17,
            status="4Q 12:51",
            detail="#12 Georgia trailing"
        ),

        #
        # MLB
        #
        Alert(
            alert_id="mlb_run",
            alert_type="score",
            league="mlb",
            team="LAD",
            player="Shohei Ohtani",
            message="RBI Double",
            away="LAD",
            home="SF",
            away_score=5,
            home_score=3,
            status="Top 8th",
            detail="Dodgers extend lead"
        ),

        Alert(
            alert_id="mlb_hr",
            alert_type="home_run",
            league="mlb",
            team="NYY",
            player="Aaron Judge",
            message="455 FT HOME RUN",
            away="BOS",
            home="NYY",
            away_score=2,
            home_score=4,
            status="Bottom 6th",
            detail="Judge's 37th HR"
        ),

        #
        # Soccer
        #
        Alert(
            alert_id="soccer_goal",
            alert_type="goal",
            league="soccer",
            team="USA",
            player="Christian Pulisic",
            message="GOAL 67'",
            away="USA",
            home="BIH",
            away_score=2,
            home_score=1,
            status="67'",
            detail="USA regain the lead"
        ),

        Alert(
            alert_id="soccer_goal2",
            alert_type="goal",
            league="soccer",
            team="ENG",
            player="Harry Kane",
            message="Penalty Goal",
            away="ENG",
            home="FRA",
            away_score=1,
            home_score=1,
            status="81'",
            detail="Match level"
        ),

        #
        # Fantasy
        #
        Alert(
            alert_id="fantasy_td",
            alert_type="fantasy_touchdown",
            league="nfl",
            team="CIN",
            player="Ja'Marr Chase",
            message="+13.2 Fantasy Points",
            away="CIN",
            home="CLE",
            away_score=17,
            home_score=14,
            status="Q3 5:51",
            detail="Your matchup projection +7%"
        ),

        #
        # Generic
        #
        Alert(
            alert_id="generic",
            alert_type="generic",
            league="nfl",
            team="KC",
            player=None,
            message="Game Starting",
            away="KC",
            home="LV",
            away_score=0,
            home_score=0,
            status="Pregame",
            detail="Kickoff in 5 minutes"
        ),

    ]


def main():
    matrix = create_matrix()

    manager = AlertManager()
    display = AlertDisplay(manager)

    for alert in make_test_alerts():
        manager.add_alerts([alert], cooldown_seconds=0)

    while manager.has_alert() or display.is_active():
        if display.is_active() or display.start_next_alert():
            frame = display.render_frame(duration=ALERT_DURATION)

            if frame is not None:
                matrix.SetImage(frame)

        time.sleep(FRAME_DELAY)


if __name__ == "__main__":
    main()