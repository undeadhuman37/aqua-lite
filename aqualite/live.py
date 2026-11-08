"""Live words: while you talk, a small fast offline model keeps transcribing the last few seconds so the
Flow bar can show what it's hearing. It's only a preview - the real transcription still runs when you let go,
with your chosen engine - so it never costs API calls and never changes what gets typed."""
import logging
import os
import statistics
import threading
import time

import numpy as np

from . import stt

log = logging.getLogger("aqualite")
RATE = 16000
WINDOW_SECS = 6.0     # how much recent audio each preview pass looks at
EVERY_SECS = 0.7      # how often to refresh


class PreviewModel:
    """Its own small model, separate from the main one, so previews never queue in front of the real thing."""

    def __init__(self, threads=2):
        self.model, self.name = None, None
        self.threads = threads
        self.lock = threading.Lock()
        self.failed = False

    def load(self, name):
        with self.lock:
            if self.model is not None and self.name == name:
                return self.model
            from faster_whisper import WhisperModel
            self.model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=self.threads)
            self.name = name
            log.info("live preview model %s ready (%d threads)", name, self.threads)
            return self.model

    def preload(self, cfg):
        def run():
            try:
                self.load(cfg.get("live_preview_model", "base"))
            except Exception as e:
                self.failed = True
                log.warning("live preview unavailable: %s", e)
        threading.Thread(target=run, daemon=True, name="preview-load").start()

    def transcribe(self, audio, cfg):
        model = self.load(cfg.get("live_preview_model", "base"))
        lang = None if cfg.get("language", "auto") == "auto" else cfg["language"]
        segs, _ = model.transcribe(audio, language=lang, beam_size=1, vad_filter=False, without_timestamps=True,
                                   condition_on_previous_text=False, initial_prompt=stt.vocab_prompt(cfg) or None)
        return " ".join(s.text.strip() for s in segs).strip()


    def words(self, audio, cfg, prompt=""):
        """Words with their timings [(text, start, end), ...] (seconds into `audio`), for instant text.
        Silence is skipped with the VAD that ships inside faster-whisper, so pauses don't turn into
        Whisper's made-up 'Thank you.'"""
        model = self.model or self.load(cfg.get("live_preview_model", "base"))
        lang = None if cfg.get("language", "auto") == "auto" else cfg["language"]
        segs, _ = model.transcribe(audio, language=lang, beam_size=1, word_timestamps=True,
                                   vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                                   condition_on_previous_text=False, initial_prompt=prompt or None)
        return [(w.word, float(w.start), float(w.end)) for s in segs for w in (s.words or [])]


class InstantModel(PreviewModel):
    """The model behind instant text. 'auto' picks the more accurate "small" model when this PC runs it fast enough
    (timed once at startup), otherwise the quick "base" one. Uses more processor threads than the bar preview."""
    FAST_ENOUGH = 0.45   # seconds per pass: word-by-word needs quick passes (the final swap fixes accuracy)

    def __init__(self):
        super().__init__(threads=max(2, min(8, (os.cpu_count() or 4) // 2)))
        self.loading = False

    def preload(self, cfg):
        if self.loading or self.failed:
            return
        self.loading = True

        def run():
            try:
                self.choose(cfg)
            except Exception as e:
                self.failed = True
                log.warning("instant text model unavailable: %s", e)
            finally:
                self.loading = False
        threading.Thread(target=run, daemon=True, name="instant-load").start()

    def choose(self, cfg):
        want = cfg.get("instant_text_model", "auto")
        if want != "auto":
            self.load(want)
            return
        try:
            self.load("small")
            secs = self.bench()
            log.info("instant text: small model takes %.2fs a pass here", secs)
            if secs <= self.FAST_ENOUGH:
                return
        except Exception as e:
            log.info("instant text: small model unavailable (%s)", e)
        self.load("base")

    def bench(self):
        """Median time of a pass over 5 s of quiet noise (the encoder dominates, so it's a fair speed check)."""
        audio = (np.random.RandomState(0).randn(RATE * 5) * 0.01).astype(np.float32)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            segs, _ = self.model.transcribe(audio, language="en", beam_size=1, word_timestamps=True,
                                            vad_filter=False, condition_on_previous_text=False)
            list(segs)
            times.append(time.perf_counter() - t0)
        return statistics.median(times)


PREVIEW = PreviewModel()
INSTANT = InstantModel()


def tidy(text, cut_off):
    """Clean a preview: drop Whisper's silence hallucinations, and the first word when the window started
    mid-word (cut_off)."""
    text = " ".join((text or "").split())
    if not text or stt.is_hallucination(text, 1.0) or text.strip(" .") == "":
        return ""
    if cut_off and " " in text:
        text = text.split(" ", 1)[1]
    return text


class LiveCaption:
    def __init__(self, recorder, cfg, on_text):
        self.recorder, self.cfg, self.on_text = recorder, cfg, on_text
        self.stop_event = threading.Event()

    def start(self):
        self.stop()
        if not self.cfg.get("live_preview", True) or PREVIEW.failed:
            return
        if PREVIEW.model is None:  # still loading (or first run downloading): no preview this time
            if not PREVIEW.lock.locked():
                PREVIEW.preload(self.cfg)
            return
        self.stop_event = threading.Event()
        threading.Thread(target=self._run, args=(self.stop_event,), daemon=True, name="live-caption").start()

    def stop(self):
        self.stop_event.set()

    def _run(self, stop):
        stop.wait(0.6)
        last = ""
        while not stop.is_set():
            t0 = time.perf_counter()
            try:
                audio = self.recorder.snapshot(WINDOW_SECS)
                if len(audio) > RATE * 0.5 and self.recorder.speech_frames > 0:
                    text = tidy(PREVIEW.transcribe(audio, self.cfg), len(audio) >= RATE * WINDOW_SECS * 0.98)
                    if text and text != last and not stop.is_set():
                        last = text
                        self.on_text(text)
            except Exception as e:
                log.warning("live preview: %s", e)
                return
            stop.wait(max(0.2, EVERY_SECS - (time.perf_counter() - t0)))
