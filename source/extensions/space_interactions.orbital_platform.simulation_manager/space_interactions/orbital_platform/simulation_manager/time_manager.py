from datetime import datetime
from typing import Optional

from pytz import UTC

import omni.ext
import omni.ui as ui
import omni.timeline
from omni.timeline import TimelineEventType
import carb.events
from omni.kit.viewport.utility import get_active_viewport_window
import omni.earth_2_command_center.app.globe_view as globe
import omni.earth_2_command_center.app.core as earth2core

import omni.kit.pipapi

from .style import _PAUSE, _PLAY, PLAYBACK_PANEL, clock_box, _CLOCK_FONT, _CLOCK_FONT_SIZE, timeline_frame

omni.kit.pipapi.install("skyfield")
from skyfield.api import load, Timescale
from skyfield import framelib

def get_controller():
    global _controller
    return _controller


class TimeControlFrame(ui.Frame):

    def __init__(self):
        super().__init__(spacing=0, style=PLAYBACK_PANEL)

        self.time_controller = SimulationTimeController()

        # UI models to store the values from the input fields
        now = datetime.now(UTC)
        self.year_model = ui.SimpleIntModel(now.year)
        self.month_model = ui.SimpleIntModel(now.month)
        self.day_model = ui.SimpleIntModel(now.day)
        self.hour_model = ui.SimpleIntModel(now.hour)
        self.minute_model = ui.SimpleIntModel(now.minute)
        self.second_model = ui.SimpleIntModel(now.second)
        self.time_scale_model = ui.SimpleFloatModel(1.0)
        self.current_time_str_model = ui.SimpleStringModel("Initializing...")

        self._window: Optional[ui.Window] = get_active_viewport_window()
        self._margin = 20

        self._timeline = omni.timeline.get_timeline_interface()
        timeline_event_stream = self._timeline.get_timeline_event_stream()
        self._subscription = timeline_event_stream.create_subscription_to_pop_by_type(
                int(TimelineEventType.CURRENT_TIME_TICKED),
                self._on_update
            )

        self.set_build_fn(self._build_fn)

    def _build_fn(self):
        w, h = 250, 100
        with ui.Placer(offset_x=self._window.width * 0.5 - w * 0.5, offset_y=self._window.height - self._margin - h):
                with ui.ZStack(width=w, height=h, content_clipping=1, opaque_for_mouse_events=True):
                    ui.Rectangle(width=ui.Percent(100), height=ui.Percent(100))
                    with ui.VStack(spacing=8, style=timeline_frame):
                        # --- SHOW DATE AND TIME ---
                        with ui.HStack(height=30, spacing=6):
                            # play/pause button
                            btn = ui.Button(
                                "",
                                tooltip='Play/Pause Simulation',
                                width=0,
                                height=0,
                                image_width=30,
                                image_height=30,
                                checked = True,
                                image_url = _PAUSE
                            )
                            btn.set_clicked_fn(lambda b=btn: self._on_play_pause_click(b))

                            def build_clock_box(model):
                                o = ui.IntField(model, enabled=False, width=40, style=clock_box)

                            ui.Label("Time:")
                            build_clock_box(self.hour_model)
                            ui.Label(":")
                            build_clock_box(self.minute_model)
                            ui.Label(":")
                            build_clock_box(self.second_model)

                        ui.Line(width=ui.Percent(80), alignment= ui.Alignment.CENTER)

                        # --- SECTION FOR SIMULATION CONTROL ---
                        with ui.HStack(height=30, spacing=2):

                            ui.Label("Speed:")
                            # A slider for more intuitive speed control
                            ui.FloatSlider(self.time_scale_model, min=0.1, max=100, step=0.1,
                                            format="%.1f x")

                        # with ui.HStack():
                        #     ui.Label("Speed:")
                        #     # A slider for more intuitive speed control
                        #     ui.FloatSlider(self.time_scale_model, min=0.1, max=100, step=0.1,
                        #                     format="%.0f x")
                        #     # When the slider value changes, update the controller
                        #     self.time_scale_model.add_value_changed_fn(
                        #         lambda m: self.time_controller.set_time_scale(m.get_value_as_float())
                        #     )


                    # with ui.VStack(spacing=8, width=w, height=h, content_clipping=1):
                    #     # --- SECTION FOR SETTING DATE AND TIME ---
                    #     with ui.CollapsableFrame("Set Date & Time (UTC)", collapsed=True):
                    #         with ui.VStack(spacing=5, style={"margin": 5}):
                    #             with ui.HStack():
                    #                 ui.Label("Date (Y/M/D):", width=100)
                    #                 ui.IntField(self.year_model)
                    #                 ui.IntField(self.month_model)
                    #                 ui.IntField(self.day_model)
                    #             with ui.HStack():
                    #                 ui.Label("Time (H:M):", width=100)
                    #                 ui.IntField(self.hour_model)
                    #                 ui.IntField(self.minute_model)
                    #             ui.Button("Apply Date and Time", clicked_fn=self._on_set_time_click)

                    #     # --- SECTION FOR SIMULATION CONTROL ---
                    #     with ui.CollapsableFrame("Playback Control", collapsed=True):
                    #         with ui.VStack(spacing=5, style={"margin": 5}):
                    #             with ui.HStack(spacing=10):
                    #                 ui.Button("▶ Play", clicked_fn=self.time_controller.play)
                    #                 ui.Button("❚❚ Pause", clicked_fn=self.time_controller.pause)

                    #             ui.Label("Time Scale (Speed):")
                    #             # A slider for more intuitive speed control
                    #             ui.FloatSlider(self.time_scale_model, min=0, max=10000, step=10,
                    #                             format="%.0f x")
                    #             # When the slider value changes, update the controller
                    #             self.time_scale_model.add_value_changed_fn(
                    #                 lambda m: self.time_controller.set_time_scale(m.get_value_as_float())
                    #             )

                    #     # --- SECTION FOR DISPLAYING CURRENT TIME ---
                    #     ui.Spacer(height=10)
                    #     ui.Label("Current Simulation Time:", style={"font_size": 16})
                    #     # This label will be updated every frame
                    #     ui.StringField(model=self.current_time_str_model, style={"color": 0xFF00DDFF})
                    #     #ui.Label(model=self.current_time_str_model, style={"color": 0xFF00DDFF})

    def _on_play_pause_click(self, btn: ui.Button):
        # Make this a toggle checkbox
        btn.checked = not btn.checked

        if btn.checked:
            print("Checked")
            btn.image_url = _PAUSE
            self.time_controller.play()
        else:
            print("Unchecked")
            btn.image_url = _PLAY
            self.time_controller.pause()


    def _on_set_time_click(self):
        """Called when the 'Apply Date and Time' button is clicked."""
        self.time_controller.set_time(
            self.year_model.get_value_as_int(),
            self.month_model.get_value_as_int(),
            self.day_model.get_value_as_int(),
            self.hour_model.get_value_as_int(),
            self.minute_model.get_value_as_int(),
        )

    def _on_update(self, e: carb.events.IEvent):
        """This function is called every single frame."""
        delta_time = e.payload["dt"]

        # 1. Advance the time in our controller
        self.time_controller.update(delta_time)

        # 2. Get the new current time from the controller
        current_skyfield_time = self.time_controller.get_current_time()

        # 3. Update the UI label to show the new time
        self.current_time_str_model.set_value(current_skyfield_time.utc_iso())

        # 4. !!! YOUR LOGIC GOES HERE !!!
        #    Use `current_skyfield_time` to calculate the position of ALL your objects.
        #    For each satellite prim in your scene:
        #
        #    satellite_prim = stage.GetPrimAtPath("/World/Satellites/MySatellite")
        #    geocentric = skyfield_satellite_object.at(current_skyfield_time)
        #    new_position = geocentric.position.km * scene_scale_factor
        #    omni.kit.commands.execute('TransformPrim',
        #        path=satellite_prim.GetPath(),
        #        new_transform_matrix=Gf.Matrix4d().SetTranslate(new_position))

    def on_shutdown(self):
        # Clean up resources
        self._update_sub = None
        self._window = None
        self.time_controller = None


class SimulationTimeController:
    """
    Manages the state of the simulation time, including date, speed, and play/pause.
    """
    def __init__(self):
        """Initializes the time controller."""
        self.ts = load.timescale()
        self._is_running = True  # Start the simulation in a 'playing' state
        self._time_scale = 1.0   # 1.0 means real-time. > 1.0 is fast-forward.
        self._current_sim_time = self.ts.now() # The current time of the simulation

    def update(self, delta_time: float):
        """
        This method should be called every frame to advance the simulation time.

        Args:
            delta_time (float): The real-world time in seconds that has passed since the last frame.
        """
        if not self._is_running:
            return

        # Calculate how much simulation time has passed
        # Skyfield's time is measured in days, so we convert delta_time from seconds to days.
        simulation_seconds_passed = delta_time * self._time_scale
        simulation_days_passed = simulation_seconds_passed / 86400.0  # (24 * 60 * 60)

        # Advance the current simulation time
        self._current_sim_time = self.ts.tt_jd(self._current_sim_time.tt + simulation_days_passed)

    def set_time(self, year: int, month: int, day: int, hour: int = 12, minute: int = 0, second: int = 0):
        """
        Manually sets the simulation to a specific UTC date and time.
        """
        try:
            self._current_sim_time = self.ts.utc(year, month, day, hour, minute, second)
            print(f"Simulation time set to: {self._current_sim_time.utc_iso()}")
        except ValueError as e:
            print(f"Error setting date: {e}. Please provide a valid date.")

    def play(self):
        """Starts or resumes the simulation."""
        self._is_running = True

    def pause(self):
        """Pauses the simulation."""
        self._is_running = False

    def set_time_scale(self, scale: float):
        """
        Sets the speed of the simulation.
        1.0 = real-time
        60.0 = 1 minute of simulation time per real second
        3600.0 = 1 hour of simulation time per real second
        """
        self._time_scale = max(0, scale) # Prevent negative time scales

    def get_current_time(self):
        """Returns the current Skyfield time object for the simulation."""
        return self._current_sim_time
