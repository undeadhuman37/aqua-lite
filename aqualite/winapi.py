"""Windows plumbing: keyboard hook, SendInput, clipboard snapshot/restore, focused-app info.

The paste path copies the rules the teardown proved in Wispr Flow Helper.exe (section 7):
  save clipboard -> write text -> all key-downs, Sleep(50), all key-ups -> wait 50 ms
  -> restore once the box shows the pasted text (never sooner than 500/3000/5000 ms depending on the app,
  longer after a long instant-text selection) -> skip restore if the clipboard changed.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes as W

from . import textproc

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
HANDLE = ctypes.c_void_p
MAGIC = 0x464C4F57  # dwExtraInfo tag on keys we inject, so our own hook ignores them

# ------------------------------------------------------------------ prototypes
def _proto(fn, res, *args):
    fn.restype, fn.argtypes = res, args
    return fn

_proto(user32.GetForegroundWindow, W.HWND)
_proto(user32.GetWindowThreadProcessId, W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
_proto(user32.GetWindowTextLengthW, ctypes.c_int, W.HWND)
_proto(user32.GetWindowTextW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_proto(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_proto(user32.MapVirtualKeyW, W.UINT, W.UINT, W.UINT)
_proto(user32.OpenClipboard, W.BOOL, W.HWND)
_proto(user32.CloseClipboard, W.BOOL)
_proto(user32.EmptyClipboard, W.BOOL)
_proto(user32.GetClipboardData, HANDLE, W.UINT)
_proto(user32.SetClipboardData, HANDLE, W.UINT, HANDLE)
_proto(user32.EnumClipboardFormats, W.UINT, W.UINT)
_proto(user32.RegisterClipboardFormatW, W.UINT, W.LPCWSTR)
_proto(user32.GetClipboardSequenceNumber, W.DWORD)
_proto(user32.CallNextHookEx, LRESULT, HANDLE, ctypes.c_int, W.WPARAM, W.LPARAM)
_proto(user32.UnhookWindowsHookEx, W.BOOL, HANDLE)
_proto(user32.GetMessageW, W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
_proto(user32.PostThreadMessageW, W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
_proto(user32.GetWindowLongPtrW, ctypes.c_ssize_t, W.HWND, ctypes.c_int)
_proto(user32.SetWindowLongPtrW, ctypes.c_ssize_t, W.HWND, ctypes.c_int, ctypes.c_ssize_t)
_proto(user32.SetWindowPos, W.BOOL, W.HWND, W.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT)
_proto(user32.GetParent, W.HWND, W.HWND)
_proto(user32.IsIconic, W.BOOL, W.HWND)
_proto(user32.ShowWindow, W.BOOL, W.HWND, ctypes.c_int)
_proto(user32.GetCursorPos, W.BOOL, ctypes.POINTER(W.POINT))
_proto(user32.MonitorFromPoint, HANDLE, W.POINT, W.DWORD)
_proto(kernel32.GlobalAlloc, HANDLE, W.UINT, ctypes.c_size_t)
_proto(kernel32.GlobalLock, ctypes.c_void_p, HANDLE)
_proto(kernel32.GlobalUnlock, W.BOOL, HANDLE)
_proto(kernel32.GlobalSize, ctypes.c_size_t, HANDLE)
_proto(kernel32.GlobalFree, HANDLE, HANDLE)
_proto(kernel32.OpenProcess, HANDLE, W.DWORD, W.BOOL, W.DWORD)
_proto(kernel32.CloseHandle, W.BOOL, HANDLE)
_proto(kernel32.QueryFullProcessImageNameW, W.BOOL, HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD))
_proto(kernel32.GetCurrentProcess, HANDLE)
_proto(kernel32.GetCurrentThreadId, W.DWORD)
_proto(kernel32.GetModuleHandleW, HANDLE, W.LPCWSTR)
_proto(kernel32.CreateMutexW, HANDLE, ctypes.c_void_p, W.BOOL, W.LPCWSTR)
_proto(advapi32.OpenProcessToken, W.BOOL, HANDLE, W.DWORD, ctypes.POINTER(HANDLE))
_proto(advapi32.GetTokenInformation, W.BOOL, HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD))


# ------------------------------------------------------------------ SendInput
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _INPUTUNION)]


_proto(user32.SendInput, W.UINT, W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "v": 0x56, "c": 0x43, "z": 0x5A, "insert": 0x2D,
      "enter": 0x0D, "backspace": 0x08, "left": 0x25, "right": 0x27, "delete": 0x2E}
EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0xA3, 0xA5, 0x5B, 0x5C}
MASK_VK = 0xE8  # unassigned VK: an "intervening key" so Win/Alt release doesn't open Start / the menu bar


def _inputs(vks, up):
    arr = (INPUT * len(vks))()
    for i, vk in enumerate(vks):
        flags = (0x2 if up else 0) | (0x1 if vk in EXTENDED else 0)
        arr[i].type = 1  # INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), flags, 0, MAGIC)
    return arr


def _send(vks, up):
    arr = _inputs(vks, up)
    return user32.SendInput(len(vks), arr, ctypes.sizeof(INPUT)) == len(vks)


def send_combo(names):
    """Wispr helper timing: all key-downs in one SendInput, Sleep(50), all key-ups (retry once)."""
    vks = [VK[n] for n in names]
    ok = _send(vks, False)
    time.sleep(0.05)
    if not _send(list(reversed(vks)), True):
        time.sleep(0.02)
        _send(list(reversed(vks)), True)
    return ok


def tap_key(name, times=1):
    """Press and release one key `times` times (in batches, so 300 backspaces don't take forever)."""
    vk = VK[name]
    left = times
    while left > 0:
        n = min(left, 40)
        downs, ups = _inputs([vk] * n, False), _inputs([vk] * n, True)
        arr = (INPUT * (2 * n))()
        for i in range(n):
            arr[2 * i], arr[2 * i + 1] = downs[i], ups[i]
        user32.SendInput(2 * n, arr, ctypes.sizeof(INPUT))
        left -= n
        time.sleep(0.01)


def type_text(text):
    """Type text as Unicode characters (no clipboard, any keyboard layout), in small batches.
    Returns False if Windows refused the input (e.g. an admin window)."""
    units = text.encode("utf-16-le")
    codes = [int.from_bytes(units[i:i + 2], "little") for i in range(0, len(units), 2)]
    for start in range(0, len(codes), 40):
        batch = codes[start:start + 40]
        arr = (INPUT * (2 * len(batch)))()
        for i, code in enumerate(batch):
            for j, flags in ((0, 0x4), (1, 0x4 | 0x2)):   # KEYEVENTF_UNICODE (+ KEYUP)
                arr[2 * i + j].type = 1
                arr[2 * i + j].ki = KEYBDINPUT(0, code, flags, 0, MAGIC)
        if user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT)) != len(arr):
            return False
    return True


def select_left(count):
    """Shift+Left `count` times: selects that many characters before the cursor."""
    if count <= 0:
        return True
    ok = _send([VK["shift"]], False)
    try:
        tap_key("left", count)
    finally:
        _send([VK["shift"]], True)
    return ok


def release_keys(vks):
    """Tell Windows these held keys are up (they stay physically held). Used so instant text can type while
    you hold Ctrl+Win: otherwise every letter would arrive as Ctrl+letter. Win/Alt get an intervening key
    first, so the Start menu doesn't open."""
    vks = [vk for vk in vks if vk]
    if not vks:
        return
    if any(vk in (0x12, 0xA4, 0xA5, 0x5B, 0x5C) for vk in vks):
        send_mask()
    _send(vks, True)


def press_enter():
    wait_modifiers_released()
    tap_key("enter")


def undo_insert(text, proc):
    """Remove text we just inserted: Ctrl+Z (one undo step for a paste in most apps), or backspaces in
    terminals, where Ctrl+Z means something else."""
    wait_modifiers_released()
    if proc.lower() in textproc.TERMINALS:
        tap_key("backspace", len(text.replace("\r\n", "\n")))
        return "backspace"
    send_combo(("ctrl", "z"))
    return "ctrl+z"


def send_mask():
    _send([MASK_VK], False)
    _send([MASK_VK], True)


MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


def modifiers_held():
    return [vk for vk in MODIFIER_VKS if user32.GetAsyncKeyState(vk) & 0x8000]


def wait_modifiers_released(timeout=2.0):
    """Wispr refuses to paste while a modifier is held (failure cause 2). We wait, then release them."""
    end = time.time() + timeout
    while time.time() < end:
        if not modifiers_held():
            return True
        time.sleep(0.02)
    held = modifiers_held()
    if held:
        if any(v in (0x12, 0x5B, 0x5C) for v in held):
            send_mask()
        _send(held, True)
    return False


# ------------------------------------------------------------------ focused app
def foreground():
    """(process name without .exe, window title, pid)."""
    hwnd = user32.GetForegroundWindow()
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    name = "unknown"
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        pbuf, size = ctypes.create_unicode_buffer(520), W.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            name = pbuf.value.rsplit("\\", 1)[-1].rsplit(".", 1)[0]
        kernel32.CloseHandle(h)
    return name, buf.value, pid.value


def _token_elevated(proc_handle):
    tok = HANDLE()
    if not advapi32.OpenProcessToken(proc_handle, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
        return None
    val, ret = W.DWORD(), W.DWORD()
    ok = advapi32.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(ret))  # TokenElevation
    kernel32.CloseHandle(tok)
    return bool(val.value) if ok else None


def self_elevated():
    return bool(_token_elevated(kernel32.GetCurrentProcess()))


def process_elevated(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        return bool(_token_elevated(h))  # unknown -> try anyway; SendInput reports a UIPI block
    finally:
        kernel32.CloseHandle(h)


# ------------------------------------------------------------------ clipboard
CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE = 1, 7, 13, 16
GDI_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}  # handles, not memory: can't be copied as bytes
MAX_SNAPSHOT = 64 * 1024 * 1024
_markers = {}


def _fmt(name):
    if name not in _markers:
        _markers[name] = user32.RegisterClipboardFormatW(name)
    return _markers[name]


def _open(retries=25):
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def _put(fmt, data):
    h = kernel32.GlobalAlloc(0x0002, max(len(data), 1))  # GMEM_MOVEABLE
    if not h:
        return False
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)
        return False
    return True


def _put_history_markers():
    # Keep dictations out of Win+V clipboard history and cloud clipboard (Wispr sets the same markers).
    zero = (0).to_bytes(4, "little")
    _put(_fmt("ExcludeClipboardContentFromMonitorProcessing"), zero)
    _put(_fmt("CanIncludeInClipboardHistory"), zero)
    _put(_fmt("CanUploadToCloudClipboard"), zero)


def sequence():
    return user32.GetClipboardSequenceNumber()


def snapshot():
    """Copy every memory-backed clipboard format so it can be put back after the paste."""
    items, total = [], 0
    if not _open():
        return None
    try:
        fmts, f = [], 0
        while True:
            f = user32.EnumClipboardFormats(f)
            if not f:
                break
            fmts.append(f)
        has_unicode = CF_UNICODETEXT in fmts
        for f in fmts:
            if f in GDI_FORMATS or 0x200 <= f <= 0x3FF:
                continue
            if has_unicode and f in (CF_TEXT, CF_OEMTEXT, CF_LOCALE):
                continue  # Windows re-creates these from the Unicode text
            h = user32.GetClipboardData(f)
            if not h:
                continue
            size = kernel32.GlobalSize(h)
            if not size or total + size > MAX_SNAPSHOT:
                continue
            p = kernel32.GlobalLock(h)
            if not p:
                continue
            items.append((f, ctypes.string_at(p, size)))
            kernel32.GlobalUnlock(h)
            total += size
    finally:
        user32.CloseClipboard()
    return items


def restore(items):
    if items is None or not _open():
        return False
    try:
        user32.EmptyClipboard()
        for f, data in items:
            _put(f, data)
        if items:
            _put_history_markers()
    finally:
        user32.CloseClipboard()
    return True


def set_text(text, private=True):
    if not _open():
        raise OSError("Clipboard is busy")
    try:
        user32.EmptyClipboard()
        _put(CF_UNICODETEXT, (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le"))
        if private:
            _put_history_markers()
    finally:
        user32.CloseClipboard()
    return sequence()


def get_text():
    if not _open():
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        if not p:
            return ""
        s = ctypes.wstring_at(p)
        kernel32.GlobalUnlock(h)
        return s.replace("\r\n", "\n")
    finally:
        user32.CloseClipboard()


# ------------------------------------------------------------------ paste / copy
def paste(text, cfg, target=None, saved=None, queued=0):
    """Insert text into the focused app. Returns a dict describing what happened.
    queued: key presses sent just before (instant text selecting its live words) that the app may still be
    working through when it gets to the Ctrl+V."""
    proc, title, pid = target or foreground()
    keys = textproc.pick_paste_keys(proc, cfg.get("shift_insert_in_editors", False))
    delay = textproc.restore_delay(proc)
    wait_modifiers_released()
    restore_on = cfg.get("restore_clipboard", True)
    if saved is None and restore_on:
        saved = snapshot()
    seq = set_text(text)
    elevated = process_elevated(pid) and not self_elevated()
    if elevated:
        # UIPI blocks our keystrokes into admin windows: leave the text on the clipboard instead.
        return {"proc": proc, "keys": "none", "delay": 0, "status": "elevated"}
    if not send_combo(keys):  # blocked (UIPI) or no input desktop: the text stays on the clipboard
        return {"proc": proc, "keys": "none", "delay": 0, "status": "blocked"}
    time.sleep(0.05)  # Wispr: "sleeping for 50 ms for paste to complete"
    if restore_on and saved is not None:
        budget = restore_budget(delay, queued, len(text))
        threading.Thread(target=_restore_when_pasted, args=(saved, seq, text, delay, budget), daemon=True,
                         name="clipboard-restore").start()
    return {"proc": proc, "keys": "+".join(keys), "delay": delay, "status": "ok"}


def restore_budget(delay, queued=0, chars=0):
    """Longest wait before the old clipboard goes back: the app's usual delay, plus time to work through any
    queued key presses and to take in a long paste."""
    return delay + min(15.0, 0.01 * queued + 0.0005 * chars)


def _restore_when_pasted(saved, seq, text, delay, budget, check=None, sleep=time.sleep, clock=time.monotonic):
    """Put the old clipboard back only after the app has pasted. An app reads the clipboard when it gets round
    to the Ctrl+V, and a long dictation can keep it busy: restoring before that pasted the user's old copy
    instead of their words. Watches the box for the pasted text; if the box can't be read, waits the full
    budget. Never restores sooner than the app's usual delay, or if something else was copied meanwhile."""
    if check is None:
        from . import instant
        check = instant.pasted
    start = clock()
    seen = None
    while clock() - start < budget:
        try:
            seen = check(text)
        except Exception:
            seen = None
        if seen is not False:
            break
        sleep(0.05)
    elapsed = clock() - start
    sleep(max(0.0, (delay if seen else budget) - elapsed))
    if sequence() == seq:  # "Clipboard changed since paste, skipping restoration"
        restore(saved)
        return True
    return False


def copy_selection(timeout=0.5):
    """Ctrl+C the current selection. Returns (selected_text, clipboard_snapshot_to_restore)."""
    wait_modifiers_released()
    saved = snapshot()
    before = sequence()
    send_combo(("ctrl", "c"))
    end = time.time() + timeout
    while time.time() < end and sequence() == before:
        time.sleep(0.02)
    text = get_text() if sequence() != before else ""
    return text, saved


# ------------------------------------------------------------------ keyboard hook
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, W.WPARAM, W.LPARAM)
_proto(user32.SetWindowsHookExW, HANDLE, ctypes.c_int, HOOKPROC, HANDLE, W.DWORD)


class KeyboardHook(threading.Thread):
    """WH_KEYBOARD_LL hook on its own message-pumping thread. handler(vk, is_down) -> swallow?"""

    def __init__(self, handler):
        super().__init__(daemon=True, name="keyboard-hook")
        self.handler = handler
        self.tid = None
        self.ok = threading.Event()
        self.error = None

    def _cb(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.dwExtraInfo != MAGIC and wparam in (0x100, 0x101, 0x104, 0x105):
                    if self.handler(kb.vkCode, wparam in (0x100, 0x104)):
                        return 1
        except Exception as e:  # never let an exception break the user's keyboard
            print("hook error:", e, file=sys.stderr)
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._cb)  # keep a reference or it gets garbage collected
        self.hook = user32.SetWindowsHookExW(13, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not self.hook:
            self.error = f"SetWindowsHookExW failed ({ctypes.get_last_error()})"
            self.ok.set()
            return
        self.ok.set()
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(self.hook)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)  # WM_QUIT


# ------------------------------------------------------------------ windows & system
class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]


_proto(user32.GetMonitorInfoW, W.BOOL, HANDLE, ctypes.POINTER(MONITORINFO))


def work_area_at_cursor():
    pt = W.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    mon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    r = mi.rcWork
    return r.left, r.top, r.right, r.bottom


def make_overlay_window(tk_window):
    """No focus stealing: WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST on the Tk frame window."""
    tk_window.update_idletasks()
    hwnd = user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
    ex = user32.GetWindowLongPtrW(hwnd, -20)
    user32.SetWindowLongPtrW(hwnd, -20, ex | 0x08000000 | 0x00000080 | 0x00000008)
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020)  # TOPMOST, no move/size/activate
    return hwnd


APP_ID = "AquaLite.Dictation"


def set_app_id(app_id=APP_ID):
    """Give Aqua Lite its own identity in Windows. Without it, Windows files our windows under pythonw.exe, so the
    taskbar and Alt+Tab show Python's logo instead of ours. Must run before the first window is created."""
    try:
        shell32 = ctypes.WinDLL("shell32")
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [W.LPCWSTR]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        return shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except (OSError, AttributeError):
        return False


def set_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


_mutex = None


def single_instance():
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, "Local\\AquaLiteSingleInstance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


_proto(kernel32.CreateEventW, HANDLE, ctypes.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR)
_proto(kernel32.SetEvent, W.BOOL, HANDLE)
_proto(kernel32.WaitForSingleObject, W.DWORD, HANDLE, W.DWORD)
OPEN_EVENT = "Local\\AquaLiteOpenSettings"


def ask_running_instance_to_open():
    """Second launch (e.g. from the Start menu): tell the running copy to show its Settings window."""
    h = kernel32.CreateEventW(None, False, False, OPEN_EVENT)
    ok = bool(h) and ctypes.get_last_error() == 183  # the running copy created it
    if h:
        kernel32.SetEvent(h)
    return ok


def watch_open_requests(callback):
    h = kernel32.CreateEventW(None, False, False, OPEN_EVENT)

    def loop():
        while kernel32.WaitForSingleObject(h, 0xFFFFFFFF) == 0:
            callback()
    threading.Thread(target=loop, daemon=True, name="open-requests").start()


def wait_for_exit(pid, timeout_ms):
    """Block until process `pid` has exited (or the timeout passes)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = HANDLE
    k32.OpenProcess.argtypes = (W.DWORD, W.BOOL, W.DWORD)
    k32.CloseHandle.argtypes = (HANDLE,)
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        kernel32.WaitForSingleObject(h, timeout_ms)
        k32.CloseHandle(h)


def startup_shortcut_path():
    return os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup\Aqua Lite.lnk")


def set_startup(enabled, script_path, icon_path=""):
    lnk = startup_shortcut_path()
    if not enabled:
        if os.path.exists(lnk):
            os.remove(lnk)
        return
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"$s.TargetPath='{exe}';$s.Arguments='\"{script_path}\"';"
          f"$s.WorkingDirectory='{os.path.dirname(script_path)}';"
          + (f"$s.IconLocation='{icon_path}';" if icon_path else "") + "$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   creationflags=0x08000000, check=False)


# ------------------------------------------------------------------ per-pixel-alpha window (soft glass edges)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


_proto(user32.GetDC, HANDLE, W.HWND)
_proto(user32.ReleaseDC, ctypes.c_int, W.HWND, HANDLE)
_proto(gdi32.CreateCompatibleDC, HANDLE, HANDLE)
_proto(gdi32.DeleteDC, W.BOOL, HANDLE)
_proto(gdi32.CreateDIBSection, HANDLE, HANDLE, ctypes.POINTER(BITMAPINFOHEADER), W.UINT,
       ctypes.POINTER(ctypes.c_void_p), HANDLE, W.DWORD)
_proto(gdi32.SelectObject, HANDLE, HANDLE, HANDLE)
_proto(gdi32.DeleteObject, W.BOOL, HANDLE)
_proto(user32.UpdateLayeredWindow, W.BOOL, W.HWND, HANDLE, ctypes.POINTER(W.POINT), ctypes.POINTER(W.SIZE),
       HANDLE, ctypes.POINTER(W.POINT), W.DWORD, ctypes.POINTER(BLENDFUNCTION), W.DWORD)


def window_dpi_scale(hwnd):
    try:
        return max(1.0, user32.GetDpiForWindow(W.HWND(hwnd)) / 96.0)
    except Exception:
        return 1.0


def make_layered(hwnd):
    ex = user32.GetWindowLongPtrW(hwnd, -20)
    user32.SetWindowLongPtrW(hwnd, -20, ex | 0x00080000 | 0x08000000 | 0x00000080 | 0x00000008)


def update_layered(hwnd, x, y, w, h, bgra):
    """Show a premultiplied BGRA image as the window's pixels, with per-pixel transparency."""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ok = False
    if hbmp and bits:
        ctypes.memmove(bits, bgra, w * h * 4)
        old = gdi32.SelectObject(mem, hbmp)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel AC_SRC_ALPHA
        ok = bool(user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(W.POINT(x, y)), ctypes.byref(W.SIZE(w, h)),
                                             mem, ctypes.byref(W.POINT(0, 0)), 0, ctypes.byref(blend), 2))
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)
    return ok


_fine_timer = False


def fine_timer(on):
    """Ask Windows for 1 ms timer ticks (default is ~15.6 ms, which makes 60 fps frames land unevenly).
    Only held while the Flow bar is animating, so it costs nothing at rest."""
    global _fine_timer
    if on == _fine_timer:
        return
    try:
        winmm = ctypes.WinDLL("winmm")
        (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        _fine_timer = on
    except OSError:
        pass


# ------------------------------------------------------------------ display timing (for frame pacing)
class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD),
                ("szDevice", W.WCHAR * 32)]


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", W.WCHAR * 32), ("dmSpecVersion", W.WORD), ("dmDriverVersion", W.WORD),
                ("dmSize", W.WORD), ("dmDriverExtra", W.WORD), ("dmFields", W.DWORD),
                ("dmUnion1", ctypes.c_byte * 16), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", W.WCHAR * 32), ("dmLogPixels", W.WORD), ("dmBitsPerPel", W.DWORD),
                ("dmPelsWidth", W.DWORD), ("dmPelsHeight", W.DWORD), ("dmDisplayFlags", W.DWORD),
                ("dmDisplayFrequency", W.DWORD), ("dmRest", W.DWORD * 8)]


_U64, _U32 = ctypes.c_uint64, ctypes.c_uint32


class DWM_TIMING_INFO(ctypes.Structure):
    _pack_ = 1   # dwmapi.h packs its structs to 1 byte
    _fields_ = ([("cbSize", _U32), ("rateRefreshNum", _U32), ("rateRefreshDen", _U32), ("qpcRefreshPeriod", _U64),
                 ("rateComposeNum", _U32), ("rateComposeDen", _U32), ("qpcVBlank", _U64), ("cRefresh", _U64),
                 ("cDXRefresh", _U32), ("qpcCompose", _U64), ("cFrame", _U64), ("cDXPresent", _U32),
                 ("cRefreshFrame", _U64), ("cFrameSubmitted", _U64), ("cDXPresentSubmitted", _U32),
                 ("cFrameConfirmed", _U64), ("cDXPresentConfirmed", _U32), ("cRefreshConfirmed", _U64),
                 ("cDXRefreshConfirmed", _U32), ("cFramesLate", _U64), ("cFramesOutstanding", _U32)]
                + [(f"rest{i}", _U64) for i in range(21)])


_proto(user32.EnumDisplaySettingsW, W.BOOL, W.LPCWSTR, W.DWORD, ctypes.POINTER(DEVMODEW))
try:
    dwmapi = ctypes.WinDLL("dwmapi")
    _proto(dwmapi.DwmGetCompositionTimingInfo, ctypes.c_long, W.HWND, ctypes.POINTER(DWM_TIMING_INFO))
    _proto(dwmapi.DwmSetWindowAttribute, ctypes.c_long, W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD)
except OSError:
    dwmapi = None


def _qpc_freq():
    f = ctypes.c_int64()
    return f.value if kernel32.QueryPerformanceFrequency(ctypes.byref(f)) and f.value else 0


def display_timing():
    """How often the screen under the cursor (where the Flow bar shows) refreshes, and when it last did.
    Returns (seconds per refresh, time.perf_counter() of a recent refresh or None). Falls back to 60 Hz."""
    hz = 0
    try:
        pt = W.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.cast(ctypes.byref(mi), ctypes.POINTER(MONITORINFO))):
            dm = DEVMODEW()
            dm.dmSize = ctypes.sizeof(DEVMODEW)
            if user32.EnumDisplaySettingsW(mi.szDevice, 0xFFFFFFFF, ctypes.byref(dm)):  # ENUM_CURRENT_SETTINGS
                hz = dm.dmDisplayFrequency
    except Exception:
        hz = 0
    period = 1.0 / hz if 23 <= hz <= 1000 else None   # 0 / 1 mean "hardware default"
    vblank = None
    try:  # the compositor's exact refresh period and the time of its last vblank, to line frames up with it
        ti = DWM_TIMING_INFO()
        ti.cbSize = ctypes.sizeof(DWM_TIMING_INFO)
        freq = _qpc_freq()
        if freq and dwmapi and dwmapi.DwmGetCompositionTimingInfo(None, ctypes.byref(ti)) == 0 \
                and ti.qpcRefreshPeriod and ti.qpcVBlank:
            dwm_period = ti.qpcRefreshPeriod / freq
            if period is None or abs(dwm_period - period) / period < 0.03:  # same screen (mixed-Hz setups differ)
                period = dwm_period
                now = ctypes.c_int64()
                kernel32.QueryPerformanceCounter(ctypes.byref(now))
                vblank = ti.qpcVBlank / freq + (time.perf_counter() - now.value / freq)
    except Exception:
        vblank = None
    return (period or 1 / 60), vblank



# ------------------------------------------------------------------ child processes
class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                  "OtherBytes")]


class _JOB_BASIC_LIMITS(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", ULONG_PTR), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _JOB_EXTENDED_LIMITS(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOB_BASIC_LIMITS), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


_proto(kernel32.CreateJobObjectW, HANDLE, ctypes.c_void_p, W.LPCWSTR)
_proto(kernel32.SetInformationJobObject, W.BOOL, HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD)
_proto(kernel32.AssignProcessToJobObject, W.BOOL, HANDLE, HANDLE)
_job = None


def close_with_us(popen):
    """Tie a child process (the private AI server) to Aqua Lite: when Aqua Lite exits - even if it crashes -
    Windows closes the child too, so it never lingers using memory."""
    global _job
    if _job is None:
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _JOB_EXTENDED_LIMITS()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        _job = job
    if not kernel32.AssignProcessToJobObject(_job, HANDLE(int(popen._handle))):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")


def tint_title_bar(hwnd, caption, text=None, border=None):
    """Windows 11: colour a window's title bar, its title text and its edge (Windows 10 ignores this)."""
    if not dwmapi:
        return False
    ok = True
    for attr, rgb in ((35, caption), (36, text), (34, border)):   # DWMWA_CAPTION/TEXT/BORDER_COLOR
        if rgb is None:
            continue
        val = W.DWORD(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16))
        ok = dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0 and ok
    return ok


# ------------------------------------------------------------------ frosted glass under the Flow bar
class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", W.DWORD), ("AccentFlags", W.DWORD), ("GradientColor", W.DWORD),
                ("AnimationId", W.DWORD)]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", W.DWORD), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


_WNDPROC = ctypes.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE), ("hCursor", HANDLE),
                ("hbrBackground", HANDLE), ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


_proto(user32.DefWindowProcW, LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_proto(user32.RegisterClassW, W.ATOM, ctypes.POINTER(_WNDCLASSW))
_proto(user32.CreateWindowExW, W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, ctypes.c_int, ctypes.c_int,
       ctypes.c_int, ctypes.c_int, W.HWND, HANDLE, HANDLE, ctypes.c_void_p)
_proto(user32.DestroyWindow, W.BOOL, W.HWND)
_proto(user32.SetWindowRgn, ctypes.c_int, W.HWND, HANDLE, W.BOOL)
_proto(gdi32.CreateRoundRectRgn, HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       ctypes.c_int)
_proto(gdi32.GetStockObject, HANDLE, ctypes.c_int)
_proto(gdi32.CombineRgn, ctypes.c_int, HANDLE, HANDLE, HANDLE, ctypes.c_int)
_proto(kernel32.GetModuleHandleW, HANDLE, W.LPCWSTR)
try:
    _SetWCA = user32.SetWindowCompositionAttribute
    _proto(_SetWCA, W.BOOL, W.HWND, ctypes.POINTER(_WINCOMPATTRDATA))
except AttributeError:
    _SetWCA = None
_frost_class = None
_frost_proc = _WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))   # kept alive for the app's life


def transparency_on():
    """Windows' own 'Transparency effects' switch (Settings > Personalisation > Colours)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


def animations_on():
    """Windows' 'Animation effects' switch (Settings > Accessibility > Visual effects)."""
    on = W.BOOL(True)
    try:
        if user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):   # SPI_GETCLIENTAREAANIMATION
            return bool(on.value)
    except (AttributeError, OSError):
        pass
    return True


def apps_light_theme():
    """Windows' app colour setting (Settings > Personalisation > Colours): True for light, False for dark."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except OSError:
        return True


def watch_theme(callback):
    """Call callback() (on a background thread) whenever Windows' colour settings change: light/dark apps or
    transparency effects. Windows wakes the thread, so nothing is polled."""
    import winreg
    adv = ctypes.WinDLL("advapi32")
    adv.RegNotifyChangeKeyValue.restype = ctypes.c_long
    adv.RegNotifyChangeKeyValue.argtypes = (HANDLE, W.BOOL, W.DWORD, HANDLE, W.BOOL)

    def loop():
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        except OSError:
            return
        ev = kernel32.CreateEventW(None, False, False, None)
        while adv.RegNotifyChangeKeyValue(int(key), False, 0x4, ev, True) == 0:   # REG_NOTIFY_CHANGE_LAST_SET
            if kernel32.WaitForSingleObject(ev, 0xFFFFFFFF) != 0:
                break
            try:
                callback()
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="theme-watch").start()


def dark_title_bar(hwnd, on):
    """Windows 10 (20H1+) and 11: a dark title bar for a window (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    if not dwmapi:
        return False
    val = W.BOOL(bool(on))
    return any(dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0 for attr in (20, 19))


class Frost:
    """A borderless window that sits right under the Flow bar's glass, shaped like the capsule, and asks Windows
    to blur whatever is behind it. Windows' compositor does the blur on the graphics card, so it costs Aqua Lite
    nothing per frame; the bar's own see-through glass, light and waveform are drawn on top."""
    TINT = 0x30C87812   # AABBGGRR: a faint sky-blue wash in the blur (Frutiger Aero)

    @staticmethod
    def shapes_ok():
        """Windows 10 blurs inside the bar's rounded shape. Windows 11 draws that blur as solid black, and its acrylic
        blur ignores the shape (a grey rectangle shows round the bar), so there the glass is drawn solid instead."""
        try:
            return sys.getwindowsversion().build < 22000
        except AttributeError:
            return False

    def __init__(self, tint=None):
        global _frost_class
        if _SetWCA is None:
            raise OSError("this Windows has no blur-behind")
        inst = kernel32.GetModuleHandleW(None)
        if _frost_class is None:
            wc = _WNDCLASSW()
            wc.lpfnWndProc = _frost_proc
            wc.hInstance = inst
            wc.hbrBackground = gdi32.GetStockObject(4)   # black: shows as fully see-through over the blur
            wc.lpszClassName = "AquaLiteFrost"
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise OSError(ctypes.get_last_error(), "RegisterClass failed")
            _frost_class = wc
        ex = 0x00000080 | 0x08000000 | 0x00000008   # tool window (no taskbar button), never activates, topmost
        self.hwnd = user32.CreateWindowExW(ex, "AquaLiteFrost", "", 0x80000000, -20000, -20000, 1, 1,
                                           None, None, inst, None)
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowEx failed")
        policy = _ACCENT_POLICY(3, 2, self.TINT if tint is None else tint, 0)   # ACCENT_ENABLE_BLURBEHIND, tinted
        data = _WINCOMPATTRDATA(19, ctypes.addressof(policy), ctypes.sizeof(policy))
        if not _SetWCA(self.hwnd, ctypes.byref(data)):
            user32.DestroyWindow(self.hwnd)
            raise OSError("blur-behind was refused")
        self.shape, self.rect, self.visible = None, None, False

    def place(self, above, x, y, w, h, radius, clip_bottom=None, extra=()):
        """Put the blur under window `above` at (x, y, w, h) on screen, rounded by `radius`; anything below
        clip_bottom is left out (the bar tucks under the screen edge when it slides). extra: more rounded
        shapes (x, y, w, h, radius) on screen to blur as well, such as a bubble above the bar."""
        if extra:
            x0, y0 = min([x] + [e[0] for e in extra]), min([y] + [e[1] for e in extra])
            x1 = max([x + w] + [e[0] + e[2] for e in extra])
            y1 = max([y + h] + [e[1] + e[3] for e in extra])
            parts = tuple((sx - x0, sy - y0, sw, sh, sr)
                          for sx, sy, sw, sh, sr in ((x, y, w, h, radius),) + tuple(extra))
            x, y, w, h = x0, y0, x1 - x0, y1 - y0
        else:
            parts = ((0, 0, w, h, radius),)
        vis_h = h if clip_bottom is None else min(h, clip_bottom - y)
        if vis_h <= 2 or w <= 2:
            self.hide()
            return
        shape = (w, h, parts)
        if shape != self.shape:
            rgn = None
            for px, py, pw, ph, pr in parts:
                d = max(2, 2 * pr)
                part = gdi32.CreateRoundRectRgn(px, py, px + pw + 1, py + ph + 1, d, d)
                if rgn is None:
                    rgn = part
                else:
                    gdi32.CombineRgn(rgn, rgn, part, 2)   # RGN_OR
                    gdi32.DeleteObject(part)
            if user32.SetWindowRgn(self.hwnd, rgn, True):
                self.shape = shape
            else:
                gdi32.DeleteObject(rgn)
        rect = (x, y, w, vis_h)
        if rect == self.rect and self.visible:
            return   # nothing moved
        user32.SetWindowPos(self.hwnd, above, x, y, w, vis_h, 0x0010 | 0x0040)   # just under the bar, no activate
        self.rect, self.visible = rect, True

    def hide(self):
        if self.visible:
            user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0, 0x0080 | 0x0001 | 0x0002 | 0x0004 | 0x0010)
            self.visible = False

    def close(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
