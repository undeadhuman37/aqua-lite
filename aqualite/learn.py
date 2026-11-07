"""Learn from corrections: after a dictation is typed, watch the text box for a little while. If you fix a word
Aqua Lite got wrong ('Patrisio' -> 'Patricio'), that word goes into your dictionary so it's right next time.

Reads the focused text box through Windows UI Automation (the accessibility API screen readers use).
Everything stays on this PC. Password boxes are never read.
"""
import logging
import sys
import threading
import time

from . import textproc

log = logging.getLogger("aqualite")
WATCH_SECS = 45      # stop watching after this long
POLL_SECS = 0.5
STABLE_SECS = 1.5    # a fix only counts once it has stayed put this long (not "Pat" halfway through typing)
CONTEXT = 40         # characters of surrounding text used to find the dictation again
UIA_TEXT, UIA_VALUE = 10014, 10002


def locate(text, before, after, length):
    """Find where the dictation sits in the box now, using the text that was around it."""
    if text is None:
        return None
    before, after = (before if before.strip() else ""), (after if after.strip() else "")  # spaces alone match anywhere
    start = 0
    if before:
        i = text.rfind(before)
        if i < 0:
            return None
        start = i + len(before)
    end = len(text)
    if after:
        j = text.find(after, start)
        if j < 0:
            return None
        end = j
    region = text[start:end]
    if not region.strip() or not (length * 0.5 - 5 <= len(region) <= length * 2 + 20):
        return None
    return region


class CorrectionWatcher:
    """read() -> current text of the focused box (or None); window() -> id of the foreground window."""

    def __init__(self, dictated, read, window, on_learned, known=(), clock=time.monotonic, sleep=time.sleep):
        self.dictated = dictated.strip()
        self.read, self.window, self.on_learned = read, window, on_learned
        self.known = {w.lower() for w in known}
        self.clock, self.sleep = clock, sleep
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()

    def run(self):
        self.sleep(0.4)  # let the paste land
        hwnd, base = self.window(), self.read()
        if not base or not self.dictated:
            return []
        idx = base.rfind(self.dictated)
        if idx < 0:
            log.info("learn: can't find the dictation in this text box, not watching")
            return []
        before = base[max(0, idx - CONTEXT):idx]
        after = base[idx + len(self.dictated):idx + len(self.dictated) + CONTEXT]
        confirmed, cand, since = [], [], self.clock()
        end = self.clock() + WATCH_SECS
        while self.clock() < end and not self.stopped.is_set():
            self.sleep(POLL_SECS)
            if self.window() != hwnd:
                break
            text = self.read()
            if text is None:
                break
            region = locate(text, before, after, len(self.dictated))
            new = textproc.learned_words(self.dictated, region) if region is not None else None
            if new != cand:
                if cand is not None and self.clock() - since >= STABLE_SECS:
                    confirmed = cand
                cand, since = new, self.clock()
        if cand is not None and self.clock() - since >= STABLE_SECS:
            confirmed = cand
        words = [w for w in (confirmed or []) if w.lower() not in self.known]
        if words and not self.stopped.is_set():
            self.on_learned(words)
        return words


# ---------------------------------------------------------------- Windows UI Automation
def _uia():
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


def make_reader(U, uia):
    def read():
        try:
            el = uia.GetFocusedElement()
            if not el or el.CurrentIsPassword:
                return None
            pat = el.GetCurrentPattern(UIA_TEXT)
            if pat:
                return pat.QueryInterface(U.IUIAutomationTextPattern).DocumentRange.GetText(200000).replace("\r\n", "\n")
            pat = el.GetCurrentPattern(UIA_VALUE)
            if pat:
                return (pat.QueryInterface(U.IUIAutomationValuePattern).CurrentValue or "").replace("\r\n", "\n")
        except Exception as e:
            log.debug("learn: read failed: %s", e)
        return None
    return read


class Learner:
    """One watcher at a time; a new dictation (or undo) replaces the previous one."""

    def __init__(self, on_learned):
        self.on_learned = on_learned
        self.current = None
        self.disabled = False

    def watch(self, dictated, known):
        self.stop()
        if self.disabled or sys.platform != "win32":
            return
        threading.Thread(target=self._run, args=(dictated, known), daemon=True, name="learn").start()

    def stop(self):
        if self.current:
            self.current.stop()
            self.current = None

    def _run(self, dictated, known):
        try:
            comtypes, U, uia = _uia()
        except ImportError:
            log.info("learn: comtypes not installed yet")
            return
        except Exception as e:
            log.warning("learn: UI Automation unavailable: %s", e)
            self.disabled = True
            return
        from . import winapi
        w = CorrectionWatcher(dictated, make_reader(U, uia), lambda: winapi.user32.GetForegroundWindow(),
                              self.on_learned, known)
        self.current = w
        try:
            w.run()
        except Exception:
            log.exception("learn: watcher failed")
        finally:
            del uia
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
