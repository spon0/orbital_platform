import math
import numpy as np
from pxr import Gf

from datetime import timedelta

import omni.kit.pipapi
omni.kit.pipapi.install("skyfield")
from skyfield.api import EarthSatellite

# Euclidean distance
def distance(a, b) -> float:
    assert(len(a) == len(b))

    v = 0.
    for x in a:
        for y in b:
            v += math.pow(x - y, 2)

    return math.sqrt(v)

def to_vec3d(x) -> Gf.Vec3d:
    return Gf.Vec3d(x[0], x[1], x[2])

def to_vec3f(x) -> Gf.Vec3f:
    return Gf.Vec3f(x[0], x[1], x[2])

def get_satellite_period(sat : EarthSatellite) -> timedelta:
        """The orbital period of the spacecraft.

        """
        period_m: float = 1 / (sat.model.no_kozai / (2 * np.pi))
        return timedelta(minutes=period_m)