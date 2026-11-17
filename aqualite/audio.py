"""Microphone capture at 16 kHz mono (same format Wispr Flow's recorder worklet uses)."""
import threading
import time

import numpy as np

RATE = 16000
SPEECH_RMS = 0.012
QUIET_RMS = 0.007   # below this counts as silence for hands-free auto-stop (lower than SPEECH_RMS: whispering counts)


def list_input_devices():
    import sounddevice as sd
    try:
        host = sd.default.hostapi
        return [d["name"] for d in sd.query_devices()
                if d["max_input_channels"] > 0 and d["hostapi"] == host]
    except Exception:
        return []


def _device_index(name):
    if not name:
        return None
    import sounddevice as sd
    host = sd.default.hostapi
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name and d["max_input_channels"] > 0 and d["hostapi"] == host:
            return i
    return None


def resample(x, src, dst=RATE):
    if src == dst or len(x) == 0:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def boost(audio):
    """Auto-gain so quiet or whispered speech reaches the recognizer at a normal level."""
    if len(audio) == 0:
        return audio
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio)))
    if 0.003 < peak < 0.5:
        audio = audio * min(0.7 / peak, 25.0)
    return np.clip(audio, -1, 1).astype(np.float32)


class Recorder:
    def __init__(self):
        self.stream = None
        self.chunks = []
        self.total = 0            # samples recorded so far (at self.rate)
        self.rate = RATE
        self.level = 0.0          # 0..1 for the Flow bar waveform
        self.speech_frames = 0
        self.started = 0.0
        self.last_sound = 0.0     # time.time() of the last non-silent block
        self.lock = threading.Lock()

    def _cb(self, data, frames, _t, _status):
        mono = data[:, 0].copy()
        self.chunks.append(mono)
        self.total += len(mono)
        rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
        if rms > SPEECH_RMS:
            self.speech_frames += frames
        if rms > QUIET_RMS:
            self.last_sound = time.time()
        self.level = min(1.0, rms * 12)

    def start(self, device_name=""):
        import sounddevice as sd
        with self.lock:
            self.stop_stream()
            self.chunks, self.speech_frames, self.level, self.total = [], 0, 0.0, 0
            dev = _device_index(device_name)
            try:
                self.rate = RATE
                self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                             device=dev, blocksize=640, callback=self._cb)
            except Exception:
                info = sd.query_devices(dev if dev is not None else sd.default.device[0], "input")
                self.rate = int(info["default_samplerate"])
                self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                             device=dev, callback=self._cb)
            self.stream.start()
            self.started = self.last_sound = time.time()

    def stop_stream(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def stop(self):
        with self.lock:
            self.stop_stream()
            audio = np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)
            self.chunks = []
            self.level = 0.0
            return resample(audio, self.rate), self.speech_frames / max(self.rate, 1)

    def take(self):
        """Hand over what's been recorded and keep recording (voice commands: one command at a time).
        Like stop(), returns (audio at 16 kHz, seconds of speech)."""
        chunks, self.chunks = self.chunks, []
        speech, self.speech_frames, self.total = self.speech_frames, 0, 0
        audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
        return resample(audio, self.rate), speech / max(self.rate, 1)

    def snapshot(self, max_secs):
        """The last `max_secs` of audio so far, at 16 kHz, without stopping (for the live preview)."""
        chunks = list(self.chunks)
        if not chunks:
            return np.zeros(0, np.float32)
        need, got, take = int(max_secs * self.rate), 0, []
        for c in reversed(chunks):
            take.append(c)
            got += len(c)
            if got >= need:
                break
        audio = np.concatenate(take[::-1])[-need:]
        return resample(audio, self.rate)

    @property
    def duration(self):
        """Seconds recorded so far."""
        return self.total / max(self.rate, 1)

    def audio_from(self, start_secs):
        """Audio from `start_secs` into the recording up to now, at 16 kHz, without stopping (for instant text).
        Walks back from the newest chunk, so it stays cheap even deep into a long hands-free session."""
        chunks = list(self.chunks)
        total = sum(map(len, chunks))   # from the same snapshot, so timings line up exactly
        want = total - int(max(0.0, start_secs) * self.rate)
        if want <= 0 or not chunks:
            return np.zeros(0, np.float32)
        got, take = 0, []
        for c in reversed(chunks):
            take.append(c)
            got += len(c)
            if got >= want:
                break
        audio = np.concatenate(take[::-1])[-want:]
        return resample(audio, self.rate)

    @property
    def silent_for(self):
        return time.time() - self.last_sound if self.active else 0.0

    @property
    def active(self):
        return self.stream is not None
