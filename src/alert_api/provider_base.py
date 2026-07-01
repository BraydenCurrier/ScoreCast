class AlertProvider:
    name = "base"

    def poll(self):
        raise NotImplementedError