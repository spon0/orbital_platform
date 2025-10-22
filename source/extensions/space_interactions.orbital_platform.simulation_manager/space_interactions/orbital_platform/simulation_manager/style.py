from omni.ui import color as cl
from omni.ui import constant as fl
from omni.ui import url
import omni.ui as ui


EXT_TOKEN = "${space_interactions.orbital_platform.simulation_manager}"

############################################
# COLOR
############################################
_LIGHT = 0xFF9E9E9E
_LIGHT_A = 0xAA9E9E9E
_MID = 0xFF535354
_MID_A = 0x55535354
_DARK = 0xFF3A3A3A
_DARK_A = 0xAA2A2825
_BLUE = 0xFFC5911A
_BLUE_A = 0xAAC5911A

############################################
# ICONS
############################################
_VISIBLE_ON = f"{EXT_TOKEN}/data/icons/visible_on_tint.svg"
_VISIBLE_OFF = f"{EXT_TOKEN}/data/icons/visible_off_tint.svg"
_ZOOM_IN = f"{EXT_TOKEN}/data/icons/navThumb_zoomIn_tint.svg"
_ZOOM_OUT = f"{EXT_TOKEN}/data/icons/navThumb_zoomOut_tint.svg"
_HOME = f"{EXT_TOKEN}/data/icons/navHome_tint.svg"
_SYNC = f"{EXT_TOKEN}/data/icons/sync.svg"
_INFO = f"{EXT_TOKEN}/data/icons/info_tint.svg"
_PLAY = f"{EXT_TOKEN}/data/icons/play.svg"
_PAUSE = f"{EXT_TOKEN}/data/icons/pause_dark.svg"
_OPTIONS = f"{EXT_TOKEN}/data/icons/options.svg"
_ADD = f"{EXT_TOKEN}/data/icons/add.svg"

# Pre-defined constants. It's possible to change them runtime.
cl.example_window_attribute_bg = cl("#1f2124")
cl.example_window_attribute_fg = cl("#0f1115")
cl.example_window_hovered = cl("#FFFFFF")
cl.example_window_text = cl("#CCCCCC")
fl.example_window_attr_hspacing = 10
fl.example_window_attr_spacing = 1
fl.example_window_group_spacing = 2


############################################
# FONT
############################################
_CLOCK_FONT = f"{EXT_TOKEN}/data/fonts/digital-7.regular.ttf"
_CLOCK_FONT_SIZE = 18

clock_box = {
    "font": _CLOCK_FONT,
    "font_size": _CLOCK_FONT_SIZE,
}

timeline_frame = {
    "Button": {"background_color": 0x0, "padding": 1},
    #"Button:checked": {"background_color": 0x0},
    #"Button:unchecked": {"background_color": 0x0},
    #"Button:hovered": {"background_color": 0x0},
    #"Button:pressed": {"background_color": 0x0},
    "Button.Image": {"background_color": 0x0, "color": _LIGHT },
    "Button.Image:hovered": {"color": _BLUE_A},
    #"Button.Image:checked": {"color": _LIGHT},
    "Button.Image:pressed": {"color": _DARK},
}


example_window_style = {
    "Label::attribute_name": {
        "alignment": ui.Alignment.RIGHT_CENTER,
        "margin_height": fl.example_window_attr_spacing,
        "margin_width": fl.example_window_attr_hspacing,
    },
    "Label::attribute_name:hovered": {"color": cl.example_window_hovered},
    "Label::collapsable_name": {"alignment": ui.Alignment.LEFT_CENTER},
    "Slider::attribute_int:hovered": {"color": cl.example_window_hovered},
    "Slider": {
        "background_color": cl.example_window_attribute_bg,
        "draw_mode": ui.SliderDrawMode.HANDLE,
    },
    "Slider::attribute_float": {
        "draw_mode": ui.SliderDrawMode.FILLED,
        "secondary_color": cl.example_window_attribute_fg,
    },
    "Slider::attribute_float:hovered": {"color": cl.example_window_hovered},
    "Slider::attribute_vector:hovered": {"color": cl.example_window_hovered},
    "Slider::attribute_color:hovered": {"color": cl.example_window_hovered},
    "CollapsableFrame::group": {"margin_height": fl.example_window_group_spacing},
    # "Image::collapsable_opened": {"color": cl.example_window_text, "image_url": url.example_window_icon_opened},
    # "Image::collapsable_closed": {"color": cl.example_window_text, "image_url": url.example_window_icon_closed},
}

PLAYBACK_PANEL = {
    "Rectangle": {"background_color": _DARK_A, "border_radius": 3},
    "Button": { "background_color": 0x0, "margin_height": 0.5, "margin_width": 0.5},
    "Button:hovered": {"background_color": 0x0},
    "Button:pressed": {"background_color": 0x0},
    "Button:checked": {"background_color": 0x0},
    "Button.Image::play": {"image_url": _PLAY},
    "Button.Image::play:checked": {"image_url": _PAUSE},
    "Label": {"color": _LIGHT},
    "Label::date": {"color": _BLUE}
}