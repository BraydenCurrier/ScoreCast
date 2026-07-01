from alerts.models import Alert

from alert_api.store import AlertEventStore
from alert_api.mlb_provider import MLBProvider


class AlertService:
    def __init__(self):
        self.store = AlertEventStore()
        self.providers = [
            MLBProvider(),
        ]
        self.warmed_up = False

    def warmup(self):
        for provider in self.providers:
            try:
                events = provider.poll()
            except Exception as e:
                print(f"Alert warmup failed: {provider.name}", e)
                continue

            for event in events:
                self.store.is_new(event.event_id)

        self.warmed_up = True
        print("Alert API warmed up")

    def poll(self):
        if not self.warmed_up:
            self.warmup()
            return []

        alerts = []

        for provider in self.providers:
            try:
                events = provider.poll()
            except Exception as e:
                print(f"Alert provider failed: {provider.name}", e)
                continue

            for event in events:
                if not self.store.is_new(event.event_id):
                    continue

                alerts.append(self.event_to_alert(event))

        return alerts