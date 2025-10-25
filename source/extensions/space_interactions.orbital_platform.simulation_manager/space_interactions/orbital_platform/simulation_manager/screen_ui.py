# internals
import time
from typing import Optional
from .satellite import Satellite
from .satellite_selection import SatelliteSelectionFrame
from .time_manager import TimeControlFrame
# omniverse
import omni.earth_2_command_center.app.globe_view as globe
import omni.ui as ui
from omni.kit.viewport.utility import get_active_viewport_window
from omni.kit.viewport.utility.camera_state import ViewportCameraState
import omni.kit.pipapi
from pxr import UsdGeom, Gf, Vt, Usd, Tf

# externals
omni.kit.pipapi.install("skyfield")
from skyfield.api import Timescale


def get_screen_ui():
    global _screen_ui
    return _screen_ui

class ScreenUI:

    def __init__(self, satellites: list[Satellite], coord_scale: float, timescale: Timescale):

        self._window: Optional[ui.Window] = get_active_viewport_window()

        self.__visible = True
        self.__frame: Optional[ui.Frame] = self._window.get_frame(globe.get_globe_view().ext_id)

        global _screen_ui
        _screen_ui = self

        self._width = self._window.width
        self._height = self._window.height
        self._margin = 10
        self._window.set_width_changed_fn(self._on_size_change)
        self._window.set_height_changed_fn(self._on_size_change)

        self.__zoom_min = 5_000
        self.__zoom_max = 400_000

        self._satellite_selection_frame: Optional[SatelliteSelectionFrame] = None
        self._timeline_frame: Optional[TimeControlFrame] = None
        self._coord_scale = coord_scale
        self._satellites = satellites
        self._timescale = timescale

        self.__build_ui()

    def __build_ui(self):
        """
            Builds the core UI Elements
        """
        if not self.__frame:
            return

        print("Build ScreenUI")
        with self.__frame:
            with ui.ZStack(width=ui.Percent(100), height=ui.Percent(100)):
                # Top right
                self._satellite_selection_frame = SatelliteSelectionFrame(self._satellites, self._coord_scale, self._timescale)
                # Bottom middle
                self._timeline_frame = TimeControlFrame()

    def _on_size_change(self, v):
        self._width = self._window.width
        self._height = self._window.height
        self._rebuild()

    def _rebuild(self):
        if self._satellite_selection_frame: self._satellite_selection_frame.rebuild()
        if self._timeline_frame: self._timeline_frame.rebuild()

    async def _interpolate_position(
            self,
            camera_state: ViewportCameraState,
            start: Gf.Vec3d,
            end: Gf.Vec3d,
            seconds_override: Optional[float] = None
    ):
            from .extension import get_sim_manager

            def ease_in_out_cubic(t):
                return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2

            def get_interp_time(start_pt: Gf.Vec3d):
                range = self.__zoom_max - self.__zoom_min
                min_dist = start_pt.GetLength() - self.__zoom_min
                return min_dist / range

            if seconds_override is not None:
                n_seconds = seconds_override
            else:
                n_seconds = get_interp_time(start) * 1.5
                n_seconds = n_seconds if n_seconds > 1.5 else 1.5

            start_time = time.time()
            while time.time() - start_time < n_seconds:
                current_time = time.time() - start_time
                t = current_time / n_seconds  # normalize 0-1
                i_val = start + (end - start) * ease_in_out_cubic(t)
                camera_state.set_position_world(i_val, True)
                camera_state.set_target_world(Gf.Vec3d(0,0,0), True)
                get_sim_manager().update_satellite_scales()
                await omni.kit.app.get_app().next_update_async()