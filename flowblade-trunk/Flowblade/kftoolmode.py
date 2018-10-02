"""
    Flowblade Movie Editor is a nonlinear video editor.
    Copyright 2012 Janne Liljeblad.

    This file is part of Flowblade Movie Editor <http://code.google.com/p/flowblade>.

    Flowblade Movie Editor is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Flowblade Movie Editor is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Flowblade Movie Editor.  If not, see <http://www.gnu.org/licenses/>.
"""

"""
Module handles Keyframe tool functionality
"""
from gi.repository import Pango, PangoCairo, Gtk

import cairo

import appconsts
import cairoarea
import edit
from editorstate import current_sequence
from editorstate import PLAYER
import gui
import guiutils
import mltfilters
import propertyedit
import propertyparse
import respaths
import tlinewidgets
import updater

CLOSE_ICON = None
HAMBURGER_ICON = None
ACTIVE_KF_ICON = None
NON_ACTIVE_KF_ICON = None

CLIP_EDITOR_WIDTH = 250 
CLIP_EDITOR_HEIGHT = 21
END_PAD = 8
TOP_PAD = 23
HEIGHT_PAD_PIXELS_TOTAL = 44
OUT_OF_RANGE_ICON_PAD = 27
OUT_OF_RANGE_KF_ICON_HALF = 6
OUT_OF_RANGE_NUMBER_X_START = 7
OUT_OF_RANGE_NUMBER_X_END_PAD = 14

KF_ICON_Y_PAD = -6
KF_TEXT_PAD = -6
KF_LOWER_OFF = 11

BUTTON_WIDTH = 26
BUTTON_HEIGHT = 24
KF_Y = 5
CENTER_LINE_Y = 11
POS_ENTRY_W = 38
POS_ENTRY_H = 20
KF_HIT_WIDTH = 8
KF_DRAG_THRESHOLD = 3

# Colors
POINTER_COLOR = (1, 0.3, 0.3)
CLIP_EDITOR_BG_COLOR = (0.7, 0.7, 0.7)
LIGHT_MULTILPLIER = 1.14
DARK_MULTIPLIER = 0.74
FRAME_SCALE_LINES = (0.07, 0.22, 0.07)
FRAME_SCALE_LINES_BRIGHT = (0.2, 0.6, 0.2)

CURVE_COLOR = (0.71, 0.13, 0.64)

OVERLAY_BG = (0.0, 0.0, 0.0, 0.8)
OVERLAY_DRAW_COLOR = (0.0, 0.0, 0.0, 0.8)
EDIT_AREA_HEIGHT = 200

# Edit types
VOLUME_KF_EDIT = 0
BRIGHTNESS_KF_EDIT = 1

# Editor states
KF_DRAG = 0
POSITION_DRAG = 1
KF_DRAG_DISABLED = 2
KF_DRAG_FRAME_ZERO_KF = 3

hamburger_menu = Gtk.Menu()
oor_before_menu = Gtk.Menu()
oor_after_menu = Gtk.Menu()

edit_data = None
enter_mode = None
_kf_editor = None

_playhead_follow_kf = True

# -------------------------------------------------- init
def load_icons():
    global CLOSE_ICON, HAMBURGER_ICON, ACTIVE_KF_ICON, NON_ACTIVE_KF_ICON

    CLOSE_ICON = cairo.ImageSurface.create_from_png(respaths.IMAGE_PATH + "close_match.png")
    HAMBURGER_ICON = cairo.ImageSurface.create_from_png(respaths.IMAGE_PATH + "hamburger.png")
    ACTIVE_KF_ICON = cairo.ImageSurface.create_from_png(respaths.IMAGE_PATH + "kf_active.png")
    NON_ACTIVE_KF_ICON = cairo.ImageSurface.create_from_png(respaths.IMAGE_PATH + "kf_not_active.png")    

def init_tool_for_clip(clip, track, edit_type=VOLUME_KF_EDIT):
    clip_index = track.clips.index(clip)

    # Save data needed to do the keyframe edits.
    global edit_data #, pressed_on_selected, drag_disabled
    edit_data = {"draw_function":_tline_overlay,
                 "clip_index":clip_index,
                 "clip_start_in_timeline":track.clip_start(clip_index),
                 "clip":clip,
                 "track":track,
                 "initializing":True}

    # Always brightness keyframes for media types that contain no audio.
    if edit_data["clip"].media_type != appconsts.VIDEO or  edit_data["clip"].media_type != appconsts.AUDIO:
         edit_type = BRIGHTNESS_KF_EDIT
    
    # Init for edit type
    if edit_type == VOLUME_KF_EDIT:
        ep = _get_volume_editable_property(clip, track, clip_index)
        if ep == None:
            filter_info = mltfilters.get_volume_filters_info()
            data = {"clip":clip, 
                    "filter_info":filter_info,
                    "filter_edit_done_func":_filter_create_dummy_func}
            action = edit.add_multipart_filter_action(data)
            action.do_edit()
            ep = _get_volume_editable_property(clip, track, clip_index)

        edit_data["editable_property"] = ep
        global _kf_editor
        _kf_editor = TLineKeyFrameEditor(ep, True, VOLUME_KF_EDIT)
        
    elif edit_type == BRIGHTNESS_KF_EDIT:
        ep = _get_brightness_editable_property(clip, track, clip_index)
        if ep == None:

            filter_info = mltfilters.get_brightness_filter_info()
            data = {"clip":clip, 
                    "filter_info":filter_info,
                    "filter_edit_done_func":_filter_create_dummy_func}
            action = edit.add_filter_action(data)
            action.do_edit()
            ep = _get_brightness_editable_property(clip, track, clip_index)
            
        edit_data["editable_property"] = ep
        global _kf_editor
        _kf_editor = TLineKeyFrameEditor(ep, True, BRIGHTNESS_KF_EDIT)
        
    tlinewidgets.set_edit_mode_data(edit_data)
    updater.repaint_tline()

def update_clip_frame(tline_frame):
    if _kf_editor != None and edit_data != None and edit_data["initializing"] != True:
        clip_frame = tline_frame - edit_data["clip_start_in_timeline"]
        _kf_editor.set_and_display_clip_frame(clip_frame)

def _get_volume_editable_property(clip, track, clip_index):
    return _get_multipart_keyframe_ep_from_service(clip, track, clip_index, "volume")

def _get_brightness_editable_property(clip, track, clip_index):
    for i in range(0, len(clip.filters)):
        filter_object = clip.filters[i]
        if filter_object.info.mlt_service_id == "brightness":
            editable_properties = propertyedit.get_filter_editable_properties(
                                                           clip, 
                                                           filter_object,
                                                           i,
                                                           track,
                                                           clip_index)
            for ep in editable_properties:          
                # Volume is one of these MLT multipart filters, so we chose this way to find the editable property in filter.
                try:
                    if ep.name == "level":
                        return ep
                except:
                    pass
                    
    return None
    
def _get_multipart_keyframe_ep_from_service(clip, track, clip_index, mlt_service_id):
    for i in range(0, len(clip.filters)):
        filter_object = clip.filters[i]
        if filter_object.info.mlt_service_id == mlt_service_id:
            editable_properties = propertyedit.get_filter_editable_properties(
                                                           clip, 
                                                           filter_object,
                                                           i,
                                                           track,
                                                           clip_index)
            for ep in editable_properties:
                try:
                    if ep.args["exptype"] == "multipart_keyframe":
                        return ep
                except:
                    pass
                    
    return None


def exit_tool():
    _set_no_clip_edit_data()
    global enter_mode
    if enter_mode != None:
        gui.editor_window.kf_tool_exit_to_mode(enter_mode)
        enter_mode = None
    updater.repaint_tline()
        
def _filter_create_dummy_func(obj1, obj2):
    pass

# ---------------------------------------------- mouse events
def mouse_press(event, frame):

    x = event.x
    y = event.y

    # If we have clip being edited and its edit area is hit, we do not need to init data.
    if _kf_editor != None and _kf_editor.overlay_area_hit(x, y):
        _handle_edit_mouse_press(event)
        return

    # Attempt to init kf tool editing on some clip
    
    # Get pressed track
    track = tlinewidgets.get_track(y)  

    # Selecting empty clears selection
    if track == None:
        exit_tool()
        return    
    
    # Get pressed clip index
    clip_index = current_sequence().get_clip_index(track, frame)

    # Selecting empty clears selection
    if clip_index == -1:
        exit_tool()
        return

    clip = track.clips[clip_index]

    init_tool_for_clip(clip, track)

def _handle_edit_mouse_press(event):
    _kf_editor.press_event(event)
        
def mouse_move(x, y, frame, state):
    if _kf_editor != None and edit_data != None and edit_data["initializing"] != True:
        _kf_editor.motion_notify_event(x, y, state)

def mouse_release(x, y, frame, state):
    if _kf_editor != None and edit_data != None and edit_data["initializing"] != True:
        _kf_editor.release_event(x, y)
        
    if edit_data != None: 
        edit_data["initializing"] = False

# -------------------------------------------- edit 
def delete_active_keyframe():
    if _kf_editor != None and edit_data != None and edit_data["initializing"] != True:
        _kf_editor.delete_active_keyframe()

def _clip_is_being_edited():
    if edit_data == None:
        return False
    if edit_data["clip_index"] == -1:
        return False
    
    return True

"""
def _clip_edit_area_hit(x, y):
    return False
"""

def _set_no_clip_edit_data():
    # set edit data to reflect that no clip is being edited currently.
    global edit_data, _kf_editor
    edit_data = {"draw_function":_tline_overlay,
                 "clip_index":-1,
                 "track":None,
                 "mouse_start_x":-1,
                 "mouse_start_y":-1}
    _kf_editor = None

    tlinewidgets.set_edit_mode_data(edit_data)

"""
def _init_for_editable_property(editable_property):
    edit_data["editable_property"] = editable_property
    adjustment = editable_property.get_input_range_adjustment()
    edit_data["lower"] = adjustment.get_lower()
    edit_data["upper"] = adjustment.get_upper()
"""
    
# ----------------------------------------------------------------------- draw
def _tline_overlay(cr):
    if _clip_is_being_edited() == False:
        return
        
    track = edit_data["track"]
    cx_start = tlinewidgets._get_frame_x(edit_data["clip_start_in_timeline"])
    clip = track.clips[edit_data["clip_index"]]
    cx_end = tlinewidgets._get_frame_x(track.clip_start(edit_data["clip_index"]) + clip.clip_out - clip.clip_in + 1)  # +1 because out inclusive
    
    # Get y position for clip's track
    ty_bottom = tlinewidgets._get_track_y(1) + current_sequence().tracks[1].height
    ty_top = tlinewidgets._get_track_y(len(current_sequence().tracks) - 2) - 6 # -6 is hand correction, no idea why the math isn't getting correct pos top most track
    ty_top_bottom_edge = ty_top + EDIT_AREA_HEIGHT
    off_step = float(ty_bottom - ty_top_bottom_edge) / float(len(current_sequence().tracks) - 2)
    ty_off = off_step * float(track.id - 1)
    ty = ty_bottom - ty_off
    cy_start = ty - EDIT_AREA_HEIGHT

    # Set draw params and draw
    _kf_editor.set_allocation(cx_start, cy_start, cx_end - cx_start, EDIT_AREA_HEIGHT)
    _kf_editor.source_track_center = tlinewidgets._get_track_y(track.id) + current_sequence().tracks[track.id].height / 2.0
    _kf_editor.draw(cr)


# ----------------------------------------------------- editor objects
class TLineKeyFrameEditor:
    """
    GUI component used to add, move and remove keyframes 
    inside a single clip. It is used as a component inside a parent editor and
    needs the parent editor to write out keyframe values.
    
    Parent editor must implement callback interface:
        def clip_editor_frame_changed(self, frame)
        def active_keyframe_changed(self)
        def keyframe_dragged(self, active_kf, frame)
        def update_slider_value_display(self, frame)
        def update_property_value(self)
    """

    def __init__(self, editable_property, use_clip_in, edit_type):
        
        self.clip_length = editable_property.get_clip_length() - 1
        self.edit_type = edit_type
        # Some filters start keyframes from *MEDIA* frame 0
        # Some filters or compositors start keyframes from *CLIP* frame 0
        # Filters starting from *MEDIA* 0 need offset 
        # to clip start added to all values.
        self.use_clip_in = use_clip_in
        if self.use_clip_in == True:
            self.clip_in = editable_property.clip.clip_in
        else:
            self.clip_in = 0
        self.current_clip_frame = self.clip_in

        self.clip_tline_pos = editable_property.get_clip_tline_pos()
        
        self.keyframes = [(0, 0.0)]
        self.active_kf_index = 0

        self.frame_scale = tlinewidgets.KFToolFrameScale(FRAME_SCALE_LINES)
        
        self.source_track_center = 0 # set externally
        
        self.media_frame_txt = _("Media Frame: ")
        self.volume_kfs_text = _("Volume Keyframes")
        self.brightness_kfs_text = _("Brightness Keyframes")
        
        self.current_mouse_action = None
        self.drag_on = False # Used to stop updating pos here if pos change is initiated here.
        self.drag_min = -1
        self.drag_max = -1

        # Init keyframes
        self.keyframe_parser = propertyparse.single_value_keyframes_string_to_kf_array
        editable_property.value.strip('"')
        self.set_keyframes(editable_property.value, editable_property.get_in_value)     

        self._set_pos_to_active_kf()

    def set_keyframes(self, keyframes_str, out_to_in_func):
        self.keyframes = self.keyframe_parser(keyframes_str, out_to_in_func)

    def overlay_area_hit(self, tx, ty):
        x, y, w, h = self.allocation
        if tx >= x and tx <= x + w:
            if ty >= y and ty <= y + h:
                return True
        
        return False
            
    def get_kf_info(self):
        return (self.active_kf_index, len(self.keyframes))
        
    def _get_panel_pos(self):
        return self._get_panel_pos_for_frame(self.current_clip_frame) 

    def _get_panel_pos_for_frame(self, frame):
        x, y, width, h = self.allocation
        active_width = width - 2 * END_PAD
        disp_frame = frame - self.clip_in 
        return x + END_PAD + int((float(disp_frame) / float(self.clip_length)) * 
                             active_width)

    def _get_frame_for_panel_pos(self, panel_x):
        rx, ry, rw, rh = self._get_edit_area_rect()
        clip_panel_x = panel_x - rx
        norm_pos = float(clip_panel_x) / float(rw)
        return int(norm_pos * self.clip_length) + self.clip_in

    def _get_value_for_panel_y(self, panel_y):
        rx, ry, rw, rh = self._get_edit_area_rect()
        editable_property = edit_data["editable_property"] 
        adjustment = editable_property.get_input_range_adjustment()
        lower = adjustment.get_lower()
        upper = adjustment.get_upper()
        value_range = upper - lower
        pos_fract = (ry + rh - panel_y) / rh
        return pos_fract * value_range + lower
        
    def _get_panel_y_for_value(self, value):
        editable_property = edit_data["editable_property"] 
        adjustment = editable_property.get_input_range_adjustment()
        lower = adjustment.get_lower()
        upper = adjustment.get_upper()
        value_range = upper - lower
        value_fract = (value - lower) / value_range
        return self._get_lower_y() - (self._get_lower_y() - self._get_upper_y()) * value_fract

    def _get_lower_y(self):
        x, y, w, h = self.allocation
        return y + TOP_PAD + h - HEIGHT_PAD_PIXELS_TOTAL

    def _get_upper_y(self):
        x, y, w, h = self.allocation
        return  y + TOP_PAD
    
    """
    def _get_center_y(self):
        l = self._get_lower_y()
        u = self._get_upper_y()
        return u + (l - u) / 2
    """

    def _set_clip_frame(self, panel_x):
        self.current_clip_frame = self._get_frame_for_panel_pos(panel_x)
    
    def move_clip_frame(self, delta):
        self.current_clip_frame = self.current_clip_frame + delta
        self._force_current_in_frame_range()

    def set_and_display_clip_frame(self, clip_frame):
        self.current_clip_frame = clip_frame
        self._force_current_in_frame_range()

    def set_allocation(self, x, y, w, h):
        self.allocation = (x, y, w, h)

    def draw(self, cr):
        """
        Callback for repaint from CairoDrawableArea.
        We get cairo context and allocation.
        """
        x, y, w, h = self.allocation
  
        # Draw bg
        cr.set_source_rgba(*OVERLAY_BG)
        cr.rectangle(x, y, w, h)
        cr.fill()

        self._draw_edit_area_borders(cr)

        # Top row
        cr.set_source_surface(HAMBURGER_ICON, x + 4.5, y + 4)
        cr.paint()

        # Frame scale and value lines
        self.frame_scale.draw(cr, edit_data["clip_start_in_timeline"], self.clip_length, self._get_upper_y(), self._get_lower_y())
        self._draw_value_lines(cr, x, w)

        kf_positions = self.get_clip_kfs_and_positions()
        
        # Draw keyframes
        for i in range(0, len(kf_positions)):
            kf, frame, kf_index, kf_pos_x, kf_pos_y = kf_positions[i]

            if frame < self.clip_in:
                continue
            if frame > self.clip_in + self.clip_length:
                continue  
                
            if kf_index == self.active_kf_index:
                icon = ACTIVE_KF_ICON
            else:
                icon = NON_ACTIVE_KF_ICON

            cr.set_source_surface(icon, kf_pos_x - 6, kf_pos_y - 6) # -6 to get kf bitmap center on calculated pixel
            cr.paint()

        cr.set_source_rgb(*CURVE_COLOR)
        cr.set_line_width(1.0)
        
        # Draw value curves,they need to be clipped into edit area
        cr.save()
        cr.set_line_width(2.0)
        ex, ey, ew, eh = self._get_edit_area_rect()
        cr.rectangle(ex, ey, ew, eh)
        cr.clip() 
        for i in range(0, len(kf_positions)):
            kf, frame, kf_index, kf_pos_x, kf_pos_y = kf_positions[i]
            if i == 0:
                cr.move_to(kf_pos_x, kf_pos_y)
            else:
                cr.line_to(kf_pos_x, kf_pos_y)
        cr.stroke()
        cr.restore()
        
        # Draw out-of-range kf icons and kf counts
        if w > 55: # dont draw on too small editors
            before_kfs = len(self.get_out_of_range_before_kfs())
            after_kfs = len(self.get_out_of_range_after_kfs())
            
            kfy = self._get_lower_y() + KF_LOWER_OFF
            if before_kfs > 0:
                cr.set_source_surface(NON_ACTIVE_KF_ICON, x + OUT_OF_RANGE_ICON_PAD - OUT_OF_RANGE_KF_ICON_HALF * 2, kfy + KF_ICON_Y_PAD)
                cr.paint()
                self._draw_text(cr, str(before_kfs), x + OUT_OF_RANGE_NUMBER_X_START, kfy + KF_TEXT_PAD)
            if after_kfs > 0:
                cr.set_source_surface(NON_ACTIVE_KF_ICON, x + w - OUT_OF_RANGE_ICON_PAD, kfy + KF_ICON_Y_PAD)
                cr.paint()
                self._draw_text(cr, str(after_kfs), x + w - OUT_OF_RANGE_NUMBER_X_END_PAD, kfy + KF_TEXT_PAD)
        
        # Draw source triangle
        cr.move_to(x + 1, self.source_track_center - 8)
        cr.line_to(x + 9, self.source_track_center)
        cr.line_to(x + 1, self.source_track_center + 8)
        cr.close_path()
        cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
        cr.fill()
        
        # Draw frame pointer
        try:
            panel_pos = self._get_panel_pos()
        except ZeroDivisionError: # math fails for 1 frame clip
            panel_pos = END_PAD
        cr.set_line_width(1.0)
        cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
        cr.move_to(panel_pos, ey - 8)
        cr.line_to(panel_pos, ey + eh + 8)
        cr.stroke()

        # Draw title
        if w > 165: # dont draw on too small editors
            if self.edit_type == VOLUME_KF_EDIT:
                text = self.volume_kfs_text
            else:
                text = self.brightness_kfs_text
            self._draw_text(cr, text, -1, y + 4, True, x, w)
            self._draw_text(cr, self.media_frame_txt + str(self.current_clip_frame), -1, kfy - 8, True, x, w)
            
    def _draw_edit_area_borders(self, cr):
        x, y, w, h = self._get_edit_area_rect()
        cr.set_source_rgb(*FRAME_SCALE_LINES)
        cr.rectangle(x, y, w, h)
        cr.stroke()

    def _get_edit_area_rect(self):
        x, y, w, h = self.allocation
        active_width = w - 2 * END_PAD
        ly = self._get_lower_y()
        uy = self._get_upper_y()
        return (x + END_PAD, uy, active_width - 1, ly - uy)
        
    def _draw_value_lines(self, cr, x, w):
        # Audio hard coded value lines
        TEXT_X_OFF = 4
        TEXT_X_OFF_END = -28
        TEXT_Y_OFF = 4
        
        active_width = w - 2 * END_PAD
        xs = x + END_PAD
        xe = xs + active_width

        cr.select_font_face ("sans-serif",
                              cairo.FONT_SLANT_NORMAL,
                              cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(12)

        # TODO: Do this in a more general way if we ever use this tool to edit other than "volume" and "brightness".
        if self.edit_type == VOLUME_KF_EDIT:
            # 0
            y = self._get_panel_y_for_value(0.0)
            cr.set_line_width(1.0)
            cr.set_source_rgb(*FRAME_SCALE_LINES)
            cr.move_to(xs, y)
            cr.line_to(xe, y)
            cr.stroke()
            
            cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
            text = "0"
            cr.move_to(xs + TEXT_X_OFF, y - TEXT_Y_OFF)
            cr.show_text(text)
            cr.move_to(xe + TEXT_X_OFF_END + 16, y - TEXT_Y_OFF)
            cr.show_text(text)
            
            # 100
            y = self._get_panel_y_for_value(100)
            cr.set_source_rgb(*FRAME_SCALE_LINES)
            cr.move_to(xs, y)
            cr.line_to(xe, y)
            cr.stroke()
            
            cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
            text = "100"
            cr.move_to(xs + TEXT_X_OFF, y - TEXT_Y_OFF)
            cr.show_text(text)
            cr.move_to(xe + TEXT_X_OFF_END, y - TEXT_Y_OFF)
            cr.show_text(text)
        elif self.edit_type == BRIGHTNESS_KF_EDIT:
            # 0
            y = self._get_panel_y_for_value(0.0)
            cr.set_line_width(1.0)
            cr.set_source_rgb(*FRAME_SCALE_LINES)
            cr.move_to(xs, y)
            cr.line_to(xe, y)
            cr.stroke()
            
            cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
            text = "0"
            cr.move_to(xs + TEXT_X_OFF, y - TEXT_Y_OFF)
            cr.show_text(text)
            cr.move_to(xe + TEXT_X_OFF_END + 16, y - TEXT_Y_OFF)
            cr.show_text(text)

            # 50
            #XOFF_END_50 = -5
            y = self._get_panel_y_for_value(50)
            cr.set_line_width(1.0)
            cr.set_source_rgb(*FRAME_SCALE_LINES)
            cr.move_to(xs, y)
            cr.line_to(xe, y)
            cr.stroke()
            
            cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
            text = "50"
            cr.move_to(xs + TEXT_X_OFF, y + 4)
            cr.show_text(text)
            cr.move_to(xe + TEXT_X_OFF_END + 6, y + 4)
            cr.show_text(text)
            
            # 100
            y = self._get_panel_y_for_value(100) 
            cr.set_source_rgb(*FRAME_SCALE_LINES)
            cr.move_to(xs, y)
            cr.line_to(xe, y)
            cr.stroke()
            
            cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
            text = "100"
            cr.move_to(xs + TEXT_X_OFF, y + 13)
            cr.show_text(text)
            cr.move_to(xe + TEXT_X_OFF_END, y + 13)
            cr.show_text(text)
            
    def _draw_text(self, cr, txt, x, y, centered=False, tline_x=-1, w=-1):
        layout = PangoCairo.create_layout(cr)
        layout.set_text(txt, -1)
        desc = Pango.FontDescription("Sans 8")
        layout.set_font_description(desc)

        if centered == True:
            lw, lh = layout.get_pixel_size()
            x = w/2 - lw/2 + tline_x

        cr.move_to(x, y)
        cr.set_source_rgb(*FRAME_SCALE_LINES_BRIGHT)
        PangoCairo.update_layout(cr, layout)
        PangoCairo.show_layout(cr, layout)
        
    def get_clip_kfs_and_positions(self):
        kf_positions = []
        for i in range(0, len(self.keyframes)):
            frame, value = self.keyframes[i]

            try:
                kf_pos_x = self._get_panel_pos_for_frame(frame)
            except ZeroDivisionError: # math fails for 1 frame clip
                kf_pos_x = END_PAD
                
            kf_pos_y = self._get_panel_y_for_value(value)
            
            kf_positions.append((self.keyframes[i], frame, i, kf_pos_x, kf_pos_y))

        return kf_positions
    
    # ----------------------------------------------------------- mouse events
    def press_event(self, event):
        """
        Mouse button callback
        """
        # Check if menu icons hit
        if self._oor_start_kf_hit(event.x, event.y) == True:
            self._show_oor_before_menu(gui.tline_canvas.widget, event)
            return

        if self._oor_end_kf_hit(event.x, event.y) == True:
            self._show_oor_after_menu(gui.tline_canvas.widget, event)
            return

        if self._hamburger_hit(event.x, event.y) == True:
            self._show_hamburger_menu(gui.tline_canvas.widget, event)
            return
            
        # Handle clip range mouse events
        self.drag_on = True # ??!? not needed here?

        lx = self._legalize_x(event.x)
        ly = self._legalize_y(event.y)
        
        if event.button == 3:
            self.current_mouse_action = POSITION_DRAG
            frame = self._get_drag_frame(lx)
            self.current_clip_frame = frame
            self.clip_editor_frame_changed(self.current_clip_frame)

            self.drag_start_x = event.x
            self.drag_min = self.clip_in
            self.drag_max = self.clip_in + self.clip_length
                
            updater.repaint_tline()
            return
            
        hit_kf = self._key_frame_hit(lx, ly)

        if hit_kf == None: # nothing was hit, add new keyframe and set it active
            frame =  self._get_frame_for_panel_pos(lx)
            value = self._get_value_for_panel_y(ly)
            self.add_keyframe(frame, value)
            hit_kf = self.active_kf_index 
        else: # some keyframe was pressed
            self.active_kf_index = hit_kf
            
        frame, value = self.keyframes[hit_kf]
        self.current_clip_frame = frame
        if hit_kf == 0:
            self.current_mouse_action = KF_DRAG_FRAME_ZERO_KF
        else:
            self.current_mouse_action = KF_DRAG
            
            self.drag_start_x = event.x
            
            prev_frame, val = self.keyframes[hit_kf - 1]
            self.drag_min = prev_frame  + 1
            try:
                next_frame, val = self.keyframes[hit_kf + 1]
                self.drag_max = next_frame - 1
            except:
                self.drag_max = self.clip_length
                
        updater.repaint_tline()

    def motion_notify_event(self, x, y, state):
        """
        Mouse move callback
        """
        lx = self._legalize_x(x)
        ly = self._legalize_y(y)
        
        if self.current_mouse_action == POSITION_DRAG:
            frame = self._get_drag_frame(lx)
            self.current_clip_frame = frame
            self.clip_editor_frame_changed(self.current_clip_frame)
            updater.repaint_tline()
        elif self.current_mouse_action == KF_DRAG or self.current_mouse_action == KF_DRAG_FRAME_ZERO_KF:
            frame = self._get_drag_frame(lx)
            if self.current_mouse_action == KF_DRAG_FRAME_ZERO_KF:
                frame = 0
            value = self._get_value_for_panel_y(ly)
            self.set_active_kf_frame_and_value(frame, value)
            if _playhead_follow_kf == True:
                self.current_clip_frame = frame
                self.clip_editor_frame_changed(self.current_clip_frame)

        updater.repaint_tline()
        
    def release_event(self, x,y):
        """
        Mouse release callback.
        """
        lx = self._legalize_x(x)
        ly = self._legalize_y(y)
        
        if self.current_mouse_action == POSITION_DRAG:
            frame = self._get_drag_frame(lx)
            self.current_clip_frame = frame
            self.clip_editor_frame_changed(self.current_clip_frame)
            updater.repaint_tline()
        elif self.current_mouse_action == KF_DRAG or self.current_mouse_action == KF_DRAG_FRAME_ZERO_KF:
            frame = self._get_drag_frame(lx)
            if self.current_mouse_action == KF_DRAG_FRAME_ZERO_KF:
                frame = 0
            value = self._get_value_for_panel_y(ly)
            self.set_active_kf_frame_and_value(frame, value)
            if _playhead_follow_kf == True:
                self.current_clip_frame = frame
                self.clip_editor_frame_changed(self.current_clip_frame)
            self.update_property_value()
            self.update_slider_value_display(frame)   

        updater.repaint_tline()
        self.current_mouse_action = None
        
        self.drag_on = False
        
    def _legalize_x(self, x):
        """
        Get x in pixel range between end pads.
        """
        rx, ry, rw, rh = self._get_edit_area_rect()
        if x < rx:
            return rx
        elif x > rx + rw:
            return rx + rw
        else:
            return x
    
    def _legalize_y(self, y):
        rx, ry, rw, rh = self._get_edit_area_rect()
        if y < ry:
            return ry
        elif y > ry + rh:
            return ry + rh
        else:
            return y

    def _force_current_in_frame_range(self):
        if self.current_clip_frame < self.clip_in:
            self.current_clip_frame = self.clip_in
        if self.current_clip_frame > self.clip_in + self.clip_length:
            self.current_clip_frame = self.clip_in + self.clip_length

    def get_out_of_range_before_kfs(self):
        # returns Keyframes before current clip start
        kfs = []
        for i in range(0, len(self.keyframes)):
            frame, value = self.keyframes[i]
            if frame < self.clip_in:
                kfs.append(self.keyframes[i])
        return kfs

    def get_out_of_range_after_kfs(self):
        # returns Keyframes before current clip start
        kfs = []
        for i in range(0, len(self.keyframes)):
            frame, value = self.keyframes[i]
            if frame > self.clip_in + self.clip_length:
                kfs.append(self.keyframes[i])
        return kfs
                
    def _get_drag_frame(self, panel_x):
        """
        Get x in range available for current drag.
        """
        frame = self._get_frame_for_panel_pos(panel_x)
        if frame < self.drag_min:
            frame = self.drag_min
        if frame > self.drag_max:
            frame = self.drag_max
        return frame
    
    def _key_frame_hit(self, x, y):
        for i in range(0, len(self.keyframes)):
            frame, val = self.keyframes[i]
            frame_x = self._get_panel_pos_for_frame(frame)
            value_y = self._get_panel_y_for_value(val)
            if((abs(x - frame_x) < KF_HIT_WIDTH)
                and (abs(y - value_y) < KF_HIT_WIDTH)):
                return i
            
        return None

    def _area_hit(self, tx, ty, x, y, w, h):
        if ty >= y and ty <= y + h: # 12 icon size
            if tx >= x and tx <= x + w:
                return True
            
        return False
        
    def _oor_start_kf_hit(self, x, y):
        rx, ry, rw, rh = self.allocation
        kfy = self._get_lower_y() + KF_LOWER_OFF
        area_y = kfy + KF_ICON_Y_PAD
        area_x = rx + OUT_OF_RANGE_ICON_PAD - OUT_OF_RANGE_KF_ICON_HALF * 2
        return self._area_hit(x, y, area_x, area_y, 12, 12)

    def _oor_end_kf_hit(self, x, y):
        rx, ry, rw, rh = self.allocation
        kfy = self._get_lower_y() + KF_LOWER_OFF
        area_x = rx + rw - OUT_OF_RANGE_ICON_PAD
        area_y = kfy + KF_ICON_Y_PAD
        return self._area_hit(x, y, area_x, area_y, 12, 12)

    def _hamburger_hit(self, x, y):
        rx, ry, rw, rh = self.allocation
        return self._area_hit(x, y, rx + 4.5, ry + 4, 12, 12)
        
    def add_keyframe(self, frame, value):
        kf_index_on_frame = self.frame_has_keyframe(frame)
        if kf_index_on_frame != -1:
            # Trying add on top of existing keyframe makes it active
            self.active_kf_index = kf_index_on_frame
            return

        for i in range(0, len(self.keyframes)):
            kf_frame, kf_value = self.keyframes[i]
            if kf_frame > frame:
                #prev_frame, prev_value = self.keyframes[i - 1]
                self.keyframes.insert(i, (frame, value))
                self.active_kf_index = i
                return
        #prev_frame, prev_value = self.keyframes[len(self.keyframes) - 1]
        self.keyframes.append((frame, value))
        self.active_kf_index = len(self.keyframes) - 1

    def print_keyframes(self):
        print "clip edit keyframes:"
        for i in range(0, len(self.keyframes)):
            print self.keyframes[i]
        
    def delete_active_keyframe(self):
        if self.active_kf_index == 0:
            # keyframe frame 0 cannot be removed
            return
        self.keyframes.pop(self.active_kf_index)
        self.active_kf_index -= 1
        if self.active_kf_index < 0:
            self.active_kf_index = 0
        self._set_pos_to_active_kf()
    
        updater.repaint_tline()
            
    def _set_pos_to_active_kf(self):
        frame, value = self.keyframes[self.active_kf_index]
        self.current_clip_frame = frame
        self._force_current_in_frame_range()
        self.update_slider_value_display(self.current_clip_frame)   
            
    def frame_has_keyframe(self, frame):
        """
        Returns index of keyframe if frame has keyframe or -1 if it doesn't.
        """
        for i in range(0, len(self.keyframes)):
            kf_frame, kf_value = self.keyframes[i]
            if frame == kf_frame:
                return i

        return -1
    
    def get_active_kf_frame(self):
        frame, val = self.keyframes[self.active_kf_index]
        return frame

    def get_active_kf_value(self):
        frame, val = self.keyframes[self.active_kf_index]
        return val
    
    def set_active_kf_value(self, new_value):
        frame, val = self.keyframes.pop(self.active_kf_index)
        self.keyframes.insert(self.active_kf_index,(frame, new_value))

    def active_kf_pos_entered(self, frame):
        if self.active_kf_index == 0:
            return
        
        prev_frame, val = self.keyframes[self.active_kf_index - 1]
        prev_frame += 1
        try:
            next_frame, val = self.keyframes[self.active_kf_index + 1]
            next_frame -= 1
        except:
            next_frame = self.clip_length - 1
        
        frame = max(frame, prev_frame)
        frame = min(frame, next_frame)

        self.set_active_kf_frame(frame)
        self.current_clip_frame = frame    
        
    def set_active_kf_frame(self, new_frame):
        frame, val = self.keyframes.pop(self.active_kf_index)
        self.keyframes.insert(self.active_kf_index,(new_frame, val))

    def set_active_kf_frame_and_value(self, new_frame, new_value):
        frame, val = self.keyframes.pop(self.active_kf_index)
        self.keyframes.insert(self.active_kf_index,(new_frame, new_value))
        
    def _show_oor_before_menu(self, widget, event):
        menu = oor_before_menu
        self._build_oor_before_menu(menu)
        menu.popup(None, None, None, None, event.button, event.time)

    def _build_oor_before_menu(self, menu):
        guiutils.remove_children(menu)
        before_kfs = len(self.get_out_of_range_before_kfs())

        if before_kfs == 0:
            # hit detection is active even if the kf icon is not displayed
            return

        if before_kfs > 1:
            menu.add(self._get_menu_item(_("Delete all but first Keyframe before Clip Range"), self._oor_menu_item_activated, "delete_all_before" ))
            sep = Gtk.SeparatorMenuItem()
            sep.show()
            menu.add(sep)

        if len(self.keyframes) > 1:
            menu.add(self._get_menu_item(_("Set Keyframe at Frame 0 to value of next Keyframe"), self._oor_menu_item_activated, "zero_next" ))
        elif before_kfs == 1:
            item = self._get_menu_item(_("No Edit Actions currently available"), self._oor_menu_item_activated, "noop" )
            item.set_sensitive(False)
            menu.add(item)

    def _show_oor_after_menu(self, widget, event):
        menu = oor_before_menu
        self._build_oor_after_menu(menu)
        menu.popup(None, None, None, None, event.button, event.time)

    def _build_oor_after_menu(self, menu):
        guiutils.remove_children(menu)
        after_kfs = self.get_out_of_range_after_kfs()
        
        if after_kfs == 0:
            # hit detection is active even if the kf icon is not displayed
            return

        menu.add(self._get_menu_item(_("Delete all Keyframes after Clip Range"), self._oor_menu_item_activated, "delete_all_after" ))
        
    def _show_hamburger_menu(self, widget, event):
        menu = hamburger_menu
        guiutils.remove_children(menu)

        if edit_data["track"].type == appconsts.VIDEO:
            if edit_data["clip"].media_type == appconsts.VIDEO:
                edit_volume = self._get_menu_item(_("Edit Volume Keyframes"), self._oor_menu_item_activated, "edit_volume" )
                if self.edit_type == VOLUME_KF_EDIT:
                    edit_volume.set_sensitive(False)
                menu.add(edit_volume)

                edit_brightness = self._get_menu_item(_("Edit Brightness Keyframes"), self._oor_menu_item_activated, "edit_brightness" )
                if self.edit_type == BRIGHTNESS_KF_EDIT:
                    edit_brightness.set_sensitive(False)
                menu.add(edit_brightness)

            sep = Gtk.SeparatorMenuItem()
            sep.show()
            menu.add(sep)

        leading_menu_item = Gtk.MenuItem(_("Leading Keyframes"))
        leading_menu = Gtk.Menu()
        self._build_oor_before_menu(leading_menu)
        leading_menu_item.set_submenu(leading_menu)
        leading_menu_item.show_all()
        menu.add(leading_menu_item)
        
        trailing_menu_item = Gtk.MenuItem(_("Trailing Keyframes"))
        trailing_menu = Gtk.Menu()
        self._build_oor_after_menu(trailing_menu)
        trailing_menu_item.set_submenu(trailing_menu)
        trailing_menu_item.show_all()
        menu.add(trailing_menu_item)
        
        sep = Gtk.SeparatorMenuItem()
        sep.show()
        menu.add(sep)
        
        playhead_follow_item = Gtk.CheckMenuItem()
        playhead_follow_item.set_label(_("Playhead Follows Dragged Keyframe"))
        playhead_follow_item.set_active(_playhead_follow_kf)
        playhead_follow_item.connect("activate", self._oor_menu_item_activated, "playhead_follows")
        playhead_follow_item.show()
        menu.add(playhead_follow_item)
        
        sep = Gtk.SeparatorMenuItem()
        sep.show()
        menu.add(sep)
        
        menu.add(self._get_menu_item(_("Exit Edit"), self._oor_menu_item_activated, "exit" ))

        menu.popup(None, None, None, None, event.button, event.time)

    def _oor_menu_item_activated(self, widget, data):
        if data == "delete_all_before":
            keep_doing = True
            while keep_doing:
                try:
                    frame, value = self.keyframes[1]
                    if frame < self.clip_in:
                        self.keyframes.pop(1)
                    else:
                        keep_doing = False 
                except:
                    keep_doing = False
        elif data == "zero_next":
            frame_zero, frame_zero_value = self.keyframes[0]
            frame, value = self.keyframes[1]
            self.keyframes.pop(0)
            self.keyframes.insert(0, (frame_zero, value))
            self.update_property_value()
        elif data == "delete_all_after":
            delete_done = False
            for i in range(0, len(self.keyframes)):
                frame, value = self.keyframes[i]
                if frame > self.clip_in + self.clip_length:
                    self.keyframes.pop(i)
                    popped = True
                    while popped:
                        try:
                            self.keyframes.pop(i)
                        except:
                            popped = False
                    delete_done = True
                if delete_done:
                    break
        elif data == "edit_brightness":
            init_tool_for_clip(edit_data["clip"] , edit_data["track"], BRIGHTNESS_KF_EDIT)
        elif data == "edit_volume":
            init_tool_for_clip(edit_data["clip"] , edit_data["track"], VOLUME_KF_EDIT)
        elif data == "exit":
            _set_no_clip_edit_data()
        elif data == "playhead_follows":
            global _playhead_follow_kf
            _playhead_follow_kf = widget.get_active()
            
            
        updater.repaint_tline()
        
    def _get_menu_item(self, text, callback, data):
        item = Gtk.MenuItem(text)
        item.connect("activate", callback, data)
        item.show()
        return item

    # ------------------------------------------------------ original parent editor stuff
    def clip_editor_frame_changed(self, clip_frame):
        self.seek_tline_frame(clip_frame)

    def seek_tline_frame(self, clip_frame):
        PLAYER().seek_frame(self.clip_tline_pos + clip_frame - self.clip_in)
        
    def update_slider_value_display(self, frame):
        # This is called after frame changed or mouse release to update
        # slider value without causing 'changed' signal to update keyframes.
        """
        if self.editable_property.value_changed_ID != DISCONNECTED_SIGNAL_HANDLER:
            self.slider.get_adjustment().handler_block(self.editable_property.value_changed_ID)

        new_value = _get_frame_value(frame, self.clip_editor.keyframes)
        self.editable_property.adjustment.set_value(new_value)
        if self.editable_property.value_changed_ID != DISCONNECTED_SIGNAL_HANDLER:
            self.slider.get_adjustment().handler_unblock(self.editable_property.value_changed_ID)
        """

    def active_keyframe_changed(self):
        pass
        """
        frame = self.clip_editor.current_clip_frame
        keyframes = self.clip_editor.keyframes
        value = _get_frame_value(frame, keyframes)
        self.slider.set_value(value)
        self.buttons_row.set_frame(frame)
        self.seek_tline_frame(frame)
        self.buttons_row.set_kf_info(self.clip_editor.get_kf_info())
        """
    
    def update_property_value(self):
        edit_data["editable_property"].write_out_keyframes(self.keyframes)
        
    def keyframe_dragged(self, active_kf, frame):
        pass
