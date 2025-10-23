from typing import Optional, Union
from pxr import Sdf, UsdLux, UsdGeom, Gf, UsdPhysics, Vt, Usd, Tf

import omni.kit.pipapi
omni.kit.pipapi.install("skyfield")
from skyfield.api import EarthSatellite, load, Timescale, Time, Distance
from skyfield import framelib

from . import utils
from .data_feed import DataFeed
import numpy as np

class Satellite(EarthSatellite):

    def __init__(self, line1, line2, name=None, ts=None):
        super().__init__(line1, line2, name, ts)

        # set defaults
        self.pos = np.array([0, 0, 0])
        self.vel = np.array([0, 0, 0])
        self.proto_index = -1
        self.id: str = '00000'
        self.nominal_temperature: float = 0.
        self.actual_temperature: float = 0.
        self.altitude: float = 0.
        self.selected = False
        self.color = Gf.Vec3f(0, 0, 0)
        self.scale = 1.0
        self.update_idx = 1
        self.proto_index = 0

        self.data_feeds: dict[str, DataFeed] = dict()

    def set_scale(self, scale):
        self.scale = scale

    def add_data_feed(self, df: DataFeed):

        self.data_feeds[df.name] = df

    def get_data_feed(self, key: str) -> Optional[DataFeed]:
        if key not in self.data_feeds: return None

        return self.data_feeds[key]

    def update_feeds(self) -> bool:
        ok = True
        for df in self.data_feeds.values():
            ok &= df.update()

        return ok

    def reset_feeds(self):
        for df in self.data_feeds.values():
            df.reset()

    def get_state(self, time: Time) -> tuple[Gf.Vec3d, Gf.Vec3d, list[float]]:
        '''Call SGP4 and pack to Gf.Vec3d and quaternion and scale to our coordinate frame.'''

        geocentric = self.at(time)
        pos, vel = geocentric.frame_xyz_and_velocity(framelib.itrs)
        self.pos = pos.km
        self.vel = vel.km_per_s
        # Pack to Gf.Vec3d and scale to our coordinate frame
        pos = utils.to_vec3d(self.pos * self.scale)
        vel = utils.to_vec3d(self.vel * self.scale)
        lookAt = pos + vel
        mat = Gf.Matrix4d().SetLookAt(pos, lookAt, -pos)
        qd = mat.ExtractRotationQuat()
        qh = Gf.Quath(qd)

        self.actual_temperature += np.random.normal(self.nominal_temperature, 0.01)

        return (pos, vel, [qh.imaginary[0], qh.imaginary[1], qh.imaginary[2], qh.real])