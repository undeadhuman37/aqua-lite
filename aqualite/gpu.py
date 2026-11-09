"""Instant text on an NVIDIA graphics card: Whisper large-v3-turbo through faster-whisper on CUDA, accurate enough
that the live words are nearly the final text.

Needs an NVIDIA card (about 4 GB of graphics memory or more) and its normal driver. The CUDA pieces faster-whisper
needs (cuBLAS and cuDNN 9 for CUDA 12) come as NVIDIA's own packages from PyPI, installed into Aqua Lite's private
Python with one click in Settings (about 1 GB), plus the model itself (about 1.6 GB) on first use.

Light on the card: it only works while you're talking (passes skip silence), and the model is unloaded from
graphics memory after IDLE_UNLOAD minutes without a dictation, then loaded again when you next talk.
"""
import glob
import logging
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time

import numpy as np

log = logging.getLogger("aqualite")
IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0
MODEL = "large-v3-turbo"     # the default pick
# Whisper models for the graphics card: graphics memory needed at full precision (float16), download size,
# languages. int8_float16 roughly halves the memory with about the same accuracy, so smaller cards can still run
# a bigger model.
MODELS = {
    "small": {"label": "Small", "vram": 1000, "size": 500, "note": "fastest, least accurate", "english": False},
    "distil-large-v3": {"label": "Distil large-v3", "vram": 1500, "size": 1500, "note": "very fast, English only",
                        "english": True},
    "large-v3-turbo": {"label": "Large-v3 turbo", "vram": 2000, "size": 1600, "note": "best balance", "english": False},
    "large-v3": {"label": "Large-v3", "vram": 4500, "size": 3100, "note": "most accurate, slower", "english": False},
}
PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10", "nvidia-cuda-runtime-cu12"]
NEEDED_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")
IDLE_UNLOAD = 5 * 60          # default; Settings > Instant text has a slider (0 = keep it loaded)
RATE = 16000


def lib_dirs():
    """Folders holding NVIDIA's DLLs from the pip packages (site-packages/nvidia/*/bin)."""
    dirs = []
    for sp in {p for p in sys.path if p.endswith("site-packages")}:
        dirs += [d for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")) if os.path.isdir(d)]
    return sorted(set(dirs))


_prepared = False


def prepare():
    """Make NVIDIA's DLLs findable before CUDA is first used (call early; harmless if not installed)."""
    global _prepared
    if _prepared or not IS_WIN:
        return
    dirs = lib_dirs()
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
    _prepared = True


def libraries_installed():
    found = {f.lower() for d in lib_dirs() for f in os.listdir(d)}
    return all(n in found for n in NEEDED_DLLS)


_detected = {"at": -1e9, "value": None}


def detect():
    """(has_nvidia, name, memory_mb), remembered for a minute (it asks nvidia-smi)."""
    if _detected["value"] is not None and time.time() - _detected["at"] < 60:
        return _detected["value"]
    _detected.update(value=_detect(), at=time.time())
    return _detected["value"]


def _detect():
    """Uses nvidia-smi, which comes with the NVIDIA driver."""
    smi = shutil.which("nvidia-smi") or (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                                      "nvidia-smi.exe") if IS_WIN else None)
    if smi and os.path.exists(smi):
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW).stdout
            line = out.strip().splitlines()[0]
            name, mem = [x.strip() for x in line.rsplit(",", 1)]
            return True, name, int(float(mem))
        except Exception:
            pass
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return True, "NVIDIA graphics card", 0
    except Exception:
        pass
    return False, "", 0


def recommend(mem_mb, language="auto"):
    """The best model this card can run comfortably (memory in MB; 0 = unknown)."""
    if not mem_mb:
        return MODEL
    if mem_mb >= 3500:   # turbo even on big cards: nearly large-v3's accuracy at several times the speed
        return "large-v3-turbo"
    if mem_mb >= 2500 and language in ("en", "auto"):
        return "large-v3-turbo"
    return "small"


def compute_for(name, mem_mb):
    """Full precision when the card has plenty of room for this model, else int8 weights (about half the memory)."""
    need = MODELS.get(name, MODELS[MODEL])["vram"]
    return "float16" if (mem_mb == 0 or mem_mb >= need * 1.6) else "int8_float16"


def fits(name, mem_mb):
    return not mem_mb or mem_mb >= MODELS[name]["vram"] * 0.6   # with int8 weights


def choice_label(name, mem_mb, best):
    m = MODELS[name]
    tag = "  - recommended for your card" if name == best else ("  - too big for your card" if not fits(name, mem_mb)
                                                                 else "")
    return f"{m['label']} ({m['note']}, ~{m['vram'] / 1000:.1f} GB, {m['size'] / 1000:.1f} GB download){tag}"


def install_libraries(log_line=None):
    """pip install NVIDIA's CUDA 12 libraries into Aqua Lite's Python (about 1 GB). Raises on failure."""
    from .updater import console_python
    cmd = [console_python(), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off"] + PACKAGES
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
    tail = []
    for line in p.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-8:]
            if log_line:
                log_line(line)
    if p.wait() != 0:
        raise RuntimeError("installing NVIDIA libraries failed: " + " | ".join(tail)[-300:])
    global _prepared
    _prepared = False
    prepare()


class GPUModel:
    """Same interface as the processor preview model (words()), running on the graphics card."""
    every = 0.25    # passes are fast on a GPU

    def __init__(self):
        self.model, self.name, self.key = None, None, None
        self.lock = threading.Lock()
        self.failed = None
        self.loading = False
        self.last_used = 0.0
        self.compute = "float16"
        self.want = "auto"           # cfg["gpu_model"]
        self.idle_secs = IDLE_UNLOAD
        threading.Thread(target=self._unload_when_idle, daemon=True, name="gpu-idle").start()

    def configure(self, cfg):
        """Take the model choice and idle time from settings (a different model is loaded on next use)."""
        self.want = cfg.get("gpu_model", "auto") or "auto"
        mins = float(cfg.get("gpu_idle_minutes", IDLE_UNLOAD / 60) or 0)
        self.idle_secs = max(0.0, mins) * 60
        if self.model is not None and self.key != self.pick()[0]:
            self.unload("switching models")

    def pick(self):
        """(model name, card name, memory MB) for the current setting."""
        has, gname, mem = detect()
        key = self.want if self.want in MODELS else recommend(mem)
        return key, gname, mem

    def load(self):
        with self.lock:
            key, gname, mem = self.pick()
            if self.model is not None and self.key == key:
                return self.model
            self.model = None
            prepare()
            from faster_whisper import WhisperModel
            self.compute = compute_for(key, mem)
            m = WhisperModel(key, device="cuda", compute_type=self.compute)
            silence = np.zeros(RATE, np.float32)
            list(m.transcribe(silence, language="en", beam_size=1)[0])   # first run: surfaces missing CUDA pieces now
            self.model, self.key = m, key
            self.name = f"{key} on {gname or 'GPU'} ({self.compute})"
            self.last_used = time.time()
            log.info("instant text: %s ready", self.name)
            return m

    def preload(self, cfg=None):
        if cfg is not None:
            self.configure(cfg)
        if self.loading or (self.model is not None and self.key == self.pick()[0]):
            return
        self.loading = True

        def run():
            try:
                self.load()
                self.failed = None
            except Exception as e:
                self.failed = str(e)
                log.warning("instant text: graphics card model unavailable: %s", e)
            finally:
                self.loading = False
        threading.Thread(target=run, daemon=True, name="gpu-load").start()

    def words(self, audio, cfg, prompt=""):
        model = self.model or self.load()
        self.last_used = time.time()
        lang = None if cfg.get("language", "auto") == "auto" else cfg["language"]
        segs, _ = model.transcribe(audio, language=lang, beam_size=1, word_timestamps=True,
                                   vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                                   condition_on_previous_text=False, initial_prompt=prompt or None)
        return [(w.word, float(w.start), float(w.end)) for s in segs for w in (s.words or [])]

    def touch(self):
        self.last_used = time.time()

    def unload(self, why="idle"):
        with self.lock:
            if self.model is not None:
                self.model = None
                import gc
                gc.collect()   # drop the last references now, so CTranslate2 returns the graphics memory at once
                log.info("instant text: freed the graphics card (%s)", why)

    def _unload_when_idle(self):
        while True:
            time.sleep(20)
            if (self.model is not None and self.idle_secs > 0 and not self.loading
                    and time.time() - self.last_used > self.idle_secs):
                self.unload(f"{self.idle_secs / 60:.0f} minutes without talking")

    def bench(self):
        audio = (np.random.RandomState(0).randn(RATE * 5) * 0.01).astype(np.float32)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            self.words(audio, {"language": "en"})
            times.append(time.perf_counter() - t0)
        return statistics.median(times)


GPU = GPUModel()
