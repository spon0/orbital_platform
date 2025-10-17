import omni.ui as ui
import numpy as np

class DataFeed:

    def __init__(self, name, mu, std_dev, lower_limit, upper_limit):
        self.name = name
        self.mu = mu
        self.std_dev = std_dev
        self.lower_limit = lower_limit
        self.upper_limit = upper_limit
        self.model = ui.SimpleStringModel("")

        self.external = True
        self.value = 0.0
        self.notified = False

        if mu != None:
            # This feed should be updated externally via self.set()
            self.value = np.random.normal(self.mu, self.std_dev)
            self.external = False

    def set(self, value):
        self.value = value
        self.update()

    def update(self) -> bool:
        if not self.external:
            self.value += np.random.normal(0., self.std_dev)

        ok =  True

        if self.value < self.lower_limit and not self.notified:
            # notify
            self.notified = True
            ok = False

        if self.value > self.upper_limit and not self.notified:
            # notify
            self.notified = True
            ok = False

        self.model.set_value(self.value)

        return ok

    def reset(self):
        self.value = self.mu

    def format_str(self) -> str:
        return f"{self.value:+6.3f}"