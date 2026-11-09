"""Instant text: your words appear in the text box while you're still talking.

A small offline model (the same one behind live words) re-reads the recent audio about twice a second. A word is
typed only once two passes in a row hear it the same way (the "local agreement" policy from whisper_streaming), so
guesses rarely reach your text box.

Each sentence is tidied by the AI as soon as you've finished it (and started the next, which it gets as context
for corrections like "actually, make that Thursday"); the tidied sentence replaces the raw one in place. With the
quick processor model, each sentence's audio is first heard again by your main speech engine, so the final words
are as accurate as a normal dictation. When you
let go, only the end is left: one last pass over the audio, the last sentence tidied, done. With "double-check the
whole recording" on, the full recording goes through your normal engine and AI formatting instead, and the
polished text replaces everything typed live.

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

    def _fresh(self, words):
        new = [w for w in words if w[1] > self.last_end - 0.1]
        if new and self.committed and abs(new[0][1] - self.last_end) < 1.0:
            # the model often hears the last typed word(s) again at the start of the window: drop the repeat
            for n in range(min(5, len(new), len(self.committed)), 0, -1):
                if [norm(w[0]) for w in self.committed[-n:]] == [norm(w[0]) for w in new[:n]]:
                    new = new[n:]
                    break
        return new

    def insert_final(self, words):
        """The last pass after you let go: every word it hears is final (there's no next pass to agree with)."""
        new = self._fresh(words)
        self.committed += new
        self.pending = []
        return new

    def insert(self, words):
        """Feed one pass; returns the words that just became final."""
        new = self._fresh(words)
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


ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "eg", "ie", "jr", "sr", "fig", "approx", "no"}
CORRECTION_CUES = ("no wait", "actually", "scratch that", "sorry", "i mean", "make that", "change that",
                   "never mind", "nevermind", "forget that", "delete that", "take that back", "not ")


def sentence_ends(text):
    """Positions just past each sentence end in `text` that's followed by more words (so the sentence is over).
    Skips abbreviations and initials like 'Dr.' and 'J.'"""
    out = []
    for m in re.finditer(r"[.?!؟。][\"')\]”]*(?=\s+\S)", text):
        if m.group(0)[0] == ".":
            word = re.search(r"(\S+)$", text[:m.start()])
            w = (word.group(1) if word else "").lower().strip("(\"'")
            if w.replace(".", "") in ABBREVIATIONS or (len(w) == 1 and w.isalpha()):
                continue
        out.append(m.end())
    return out


def is_correction(text):
    t = " " + re.sub(r"[^\w\s]", " ", (text or "").lower()) + " "
    t = re.sub(r"\s+", " ", t)
    return any(" " + c in t for c in CORRECTION_CUES)


class Polisher:
    """Tidies each sentence with the AI while you're still talking, so letting go only finishes the last one.

    The engine feeds it the confirmed raw words (feed). Once a sentence is over and the next one is too, the first
    is sent to the AI with the next as context (so "...Friday. Actually, make that Thursday." still corrects it).
    compose(raw) gives what the box should show: tidied sentences, then the raw rest. finish() tidies whatever is
    left after you let go. Sentences are tidied one at a time, in order, on one background thread.

    polish(raw, before, after, span) -> text: `before` is the tidied text so far, `after` the next sentence (""
    at the end), `span` (start, end) seconds of the sentence's audio when the engine knows its word timings (end
    None = to the end of the recording), so the caller can hear it again with a better engine. It may raise; that
    sentence then stays as it was heard."""

    MIN_WORDS = 4     # shorter sentences ride along with the next one
    LOOKAHEAD = 1

    def __init__(self, polish):
        self.polish = polish
        self.segs = []        # [raw, tidied or None, next sentence, span]: the tidied part of the text, in order
        self.found = []       # finished raw sentences not handed out yet
        self.scanned = 0      # chars of the raw text split into segs + found
        self.cond = threading.Condition()
        self.changed = False
        self.closed = False
        self.gen = 0
        self.busy = False
        self.thread = threading.Thread(target=self._work, daemon=True, name="instant-polish")
        self.thread.start()

    @staticmethod
    def _raw_of(segs):
        return "".join(seg[0] for seg in segs)

    @staticmethod
    def _shown(segs):
        return "".join(seg[1] if seg[1] is not None else seg[0] for seg in segs)

    @staticmethod
    def span_of(spans, a, b):
        """Seconds of audio for characters a..b of the raw text, from the engine's word spans
        [(first char, end char, start s, end s), ...]: cut halfway into the pauses on each side, so neither
        neighbour's words leak in. b=None: to the end of the recording."""
        inside = [i for i, w in enumerate(spans) if w[0] >= a and (b is None or w[1] <= b)]
        if not spans or not inside:
            return None
        i, j = inside[0], inside[-1]
        start = (spans[i - 1][3] + spans[i][2]) / 2 if i > 0 else max(0.0, spans[i][2] - 0.25)
        if b is None:
            return start, None
        end = (spans[j][3] + spans[j + 1][2]) / 2 if j + 1 < len(spans) else spans[j][3] + 0.25
        return start, end

    def feed(self, stable, spans=None):
        """Confirmed raw text so far (it only ever grows), and its word spans if the engine has them."""
        with self.cond:
            if self.closed:
                return
            done = self._raw_of(self.segs) + "".join(self.found)
            if not stable.startswith(done):
                return   # shouldn't happen (confirmed words don't change); never guess
            for end in (e for e in sentence_ends(stable) if e > self.scanned):
                self.found.append(stable[self.scanned:end])
                self.scanned = end
            while len(self.found) > self.LOOKAHEAD:
                if len(self.found[0].split()) < self.MIN_WORDS:
                    self.found[0:2] = [self.found[0] + self.found[1]]
                    continue
                a = len(self._raw_of(self.segs))
                raw = self.found.pop(0)
                span = self.span_of(spans, a, a + len(raw)) if spans else None
                self.segs.append([raw, None, self.found[0].strip(), span])
                self.cond.notify_all()

    def _work(self):
        while True:
            with self.cond:
                while not self.closed and all(seg[1] is not None for seg in self.segs):
                    self.cond.wait()
                if self.closed:
                    return
                i = next(i for i, seg in enumerate(self.segs) if seg[1] is None)
                raw, after, span = self.segs[i][0], self.segs[i][2], self.segs[i][3]
                before = self._shown(self.segs[:i])
                gen = self.gen
                self.busy = True
            out = self._polish_one(raw, before, after, span)
            with self.cond:
                self.busy = False
                if gen == self.gen and i < len(self.segs) and self.segs[i][0] == raw:
                    self.segs[i][1] = out
                    self.changed = True
                self.cond.notify_all()

    def _polish_one(self, raw, before, after, span=None):
        lead = raw[:len(raw) - len(raw.lstrip())]
        try:
            out = (self.polish(raw.strip(), before, after, span) or "").strip()
        except Exception as e:
            log.info("instant text: couldn't tidy a sentence: %s", e)
            return raw
        if not out and not (is_correction(raw) or is_correction(after)):
            return raw   # an empty answer only makes sense for a sentence that was taken back
        # line breaks can't be typed safely (Enter sends the message in chat apps): spaces while you talk
        out = re.sub(r"\s*\n\s*", " ", out)
        return lead + out if out else ""

    def take_changed(self):
        with self.cond:
            ch, self.changed = self.changed, False
            return ch

    def compose(self, raw):
        """What the box should show for the raw text `raw`: the tidied sentences, then the rest as heard."""
        with self.cond:
            head = self._raw_of(self.segs)
            if not raw.startswith(head):
                return raw
            return (self._shown(self.segs) + raw[len(head):]).lstrip()

    def finish(self, raw, wait=2.5, spans=None):
        """After you let go: the whole tidied text for the final raw text, or None if it doesn't line up (then
        the caller formats everything the normal way). Waits a little for a sentence still being tidied; any
        that aren't back by then are tidied together with the end."""
        with self.cond:
            self.closed = True   # no new sentences; the worker stops after the one it's on
            self.cond.notify_all()
            end = time.monotonic() + wait
            while self.busy and time.monotonic() < end:
                self.cond.wait(end - time.monotonic())
            self.gen += 1        # a late answer is ignored
            done = []
            for seg in self.segs:
                if seg[1] is None:
                    break
                done.append(seg)
            head = self._raw_of(done)
            if not raw.startswith(head):
                return None
            prefix = self._shown(done)
        tail = raw[len(head):]
        if not tail.strip():
            return prefix.strip()
        lead = " " if prefix.strip() else ""
        span = self.span_of(spans, len(head), None) if spans else None
        try:
            out = (self.polish(tail.strip(), prefix, "", span) or "").strip()
        except Exception as e:
            log.info("instant text: couldn't tidy the end: %s", e)
            out = tail.strip()
        if not out and not is_correction(tail):
            out = tail.strip()
        return (prefix + (lead + out if out else "")).strip()


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
        self.polisher = None        # Polisher: tidies finished sentences in place while you talk
        self.unconfirmed = 0        # keys sent since the box last matched: the app may still be working through them

    def view(self, raw):
        """What the box should show for the raw words: with tidied sentences swapped in, when that's possible."""
        if self.polisher is None or not self.fixing:
            return raw
        return self.polisher.compose(raw)

    def feed_polisher(self, stable, spans=None):
        if self.polisher is not None and self.fixing:
            self.polisher.feed(stable, spans)

    def settle(self, want):
        """After you let go: make the box show exactly `want` (the finished, tidied text), changing only what
        differs. Same safety as while talking: the box must still end with what was typed. Returns True when the
        box shows `want`; False means nothing more was done (the caller falls back to select + paste)."""
        with self.lock:
            have = self.typed
            if want == have:
                return True
            if not (self.fixing and self.begun) or "\n" in want or "\r" in want:
                return False   # line breaks go in by pasting (typing Enter would send a chat message)
            keep = common_prefix(have, want)
            if keep < len(have):
                if keep < len(want):
                    keep = have.rfind(" ", 0, keep) + 1
                if not self._box_matches(have):
                    return False
                n = presses(have[keep:])
                if not self.delete_fn(n):
                    return False
                self.unconfirmed += n
                self.typed = have = have[:keep]
            add = want[len(have):]
            if add:
                if not self.type_fn(add):
                    return False
                self.unconfirmed += len(add)
                self.typed = want
            return True

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
                n = presses(have[keep:])
                if not self.delete_fn(n):
                    return self._halt("backspace was blocked")
                self.unconfirmed += n
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
                self.unconfirmed += len(piece)
                self.typed += piece
                if i < len(pieces) - 1:
                    time.sleep(gap)

    def _box_matches(self, have):
        """check(have), allowing for lag: after a burst of keys (a tidied sentence is a lot of Backspace and retyping)
        a busy app - web editors especially - shows the old text for a moment. Keep looking for a short while,
        longer the more keys are still on their way; only a box that never catches up has really been changed."""
        end = time.monotonic() + min(2.5, 0.3 + 0.004 * self.unconfirmed)
        tries = 0
        while True:
            got = self.check(have)
            tries += 1
            if got:
                if tries > 1:
                    log.info("instant text: the box caught up after %d checks (%d keys)", tries, self.unconfirmed)
                self.unconfirmed = 0
                return True
            if got is None or self.stop_event.is_set() or time.monotonic() >= end:
                return False
            time.sleep(0.05)

    def _safe_to_fix(self, have):
        if self._box_matches(have):
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
            if self.polisher is not None and self.polisher.take_changed():
                self.show(self.view(self.target()))
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
        self.feed_polisher(self.agree.text(), self.word_spans())
        self.show(self.view(self.target()))
        if self.on_caption:
            shown = self.agree.committed[-8:] + self.agree.pending
            self.on_caption(join_words(shown))
        self._trim()
        return True

    def word_spans(self):
        """(first char, end char, start s, end s) for each confirmed word, matching agree.text() exactly."""
        out, pos = [], 0
        for w in self.agree.committed:
            t = w[0].strip()
            if not t:
                continue
            if out:
                pos += 1
            out.append((pos, pos + len(t), w[1], w[2]))
            pos += len(t)
        return out

    def final_text(self, pcm):
        """After you let go: stop, then one last pass over the end of the recording (`pcm`, 16 kHz), keeping every
        word it hears. Returns the whole raw text: the confirmed words plus that end."""
        self.finish()
        try:
            audio = pcm[int(self.offset * RATE):]
            words = []
            if len(audio) >= RATE * 0.3:
                words = [(w, s + self.offset, e + self.offset)
                         for w, s, e in self.model.words(audio, self.cfg, self.prompt())]
                if words and stt.is_hallucination(join_words(words), 1.0):
                    words = []
            self.agree.insert_final(words)
        except Exception as e:
            log.info("instant text: last pass failed: %s", e)
        return self.agree.text()

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
            if self.polisher is not None and self.polisher.take_changed():
                self.show(self.view(self.target()))
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
                self.feed_polisher(" ".join(f.strip() for f in self.finals if f.strip()))
                self.show(self.view(self.target()))
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


def _norm(text):
    """Text as two apps would agree on it: same line breaks, plain spaces, any case, no trailing space."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").rstrip().lower()


def selected_text():
    """The selected text in the focused box (UI Automation), or None if it can't be read."""
    comtypes = None
    try:
        from . import learn
        comtypes, U, uia = learn._uia()
        el = uia.GetFocusedElement()
        if not el or el.CurrentIsPassword:
            return None
        pat = el.GetCurrentPattern(10014)  # TextPattern
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
        if comtypes is not None:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def wait_selected(typed, timeout, read=None, clock=time.monotonic, sleep=time.sleep):
    """After Shift+Left: wait until the app has caught up and `typed` is what's selected, so the paste replaces
    exactly the live words. Returns True (it matches), "settled" (the selection stopped growing but reads a
    little differently, e.g. emoji), False (timed out) or None (this box can't be read)."""
    read = read or selected_text
    want = _norm(typed)
    start = clock()
    last, since = None, start
    while True:
        got = read()
        if got is None:
            return None
        got = _norm(got)
        if got == want:
            return True
        now = clock()
        if got != last:
            last, since = got, now
        elif got and now - since >= 0.3:
            return "settled"
        if now - start >= timeout:
            return False
        sleep(0.03)


def pasted(text, read=None):
    """True once `text` sits right before the cursor in the focused box, False if not (yet), None if the box
    can't be read."""
    before, _exact = (read or text_before_caret)(len(text))
    if before is None:
        return None
    want = _norm(text)
    return not want or _norm(before).endswith(want)


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
