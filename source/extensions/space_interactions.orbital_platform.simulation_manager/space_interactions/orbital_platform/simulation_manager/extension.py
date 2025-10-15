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
import math
from datetime import datetime, timedelta
import warp as wp

import omni.ext
import omni.usd
import omni.ui as ui
from omni.ui import DockPreference
from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window
from omni.timeline import TimelineEventType
from omni.kit.widget.searchable_combobox import build_searchable_combo_widget, ComboBoxListDelegate
from omni.kit.viewport.utility.camera_state import ViewportCameraState
import omni.kit.app

import omni.earth_2_command_center.app.core as earth2core
import omni.earth_2_command_center.app.globe_view as globe

import omni.kit.pipapi
from pxr import Sdf, UsdLux, UsdGeom, Gf, UsdPhysics, Vt, Usd
from . import utils

omni.kit.pipapi.install("skyfield")
from skyfield.api import EarthSatellite, load, Timescale, Time, Distance
from skyfield import framelib

SATTYPE_COLOR_MAPPING = {
    'ROCKET BODY': Gf.Vec3f(1, 0, 1),
    'DEBRIS': Gf.Vec3f(0, 1, 1),
    'PAYLOAD': Gf.Vec3f(0, 1, 0),
    'UNKNOWN': Gf.Vec3f(1, 0, 0)
}
# WGS84 vals in kilometer
WGS84_SEMIMAJOR = 6378.137
WGS84_SEMIMINOR = 6356.752314245
WGS84_RADIUS = 6371.0
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

        self._ext_id = _ext_id

        global _sim_manager
        _sim_manager = self

        print("[space_interactions.orbital_platform.simulation_manager] Extension startup")

        self._time_manager = earth2core.get_state().get_time_manager()
        self._timestep_subscription = self._time_manager.get_utc_event_stream().create_subscription_to_pop(
            fn=self._on_timestep
        )

        self._usd_stage = omni.usd.get_context().get_stage()

        self.satellites = []
        self.timestepsPerUpdate = 60
        self.scale = globe.get_globe_view()._earth_radius / WGS84_RADIUS
        self.speed = 1.0
        self._sat_distace_scaler : float = 0.00005
        self._timescale = load.timescale()
        self._frame_num = 0
        self._prev_time: datetime = None
        self._curr_time: datetime = None
        self.satellitesPrim = None
        self.satPositions = None
        self.satVelocities = None
        self.satScales = None
        self._load_satellites_json()
        self._initialize_satellites_geom()

        self._satellite_selection_widget = SatelliteSelectionWindow(self.satellites, self._timescale)

    def _load_satellites_json(self, path:str = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup.tle')):
        tles = json.load(open(path))

        print("Received", len(tles), "TLEs")
        ts = load.timescale()
        t = ts.now()
        for tle in tles:
            sat = EarthSatellite(line1=tle['TLE_LINE1'], line2=tle['TLE_LINE2'], name=tle['OBJECT_NAME'], ts=ts)
            sat.color = SATTYPE_COLOR_MAPPING[tle['OBJECT_TYPE']]
            geocentric = sat.at(t)
            sat.pos = geocentric.xyz.km
            sat.vel = geocentric.velocity.km_per_s
            sat.id = tle['NORAD_CAT_ID'].rjust(5, '0')
            sat.selected = False
            self.satellites.append(sat)

    def _initialize_satellites_geom(self):
        protoPath = "/World/Prototypes/Sphere"
        protoPrim = UsdGeom.Sphere.Define(self._usd_stage, protoPath)
        protoPrim.GetRadiusAttr().Set(15)

        ptInstancePath = "/World/satellites"
        self.satellitesPrim = UsdGeom.PointInstancer.Define(self._usd_stage, ptInstancePath)
        self.satellitesPrim.GetPrototypesRel().AddTarget(protoPath)

        if len(self.satellites) == 0: return

        positions = []
        velocities = []
        oris = []
        indices = []
        colors = []
        for sat in self.satellites:

            positions.append(sat.pos * self.scale)
            velocities.append(sat.vel * self.scale)
            indices.append(0)
            oris.append(Gf.Quath(1, 0, 0, 0))
            colors.append(sat.color)

        self.satPositions = np.array(positions)
        self.satVelocities = np.array(velocities)

        # Scale calc
        n = len(self.satellites)
        scalesOut = wp.empty(shape=n, dtype=wp.vec3, device="cuda")
        pos = wp.from_numpy(self.satPositions, dtype=wp.vec3, device="cuda")
        wp.launch(cameraDistKernel, dim=n, inputs=[pos, self.get_camera_position(), self._sat_distace_scaler, scalesOut], device="cuda")
        self.satScales = scalesOut.numpy()

        self.satellitesPrim.GetPositionsAttr().Set(self.satPositions)
        self.satellitesPrim.GetOrientationsAttr().Set(oris)
        self.satellitesPrim.GetScalesAttr().Set(self.satScales)
        self.satellitesPrim.GetProtoIndicesAttr().Set(indices)
        primvarApi = UsdGeom.PrimvarsAPI(self.satellitesPrim)
        diffuse_color_primvar = primvarApi.CreatePrimvar(
            "primvars:displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.varying
        ) # type: ignore
        diffuse_color_primvar.Set(colors)

        # Assign timestep for SGP4 update call
        for sat in self.satellites:
            sat.updateIdx = np.random.randint(self.timestepsPerUpdate) # type: ignore

    def _on_timestep(self, event):
        if event.type in [
                earth2core.time_manager.UTC_CURRENT_TIME_CHANGED ]:

            utc_time = self._time_manager.current_utc_time
            sim_time = self._timescale.from_datetime(utc_time)

            if self._prev_time == None:
                self._prev_time = utc_time
            if self._curr_time == None:
                self._curr_time = utc_time

            self._prev_time = self._curr_time
            self._curr_time = utc_time

            selectedSatelliteIdx = None

            if len(self.satellites) > 0:
                # Update any pos/vel for whose turn it is
                for i, sat in enumerate(self.satellites):
                    if self._frame_num % self.timestepsPerUpdate == sat.updateIdx or sat.selected:
                        geocentric = sat.at(sim_time)
                        self.satPositions[i,:] = geocentric.xyz.km * self.scale
                        self.satVelocities[i, :] = geocentric.velocity.km_per_s * self.scale

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

                # Scale calc
                scalesOut = wp.empty(shape=n, dtype=wp.vec3, device="cuda")

                wp.launch(cameraDistKernel, dim=n, inputs=[pos, self.get_camera_position(), self._sat_distace_scaler, scalesOut], device="cuda")
                self.satScales = scalesOut.numpy()

                # if the user has a seleceted satellite, 10x the scale
                if get_sim_ui().selectedSatIdx != None:
                    self.satScales[get_sim_ui().selectedSatIdx] *= 10
                    get_sim_ui().set_orbit_scale(self.get_camera_position())

                self.satellitesPrim.GetScalesAttr().Set(self.satScales)

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


class SatelliteSelectionWindow(ui.Window):

    def __init__(self, satellites: list[EarthSatellite], timescale: Timescale) -> None:
        super().__init__("Satellite Selection", DockPreference.RIGHT, width=300)

        global _sim_ui
        _sim_ui = self

        self._satellites = satellites
        self._selected_sat = None
        self._stage = omni.usd.get_context().get_stage()
        self.selectedSatIdx = None
        self._timescale = timescale
        self._orbit_curve_path = "/World/orbit/curve"
        self._orbit_curve = None

        with self.frame:
            with ui.VStack():
                # Define the list of items for the combo box
                itemList = []
                for sat in satellites:
                    item = f'{sat.name} -- {sat.id}'
                    itemList.append(item)

                # Add the searchable combo box to the UI
                # Create the searchable combo box with the specified items and callback
                searchable_combo_widget = build_searchable_combo_widget(
                    combo_list=itemList,
                    combo_index=-1,  # Start with no item selected
                    combo_click_fn=self.satelliteComboClick,
                    widget_height=18,
                    default_value=EMPTY_COMBO_VAL,  # Placeholder text when no item is selected
                    window_id="SearchableComboBoxWindow",
                    delegate=ComboBoxListDelegate()  # Use the default delegate for item rendering
                )

        asyncio.ensure_future(self._dock())

    def satelliteComboClick(self, model):
        selected_item = model.get_value_as_string()

        if selected_item == EMPTY_COMBO_VAL:
            self.clearSelectedSatellite()

        # Get norad cat id and set selectedSat
        ssc = selected_item[-5:]
        for i, sat in enumerate(self._satellites):
            if sat.id == ssc:
                self.selecteSatellite(sat, i)
                break

    def selecteSatellite(self, sat, index) -> None:
        self._selected_sat = sat
        self._selected_sat.selected = True
        self.selectedSatIdx = index

        points = []
        widths = []
        now = self._timescale.from_datetime(earth2core.get_state().get_time_manager().current_utc_time)
        times = np.linspace(0, 120 * 60.0 , 360)
        for t in times:
            pos = sat.at(now + (t/86400)).xyz.km * globe.get_globe_view()._earth_radius / WGS84_RADIUS
            points.append(Gf.Vec3f(pos[0], pos[1], pos[2]))
            widths.append(10.0)

        self._orbit_curve = UsdGeom.NurbsCurves.Define(self._stage, self._orbit_curve_path)

        # Set the points attribute
        self._orbit_curve.CreatePointsAttr().Set(Vt.Vec3fArray(points))

        # Set the widths
        self._orbit_curve.CreateWidthsAttr(Vt.FloatArray(widths))

        # Set the color
        self._orbit_curve.CreateDisplayColorAttr(Vt.Vec3fArray(1, Gf.Vec3f(1.0, 1.0, 0.0)), writeSparsely=False)

        # Set the curve vertex counts attribute
        self._orbit_curve.CreateCurveVertexCountsAttr().Set([len(points)])

        # Get screen UI handle and interpolate camera to see selected satellite
        screen_ui = globe.get_globe_view()._screen_ui

        # Maneuver camera to sit back 10,000 units
        distance = 10000.0
        camera_state = ViewportCameraState(screen_ui.camera_path)
        start_pos = camera_state.position_world
        sat_pos = get_sim_manager().satPositions[index, :]
        sat_unit_vector = sat_pos / np.linalg.norm(sat_pos)
        end_pos = sat_pos + sat_unit_vector * distance
        end_pos = Gf.Vec3d(float(end_pos[0]), float(end_pos[1]), float(end_pos[2]))

        asyncio.ensure_future(screen_ui._interpolate_position(camera_state, start_pos, end_pos))

    def clearSelectedSatellite(self) -> None:
        self._selected_sat.selected = False # type: ignore
        self._selected_sat = None
        self.selectedSatIdx = None
        self._stage.RemovePrim(self._orbit_curve_path)

    def set_orbit_scale(self, cam_pos) -> None:
        pts = self._orbit_curve.GetPointsAttr().Get()
        widths = []
        for pt in pts:
            width = utils.distance(cam_pos, pt) * 0.0005
            widths.append(width)
        self._orbit_curve.GetWidthsAttr().Set(Vt.FloatArray(widths))

    async def _dock(self) -> None:
        '''Dock window in the viewport window.'''

        await omni.kit.app.get_app().next_update_async()
        viewportWindow = ui.Workspace.get_window("Globe View")

        # Dock select satellite window
        self.dock_in(viewportWindow, ui.DockPosition.RIGHT, 0.10)

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
