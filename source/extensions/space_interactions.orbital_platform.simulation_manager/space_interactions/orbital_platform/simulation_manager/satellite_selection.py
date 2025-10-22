import numpy as np
import asyncio
import time
from typing import Optional
from .satellite import Satellite
from .style import PLAYBACK_PANEL
from . import utils

import omni.earth_2_command_center.app.core as earth2core
from pxr import UsdGeom, Gf, Vt
import omni.ui as ui
from omni.kit.viewport.utility import get_active_viewport, get_active_viewport_window
from omni.kit.widget.searchable_combobox import build_searchable_combo_widget, ComboBoxListDelegate
from omni.kit.viewport.utility.camera_state import ViewportCameraState
import omni.kit.pipapi

# externals
omni.kit.pipapi.install("skyfield")
from skyfield.api import load, Timescale
from skyfield import framelib

NULL_STRING_MODEL = ui.SimpleStringModel("")
EMPTY_COMBO_VAL = "Search..."

class SatelliteSelectionFrame(ui.Frame):

    def __init__(self, satellites: list[Satellite], coord_scale: float, timescale: Timescale) -> None:
        super().__init__(spacing=0, style=PLAYBACK_PANEL)

        self._satellites = satellites
        self._selected_sat = None
        self._stage = omni.usd.get_context().get_stage()
        self.selectedSatIdx = None
        self._timescale = timescale
        self._coord_scale = coord_scale
        self._orbit_curve_path = "/World/orbit/curve"
        self._orbit_curve = None
        self._window: Optional[ui.Window] = get_active_viewport_window()
        self._margin = 10

        self._fields: dict[str, ui.StringField] = {
            "panel_temperature": None,
            "electrical_temperature": None,
            "latitude": None,
            "longitude": None,
            "altitude": None
        }
        self._satellite_search = None
        self.set_build_fn(self._build_ui)

    def _build_ui(self):
        w1, h1 = 250, 400
        with ui.Placer(offset_x=self._window.width - self._margin - w1, offset_y=self._margin):
            with ui.ZStack(width=w1, height=h1 , content_clipping=True):
                ui.Rectangle()
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
            item = f'{sat.id} {sat.name}'
            itemList.append(item)

        # Add the searchable combo box to the UI
        # Create the searchable combo box with the specified items and callback
        self._satellite_search = build_searchable_combo_widget(
            combo_list=itemList,
            combo_index=-1,  # Start with no item selected
            combo_click_fn=self.satellite_combo_click,
            widget_height=18,
            default_value=EMPTY_COMBO_VAL,  # Placeholder text when no item is selected
            window_id="SearchableComboBoxWindow",
            delegate=ComboBoxListDelegate()  # Use the default delegate for item rendering
        )

    def _build_satellite_positions(self):
        with ui.CollapsableFrame("Position", collapsed=False, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Latitude (°): ")
                    self._fields["latitude"] = ui.StringField(None, read_only=True)
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Longitude (°): ")
                    self._fields["longitude"] = ui.StringField(None, read_only=True)
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Altitude (km): ")
                    self._fields["altitude"] = ui.StringField(None, read_only=True)

    def _build_electrical_components(self):
        with ui.CollapsableFrame("Electrical Components", collapsed=False, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Temperature (°C):")
                    self._fields["electrical_temperature"] = ui.StringField(None, read_only=True)

    def _build_solar_panels(self):
        with ui.CollapsableFrame("Solar Panels", collapsed=False, name="group"):
            with ui.VStack(height=0, spacing=5):
                with ui.HStack(height=ui.Length(30)):
                    ui.Label("Temperature (°C):")
                    self._fields["panel_temperature"] = ui.StringField(None, read_only=True)

    def satellite_combo_click(self, model):
        selected_item = model.get_value_as_string()

        if selected_item == EMPTY_COMBO_VAL:
            self.clear_selected_satellite()

        # Get norad cat id and set selectedSat
        ssc = selected_item[0:5]
        for i, sat in enumerate(self._satellites):
            if sat.id == ssc:
                self.select_satellite(sat, i)
                break

    def select_satellite(self, sat: Satellite, index: int) -> None:
        from .extension import get_sim_manager
        from .screen_ui import get_screen_ui
        from .time_manager import get_time_controller

        self._selected_sat = sat
        self._selected_sat.selected = True
        self.selectedSatIdx = index

        # Ensure search box reads correctly
        self._satellite_search.set_text(f'{sat.id} {sat.name}')

        # Update field models
        for field_key in self._fields.keys():
            if df := sat.get_data_feed(field_key):
                self._fields[field_key].model = df.model
            else:
                print(field_key)

        points = []
        widths = []

        now = get_time_controller().get_current_time()
        # Get the orbital period in days
        period_days = utils.get_satellite_period(sat).total_seconds() / (86400.0) # Period is in seconds
        times = self._timescale.linspace(now, now + period_days, 360)
        for t in times:
            geocentric = sat.at(t)
            pos = geocentric.frame_xyz(framelib.itrs)
            # Pack to Gf.Vec3d and scale to our coordinate frame
            pos = utils.to_vec3f(pos.km * self._coord_scale)
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
        indices = [0] * len(self._satellites)
        indices[self.selectedSatIdx] = sat.proto_index
        get_sim_manager().satellitesPrim.GetProtoIndicesAttr().Set(indices)

        # Maneuver camera to sit back 10,000 units
        viewport_api = get_active_viewport()
        camera_path = viewport_api.camera_path
        distance = 10000.0
        camera_state = ViewportCameraState(camera_path)
        start_pos = camera_state.position_world
        sat_pos = get_sim_manager().satPositions[index, :]
        sat_unit_vector = sat_pos / np.linalg.norm(sat_pos)
        end_pos = sat_pos + sat_unit_vector * distance
        end_pos = Gf.Vec3d(float(end_pos[0]), float(end_pos[1]), float(end_pos[2]))

        asyncio.ensure_future(get_screen_ui()._interpolate_position(camera_state, start_pos, end_pos))

    def clear_selected_satellite(self) -> None:
        from .extension import get_sim_manager
        self._selected_sat.selected = False # type: ignore
        self._selected_sat = None
        self.selectedSatIdx = None
        self._stage.RemovePrim(self._orbit_curve_path)

        # Change geometry for unselected satellite
        indices = [0] * len(get_sim_manager().satellites)
        get_sim_manager().satellitesPrim.GetProtoIndicesAttr().Set(indices)

        # Update field models
        for field_key in self._fields.keys():
            self._fields[field_key].model = NULL_STRING_MODEL

    def set_orbit_scale(self, cam_pos) -> None:
        pts = self._orbit_curve.GetPointsAttr().Get()
        widths = []
        for pt in pts:
            width = (utils.distance(cam_pos, pt) * 0.0002)**2
            widths.append(width)
        widths_clamped = np.clip(widths, 1.0, 100.0)
        self._orbit_curve.GetWidthsAttr().Set(Vt.FloatArray(widths_clamped))