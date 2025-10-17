from omni.ui import color as cl
from omni.ui import constant as fl
from omni.ui import url
import omni.ui as ui

# Pre-defined constants. It's possible to change them runtime.
cl.example_window_attribute_bg = cl("#1f2124")
cl.example_window_attribute_fg = cl("#0f1115")
cl.example_window_hovered = cl("#FFFFFF")
cl.example_window_text = cl("#CCCCCC")
fl.example_window_attr_hspacing = 10
fl.example_window_attr_spacing = 1
fl.example_window_group_spacing = 2

# The main style dict
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