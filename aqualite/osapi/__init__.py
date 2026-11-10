"""Everything that talks to the operating system, behind one small interface.

    from . import osapi
    osapi.paste(text, cfg)        # Windows: winapi.py; macOS: mac.py (PyObjC); elsewhere: other.py (does nothing)

The module for this system is imported the first time a name is used, so importing osapi is free and Windows
never imports PyObjC (nor macOS comtypes). other.py lists the whole interface; in short:

  process      prepare_process, tk_ready, activate_app, single_instance, ask_running_instance_to_open,
               watch_open_requests, wait_for_exit, show_message, open_path, open_folder, play_sound,
               startup_enabled, set_startup, permission_problems, open_permission_settings, close_with_us
  keyboard     KeyboardHook(handler(vk, down) -> swallow?), tap_key, type_text, select_left, press_enter,
               undo_insert, release_keys, send_mask, wait_modifiers_released
  focused app  foreground() -> (name, title, pid), foreground_window(), process_elevated, self_elevated
  clipboard    paste(text, cfg, target, saved, queued) -> {"status": ...}, copy_selection, set_text, get_text,
               snapshot, restore, sequence
  text boxes   text_before_caret(n) -> (text, exact), selected_text, is_password_box, text_reader(), read_window
  screen       window_handle, dpi_scale, work_area_at_cursor, display_timing, fine_timer, Overlay (Flow bar
               window), Frost (blur, Windows 10 only), frost_available, frost_supported, title_bar
  theme        apps_light_theme, transparency_on, animations_on, watch_theme
  constants    OS_NAME, PASTE_KEYS, CAN_RELEASE_KEYS (here: NAME, IS_WIN, IS_MAC, SUPPORTED)

Adding something: put it in other.py, win.py and mac.py (the self-test checks all three have the same names).
"""
import importlib
import sys

if sys.platform == "win32":
    NAME = "win"
elif sys.platform == "darwin":
    NAME = "mac"
else:
    NAME = "other"

IS_WIN, IS_MAC = NAME == "win", NAME == "mac"
SUPPORTED = NAME != "other"   # can type into other apps, read their text boxes, listen for global shortcuts

_impl = None


def impl():
    """The module for this system (win, mac or other)."""
    global _impl
    if _impl is None:
        _impl = importlib.import_module("." + NAME, __name__)
    return _impl


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(impl(), name)
