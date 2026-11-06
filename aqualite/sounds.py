"""Soft start/stop chimes, generated once into small WAV files."""
import os
import wave

import numpy as np

from .config import data_dir

RATE = 44100
_files = {}


def _tone(freqs, step=0.075, tail=0.9, vol=0.16):
    """Glassy Aero chime: bell partials per note, notes overlapping like a little arpeggio."""
    n = int(RATE * (step * len(freqs) + tail))
    out = np.zeros(n)
    t = np.arange(int(RATE * tail)) / RATE
    for i, f in enumerate(freqs):
        env = np.minimum(1, t / 0.004)
        note = sum(a * np.sin(2 * np.pi * f * m * t) * np.exp(-t * d)
                   for m, a, d in ((1, 1.0, 6), (2.76, 0.35, 11), (5.4, 0.12, 18), (0.5, 0.15, 5)))
        start = int(RATE * step * i)
        out[start:start + len(t)] += note * env
    out /= max(1e-6, np.max(np.abs(out)))
    return (out * vol * 32767).astype(np.int16)


def _make():
    d = os.path.join(data_dir(), "sounds")
    os.makedirs(d, exist_ok=True)
    for name, freqs in (("start", (1046.5, 1568.0)), ("stop", (1568.0, 1174.7)),
                        ("lock", (1046.5, 1318.5, 1568.0)), ("error", (523.3, 392.0))):
        p = os.path.join(d, name + "_aero.wav")
        if not os.path.exists(p):
            with wave.open(p, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(_tone(freqs).tobytes())
        _files[name] = p


def play(name):
    try:
        import winsound
        if not _files:
            _make()
        winsound.PlaySound(_files[name], winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass
