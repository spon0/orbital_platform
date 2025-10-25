import math
from typing import Optional
import omni.ui as ui
import numpy as np

import omni.kit.pipapi
omni.kit.pipapi.install("skyfield")
from skyfield.api import Time

class DataFeed:

    def __init__(self, name, lower_limit, upper_limit):
        self.name = name

        self.lower_limit = lower_limit
        self.upper_limit = upper_limit
        self.model = ui.SimpleStringModel("")
        self.value = 0.0
        self.notified = False

    def set(self, value):
        self.value = value
        self.update(None)

    def update(self, time: Optional[Time]) -> bool:
        raise NotImplementedError("update() not implemented for base DataFeed")

    def reset(self):
        self.value = 0.0

    def format_str(self) -> str:
        return f"{self.value:+6.3f}"

class ExternalDataFeed(DataFeed):

    def __init__(self, name, lower_limit, upper_limit):
        super().__init__(name, lower_limit, upper_limit)

    def update(self, time: Optional[Time]) -> bool:

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

class GuassianDataFeed(DataFeed):

    def __init__(self, name, mu, std_dev, lower_limit, upper_limit):
        super().__init__(name, lower_limit, upper_limit)
        self._mu = mu
        self._std_dev = std_dev

    def update(self, time: Optional[Time]) -> bool:

        self.value = np.random.normal(self._mu, self._std_dev)

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


class SinusoidDataFeed(DataFeed):

    def __init__(self, name, amplitude, period, phase, noise, lower_limit, upper_limit):
        super().__init__(name, lower_limit, upper_limit)
        self._amplitude = amplitude
        self._period = ((2 * math.pi) / (period)) / (2 * math.pi)
        self._phase = np.random.uniform(0, 2 * math.pi)
        self._noise = noise # defines the standard deviation of the 0-mean, guassian white noise of the system
        self._vertical_shift = (upper_limit + lower_limit) / 2

    def update(self, time: Time):

        self.value = self._amplitude * np.sin(self._period * (time.utc_datetime().timestamp() + self._phase)) + self._vertical_shift
        self.value += np.random.normal(0, self._noise)

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