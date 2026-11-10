"""Learn from corrections: after a dictation is typed, watch the text box for a little while. If you fix a word
Aqua Lite got wrong ('Kaitlin' -> 'Kaitlyn'), that word goes into your dictionary so it's right next time.
If you reword it (punctuation, phrasing, formatting), that before/after pair is kept so the AI can follow your
preferences next time (see textproc.style_edit and history.add_correction).

Reads the focused text box through the accessibility API screen readers use (see osapi).
Everything stays on this PC. Password boxes are never read.
"""
import logging
import threading
import time

from . import textproc

log = logging.getLogger("aqualite")
WATCH_SECS = 45      # stop watching after this long
POLL_SECS = 0.5
STABLE_SECS = 1.5    # a fix only counts once it has stayed put this long (not "Pat" halfway through typing)
CONTEXT = 40         # characters of surrounding text used to find the dictation again


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

    def __init__(self, dictated, read, window, on_learned, known=(), clock=time.monotonic, sleep=time.sleep,
                 on_edited=None):
        self.dictated = dictated.strip()
        self.read, self.window, self.on_learned, self.on_edited = read, window, on_learned, on_edited
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
        kept, region_now, region_since = None, self.dictated, self.clock()   # the edit, once it has settled
        end = self.clock() + WATCH_SECS
        while self.clock() < end and not self.stopped.is_set():
            self.sleep(POLL_SECS)
            if self.window() != hwnd:
                break
            text = self.read()
            if text is None:
                break
            region = locate(text, before, after, len(self.dictated))
            if region is not None and region != region_now:
                if self.clock() - region_since >= STABLE_SECS:
                    kept = region_now
                region_now, region_since = region, self.clock()
            new = textproc.learned_words(self.dictated, region) if region is not None else None
            if new != cand:
                if cand is not None and self.clock() - since >= STABLE_SECS:
                    confirmed = cand
                cand, since = new, self.clock()
        if cand is not None and self.clock() - since >= STABLE_SECS:
            confirmed = cand
        if self.clock() - region_since >= STABLE_SECS:
            kept = region_now
        words = [w for w in (confirmed or []) if w.lower() not in self.known]
        if words and not self.stopped.is_set():
            self.on_learned(words)
        if self.on_edited and kept and kept.strip() != self.dictated and not self.stopped.is_set():
            self.on_edited(self.dictated, kept)
        return words


class Learner:
    """One watcher at a time; a new dictation (or undo) replaces the previous one."""

    def __init__(self, on_learned, on_edited=None):
        self.on_learned, self.on_edited = on_learned, on_edited
        self.current = None
        self.disabled = False

    def watch(self, dictated, known, edits=False, words=True):
        """words: learn misheard words for the dictionary. edits: also report the user's settled edit of the whole
        dictation (to learn their phrasing)."""
        self.stop()
        from . import osapi
        if self.disabled or not osapi.SUPPORTED or not (words or edits):
            return
        threading.Thread(target=self._run, args=(dictated, known, edits, words), daemon=True, name="learn").start()

    def stop(self):
        if self.current:
            self.current.stop()
            self.current = None

    def _run(self, dictated, known, edits=False, words=True):
        from . import osapi
        try:
            reader = osapi.text_reader()
            read = reader.__enter__()
        except ImportError:
            log.info("learn: comtypes not installed yet")
            return
        except Exception as e:
            log.warning("learn: reading text boxes unavailable: %s", e)
            self.disabled = True
            return
        w = CorrectionWatcher(dictated, read, osapi.foreground_window,
                              self.on_learned if words else (lambda _w: None), known,
                              on_edited=self.on_edited if edits else None)
        self.current = w
        try:
            w.run()
        except Exception:
            log.exception("learn: watcher failed")
        finally:
            try:
                reader.__exit__(None, None, None)
            except Exception:
                pass
