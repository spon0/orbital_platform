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
import time
import math
from datetime import datetime, timedelta
import warp as wp

import carb
import omni.ext
import omni.usd
import omni.ui as ui
from omni.ui import DockPreference, DockPosition
from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window
from omni.timeline import TimelineEventType
from omni.kit.widget.searchable_combobox import build_searchable_combo_widget, ComboBoxListDelegate
from omni.kit.viewport.utility.camera_state import ViewportCameraState
import omni.kit.app

import omni.earth_2_command_center.app.core as earth2core
import omni.earth_2_command_center.app.globe_view as globe
import omni.earth_2_command_center.app.geo_utils as geo_utils

import omni.kit.pipapi
from pxr import Sdf, UsdLux, UsdGeom, Gf, UsdPhysics, Vt, Usd, Tf
from . import utils
from .satellite import Satellite
from .style import example_window_style

omni.kit.pipapi.install("skyfield")
from skyfield.api import EarthSatellite, load, Timescale, Time, Distance
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

        self._set_settings()

        print("[space_interactions.orbital_platform.simulation_manager] Extension startup")

        self._time_manager = earth2core.get_state().get_time_manager()
        self._timestep_subscription = self._time_manager.get_utc_event_stream().create_subscription_to_pop(
            fn=self._on_timestep
        )
        self._camera_subscription = earth2core.get_state().get_globe_view_event_stream().create_subscription_to_pop(
            fn=self._on_camera_move
        )
        self._globe_view_subscription = earth2core.get_state().get_globe_view_event_stream().create_subscription_to_pop(
            fn=self._on_globe_view_setup
        )

        self._usd_stage = omni.usd.get_context().get_stage()

        self.satellites: list[Satellite] = []
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

        self._satellite_selection_widget = SatelliteSelectionWindow(self.satellites, self._timescale)

        self._scale_update_rate = 1/60
        self._last_scale_update = float()

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

    def _on_timestep(self, event):
        if event.type == earth2core.time_manager.UTC_CURRENT_TIME_CHANGED:

            utc_time = self._time_manager.current_utc_time
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
                    if self._frame_num % self.timestepsPerUpdate == sat.update_idx or sat.selected:

                        pos, vel, ori = sat.get_state(sim_time)

                        self.satPositions[i, :] = pos
                        self.satVelocities[i, :] = vel
                        self.satOrientations[i, :] = ori

                # Move points to new positions
                self.update_satellite_states()

                # Update scales based on new positions
                self.update_satellite_scales()

                get_sim_ui().update_info()

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
        if event.type == globe.gestures.CAMERA_POS_CHANGED:
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
            if get_sim_ui().selectedSatIdx != None:
                get_sim_ui().set_orbit_scale(self.get_camera_position())

            self.satellitesPrim.GetScalesAttr().Set(self.satScales)

            self._last_scale_update = t

    def _set_settings(self):
        settings = carb.settings.get_settings()
        settings.set("/rtx/post/dlss/execMode", 3)

    def _on_globe_view_setup(self, event):
        if event.type == globe.extension.GLOBE_VIEW_SETUP:
            self.update_satellite_scales()
            earth2core.get_state().get_time_manager().get_timeline().play()
            asyncio.ensure_future(get_sim_ui()._dock())

class SatelliteSelectionWindow(ui.Window):

    def __init__(self, satellites: list[Satellite], timescale: Timescale) -> None:
        super().__init__("Satellite Selection", width=300, height=100)

        global _sim_ui
        _sim_ui = self

        self._satellites = satellites
        self._selected_sat = None
        self._stage = omni.usd.get_context().get_stage()
        self.selectedSatIdx = None
        self._timescale = timescale
        self._orbit_curve_path = "/World/orbit/curve"
        self._orbit_curve = None

        self._temperature_model = ui.SimpleStringModel("")
        self._latitude_model = ui.SimpleStringModel("")
        self._longitude_model = ui.SimpleStringModel("")
        self._altitude_model = ui.SimpleStringModel("")

        self.frame.style = example_window_style
        self.frame.set_build_fn(self._build_ui)

    def _build_ui(self):

        with ui.VStack():
            self._build_satellite_combobox()
            with ui.ScrollingFrame():
                with ui.VStack(height=0):
                    self._build_satellite_positions()
                    self._build_electrical_components()
                    self._build_solar_panels()

    def _build_satellite_combobox(self):
        # Define the list of items for the combo box
        itemList = []
        for sat in self._satellites:
            item = f'{sat.name} -- {sat.id}'
            itemList.append(item)

        # Add the searchable combo box to the UI
        # Create the searchable combo box with the specified items and callback
        build_searchable_combo_widget(
            combo_list=itemList,
            combo_index=-1,  # Start with no item selected
            combo_click_fn=self.satelliteComboClick,
            widget_height=18,
            default_value=EMPTY_COMBO_VAL,  # Placeholder text when no item is selected
            window_id="SearchableComboBoxWindow",
            delegate=ComboBoxListDelegate()  # Use the default delegate for item rendering
        )

    def _build_satellite_positions(self):
        with ui.CollapsableFrame("Position", collapsed=True, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Latitude (°): ")
                    ui.StringField(self._latitude_model, read_only=True)
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Longitude (°): ")
                    ui.StringField(self._longitude_model, read_only=True)
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Altitude (km): ")
                    ui.StringField(self._altitude_model, read_only=True)

    def _build_electrical_components(self):
        with ui.CollapsableFrame("Electrical Components", collapsed=True, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Temperature (°C):")
                    ui.StringField(self._temperature_model, read_only=True)

    def _build_solar_panels(self):
        with ui.CollapsableFrame("Solar Panels", collapsed=True, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Temperature (°C):")
                    ui.StringField(self._temperature_model, read_only=True)

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

    def selecteSatellite(self, sat: Satellite, index: int) -> None:
        self._selected_sat = sat
        self._selected_sat.selected = True
        self.selectedSatIdx = index

        points = []
        widths = []

        now = self._timescale.from_datetime(earth2core.get_state().get_time_manager().current_utc_time)
        # Get the orbital period in days
        period_days = utils.get_satellite_period(sat).total_seconds() / (86400.0) # Period is in seconds
        times = self._timescale.linspace(now, now + period_days, 360)
        for t in times:
            geocentric = sat.at(t)
            pos = geocentric.frame_xyz(framelib.itrs)
            # Pack to Gf.Vec3d and scale to our coordinate frame
            pos = utils.to_vec3f(pos.km * get_sim_manager().scale)
            points.append(pos)
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

        # Change geometry for selected satellite
        indices = [0] * len(get_sim_manager().satellites)
        indices[self.selectedSatIdx] = sat.proto_index
        get_sim_manager().satellitesPrim.GetProtoIndicesAttr().Set(indices)

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

        # Change geometry for unselected satellite
        indices = [0] * len(get_sim_manager().satellites)
        get_sim_manager().satellitesPrim.GetProtoIndicesAttr().Set(indices)

    def set_orbit_scale(self, cam_pos) -> None:
        pts = self._orbit_curve.GetPointsAttr().Get()
        widths = []
        for pt in pts:
            width = (utils.distance(cam_pos, pt) * 0.0002)**2
            widths.append(width)
        widths_clamped = np.clip(widths, 1.0, 100.0)
        self._orbit_curve.GetWidthsAttr().Set(Vt.FloatArray(widths_clamped))

    def update_info(self):
        if self._selected_sat:
            self._temperature_model.set_value(f"{self._selected_sat.actual_temperature:+5.3f}")

            pos = self._selected_sat.pos
            lat, lon, alt = utils.xyz_to_lla(pos[0], pos[1], pos[2])
            self._altitude_model.set_value(alt)
            self._longitude_model.set_value(lon)
            self._latitude_model.set_value(lat)
        # clear contents
        else:
            self._temperature_model.set_value("")
            self._altitude_model.set_value("")
            self._longitude_model.set_value("")
            self._latitude_model.set_value("")

    async def _dock(self) -> None:
        '''Dock window in the viewport window.'''

        windowsToHide = [
            "Content",
            "Property",
            "Render Settings"
        ]

        await omni.kit.app.get_app().next_update_async()
        dock_space = ui.Workspace.get_window("DockSpace")

        for window in ui.Workspace.get_windows():
            if window.title in windowsToHide:
                window.visible = False

        # Dock viewport

        # Dock select satellite
        ui.Workspace.get_window("Globe View").dock_in(dock_space, ui.DockPosition.LEFT, 0.80)
        self.dock_in(dock_space, ui.DockPosition.RIGHT, 0.20)

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
