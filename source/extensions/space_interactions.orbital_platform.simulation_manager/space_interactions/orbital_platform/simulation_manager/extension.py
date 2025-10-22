# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import os
import asyncio
import json
import numpy as np
# For testing
np.random.seed(123)
import time
import math
from datetime import datetime, timedelta
import warp as wp
from typing import List
from functools import partial

import carb
import omni.ext
import omni.usd
import omni.ui as ui
from omni.ui import DockPreference, DockPosition
from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window, get_active_viewport_camera_path
from omni.timeline import TimelineEventType
from omni.kit.widget.searchable_combobox import build_searchable_combo_widget, ComboBoxListDelegate
from omni.kit.viewport.utility.camera_state import ViewportCameraState
import omni.kit.app
import omni.kit.notification_manager as notify

import omni.earth_2_command_center.app.core as earth2core
import omni.earth_2_command_center.app.globe_view as globe

import omni.kit.pipapi
from pxr import Sdf, UsdGeom, Gf, Usd
from . import utils
from .satellite import Satellite
from .screen_ui import ScreenUI
from .data_feed import DataFeed

omni.kit.pipapi.install("skyfield")
from skyfield.api import load, Timescale, Time
from skyfield import framelib

SATTYPE_COLOR_MAPPING = {
    'ROCKET BODY': Gf.Vec3f(1, 0, 1),
    'DEBRIS': Gf.Vec3f(0, 1, 1),
    'PAYLOAD': Gf.Vec3f(0, 1, 0),
    'UNKNOWN': Gf.Vec3f(1, 0, 0)
}
SAT_MODEL_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sat2.usda'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sat3.usda')
]
DATA_FEED_TEMPLATES = [
    # name, expected value, standard deviation, low limit, high limit
    ("electrical_temperature", 4.0, 0.1, 3.0, 5.0),
    ("panel_temperature", 12.0, 0.4, 8.0, 16.0),
    ("latitude", None, None, -90, 90),
    ("longitude", None, None, -180, 180),
    ("altitude", None, None, 200, 40E6),
]
CAM_DEFAULTS = {
        'xformOp:translate': Gf.Vec3d(14508.205314825205, 12510.310453034006, 5827.069287601547),
        'xformOp:rotateXYZ': Gf.Vec3d(73.0817, -2.2263883e-14, 130.77094),
}
NULL_STRING_MODEL = ui.SimpleStringModel("")

EMPTY_COMBO_VAL = "Search..."

def get_sim_manager():
    global _sim_manager
    return _sim_manager

def get_sim_ui():
    global _sim_ui
    return _sim_ui

# Any class derived from `omni.ext.IExt` in the top level module (defined in
# `python.modules` of `extension.toml`) will be instantiated when the extension
# gets enabled, and `on_startup(ext_id)` will be called. Later when the
# extension gets disabled on_shutdown() is called.
class SimulationManager(omni.ext.IExt):
    """This is a blank extension template."""
    # ext_id is the current extension id. It can be used with the extension
    # manager to query additional information, like where this extension is
    # located on the filesystem.
    def on_startup(self, _ext_id):
        """This is called every time the extension is activated."""
        print("[space_interactions.orbital_platform.simulation_manager] Extension startup")

        self._ext_id = _ext_id

        global _sim_manager
        _sim_manager = self

        self._set_settings()

        self._time_manager = earth2core.get_state().get_time_manager()
        # self._timestep_subscription = self._time_manager.get_utc_event_stream().create_subscription_to_pop_by_type(
        #     event_type=earth2core.time_manager.UTC_CURRENT_TIME_CHANGED,
        #     fn=self._on_timestep
        # )
        self._camera_subscription = earth2core.get_state().get_globe_view_event_stream().create_subscription_to_pop_by_type(
            event_type=globe.gestures.CAMERA_POS_CHANGED,
            fn=self._on_camera_move
        )
        self._globe_view_subscription = earth2core.get_state().get_globe_view_event_stream().create_subscription_to_pop_by_type(
            event_type=globe.extension.GLOBE_VIEW_SETUP,
            fn=self._on_globe_view_setup
        )

        self._usd_stage = omni.usd.get_context().get_stage()

        self.satellites: List[Satellite] = list()
        self.timestepsPerUpdate = 60
        self.scale = globe.get_globe_view()._earth_radius / utils.WGS84_RADIUS
        self.speed = 1.0
        self._sat_distace_scaler : float = 0.001
        self._timescale = load.timescale()
        self._frame_num = 0
        self._prev_time: datetime = None
        self._curr_time: datetime = earth2core.get_state().get_time_manager().utc_start_time
        self.satellitesPrim = None
        self.satPositions = None
        self.satVelocities = None
        self.satIndices = None
        self.satOrientations = None
        self.satScales = None

        self.model_prims = []
        self._load_satellites_json()
        self._initialize_satellites_geom()

        self._screen_ui = None

        #self._satellite_selection_widget = SatelliteSelectionWindow(self.satellites, self._timescale)

        self._scale_update_rate = 1/60
        self._last_scale_update = float()

        #print("oonky")
        #self._time_manager2 = SimulationUIController()
        #self._time_manager2.startup("space_interactions.orbital_platform.simulation_manager.time_manager")
        #print("boonky")


    def _load_satellites_json(self, path:str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup.tle')):
        tles = json.load(open(path))

        print("Received", len(tles), "TLEs")
        ts = load.timescale()
        t = ts.now()
        for tle in tles:
            sat = Satellite(line1=tle['TLE_LINE1'], line2=tle['TLE_LINE2'], name=tle['OBJECT_NAME'], ts=ts)

            # set necessary extras
            sat.color = SATTYPE_COLOR_MAPPING[tle['OBJECT_TYPE']]
            sat.id = tle['NORAD_CAT_ID'].rjust(5, '0')
            sat.set_scale(self.scale)

            # call get_state to cache state
            sat.get_state(t)

            # attach data feeds
            for dft in DATA_FEED_TEMPLATES:
                sat.add_data_feed(DataFeed(dft[0], dft[1], dft[2], dft[3], dft[4]))


            self.satellites.append(sat)

    def _initialize_satellites_geom(self):

        # default sphere geometry instance
        default_proto_path = "/World/Prototypes/Sphere"
        proto_prim = UsdGeom.Sphere.Define(self._usd_stage, default_proto_path)
        proto_prim.GetRadiusAttr().Set(1)

        # list of all prototype paths
        prototype_paths = [default_proto_path]

        proto_indices = [0]

        # Satellite geometry instances
        for i, sat_path in enumerate(SAT_MODEL_PATHS):
            proto_sat_path = f"/World/Prototypes/Satellite_{i}"
            proto_sat : Usd.Prim = UsdGeom.Xform.Define(self._usd_stage, Sdf.Path(proto_sat_path)).GetPrim()
            proto_sat.GetReferences().AddReference(
                assetPath=sat_path
            )
            self.model_prims.append(proto_sat)
            prototype_paths.append(proto_sat_path)
            proto_indices.append(i+1)

        ptInstancePath = "/World/satellites"
        self.satellitesPrim = UsdGeom.PointInstancer.Define(self._usd_stage, ptInstancePath)
        self.satellitesPrim.GetPrototypesRel().SetTargets(prototype_paths)

        n = len(self.satellites)

        if n == 0: return

        self.satPositions = np.zeros((n, 3))
        self.satVelocities = np.zeros((n, 3))
        self.satOrientations = np.zeros((n, 4))
        self.satIndices = np.zeros(n)
        self.satScales = np.zeros((n, 3))

        colors = []
        sat_model_ct = len(SAT_MODEL_PATHS)
        sim_time = self._timescale.from_datetime(self._curr_time)
        for i, sat in enumerate(self.satellites):

            # Assign prototype index for when satellite is selected (+1 because 0 is always default sphere)
            sat.proto_index = (i % sat_model_ct) + 1

            pos, vel, ori = sat.get_state(sim_time)

            self.satPositions[i, :] = pos
            self.satVelocities[i, :] = vel
            self.satOrientations[i, :] = ori
            scale = utils.distance(self.get_camera_position(), pos) * self._sat_distace_scaler
            self.satScales[i] = [scale, scale, scale]

            # set to default model
            self.satIndices[i] = 0
            #self.satIndices[i] = sat.proto_index

            colors.append(sat.color)

        self.satellitesPrim.GetPositionsAttr().Set(self.satPositions)
        self.satellitesPrim.GetOrientationsAttr().Set(self.satOrientations)
        self.satellitesPrim.GetScalesAttr().Set(self.satScales)
        self.satellitesPrim.GetProtoIndicesAttr().Set(self.satIndices)

        primvarApi = UsdGeom.PrimvarsAPI(self.satellitesPrim)
        diffuse_color_primvar = primvarApi.CreatePrimvar(
            "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.varying
        ) # type: ignore
        diffuse_color_primvar.Set(colors)

        # Assign timestep for SGP4 update call
        for sat in self.satellites:
            sat.update_idx = np.random.randint(self.timestepsPerUpdate) # type: ignore

    def _on_timestep(self, t: datetime):

        utc_time = t
        sim_time = self._timescale.from_datetime(utc_time)

        if self._prev_time == None:
            self._prev_time = utc_time
        if self._curr_time == None:
            self._curr_time = utc_time

        self._prev_time = self._curr_time
        self._curr_time = utc_time

        if len(self.satellites) > 0:
            # Update any pos/vel/orientation for whose turn it is
            for i, sat in enumerate(self.satellites):
                if self._frame_num % self.timestepsPerUpdate == sat.update_idx:

                    pos, vel, ori = sat.get_state(sim_time)
                    self.satPositions[i, :] = pos
                    self.satVelocities[i, :] = vel
                    self.satOrientations[i, :] = ori


                    lat, lon, alt = utils.xyz_to_lla(sat.pos[0], sat.pos[1], sat.pos[2])
                    sat.get_data_feed("latitude").set(lat)
                    sat.get_data_feed("longitude").set(lon)
                    sat.get_data_feed("altitude").set(alt)
                    ok = sat.update_feeds()

                    if not ok:
                        n = notify.post_notification(
                            text=f"{sat.name} has triggered an anomaly",
                            duration=5,
                            hide_after_timeout=False,
                            status=notify.NotificationStatus.INFO,
                            button_infos=[notify.NotificationButtonInfo("Select object", on_complete=partial(get_sim_ui().select_satellite, sat=sat, index=i))]
                        )

                        # sat.reset_feeds()

            # Move points to new positions
            self.update_satellite_states()

            # Update scales based on new positions
            self.update_satellite_scales()

            # Update sun position
            globe.get_globe_view()._sun_feature_motion.force_update(utc_time)
            #print(globe.get_globe_view()._sun_feature.latitude, globe.get_globe_view()._sun_feature.longitude)

        self._frame_num += 1

    def get_camera_position(self) -> wp.vec3:
        viewport_api = get_active_viewport()
        camera_path = viewport_api.camera_path
        camera = UsdGeom.Camera(self._usd_stage.GetPrimAtPath(camera_path))

        gf_camera = camera.GetCamera(viewport_api.time)

        cam_pos = gf_camera.transform.GetRow(3)
        cam_pos = wp.vec3(cam_pos[0], cam_pos[1], cam_pos[2])
        return cam_pos

    def on_shutdown(self):
        """This is called every time the extension is deactivated. It is used
        to clean up the extension state."""
        print("[space_interactions.orbital_platform.simulation_manager] Extension shutdown")

    def _on_camera_move(self, event):
        self.update_satellite_scales()

    def update_satellite_states(self):
        '''Update UsdGeom.PointsInstancer point positions'''

        # Get dimension for warp kernel
        n = len(self.satellites)
        # Pack all pos/vels
        pos = wp.from_numpy(self.satPositions, dtype=wp.vec3, device="cuda")
        vel = wp.from_numpy(self.satVelocities, dtype=wp.vec3, device="cuda")
        td = (self._curr_time - self._prev_time).total_seconds()
        out = wp.empty(shape=n, dtype=wp.vec3, device="cuda") # type: ignore

        # Position calc
        wp.launch(sgp4kernel, dim=n, inputs=[pos, vel, td, out], device="cuda")

        self.satPositions = out.numpy()
        self.satellitesPrim.GetPositionsAttr().Set(self.satPositions)

    def update_satellite_scales(self):
        '''Update UsdGeom.PointsInstancer point scales based on distance to camera. Additionally, update orbit curve if it is present.'''

        # Cull calls that come too quickly
        t = time.time()
        if t - self._last_scale_update > self._scale_update_rate:

            # Get dimension for warp kernel
            n = len(self.satellites)

            # Scale calc
            out = wp.empty(shape=n, dtype=wp.vec3, device="cuda")
            pos = wp.from_numpy(self.satPositions, dtype=wp.vec3, device="cuda")
            wp.launch(cameraDistKernel, dim=n, inputs=[pos, self.get_camera_position(), self._sat_distace_scaler, out], device="cuda")
            self.satScales = np.clip(out.numpy(), 2.0, 500.0)

            # if the user has a seleceted satellite
            # if get_sim_ui().selectedSatIdx != None:
            #     get_sim_ui().set_orbit_scale(self.get_camera_position())

            self.satellitesPrim.GetScalesAttr().Set(self.satScales)

            self._last_scale_update = t

    def _set_settings(self):
        settings = carb.settings.get_settings()
        settings.set("/rtx/post/dlss/execMode", 3)

    def _on_globe_view_setup(self, event):
        if event.type == globe.extension.GLOBE_VIEW_SETUP:
            self.update_satellite_scales()
            earth2core.get_state().get_time_manager().get_timeline().play()

            self._screen_ui = ScreenUI(self.satellites, self.scale, self._timescale)
            #asyncio.ensure_future(get_sim_ui()._dock())

            end_pos = CAM_DEFAULTS["xformOp:translate"] * 4
            camera_state = ViewportCameraState(get_active_viewport_camera_path())
            camera_state.set_position_world(end_pos, True)
            camera_state.set_target_world(Gf.Vec3d(0,0,0), True)



@wp.kernel
def sgp4kernel(pos: wp.array(dtype=wp.vec3), vel: wp.array(dtype=wp.vec3), s: float, out: wp.array(dtype=wp.vec3)): # type: ignore
    tid = wp.tid()
    x = pos[tid]
    v = vel[tid]
    out[tid] = x + v * s

@wp.kernel
def cameraDistKernel(pos: wp.array(dtype=wp.vec3), camPos: wp.vec3, s: float, out: wp.array(dtype=wp.vec3)): # type: ignore
    tid = wp.tid()
    x = pos[tid]
    dx = x[0] - camPos[0]
    dy = x[1] - camPos[1]
    dz = x[2] - camPos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    scale = dist * s
    out[tid] = wp.vec3(scale, scale, scale)
