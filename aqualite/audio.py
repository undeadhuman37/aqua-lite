"""Microphone capture at 16 kHz mono (same format Wispr Flow's recorder worklet uses)."""
import threading
import time

import numpy as np

RATE = 16000
SPEECH_RMS = 0.012


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
        self.rate = RATE
        self.level = 0.0          # 0..1 for the Flow bar waveform
        self.speech_frames = 0
        self.started = 0.0
        self.lock = threading.Lock()

    def _cb(self, data, frames, _t, _status):
        mono = data[:, 0].copy()
        self.chunks.append(mono)
        rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
        if rms > SPEECH_RMS:
            self.speech_frames += frames
        self.level = min(1.0, rms * 12)

    def start(self, device_name=""):
        import sounddevice as sd
        with self.lock:
            self.stop_stream()
            self.chunks, self.speech_frames, self.level = [], 0, 0.0
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
            self.started = time.time()

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

    @property
    def active(self):
        return self.stream is not None
