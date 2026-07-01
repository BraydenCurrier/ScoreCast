import os
import sys

PROJECT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from alert_api.service import AlertService


def main():
    service = AlertService()
    alerts = service.poll()

    print(f"Found {len(alerts)} alerts")

    for alert in alerts:
        print()
        print(alert.alert_id)
        print(alert.alert_type)
        print(alert.league, alert.team, alert.player)
        print(alert.message)
        print(alert.away, alert.away_score, "-", alert.home, alert.home_score)
        print(alert.status)
        print(alert.detail)


if __name__ == "__main__":
    main()