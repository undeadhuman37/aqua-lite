"""Music while you talk: plays a random part of a song from your music folder, softly, while you dictate.

Put any songs you own (mp3, m4a, flac, ogg, wav, opus, aac) in %APPDATA%\\AquaLite\\music,
or point Settings at another folder. Decoding uses PyAV (installed with faster-whisper).
"""
import os
import random
import threading

import numpy as np

from .config import data_dir

SR = 44100
EXTS = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma", ".webm")
SEGMENT_SECONDS = 150
FADE_IN, FADE_OUT = 1.5, 0.9


def default_folder():
    d = os.path.join(data_dir(), "music")
    os.makedirs(d, exist_ok=True)
    return d


def list_songs(folder):
    out = []
    for root, _dirs, files in os.walk(folder or default_folder()):
        out += [os.path.join(root, f) for f in files if f.lower().endswith(EXTS)]
    return sorted(out)


def duration_of(path):
    import av
    with av.open(path) as c:
        return float(c.duration / av.time_base) if c.duration else 0.0


def pick_start(duration, recent, seconds=SEGMENT_SECONDS, gap=360.0, rng=random):
    """Random start point. In long mixes, stay `gap` seconds away from recently played spots,
    so each dictation lands on a different song."""
    if duration <= 40:
        return 0.0
    lo, hi = duration * 0.04, max(duration * 0.04, duration - seconds * 0.5)
    best, best_dist = None, -1.0
    for _ in range(40):
        s = rng.uniform(lo, hi)
        dist = min((abs(s - r) for r in recent), default=1e9)
        if dist >= gap or duration < gap * 3:
            return s
        if dist > best_dist:
            best, best_dist = s, dist
    return best


def decode_segment(path, seconds=SEGMENT_SECONDS, start=None):
    """Decode `seconds` of audio from a random point (skipping intros/outros) -> float32 stereo @ 44.1 kHz."""
    import av
    with av.open(path) as c:
        stream = next(s for s in c.streams if s.type == "audio")
        dur = float(c.duration / av.time_base) if c.duration else 0.0
        if start is None:
            start = random.uniform(dur * 0.08, max(dur * 0.08, dur * 0.75 - seconds * 0.3)) if dur > 40 else 0.0
        if start > 0:
            c.seek(int(start * av.time_base), any_frame=False, backward=True)
        res = av.AudioResampler(format="flt", layout="stereo", rate=SR)
        need, chunks, got = int(seconds * SR), [], 0
        for frame in c.decode(stream):
            for f in res.resample(frame):
                a = f.to_ndarray()
                a = a.reshape(-1, 2) if a.ndim == 2 and a.shape[0] == 1 else a.T
                chunks.append(a.astype(np.float32))
                got += len(a)
            if got >= need:
                break
    if not chunks:
        return np.zeros((0, 2), np.float32)
    data = np.concatenate(chunks)[:need]
    peak = float(np.max(np.abs(data))) or 1.0
    return data / max(peak, 0.3) * 0.9  # level-match quiet and loud songs


class MusicPlayer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stream = None
        self.lock = threading.Lock()
        self.buf = None          # current segment
        self.pos = 0
        self.gain = 0.0          # fade envelope 0..1
        self.target = 0.0
        self.next_buf = None     # pre-decoded next segment so playback starts instantly
        self.next_name = ""
        self.now_playing = ""
        self.last_path = None
        self.recent = {}         # path -> recent start points, so we don't replay the same part
        self._prepare_next()

    # ---------------------------------------------------------------- loading
    def _pick(self):
        songs = list_songs(self.cfg.get("music_folder") or default_folder())
        if not songs:
            return None
        if len(songs) > 1 and self.last_path in songs:
            songs.remove(self.last_path)  # never the same song twice in a row
        return random.choice(songs)

    def _prepare_next(self):
        def work():
            path = self._pick()
            if not path:
                return
            try:
                hist = self.recent.setdefault(path, [])
                start = pick_start(duration_of(path), hist)
                hist[:] = (hist + [start])[-12:]
                buf = decode_segment(path, start=start)
                with self.lock:
                    self.next_buf, self.next_name, self.last_path = buf, os.path.basename(path), path
            except Exception as e:  # unreadable file: skip it next time
                print("music: could not decode", path, e)
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- playback
    def _volume(self):
        return max(0, min(100, int(self.cfg.get("music_volume", 30)))) / 100.0

    def _cb(self, out, frames, _t, _status):
        with self.lock:
            buf = self.buf
            if buf is None or len(buf) == 0:
                out.fill(0)
                return
            idx = (np.arange(frames) + self.pos) % len(buf)  # loop the segment if you talk a long time
            chunk = buf[idx]
            self.pos = (self.pos + frames) % len(buf)
            # per-sample fade towards target
            step_in, step_out = 1.0 / (FADE_IN * SR), 1.0 / (FADE_OUT * SR)
            if self.target > self.gain:
                env = np.minimum(self.target, self.gain + step_in * np.arange(1, frames + 1))
            else:
                env = np.maximum(self.target, self.gain - step_out * np.arange(1, frames + 1))
            self.gain = float(env[-1])
            vol = self._volume()
        out[:] = chunk * (env[:, None] ** 2 * vol)  # squared envelope sounds smoother

    def start(self):
        if not self.cfg.get("music_enabled", True):
            return False
        import sounddevice as sd
        with self.lock:
            if self.next_buf is None or len(self.next_buf) == 0:
                self._prepare_next()  # nothing ready yet (empty folder or still decoding)
                return False
            self.buf, self.pos, self.now_playing = self.next_buf, 0, self.next_name
            self.next_buf = None
            self.gain, self.target = 0.0, 1.0
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32", callback=self._cb,
                                          blocksize=1024, latency="high")
            self.stream.start()
        self._prepare_next()
        return True

    def stop(self):
        with self.lock:
            self.target = 0.0
        threading.Timer(FADE_OUT + 0.3, self._close_if_silent).start()

    def _close_if_silent(self):
        with self.lock:
            silent = self.target == 0.0 and self.gain <= 0.001
        if silent and self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def preview(self, seconds=6):
        if self.start():
            threading.Timer(seconds, self.stop).start()
            return True
        return False
