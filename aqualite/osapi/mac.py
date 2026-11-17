"""macOS: the osapi interface with PyObjC (Quartz event taps, NSPasteboard, the Accessibility API, AppKit).

STATUS: written without a Mac to run it on. Nothing in this file has been run on macOS yet. Each section says
UNTESTED and what to try; docs/MAC.md lists the same checks for a tester. The pure helpers (key-code table,
modifier decoding, the LaunchAgent file, coordinate conversion) are covered by the self-test on any system.

Needs: pyobjc-framework-Quartz, pyobjc-framework-Cocoa, pyobjc-framework-ApplicationServices (requirements-mac.txt).
Permissions (System Settings > Privacy & Security), all granted to the app that runs Aqua Lite (Terminal, the
Python launcher, or Aqua Lite.app):
  - Accessibility: typing and pasting into other apps, reading the text box (and the active keyboard tap)
  - Input Monitoring: hearing the push-to-talk shortcut while other apps are in front
  - Microphone: asked by macOS the first time recording starts
"""
import contextlib
import logging
import os
import plistlib
import socket
import subprocess
import sys
import threading
import time

from .. import textproc
from . import common

log = logging.getLogger("aqualite")

OS_NAME = "macOS"
PASTE_KEYS = "Cmd+V"
CAN_RELEASE_KEYS = False   # a Mac can't be told a held key is up; typed keys carry their own (empty) modifiers
MAGIC = 0x464C4F57         # kCGEventSourceUserData on keys we post, so our own tap ignores them

try:   # PyObjC: only ever imported on a Mac (osapi picks this file only when sys.platform == "darwin")
    import AppKit
    import ApplicationServices as AX
    import Foundation
    import Quartz
    from CoreFoundation import (CFMachPortCreateRunLoopSource, CFRangeMake, CFRunLoopAddSource, CFRunLoopGetCurrent,
                                CFRunLoopRun, CFRunLoopStop, kCFRunLoopCommonModes)
    OBJC_ERROR = None
except Exception as e:   # not installed (yet): every piece that needs it reports this in plain words
    AppKit = AX = Foundation = Quartz = None
    OBJC_ERROR = f"PyObjC isn't installed ({e}); run install-mac.sh again"


def _need():
    if OBJC_ERROR:
        raise OSError(OBJC_ERROR)


# ------------------------------------------------------------------ key codes (pure; self-tested anywhere)
# Mac virtual key code -> the Windows VK code hotkeys.py works with. Command = Win, Option = Alt, Fn = 0x100.
FN_VK = 0x100
MAC_TO_VK = {
    0: 0x41, 11: 0x42, 8: 0x43, 2: 0x44, 14: 0x45, 3: 0x46, 5: 0x47, 4: 0x48, 34: 0x49, 38: 0x4A, 40: 0x4B,
    37: 0x4C, 46: 0x4D, 45: 0x4E, 31: 0x4F, 35: 0x50, 12: 0x51, 15: 0x52, 1: 0x53, 17: 0x54, 32: 0x55, 9: 0x56,
    13: 0x57, 7: 0x58, 16: 0x59, 6: 0x5A,                                                      # A..Z
    29: 0x30, 18: 0x31, 19: 0x32, 20: 0x33, 21: 0x34, 23: 0x35, 22: 0x36, 26: 0x37, 28: 0x38, 25: 0x39,  # 0..9
    36: 0x0D, 76: 0x0D, 48: 0x09, 49: 0x20, 50: 0xC0, 51: 0x08, 53: 0x1B, 117: 0x2E,
    115: 0x24, 119: 0x23, 116: 0x21, 121: 0x22, 123: 0x25, 126: 0x26, 124: 0x27, 125: 0x28,
    27: 0xBD, 24: 0xBB, 33: 0xDB, 30: 0xDD, 42: 0xDC, 41: 0xBA, 39: 0xDE, 43: 0xBC, 47: 0xBE, 44: 0xBF,
    55: 0x5B, 54: 0x5C, 56: 0xA0, 60: 0xA1, 58: 0xA4, 61: 0xA5, 59: 0xA2, 62: 0xA3, 57: 0x14, 63: FN_VK,
    122: 0x70, 120: 0x71, 99: 0x72, 118: 0x73, 96: 0x74, 97: 0x75, 98: 0x76, 100: 0x77, 101: 0x78, 109: 0x79,
    103: 0x7A, 111: 0x7B, 105: 0x7C, 107: 0x7D, 113: 0x7E, 106: 0x7F, 64: 0x80, 79: 0x81, 80: 0x82, 90: 0x83,
}
# modifier key code -> its own bit in the event flags (left and right keys have separate bits)
MODIFIER_BITS = {59: 0x1, 56: 0x2, 60: 0x4, 55: 0x8, 54: 0x10, 58: 0x20, 61: 0x40, 62: 0x2000, 63: 0x800000}
CAPS_LOCK = 57
# names used by the app (winapi's VK names) -> Mac key codes for posting
KEYCODE = {"enter": 36, "backspace": 51, "left": 123, "right": 124, "delete": 117, "v": 9, "c": 8, "z": 6,
           "shift": 56, "cmd": 55, "ctrl": 59, "alt": 58,
           # the rest are for voice commands ("new tab", "scroll down")
           "tab": 48, "esc": 53, "space": 49, "pageup": 116, "pagedown": 121, "home": 115, "end": 119, "up": 126,
           "down": 125, "=": 24, "-": 27, "[": 33, "]": 30, "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "x": 7,
           "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
           "j": 38, "k": 40, "n": 45, "m": 46}
MAC_SHORTCUTS = {   # Windows shortcut -> the Mac's own (already in Mac names: cmd, ctrl, alt = Option)
    "alt+left": "cmd+[", "alt+right": "cmd+]", "ctrl+y": "cmd+shift+z", "ctrl+tab": "ctrl+tab",
    "ctrl+shift+tab": "ctrl+shift+tab", "home": "cmd+up", "end": "cmd+down",
}
FLAG_SHIFT, FLAG_CTRL, FLAG_ALT, FLAG_CMD, FLAG_FN = 0x20000, 0x40000, 0x80000, 0x100000, 0x800000


def vk_for(keycode):
    """The Windows VK code for a Mac key code. Keys without one get a code of their own above 0x1000, so they
    still count as 'some other key' (which cancels a recording, as on Windows)."""
    return MAC_TO_VK.get(keycode, 0x1000 + keycode)


def modifier_down(keycode, flags):
    """For a flags-changed event: True if the modifier `keycode` is now down, False if up, None if it isn't one
    we know (caps lock is handled by the caller: it toggles)."""
    bit = MODIFIER_BITS.get(keycode)
    if bit is None:
        return None
    return bool(flags & bit)


# ------------------------------------------------------------------ keyboard tap               UNTESTED
class KeyboardHook(threading.Thread):
    """A Quartz event tap on its own thread with its own run loop. handler(vk, is_down) -> swallow?
    Ordinary keys can be swallowed (the space that starts hands-free never reaches the app). Modifier keys
    (Fn, Ctrl, Option, Cmd, Shift) always pass through: swallowing their change would leave the Mac thinking a
    key is still held. Needs Accessibility (an active tap) and, on macOS 10.15+, Input Monitoring.
    UNTESTED: hold Fn and talk in TextEdit; Fn+Space for hands-free; Esc cancels."""

    def __init__(self, handler):
        super().__init__(daemon=True, name="keyboard-hook")
        self.handler = handler
        self.ok = threading.Event()
        self.error = None
        self.tap = self.loop = None

    def run(self):
        try:
            _need()
            Q = Quartz
            mask = (Q.CGEventMaskBit(Q.kCGEventKeyDown) | Q.CGEventMaskBit(Q.kCGEventKeyUp)
                    | Q.CGEventMaskBit(Q.kCGEventFlagsChanged))
            self.tap = Q.CGEventTapCreate(Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionDefault,
                                          mask, self._cb, None)
            if not self.tap:
                self.error = ("macOS didn't allow the shortcut listener: switch on Aqua Lite (or Terminal) in System "
                              "Settings > Privacy & Security > Accessibility and Input Monitoring, then restart it")
                self.ok.set()
                return
            source = CFMachPortCreateRunLoopSource(None, self.tap, 0)
            self.loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self.loop, source, kCFRunLoopCommonModes)
            Q.CGEventTapEnable(self.tap, True)
            self.ok.set()
            CFRunLoopRun()
        except Exception as e:
            self.error = f"shortcut listener failed: {e}"
            self.ok.set()

    def _cb(self, _proxy, etype, event, _refcon):
        Q = Quartz
        try:
            if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
                Q.CGEventTapEnable(self.tap, True)   # macOS switches a slow tap off: switch it straight back on
                return event
            if Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == MAGIC:
                return event   # one of ours
            code = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
            vk = vk_for(code)
            if etype == Q.kCGEventFlagsChanged:
                if code == CAPS_LOCK:
                    self.handler(vk, True)
                    self.handler(vk, False)
                    return event
                down = modifier_down(code, Q.CGEventGetFlags(event))
                if down is not None:
                    self.handler(vk, down)
                return event   # never swallow a modifier change
            if self.handler(vk, etype == Q.kCGEventKeyDown):
                return None
        except Exception as e:   # never let an exception break the user's keyboard
            print("hook error:", e, file=sys.stderr)
        return event

    def stop(self):
        if self.loop is not None:
            CFRunLoopStop(self.loop)


# ------------------------------------------------------------------ posting keys                UNTESTED
_source = None


def _src():
    global _source
    if _source is None:
        # a private source: our keys don't pick up the modifiers the user is holding (Fn, Ctrl+Option...)
        _source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStatePrivate)
    return _source


def _key_event(keycode, down, flags=0):
    ev = Quartz.CGEventCreateKeyboardEvent(_src(), keycode, down)
    Quartz.CGEventSetFlags(ev, flags)
    Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGEventSourceUserData, MAGIC)
    return ev


def _post(ev):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _combo(key, flags, mod_keys):
    """Hold modifier keys, tap `key`, let go (Wispr's timing: downs, 50 ms, ups)."""
    if not trusted():
        return False
    held = 0
    for name in mod_keys:
        held |= {"cmd": FLAG_CMD, "shift": FLAG_SHIFT, "ctrl": FLAG_CTRL, "alt": FLAG_ALT}[name]
        _post(_key_event(KEYCODE[name], True, held))
    _post(_key_event(KEYCODE[key], True, flags))
    time.sleep(0.05)
    _post(_key_event(KEYCODE[key], False, flags))
    for name in reversed(mod_keys):
        held &= ~{"cmd": FLAG_CMD, "shift": FLAG_SHIFT, "ctrl": FLAG_CTRL, "alt": FLAG_ALT}[name]
        _post(_key_event(KEYCODE[name], False, held))
    return True


def send_combo(names):
    """Windows-style names ('ctrl', 'v') -> the Mac shortcut (Cmd+V). Shift+Insert has no Mac meaning: Cmd+V."""
    names = tuple(names)
    key = names[-1] if names[-1] in ("v", "c", "z") else "v"
    return _combo(key, FLAG_CMD, ("cmd",))


def tap_key(name, times=1):
    """Press and release one key `times` times (in batches, with a breath between them)."""
    _need()
    code = KEYCODE[name]
    flags = FLAG_FN if name in ("left", "right", "delete") else 0   # what the real arrow / forward delete keys send
    for i in range(times):
        _post(_key_event(code, True, flags))
        _post(_key_event(code, False, flags))
        if i % 40 == 39:
            time.sleep(0.01)
    time.sleep(0.01)


def type_text(text):
    """Type text as Unicode (no clipboard, any keyboard layout), a few characters per key event.
    Returns False if macOS won't let us (no Accessibility permission)."""
    _need()
    if not trusted():
        return False
    chunk, size = [], 0
    pieces = []
    for ch in text:
        n = common.utf16_len(ch)
        if size + n > 16:   # macOS takes up to 20 UTF-16 units per event; stay under it
            pieces.append("".join(chunk))
            chunk, size = [], 0
        chunk.append(ch)
        size += n
    if chunk:
        pieces.append("".join(chunk))
    for piece in pieces:
        n = common.utf16_len(piece)
        for down in (True, False):
            ev = _key_event(0, down, 0)
            Quartz.CGEventKeyboardSetUnicodeString(ev, n, piece)
            _post(ev)
        time.sleep(0.002)
    return True


def select_left(count):
    """Shift+Left `count` times: selects that many characters before the cursor."""
    if count <= 0:
        return True
    _need()
    _post(_key_event(KEYCODE["shift"], True, FLAG_SHIFT))
    try:
        for i in range(count):
            _post(_key_event(KEYCODE["left"], True, FLAG_SHIFT | FLAG_FN))
            _post(_key_event(KEYCODE["left"], False, FLAG_SHIFT | FLAG_FN))
            if i % 40 == 39:
                time.sleep(0.01)
    finally:
        _post(_key_event(KEYCODE["shift"], False, 0))
    return True


def release_keys(vks):
    """Nothing to do: the keys we type carry no modifiers of their own (see _src)."""


def send_mask():
    """Windows-only (stops the Start menu opening); nothing on a Mac."""


def press_enter():
    wait_modifiers_released()
    tap_key("enter")


def installed_apps():
    """UNTESTED: the apps in the Applications folders: {name: path}."""
    apps = {}
    for folder in ("/Applications", "/System/Applications", "/System/Applications/Utilities",
                   "/Applications/Utilities", os.path.expanduser("~/Applications")):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            if n.endswith(".app"):
                apps.setdefault(n[:-4], os.path.join(folder, n))
    return apps


def launch_app(app_id):
    subprocess.Popen(["open", "-a", app_id])
    return True


def press_shortcut(spec):
    """UNTESTED: a Windows shortcut ('ctrl+t') -> the Mac's (Cmd+T); Ctrl becomes Cmd unless MAC_SHORTCUTS says."""
    spec = spec.lower()
    mac = MAC_SHORTCUTS.get(spec) or spec.replace("ctrl", "cmd").replace("win", "ctrl")
    *mods, key = mac.split("+")
    if key not in KEYCODE or any(m not in ("cmd", "ctrl", "alt", "shift") for m in mods):
        return False
    wait_modifiers_released()
    held = 0
    for m in mods:
        held |= {"cmd": FLAG_CMD, "shift": FLAG_SHIFT, "ctrl": FLAG_CTRL, "alt": FLAG_ALT}[m]
    nav = key in ("left", "right", "up", "down", "pageup", "pagedown", "home", "end", "delete")
    return _combo(key, held | (FLAG_FN if nav else 0), tuple(mods))


def undo_insert(text, proc):
    """Remove text we just inserted: Cmd+Z, or backspaces in terminals."""
    wait_modifiers_released()
    if proc.lower() in textproc.TERMINALS:
        tap_key("backspace", len(text.replace("\r\n", "\n")))
        return "backspace"
    send_combo(("ctrl", "z"))
    return "cmd+z"


def modifiers_held():
    if Quartz is None:
        return 0
    flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState)
    return flags & (FLAG_SHIFT | FLAG_CTRL | FLAG_ALT | FLAG_CMD | FLAG_FN)


def wait_modifiers_released(timeout=2.0):
    """Wait until the user lets go of Fn/Ctrl/Option/Cmd/Shift (a Mac can't be told they're up)."""
    end = time.time() + timeout
    while time.time() < end:
        if not modifiers_held():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ the focused app             UNTESTED
# bundle id -> the name the app's rules use (textproc / context lists were written with Windows process names)
BUNDLE_NAMES = {
    "com.google.Chrome": "chrome", "com.microsoft.edgemac": "msedge", "org.mozilla.firefox": "firefox",
    "com.brave.Browser": "brave", "company.thebrowser.Browser": "arc", "com.vivaldi.Vivaldi": "vivaldi",
    "com.operasoftware.Opera": "opera", "app.zen-browser.zen": "zen", "com.apple.Safari": "safari",
    "com.microsoft.VSCode": "code", "com.todesktop.230313mt0tgm5": "cursor", "com.exafunction.windsurf": "windsurf",
    "dev.zed.Zed": "zed", "com.sublimetext.4": "sublime_text", "com.jetbrains.pycharm": "pycharm64",
    "com.apple.Terminal": "terminal", "com.googlecode.iterm2": "iterm2", "dev.warp.Warp-Stable": "warp",
    "com.mitchellh.ghostty": "ghostty", "net.kovidgoyal.kitty": "kitty", "io.alacritty": "alacritty",
    "com.github.wez.wezterm": "wezterm-gui",
    "com.apple.mail": "applemail", "com.microsoft.Outlook": "outlook", "com.microsoft.Word": "winword",
    "com.tinyspeck.slackmacgap": "slack", "com.microsoft.teams2": "teams", "us.zoom.xos": "zoom",
    "net.whatsapp.WhatsApp": "whatsapp", "ru.keepcoder.Telegram": "telegram", "org.whispersystems.signal-desktop":
    "signal", "com.hnc.Discord": "discord", "com.apple.MobileSMS": "imessage", "notion.id": "notion",
    "com.linear": "linear", "com.1password.1password": "1password", "com.bitwarden.desktop": "bitwarden",
    "com.apple.keychainaccess": "keychain access",
}
_manual_ax = set()   # Electron apps told to switch their accessibility tree on


def trusted(prompt=False):
    """Accessibility permission granted to whatever runs Aqua Lite."""
    if AX is None:
        return False
    try:
        if prompt:
            return bool(AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True}))
        return bool(AX.AXIsProcessTrusted())
    except Exception:
        return False


def _ax(el, attr):
    err, value = AX.AXUIElementCopyAttributeValue(el, attr, None)
    return value if err == 0 else None


_system = None


def _system_wide():
    global _system
    if _system is None:
        _system = AX.AXUIElementCreateSystemWide()
        AX.AXUIElementSetMessagingTimeout(_system, 0.5)   # a hung app mustn't hang us
    return _system


def _focused_pid():
    app = _ax(_system_wide(), "AXFocusedApplication")
    if app is not None:
        err, pid = AX.AXUIElementGetPid(app, None)
        if err == 0:
            return pid, app
    front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return (front.processIdentifier() if front else 0), None


def app_name(bundle, exe, localized):
    """The name the rules use for an app: a known bundle id, else the program's file name."""
    if bundle in BUNDLE_NAMES:
        return BUNDLE_NAMES[bundle]
    return (exe or localized or "unknown").strip()


def foreground():
    """(app name, focused window title, pid)."""
    _need()
    pid, app_el = _focused_pid()
    ra = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid) if pid else None
    bundle = str(ra.bundleIdentifier() or "") if ra else ""
    exe = str(ra.executableURL().lastPathComponent()) if ra and ra.executableURL() else ""
    name = app_name(bundle, exe, str(ra.localizedName() or "") if ra else "")
    title = ""
    try:
        win = _ax(app_el or AX.AXUIElementCreateApplication(pid), "AXFocusedWindow") if pid else None
        title = str(_ax(win, "AXTitle") or "") if win is not None else ""
    except Exception:
        pass
    return name, title, pid


def foreground_window():
    """The app in front (its pid): compare two of these to see if the user switched."""
    if AX is None:
        return 0
    try:
        return _focused_pid()[0]
    except Exception:
        return 0


def self_elevated():
    return False


def process_elevated(pid):
    return False   # macOS has no admin windows that block typed keys


# ------------------------------------------------------------------ clipboard                   UNTESTED
MAX_SNAPSHOT = 64 * 1024 * 1024
# nspasteboard.org markers: clipboard managers (Maccy, Paste, Raycast...) leave these out of their history
PRIVATE_TYPES = ("org.nspasteboard.TransientType", "org.nspasteboard.ConcealedType",
                 "org.nspasteboard.AutoGeneratedType")


def _pb():
    return AppKit.NSPasteboard.generalPasteboard()


def sequence():
    return int(_pb().changeCount()) if AppKit else 0


def snapshot():
    """Every item and type on the clipboard, as bytes, to put back after the paste."""
    if AppKit is None:
        return None
    items, total = [], 0
    for item in _pb().pasteboardItems() or []:
        kept = []
        for t in item.types() or []:
            data = item.dataForType_(t)
            if data is None:
                continue
            size = data.length()
            if total + size > MAX_SNAPSHOT:
                continue
            kept.append((str(t), bytes(data)))
            total += size
        if kept:
            items.append(kept)
    return items


def restore(items):
    if items is None or AppKit is None:
        return False
    pb = _pb()
    pb.clearContents()
    objs = []
    for kept in items:
        it = AppKit.NSPasteboardItem.alloc().init()
        for t, data in kept:
            it.setData_forType_(Foundation.NSData.dataWithBytes_length_(data, len(data)), t)
        objs.append(it)
    if objs:
        pb.writeObjects_(objs)
    return True


def set_text(text, private=True):
    _need()
    pb = _pb()
    pb.clearContents()
    pb.setString_forType_(text.replace("\r\n", "\n"), AppKit.NSPasteboardTypeString)
    if private:
        for t in PRIVATE_TYPES:
            pb.setData_forType_(Foundation.NSData.data(), t)
    return sequence()


def get_text():
    if AppKit is None:
        return ""
    s = _pb().stringForType_(AppKit.NSPasteboardTypeString)
    return str(s).replace("\r\n", "\n") if s is not None else ""


def paste(text, cfg, target=None, saved=None, queued=0):
    """Insert text into the focused app: clipboard + Cmd+V, then put the old clipboard back once the app has
    pasted (same rules as Windows). Without Accessibility the text is left on the clipboard (status 'blocked')."""
    proc, _title, _pid = target or foreground()
    delay = textproc.restore_delay(proc)
    wait_modifiers_released()
    restore_on = cfg.get("restore_clipboard", True)
    if saved is None and restore_on:
        saved = snapshot()
    seq = set_text(text)
    if not send_combo(("ctrl", "v")):
        return {"proc": proc, "keys": "none", "delay": 0, "status": "blocked"}
    time.sleep(0.05)
    if restore_on and saved is not None:
        budget = common.restore_budget(delay, queued, len(text))
        threading.Thread(target=common.restore_when_pasted, args=(saved, seq, text, delay, budget, sequence, restore),
                         daemon=True, name="clipboard-restore").start()
    return {"proc": proc, "keys": "cmd+v", "delay": delay, "status": "ok"}


def copy_selection(timeout=0.5):
    """Cmd+C the current selection. Returns (selected_text, clipboard_snapshot_to_restore)."""
    wait_modifiers_released()
    saved = snapshot()
    before = sequence()
    send_combo(("ctrl", "c"))
    end = time.time() + timeout
    while time.time() < end and sequence() == before:
        time.sleep(0.02)
    text = get_text() if sequence() != before else ""
    return text, saved


# ------------------------------------------------------------------ Accessibility: text boxes   UNTESTED
def _focused_element():
    """The focused element (a text box, hopefully), or None. Electron apps (Slack, Discord, VS Code...) only build
    their accessibility tree when asked: ask once per app."""
    _need()
    pid, app_el = _focused_pid()
    if app_el is not None and pid and pid not in _manual_ax:
        _manual_ax.add(pid)
        try:
            AX.AXUIElementSetAttributeValue(app_el, "AXManualAccessibility", True)
        except Exception:
            pass
    return _ax(_system_wide(), "AXFocusedUIElement")


def _is_secure(el):
    return str(_ax(el, "AXSubrole") or "") == "AXSecureTextField" or str(_ax(el, "AXRole") or "") == "AXSecureTextField"


def _range_type():
    return getattr(AX, "kAXValueCFRangeType", getattr(AX, "kAXValueTypeCFRange", 4))


def _caret(el):
    """(caret position, selection length) in UTF-16 units, or None."""
    rng = _ax(el, "AXSelectedTextRange")
    if rng is None:
        return None
    ok, r = AX.AXValueGetValue(rng, _range_type(), None)
    if not ok:
        return None
    return int(r.location), int(r.length)


def text_before_caret(n):
    """Up to `n` characters right before the cursor in the focused box. (text, exact) like Windows: exact=False when
    only the whole box was readable (cursor assumed at the end); (None, False) if unreadable or a password box."""
    try:
        el = _focused_element()
        if el is None or _is_secure(el):
            return None, False
        caret = _caret(el)
        if caret is not None:
            loc = caret[0]
            start = max(0, loc - (n + 64))
            param = AX.AXValueCreate(_range_type(), CFRangeMake(start, loc - start))
            err, text = AX.AXUIElementCopyParameterizedAttributeValue(el, "AXStringForRange", param, None)
            if err == 0 and text is not None:
                return str(text).replace("\r\n", "\n"), True
            value = _ax(el, "AXValue")
            if isinstance(value, str):
                return common.utf16_slice(value, start, loc).replace("\r\n", "\n"), True
        value = _ax(el, "AXValue")
        if isinstance(value, str):
            return value.replace("\r\n", "\n"), False
    except Exception as e:
        log.info("instant text: couldn't read the box: %s", e)
    return None, False


def selected_text():
    try:
        el = _focused_element()
        if el is None or _is_secure(el):
            return None
        caret = _caret(el)
        if caret is not None and caret[1] <= 0:
            return None
        text = _ax(el, "AXSelectedText")
        return str(text) if text is not None else None
    except Exception as e:
        log.info("instant text: couldn't read the selection: %s", e)
        return None


def is_password_box():
    try:
        el = _focused_element()
        return el is not None and _is_secure(el)
    except Exception:
        return False


def _focused_value():
    try:
        el = _focused_element()
        if el is None or _is_secure(el):
            return None
        value = _ax(el, "AXValue")
        return str(value).replace("\r\n", "\n")[:200000] if isinstance(value, str) else None
    except Exception as e:
        log.debug("learn: read failed: %s", e)
        return None


@contextlib.contextmanager
def text_reader():
    """For a thread that reads the focused box many times: yields read() -> its whole text, or None."""
    _need()
    if not trusted():
        raise OSError("Accessibility isn't switched on for Aqua Lite")
    yield _focused_value


TEXT_ROLES = ("AXStaticText", "AXTextArea", "AXTextField", "AXCell", "AXHeading", "AXLink")


def read_window(window, max_elements, budget=1.0, max_nodes=6000):
    """Screen context: the text shown in the focused window of app `window` (a pid), in screen order, plus the
    focused box's text. Walks the accessibility tree for at most `budget` seconds."""
    _need()
    if not trusted():
        raise OSError("Accessibility isn't switched on for Aqua Lite")
    app = AX.AXUIElementCreateApplication(window)
    AX.AXUIElementSetMessagingTimeout(app, 0.3)
    root = _ax(app, "AXFocusedWindow")
    names, seen, stack, t0 = [], 0, [root] if root is not None else [], time.monotonic()
    while stack and seen < max_nodes and time.monotonic() - t0 < budget:
        el = stack.pop()
        seen += 1
        role = str(_ax(el, "AXRole") or "")
        if role == "AXSecureTextField":
            continue
        if role in TEXT_ROLES:
            for attr in ("AXValue", "AXTitle", "AXDescription"):
                v = _ax(el, attr)
                if isinstance(v, str) and v.strip():
                    names.append(v)
                    break
        kids = _ax(el, "AXChildren") or []
        stack.extend(reversed(list(kids)))   # depth first, in order
    return names[-max_elements:], _focused_value() or "", seen


# ------------------------------------------------------------------ the Flow bar window         UNTESTED
_scale_cache = None


def _screens():
    return AppKit.NSScreen.screens()


def _scale():
    """Pixels per point of the main display (2.0 on Retina). The bar is drawn at this size and shown at points."""
    global _scale_cache
    if _scale_cache is None:
        try:
            _scale_cache = float(_screens()[0].backingScaleFactor())
        except Exception:
            _scale_cache = 1.0
    return _scale_cache


def to_cocoa(x, y, w, h, scale, primary_h):
    """Top-left pixel position (as the app uses on Windows) -> Cocoa's bottom-left point origin. Pure."""
    return x / scale, primary_h - (y + h) / scale


def from_cocoa_rect(rx, ry, rw, rh, scale, primary_h):
    """A Cocoa rectangle (points, bottom-left origin) -> (left, top, right, bottom) in pixels, top-left origin."""
    top = primary_h - (ry + rh)
    return (round(rx * scale), round(top * scale), round((rx + rw) * scale), round((top + rh) * scale))


def window_handle(tk_window):
    return tk_window.winfo_id()


def dpi_scale(tk_window):
    """Draw the bar at the display's pixel density (only when our own window can show it; Tk's canvas fallback
    works in points)."""
    return _scale() if OBJC_ERROR is None else 1.0


def work_area_at_cursor():
    """The usable part (no menu bar, no Dock) of the display under the mouse, in pixels from the top-left."""
    _need()
    mouse = AppKit.NSEvent.mouseLocation()
    screens = _screens()
    primary_h = screens[0].frame().size.height
    target = screens[0]
    for s in screens:
        f = s.frame()
        if f.origin.x <= mouse.x < f.origin.x + f.size.width and f.origin.y <= mouse.y < f.origin.y + f.size.height:
            target = s
            break
    v = target.visibleFrame()
    return from_cocoa_rect(v.origin.x, v.origin.y, v.size.width, v.size.height, _scale(), primary_h)


def display_timing():
    """(seconds per frame, None): macOS gives no vblank time to Python, so frames are paced by a steady clock."""
    fps = 60.0
    try:
        fps = float(_screens()[0].maximumFramesPerSecond()) or 60.0   # macOS 12+ (ProMotion: 120)
    except Exception:
        pass
    return 1.0 / fps, None


def fine_timer(on):
    pass


_bar_view_class = None
_bar_click = [None]


def _view_class():
    """A layer-backed view that shows each frame and reports clicks (defined once: Objective-C classes can't be
    defined twice)."""
    global _bar_view_class
    if _bar_view_class is None:
        class AquaLiteBarView(AppKit.NSView):
            def acceptsFirstMouse_(self, _event):
                return True

            def mouseDown_(self, _event):
                cb = _bar_click[0]
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        log.exception("flow bar click")
        _bar_view_class = AquaLiteBarView
    return _bar_view_class


class Overlay:
    """The Flow bar's see-through window: a borderless, non-activating NSPanel above every app and on every Space
    (also over full-screen apps), showing each premultiplied BGRA frame as its layer's picture. The Tk window it
    was made for is hidden. Clicks on the bar call on_click; while the bar is hidden it lets clicks through.
    UNTESTED: the bar shows at the bottom middle, edges are soft (not boxy), it never takes focus from the app
    you're typing in, a click on the idle bar starts hands-free, and it stays sharp on a Retina display."""

    def __init__(self, tk_window, w, h, bgra, on_click=None):
        _need()
        self.ok = False
        tk_window.withdraw()
        self.w, self.h, self.scale = w, h, _scale()
        self.pw, self.ph = w / self.scale, h / self.scale
        _bar_click[0] = on_click
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        rect = Foundation.NSMakeRect(-20000, -20000, self.pw, self.ph)
        p = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False)
        p.setOpaque_(False)
        p.setBackgroundColor_(AppKit.NSColor.clearColor())
        p.setHasShadow_(False)   # the bar draws its own soft shadow
        p.setLevel_(AppKit.NSStatusWindowLevel)
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorStationary
                                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        p.setHidesOnDeactivate_(False)
        p.setFloatingPanel_(True)
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setReleasedWhenClosed_(False)
        view = _view_class().alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, self.pw, self.ph))
        view.setWantsLayer_(True)
        self.layer = view.layer()
        self.layer.setContentsScale_(self.scale)
        self.layer.setContentsGravity_("resize")
        p.setContentView_(view)
        self.panel, self.view = p, view
        self.space = Quartz.CGColorSpaceCreateDeviceRGB()
        self.pos = None
        self.clickable = None
        self.handle = p.windowNumber()
        self._set_image(bgra)
        p.orderFrontRegardless()
        self.ok = True

    def _set_image(self, bgra):
        data = Foundation.NSData.dataWithBytes_length_(bytes(bgra), self.w * self.h * 4)
        provider = Quartz.CGDataProviderCreateWithCFData(data)
        info = Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaPremultipliedFirst   # = BGRA, premultiplied
        img = Quartz.CGImageCreate(self.w, self.h, 8, 32, self.w * 4, self.space, info, provider, None, False,
                                   Quartz.kCGRenderingIntentDefault)
        Quartz.CATransaction.begin()
        Quartz.CATransaction.setDisableActions_(True)   # no implicit cross-fade between frames
        self.layer.setContents_(img)
        Quartz.CATransaction.commit()

    def show(self, x, y, bgra, restack=False, clickable=True):
        self._set_image(bgra)
        if clickable != self.clickable:
            self.panel.setIgnoresMouseEvents_(not clickable)
            self.clickable = clickable
        primary_h = _screens()[0].frame().size.height
        pos = to_cocoa(x, y, self.w, self.h, self.scale, primary_h)
        if pos != self.pos:
            self.panel.setFrameOrigin_(Foundation.NSMakePoint(*pos))
            self.pos = pos
        if restack:
            self.panel.orderFrontRegardless()


Frost = None   # the Windows blur window; on a Mac the glass is drawn solid (an NSVisualEffectView could come later)


def frost_available():
    return False


def frost_supported():
    return False


def title_bar(tk_window, dark, caption, text=None, border=None):
    """Tk windows on a Mac follow the system's light/dark title bar by themselves."""


# ------------------------------------------------------------------ light/dark & accessibility  UNTESTED
def apps_light_theme():
    """System Settings > Appearance: True for Light (and Auto while it's light)."""
    if Foundation is None:
        return True
    style = Foundation.NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
    return str(style or "").lower() != "dark"


def transparency_on():
    """Accessibility > Display > Reduce transparency is off."""
    try:
        return not AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency()
    except Exception:
        return True


def animations_on():
    """Accessibility > Display > Reduce motion is off."""
    try:
        return not AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
    except Exception:
        return True


_observers = []


def watch_theme(callback):
    """Call callback() when the Mac switches light/dark or the Reduce transparency / motion settings change.
    macOS sends notifications, so nothing is polled. Call from the main thread."""
    if OBJC_ERROR:
        return

    def fire(_note):
        try:
            callback()
        except Exception:
            pass
    dist = Foundation.NSDistributedNotificationCenter.defaultCenter()
    _observers.append(dist.addObserverForName_object_queue_usingBlock_(
        "AppleInterfaceThemeChangedNotification", None, None, fire))
    ws = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
    _observers.append(ws.addObserverForName_object_queue_usingBlock_(
        "NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification", None, None, fire))


# ------------------------------------------------------------------ process, start at login     UNTESTED
def prepare_process():
    pass


def tk_ready(root):
    """No Dock icon: Aqua Lite lives in the menu bar, like the tray on Windows."""
    if OBJC_ERROR:
        return
    try:
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception as e:
        log.info("mac: dock icon not hidden: %s", e)


def activate_app():
    """Bring our windows (Settings) in front of the app the user was in."""
    if OBJC_ERROR:
        return
    try:
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


AGENT_LABEL = "com.aqualite.app"


def agent_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", AGENT_LABEL + ".plist")


def launch_args(script_path):
    """How to start Aqua Lite again: the .app bundle when running from one (py2app), else Python + the script."""
    bundle = _bundle()
    if bundle:   # through the app, so macOS gives it the permissions granted to Aqua Lite
        return ["/usr/bin/open", "-a", bundle]
    return [sys.executable, script_path]


def _bundle():
    """The Aqua Lite.app we were started from: a py2app build, or install-mac.sh's launcher (which sets
    AQUALITE_BUNDLE). None when started from a terminal."""
    if getattr(sys, "frozen", None) == "macosx_app":
        return os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
    path = os.environ.get("AQUALITE_BUNDLE", "")
    return path if path.endswith(".app") and os.path.isdir(path) else None


def agent_plist(script_path):
    """The LaunchAgent file that starts Aqua Lite when you log in. Pure (self-tested)."""
    return plistlib.dumps({"Label": AGENT_LABEL, "ProgramArguments": launch_args(script_path), "RunAtLoad": True,
                           "ProcessType": "Interactive", "WorkingDirectory": os.path.dirname(script_path)})


def startup_enabled():
    return os.path.exists(agent_path())


def set_startup(enabled, script_path, icon_path=""):
    path = agent_path()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(agent_plist(script_path))


def _runtime_path(name):
    from .. import config
    p = os.path.join(config.data_dir(), name)
    if len(p) > 100:   # Unix socket paths are limited to about 104 bytes
        p = os.path.join("/tmp", f"aqualite-{os.getuid()}-{name}")
    return p


_lock_file = None


def single_instance():
    import fcntl
    global _lock_file
    _lock_file = open(_runtime_path("running.lock"), "w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def ask_running_instance_to_open():
    """Second launch: tell the running copy to show its Settings window."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(_runtime_path("open.sock"))
            s.sendall(b"open")
        return True
    except OSError:
        return False


def watch_open_requests(callback):
    path = _runtime_path("open.sock")
    try:
        os.unlink(path)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(2)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    if conn.recv(16).startswith(b"open"):
                        callback()
            except OSError:
                return
    threading.Thread(target=loop, daemon=True, name="open-requests").start()


def wait_for_exit(pid, timeout_ms):
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


def show_message(text, title="Aqua Lite"):
    def q(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    subprocess.run(["osascript", "-e", f"display dialog {q(text)} with title {q(title)} buttons {{\"OK\"}}"],
                   check=False)


def open_path(path):
    subprocess.Popen(["open", path])


def open_folder(path):
    subprocess.Popen(["open", path])


def close_with_us(popen):
    """Windows ties the private AI server to us with a job object; here it's stopped when Aqua Lite quits."""


def play_sound(path):
    subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ permissions                  UNTESTED
SETTINGS_URLS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}


def _host_app():
    """What macOS shows in the permission lists: Aqua Lite.app, or the terminal / Python that started us."""
    if _bundle():
        return "Aqua Lite"
    term = os.environ.get("TERM_PROGRAM", "")
    return {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm"}.get(term, term or "Python")


def permission_problems():
    """What macOS hasn't allowed yet: [(kind, title, plain explanation)]. Asks macOS to show its own prompt for
    each missing one the first time."""
    if OBJC_ERROR:
        return [("pyobjc", "Mac support isn't installed", OBJC_ERROR)]
    host = _host_app()
    out = []
    if not trusted(prompt=True):
        out.append(("accessibility", "Accessibility",
                    f"Lets Aqua Lite type your words into other apps and read the text box. Switch on {host} in "
                    "System Settings > Privacy & Security > Accessibility."))
    listen = getattr(Quartz, "CGPreflightListenEventAccess", None)
    if listen is not None and not listen():
        request = getattr(Quartz, "CGRequestListenEventAccess", None)
        if request is not None:
            request()
        out.append(("input", "Input Monitoring",
                    f"Lets Aqua Lite notice when you hold the talk shortcut. Switch on {host} in "
                    "System Settings > Privacy & Security > Input Monitoring, then quit and reopen Aqua Lite."))
    try:
        import AVFoundation
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeAudio)
        if status in (1, 2):   # restricted, denied (0 = not asked yet: macOS asks when recording starts)
            out.append(("microphone", "Microphone",
                        f"Lets Aqua Lite hear you. Switch on {host} in System Settings > Privacy & Security > "
                        "Microphone."))
    except Exception:
        pass
    return out


def open_permission_settings(kind):
    url = SETTINGS_URLS.get(kind)
    if url:
        subprocess.Popen(["open", url])
