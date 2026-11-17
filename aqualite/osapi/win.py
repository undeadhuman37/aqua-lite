"""Windows: the osapi interface on top of winapi.py (keyboard hook, SendInput, clipboard, layered window, blur)
and UI Automation (reading the focused text box and the window on screen). Behaviour is exactly what the app did
before the platform layer existed; this file only gives it the shared names."""
import contextlib
import logging
import os
import sys

from .. import hotkeys, winapi
# the same functions and classes as winapi.py (the app called them there before)
animations_on = winapi.animations_on
apps_light_theme = winapi.apps_light_theme
ask_running_instance_to_open = winapi.ask_running_instance_to_open
close_with_us = winapi.close_with_us
copy_selection = winapi.copy_selection
display_timing = winapi.display_timing
fine_timer = winapi.fine_timer
foreground = winapi.foreground
Frost = winapi.Frost
get_text = winapi.get_text
KeyboardHook = winapi.KeyboardHook
press_enter = winapi.press_enter


def installed_apps():
    """Every app in the Start menu, desktop and Store apps alike: {name: AppID}. Takes about a second."""
    import json
    import subprocess
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                         capture_output=True, timeout=30, creationflags=0x08000000).stdout   # no console window
    items = json.loads(out.decode("utf-8-sig").strip() or "[]")
    items = [items] if isinstance(items, dict) else items
    return {i["Name"]: i["AppID"] for i in items if i.get("Name") and i.get("AppID")}


def launch_app(app_id):
    import subprocess
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id])
    return True


def press_shortcut(spec):
    try:
        vks = [min(g) for g in hotkeys.parse(spec)]   # the plain key of each group: "ctrl" -> VK_CONTROL
    except ValueError:
        return False
    winapi.wait_modifiers_released()
    return winapi.send_combo(vks)


process_elevated = winapi.process_elevated
release_keys = winapi.release_keys
restore = winapi.restore
select_left = winapi.select_left
self_elevated = winapi.self_elevated
send_mask = winapi.send_mask
sequence = winapi.sequence
set_text = winapi.set_text
single_instance = winapi.single_instance
snapshot = winapi.snapshot
tap_key = winapi.tap_key
transparency_on = winapi.transparency_on
type_text = winapi.type_text
undo_insert = winapi.undo_insert
wait_for_exit = winapi.wait_for_exit
wait_modifiers_released = winapi.wait_modifiers_released
watch_open_requests = winapi.watch_open_requests
watch_theme = winapi.watch_theme
work_area_at_cursor = winapi.work_area_at_cursor

log = logging.getLogger("aqualite")

OS_NAME = "Windows"
PASTE_KEYS = "Ctrl+V"
CAN_RELEASE_KEYS = True   # release_keys() really tells the system held keys are up


# ------------------------------------------------------------------ process
def prepare_process():
    """Before the first window: our own taskbar identity (so Windows shows our logo instead of Python's) and
    sharp drawing on high-DPI screens."""
    winapi.set_app_id()
    winapi.set_dpi_aware()


def tk_ready(root):
    pass


def startup_enabled():
    return os.path.exists(winapi.startup_shortcut_path())


def set_startup(enabled, script_path, icon_path=""):
    winapi.set_startup(enabled, script_path, icon_path)


def show_message(text, title="Aqua Lite"):
    winapi.user32.MessageBoxW(None, text, title, 0x40)


def open_path(path):
    os.startfile(path)


def open_folder(path):
    os.startfile(path)


def play_sound(path):
    import winsound
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def activate_app():
    pass


def permission_problems():
    """Windows asks for nothing up front."""
    return []


def open_permission_settings(kind):
    pass


# ------------------------------------------------------------------ typing & the focused app
def paste(text, cfg, target=None, saved=None, queued=0):
    return winapi.paste(text, cfg, target=target, saved=saved, queued=queued)


def foreground_window():
    """Which window has focus right now (compare two of these to see if the user switched)."""
    return winapi.user32.GetForegroundWindow()


# ------------------------------------------------------------------ UI Automation (reading text boxes)
UIA_TEXT, UIA_VALUE = 10014, 10002   # TextPattern, ValuePattern


def uia():
    """(comtypes, UIAutomationClient module, IUIAutomation) on this thread. Call comtypes.CoUninitialize() when
    done. Raises ImportError while comtypes isn't installed yet."""
    if not hasattr(sys, "coinit_flags"):
        sys.coinit_flags = 0  # COINIT_MULTITHREADED: what UI Automation clients should use
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitializeEx(0)
    except OSError:
        pass
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as U
    return comtypes, U, comtypes.client.CreateObject(U.CUIAutomation._reg_clsid_, interface=U.IUIAutomation)


def _uninit(comtypes):
    if comtypes is not None:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


def make_reader(U, ua):
    def read():
        try:
            el = ua.GetFocusedElement()
            if not el or el.CurrentIsPassword:
                return None
            pat = el.GetCurrentPattern(UIA_TEXT)
            if pat:
                doc = pat.QueryInterface(U.IUIAutomationTextPattern).DocumentRange
                return doc.GetText(200000).replace("\r\n", "\n")
            pat = el.GetCurrentPattern(UIA_VALUE)
            if pat:
                return (pat.QueryInterface(U.IUIAutomationValuePattern).CurrentValue or "").replace("\r\n", "\n")
        except Exception as e:
            log.debug("learn: read failed: %s", e)
        return None
    return read


@contextlib.contextmanager
def text_reader():
    """For a thread that reads the focused box many times: yields read() -> its whole text, or None."""
    comtypes, U, ua = uia()
    try:
        yield make_reader(U, ua)
    finally:
        del ua
        _uninit(comtypes)


def text_before_caret(n):
    """Up to `n` characters right before the cursor in the focused box, through UI Automation.
    Returns (text, exact): exact=False when only the whole box text was readable (cursor assumed at the end),
    or (None, False) if it can't be read (or it's a password box)."""
    comtypes = None
    try:
        comtypes, U, ua = uia()
        el = ua.GetFocusedElement()
        if not el or el.CurrentIsPassword:
            return None, False
        pat = el.GetCurrentPattern(UIA_TEXT)
        if pat:
            tp = pat.QueryInterface(U.IUIAutomationTextPattern)
            sel = tp.GetSelection()
            if sel and sel.Length > 0:
                r = sel.GetElement(0).Clone()
                r.MoveEndpointByRange(1, r, 0)            # collapse to the cursor (End -> Start)
                r.MoveEndpointByUnit(0, 0, -(n + 64))     # Start back by characters
                return (r.GetText(-1) or "").replace("\r\n", "\n"), True
        pat = el.GetCurrentPattern(UIA_VALUE)
        if pat:
            value = pat.QueryInterface(U.IUIAutomationValuePattern).CurrentValue or ""
            return value.replace("\r\n", "\n"), False
    except Exception as e:
        log.info("instant text: couldn't read the box: %s", e)
    finally:
        _uninit(comtypes)
    return None, False


def selected_text():
    """The selected text in the focused box (UI Automation), or None if it can't be read."""
    comtypes = None
    try:
        comtypes, U, ua = uia()
        el = ua.GetFocusedElement()
        if not el or el.CurrentIsPassword:
            return None
        pat = el.GetCurrentPattern(UIA_TEXT)
        if not pat:
            return None
        sel = pat.QueryInterface(U.IUIAutomationTextPattern).GetSelection()
        if not sel or sel.Length <= 0:
            return None
        return sel.GetElement(0).GetText(-1) or ""
    except Exception as e:
        log.info("instant text: couldn't read the selection: %s", e)
        return None
    finally:
        _uninit(comtypes)


def is_password_box():
    comtypes = None
    try:
        comtypes, _U, ua = uia()
        el = ua.GetFocusedElement()
        return bool(el and el.CurrentIsPassword)
    except Exception:
        return False
    finally:
        _uninit(comtypes)


UIA_NAME, UIA_TYPE, UIA_OFFSCREEN, UIA_PASSWORD = 30005, 30003, 30022, 30019
UIA_TEXT_CONTROL, UIA_LISTITEM_CONTROL = 50020, 50007


def read_window(window, max_elements):
    """The visible text of a window, for screen context: (list of text pieces in screen order, the focused box's
    text). window: from foreground_window(). Raises ImportError while comtypes isn't installed yet."""
    comtypes = ua = None
    try:
        comtypes, U, ua = uia()
        root = ua.ElementFromHandle(window)
        cr = ua.CreateCacheRequest()
        for prop in (UIA_NAME, UIA_TYPE, UIA_OFFSCREEN, UIA_PASSWORD):
            cr.AddProperty(prop)
        cond = ua.CreateOrCondition(ua.CreatePropertyCondition(UIA_TYPE, UIA_TEXT_CONTROL),
                                    ua.CreatePropertyCondition(UIA_TYPE, UIA_LISTITEM_CONTROL))
        found = root.FindAllBuildCache(4, cond, cr)  # TreeScope_Descendants, one round trip for everything
        n = found.Length if found else 0
        names = []
        for i in range(max(0, n - max_elements), n):
            el = found.GetElement(i)
            try:
                if el.CachedIsOffscreen or el.CachedIsPassword:
                    continue
                names.append(el.CachedName)
            except Exception:
                continue
        draft = make_reader(U, ua)() or ""
        return names, draft, n
    finally:
        ua = None
        _uninit(comtypes)


# ------------------------------------------------------------------ windows on screen
def window_handle(tk_window):
    """The system window behind a Tk window."""
    tk_window.update_idletasks()
    return winapi.user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()


def dpi_scale(tk_window):
    return winapi.window_dpi_scale(window_handle(tk_window))


class Overlay:
    """The Flow bar's see-through window: the Tk window itself, made layered so each frame (premultiplied BGRA)
    is shown with per-pixel transparency. ok=False: layered windows failed and the window was switched to
    colour-key transparency, so the caller draws into its canvas over #ff00fe instead."""
    COLOR_KEY = "#ff00fe"

    def __init__(self, tk_window, w, h, bgra, on_click=None):
        self.w, self.h = w, h
        self.handle = window_handle(tk_window)
        winapi.make_layered(self.handle)
        self.ok = winapi.update_layered(self.handle, -20000, -20000, w, h, bgra)
        if not self.ok:  # fallback: colour-key transparency
            ex = winapi.user32.GetWindowLongPtrW(self.handle, -20)
            winapi.user32.SetWindowLongPtrW(self.handle, -20, ex & ~0x00080000)
            tk_window.attributes("-transparentcolor", self.COLOR_KEY)
            winapi.make_overlay_window(tk_window)

    def show(self, x, y, bgra, restack=False, clickable=True):
        if winapi.user32.IsIconic(self.handle):  # something minimized us (e.g. Win+D): come back quietly
            winapi.user32.ShowWindow(self.handle, 4)
        winapi.update_layered(self.handle, x, y, self.w, self.h, bgra)
        if restack:
            winapi.user32.SetWindowPos(self.handle, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)


def frost_available():
    """Windows can blur behind the bar's rounded shape: Windows 10 with Transparency effects on."""
    return transparency_on() and Frost.shapes_ok()


def frost_supported():
    """This Windows can blur behind a rounded shape at all (Windows 10; not Windows 11)."""
    return Frost.shapes_ok()


def title_bar(tk_window, dark, caption, text=None, border=None):
    """Dark title bar and (Windows 11) a title bar tinted to match the Settings window."""
    hwnd = window_handle(tk_window)
    winapi.dark_title_bar(hwnd, dark)
    winapi.tint_title_bar(hwnd, caption, text, border)
