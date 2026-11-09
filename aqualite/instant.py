"""Instant text: your words appear in the text box while you're still talking.

A small offline model (the same one behind live words) re-reads the recent audio about twice a second. A word is
typed only once two passes in a row hear it the same way (the "local agreement" policy from whisper_streaming), so
guesses rarely reach your text box. When you let go, the full recording goes through your normal engine and AI
formatting as always, and the polished text replaces what was typed live.

Before replacing anything, Aqua Lite checks that the text it typed is still right before the cursor (through
Windows UI Automation). If you clicked somewhere else or edited it in the meantime, nothing is deleted: the
polished version goes on the clipboard instead.
"""
import json
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
            agreed.append((b[0], a[1], a[2]))   # keep the spelling already on screen, so it isn't retyped
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


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class LiveTyper:
    """Keeps the text box in step with what's being heard, word by word. Shared by every instant-text engine.

    show(text) makes the box show `text`: new words are typed; when the newest words change (the engine heard them
    better), they're backspaced and retyped - but only after check(text) confirms the box still ends with exactly
    what was typed, so your own text is never touched. Boxes that can't be read get confirmed words only and never a
    backspace (the engine asks for those via self.fixing).

    type_fn(text) -> bool types; delete_fn(n) -> bool presses Backspace n times; check(text) -> True / False /
    None (can't read the box); before_first() runs once before the first word; allow() -> bool vetoes the box."""

    def __init__(self, type_fn, before_first=None, allow=None, delete_fn=None, check=None, on_caption=None):
        self.type_fn, self.before_first, self.on_caption = type_fn, before_first, on_caption
        self.delete_fn, self.check = delete_fn, check
        self.fixing = delete_fn is not None and check is not None   # may correct guesses (else confirmed only)
        self.begun = False          # the first word has gone in (allow / before_first done)
        self.allow = allow or (lambda: True)   # checked before the first word: e.g. not a password box
        self.typed = ""             # exactly what has been typed into the app
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.closed = False
        self.failed = None
        self.thread = None
        self.finished = False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="instant-text")
        self.thread.start()
        return self

    def _run(self):
        raise NotImplementedError

    def finish(self, wait=1.5):
        """Stop typing (call when recording stops). Returns exactly what was typed. Safe to call twice."""
        self.stop_event.set()
        with self.lock:
            self.closed = True
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(wait)
        if not self.finished:
            self.finished = True
            self.report()
        return self.typed

    def report(self):
        pass

    def show(self, want):
        with self.lock:
            if self.closed or self.stop_event.is_set():
                return
            have = self.typed
            if want == have or not want:
                return
            keep = common_prefix(have, want)
            if keep < len(have):
                if not self.fixing:
                    return
                if keep < len(want):   # redo whole words: back up to the start of the word that differs
                    keep = have.rfind(" ", 0, keep) + 1
                if not self._safe_to_fix(have):
                    return
                if not self.delete_fn(presses(have[keep:])):
                    return self._halt("backspace was blocked")
                self.typed = have = have[:keep]
            add = want[len(have):]
            if not add:
                return
            if not self.begun:
                if not self.allow():
                    return self._halt("not typing into this box")
                if self.fixing and self.check("") is None:
                    # can't read this box, so corrections couldn't be checked: confirmed words only, no backspace
                    log.info("instant text: can't read this box, typing confirmed words only")
                    self.fixing = False
                    return
                if self.before_first:
                    self.before_first()
                self.begun = True
            # one word at a time, so it reads like typing rather than chunks appearing
            pieces = re.findall(r"\s*\S+\s*", add) or [add]
            gap = min(0.05, 0.2 / max(1, len(pieces)))
            for i, piece in enumerate(pieces):
                if self.stop_event.is_set():
                    return
                if not self.type_fn(piece):
                    return self._halt("typing was blocked")
                self.typed += piece
                if i < len(pieces) - 1:
                    time.sleep(gap)

    def _safe_to_fix(self, have):
        if self.check(have):
            return True
        self._halt("the text box changed")   # a click, an edit, or it can't be read any more: hands off
        return False

    def _halt(self, why):
        log.info("instant text: %s, stopping", why)
        self.stop_event.set()


class Streamer(LiveTyper):
    """Local engines (the quick processor model, or Whisper on the graphics card): re-read the recent audio a few
    times a second; words two passes agree on are confirmed, the newest are shown as guesses."""

    def __init__(self, recorder, cfg, model, type_fn, before_first=None, on_caption=None, allow=None,
                 delete_fn=None, check=None, every=None):
        super().__init__(type_fn, before_first, allow, delete_fn, check, on_caption)
        self.recorder, self.cfg, self.model = recorder, cfg, model
        self.agree = Agreement()
        self.offset = 0.0           # where the re-read window starts (seconds into the recording)
        self.every = every or getattr(model, "every", None) or EVERY_SECS
        self.heard_upto = -1        # speech frames seen at the last pass: no new speech -> no pass (saves CPU/GPU)
        self.pass_secs = []          # how long each pass took, for the log

    def report(self):
        if self.pass_secs:
            ps = sorted(self.pass_secs)
            log.info("instant text: %d passes, median %.2fs, slowest %.2fs, model %s, typed %d chars",
                     len(ps), ps[len(ps) // 2], ps[-1], getattr(self.model, "name", "?"), len(self.typed))

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
            self.stop_event.wait(max(0.05, self.every - (time.perf_counter() - t0)))

    def prompt(self):
        tail = self.agree.text()[-PROMPT_CHARS:]
        return " ".join(p for p in (stt.vocab_prompt(self.cfg), tail) if p)

    def step(self):
        spoken = self.recorder.speech_frames
        if spoken <= 0 or (spoken == self.heard_upto and not self.agree.pending):
            return False   # nothing new said since the last pass and nothing left to confirm: skip the work
        audio = self.recorder.audio_from(self.offset)
        if len(audio) < RATE * MIN_SECS:
            return False
        self.heard_upto = spoken
        words = [(w, s + self.offset, e + self.offset) for w, s, e in self.model.words(audio, self.cfg, self.prompt())]
        heard = join_words(words)
        if heard and stt.is_hallucination(heard, 1.0):
            words = []
        self.agree.insert(words)
        self.show(self.target())
        if self.on_caption:
            shown = self.agree.committed[-8:] + self.agree.pending
            self.on_caption(join_words(shown))
        self._trim()
        return True

    def target(self):
        """What the box should show now: confirmed words, plus the newest guesses when they can be corrected."""
        words = self.agree.committed + (self.agree.pending if self.fixing else [])
        return join_words(words)

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


class DeepgramStreamer(LiveTyper):
    """Cloud engine: streams the microphone to Deepgram's live speech-to-text (Nova-3) and types its words as they
    arrive (~0.3 s). Deepgram sends 'interim' words that it refines, then final ones; the box shows finals plus the
    current interim. When you let go, its final transcript is used as the speech-to-text too, so the polished
    version comes back sooner. Needs a Deepgram API key (console.deepgram.com, free credit on sign-up)."""

    URL = "wss://api.deepgram.com/v1/listen"
    SEND_SECS = 0.08

    def __init__(self, recorder, cfg, key, type_fn, before_first=None, allow=None, delete_fn=None, check=None,
                 on_error=None, connect=None):
        super().__init__(type_fn, before_first, allow, delete_fn, check)
        self.recorder, self.cfg, self.key = recorder, cfg, key
        self.on_error = on_error or (lambda msg: None)
        self.connect = connect or self._connect
        self.finals, self.interim = [], ""
        self.sent = 0.0                      # seconds of audio sent so far
        self.ws = None
        self.receiver = None
        self.flushed = threading.Event()     # Deepgram answered our Finalize
        self.ready = threading.Event()       # connected (or failed)
        self.transcript = None

    def params(self):
        from urllib.parse import urlencode
        lang = self.cfg.get("language", "auto")
        q = [("model", "nova-3"), ("encoding", "linear16"), ("sample_rate", str(RATE)), ("channels", "1"),
             ("interim_results", "true"), ("punctuate", "true"), ("smart_format", "true"), ("endpointing", "300"),
             ("language", "multi" if lang in ("auto", "", None) else lang)]
        q += [("keyterm", w) for w in (self.cfg.get("dictionary") or [])[:50] if w.strip()]
        return urlencode(q)

    def _connect(self):
        import websocket   # websocket-client
        return websocket.create_connection(f"{self.URL}?{self.params()}", timeout=10,
                                           header=[f"Authorization: Token {self.key}"])

    def target(self):
        parts = self.finals + ([self.interim] if (self.fixing and self.interim) else [])
        return " ".join(p.strip() for p in parts if p.strip())

    def _run(self):
        try:
            self.ws = self.connect()
        except Exception as e:
            self.failed = str(e)
            msg = str(e)
            log.warning("instant text: Deepgram connection failed: %s", msg)
            if isinstance(e, ImportError):
                self.on_error("Instant text is finishing its setup - try again in a minute")
            else:
                self.on_error("Deepgram key was rejected - check it in Settings" if ("401" in msg or "403" in msg)
                              else "Couldn't reach Deepgram for instant text")
            self.ready.set()
            self.flushed.set()
            return
        self.ready.set()
        self.receiver = threading.Thread(target=self._receive, daemon=True, name="deepgram-recv")
        self.receiver.start()
        while not self.stop_event.is_set():
            self._send_new_audio()
            self.stop_event.wait(self.SEND_SECS)

    def _send_new_audio(self):
        audio = self.recorder.audio_from(self.sent)
        if len(audio):
            import numpy as np
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            self.ws.send_binary(pcm)
            self.sent += len(audio) / RATE

    def _receive(self):
        try:
            while True:
                msg = self.ws.recv()
                if not msg:
                    break
                if isinstance(msg, bytes):
                    continue
                data = json.loads(msg)
                if data.get("type") != "Results":
                    continue
                alts = (data.get("channel") or {}).get("alternatives") or [{}]
                text = (alts[0].get("transcript") or "").strip()
                if data.get("is_final"):
                    if text:
                        self.finals.append(text)
                    self.interim = ""
                else:
                    self.interim = text
                if data.get("from_finalize"):
                    self.flushed.set()
                self.show(self.target())
        except Exception as e:
            if not self.closed:
                log.info("instant text: Deepgram stream ended: %s", e)
        finally:
            self.flushed.set()

    def final_transcript(self, wait=1.5):
        """Stop typing, send the last bit of audio, ask Deepgram to finalize, and return its whole transcript
        ('' if it isn't available - then the normal engine transcribes)."""
        self.finish(0)
        if self.thread:
            self.thread.join(1.0)        # the sender has stopped; the socket is ours now
        if self.transcript is not None:
            return self.transcript
        self.transcript = ""
        if self.ws is None or self.failed:
            return ""
        try:
            self._send_new_audio()
            self.ws.send(json.dumps({"type": "Finalize"}))
            self.flushed.wait(wait)
            self.ws.send(json.dumps({"type": "CloseStream"}))
        except Exception as e:
            log.info("instant text: Deepgram finalize failed: %s", e)
        finally:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.flushed.is_set():
            self.transcript = " ".join(f.strip() for f in self.finals if f.strip())
        return self.transcript

    def report(self):
        log.info("instant text: Deepgram, %.1fs streamed, %d final segments, typed %d chars",
                 self.sent, len(self.finals), len(self.typed))


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
