"""Instant text: your words appear in the text box while you're still talking.

A small offline model (the same one behind live words) re-reads the recent audio about twice a second. A word is
typed only once two passes in a row hear it the same way (the "local agreement" policy from whisper_streaming), so
guesses rarely reach your text box. When you let go, the full recording goes through your normal engine and AI
formatting as always, and the polished text replaces what was typed live.

Before replacing anything, Aqua Lite checks that the text it typed is still right before the cursor (through
Windows UI Automation). If you clicked somewhere else or edited it in the meantime, nothing is deleted: the
polished version goes on the clipboard instead.
"""
import logging
import re
import threading
import time
import unicodedata

from . import stt

log = logging.getLogger("aqualite")
RATE = 16000
EVERY_SECS = 0.3      # how often to re-read the audio
MIN_SECS = 0.6        # don't bother with less audio than this
TRIM_SECS = 6.0       # keep the re-read window short: cut it after the last finished sentence
HARD_TRIM_SECS = 9.0  # no sentence end for this long: cut after the last typed word anyway
PROMPT_CHARS = 200    # typed text passed back to the model, so it keeps the thread
SENTENCE_END = (".", "?", "!", "؟", "。")


def norm(word):
    """Compare words without case or punctuation: 'Hello,' and 'hello' are the same word heard twice."""
    return re.sub(r"[^\w]", "", (word or "").lower())


class Agreement:
    """Local agreement between two passes. Words are (text, start, end) with times in seconds from the start of the
    recording. committed = typed (final); pending = the last pass's words after that, waiting for a second opinion."""

    def __init__(self):
        self.committed, self.pending = [], []

    @property
    def last_end(self):
        return self.committed[-1][2] if self.committed else 0.0

    def insert(self, words):
        """Feed one pass; returns the words that just became final."""
        new = [w for w in words if w[1] > self.last_end - 0.1]
        if new and self.committed and abs(new[0][1] - self.last_end) < 1.0:
            # the model often hears the last typed word(s) again at the start of the window: drop the repeat
            for n in range(min(5, len(new), len(self.committed)), 0, -1):
                if [norm(w[0]) for w in self.committed[-n:]] == [norm(w[0]) for w in new[:n]]:
                    new = new[n:]
                    break
        agreed = []
        for a, b in zip(new, self.pending):
            if not norm(a[0]) or norm(a[0]) != norm(b[0]):
                break
            agreed.append(a)
        self.committed += agreed
        self.pending = new[len(agreed):]
        return agreed

    def text(self):
        return join_words(self.committed)


def join_words(words, first=True):
    """Whisper's words carry their own leading space (' hello'); type exactly one space between words."""
    out = ""
    for i, w in enumerate(words):
        t = w[0].strip()
        if not t:
            continue
        out += t if (first and not out) else " " + t
    return out


def presses(text):
    """How many Left-arrow presses cover `text`: one per character, but accents and other combining marks ride
    along with the letter before them."""
    return sum(1 for c in text if not unicodedata.combining(c))


class Streamer:
    """Runs the passes on its own thread. type_fn(text) -> bool types text into the app; before_first() runs once,
    right before the first word is typed; on_caption(text) shows what's being heard in the Flow bar."""

    def __init__(self, recorder, cfg, model, type_fn, before_first=None, on_caption=None, allow=None):
        self.recorder, self.cfg, self.model = recorder, cfg, model
        self.type_fn, self.before_first, self.on_caption = type_fn, before_first, on_caption
        self.allow = allow or (lambda: True)   # checked before the first word: e.g. not a password box
        self.agree = Agreement()
        self.offset = 0.0           # where the re-read window starts (seconds into the recording)
        self.typed = ""             # exactly what has been typed into the app
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.closed = False
        self.failed = None
        self.thread = None
        self.pass_secs = []          # how long each pass took, for the log

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="instant-text")
        self.thread.start()
        return self

    def finish(self, wait=1.5):
        """Stop typing (call when recording stops). Returns exactly what was typed."""
        self.stop_event.set()
        with self.lock:
            self.closed = True
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(wait)
        if self.pass_secs:
            ps = sorted(self.pass_secs)
            log.info("instant text: %d passes, median %.2fs, slowest %.2fs, model %s, typed %d chars",
                     len(ps), ps[len(ps) // 2], ps[-1], getattr(self.model, "name", "?"), len(self.typed))
        return self.typed

    # ------------------------------------------------------------------ the passes
    def _run(self):
        self.stop_event.wait(0.5)
        while not self.stop_event.is_set():
            t0 = time.perf_counter()
            try:
                if self.step():
                    self.pass_secs.append(time.perf_counter() - t0)
            except Exception as e:
                self.failed = str(e)
                log.warning("instant text stopped: %s", e)
                return
            self.stop_event.wait(max(0.05, EVERY_SECS - (time.perf_counter() - t0)))

    def prompt(self):
        tail = self.agree.text()[-PROMPT_CHARS:]
        return " ".join(p for p in (stt.vocab_prompt(self.cfg), tail) if p)

    def step(self):
        audio = self.recorder.audio_from(self.offset)
        if len(audio) < RATE * MIN_SECS or self.recorder.speech_frames <= 0:
            return False
        words = [(w, s + self.offset, e + self.offset) for w, s, e in self.model.words(audio, self.cfg, self.prompt())]
        heard = join_words(words)
        if heard and stt.is_hallucination(heard, 1.0):
            words = []
        new = self.agree.insert(words)
        if new:
            self._type(new)
        if self.on_caption:
            shown = self.agree.committed[-8:] + self.agree.pending
            self.on_caption(join_words(shown))
        self._trim()
        return True

    def _type(self, words):
        text = join_words(words, first=not self.typed)
        if not text:
            return
        with self.lock:
            if self.closed or self.stop_event.is_set():
                return
            if not self.typed:
                if not self.allow():
                    log.info("instant text: not typing into this box")
                    self.stop_event.set()
                    return
                if self.before_first:
                    self.before_first()
            if self.type_fn(text):
                self.typed += text
            else:
                log.info("instant text: typing was blocked, stopping")
                self.stop_event.set()

    def _trim(self):
        """Keep the re-read window short (each pass gets slower as it grows): start it after the last finished
        sentence that's already typed."""
        if self.recorder.duration - self.offset < TRIM_SECS:
            return
        cut = None
        for w in reversed(self.agree.committed):
            if w[2] <= self.offset:
                break
            if w[0].strip().endswith(SENTENCE_END):
                cut = w[2]
                break
        if cut is None and self.recorder.duration - self.offset >= HARD_TRIM_SECS and self.agree.committed \
                and self.agree.last_end > self.offset:
            cut = self.agree.last_end
        if cut is not None:
            self.offset = cut
            self.agree.pending = [w for w in self.agree.pending if w[1] >= cut]


# ---------------------------------------------------------------- checking before replacing (Windows)
def text_before_caret(n):
    """Up to `n` characters right before the cursor in the focused box, through UI Automation.
    Returns (text, exact): exact=False when only the whole box text was readable (cursor assumed at the end),
    or (None, False) if it can't be read (or it's a password box)."""
    comtypes = None
    try:
        from . import learn
        comtypes, U, uia = learn._uia()
        el = uia.GetFocusedElement()
        if not el or el.CurrentIsPassword:
            return None, False
        pat = el.GetCurrentPattern(10014)  # TextPattern
        if pat:
            tp = pat.QueryInterface(U.IUIAutomationTextPattern)
            sel = tp.GetSelection()
            if sel and sel.Length > 0:
                r = sel.GetElement(0).Clone()
                r.MoveEndpointByRange(1, r, 0)            # collapse to the cursor (End -> Start)
                r.MoveEndpointByUnit(0, 0, -(n + 64))     # Start back by characters
                return (r.GetText(-1) or "").replace("\r\n", "\n"), True
        pat = el.GetCurrentPattern(10002)  # ValuePattern
        if pat:
            value = pat.QueryInterface(U.IUIAutomationValuePattern).CurrentValue or ""
            return value.replace("\r\n", "\n"), False
    except Exception as e:
        log.info("instant text: couldn't read the box: %s", e)
    finally:
        if comtypes is not None:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
    return None, False


def is_password_box():
    comtypes = None
    try:
        from . import learn
        comtypes, _U, uia = learn._uia()
        el = uia.GetFocusedElement()
        return bool(el and el.CurrentIsPassword)
    except Exception:
        return False
    finally:
        if comtypes is not None:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def safe_to_replace(typed, before, exact, user_typed):
    """Decide whether the live text can be selected and replaced.
    before/exact: from text_before_caret. user_typed: the user pressed keys during the dictation."""
    if not typed:
        return True
    if before is None:
        return not user_typed          # can't read the box: trust it only if nobody touched the keyboard
    # same length, so selecting len(typed) characters still covers exactly it: web editors turn spaces into
    # non-breaking ones, and apps like Word capitalise a word as you type it
    tail = before.replace("\u00a0", " ")[-len(typed):]
    return len(tail) == len(typed) and tail.lower() == typed.lower()
