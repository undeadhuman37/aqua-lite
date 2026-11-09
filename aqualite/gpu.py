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
MODEL = "large-v3-turbo"
PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10", "nvidia-cuda-runtime-cu12"]
NEEDED_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")
IDLE_UNLOAD = 15 * 60
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


def detect():
    """(has_nvidia, name, memory_mb). Uses nvidia-smi, which comes with the NVIDIA driver."""
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
        self.model, self.name = None, None
        self.lock = threading.Lock()
        self.failed = None
        self.loading = False
        self.last_used = 0.0
        self.compute = "float16"
        threading.Thread(target=self._unload_when_idle, daemon=True, name="gpu-idle").start()

    def load(self):
        with self.lock:
            if self.model is not None:
                return self.model
            prepare()
            from faster_whisper import WhisperModel
            has, gname, mem = detect()
            # roomy cards get full precision; smaller ones int8 weights (about half the memory, same accuracy)
            self.compute = "float16" if (mem == 0 or mem >= 6000) else "int8_float16"
            m = WhisperModel(MODEL, device="cuda", compute_type=self.compute)
            silence = np.zeros(RATE, np.float32)
            list(m.transcribe(silence, language="en", beam_size=1)[0])   # first run: surfaces missing CUDA pieces now
            self.model, self.name = m, f"{MODEL} on {gname or 'GPU'} ({self.compute})"
            self.last_used = time.time()
            log.info("instant text: %s ready", self.name)
            return m

    def preload(self, cfg=None):
        if self.loading or self.model is not None:
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

    def unload(self):
        with self.lock:
            if self.model is not None:
                self.model = None
                log.info("instant text: freed the graphics card after %d idle minutes", IDLE_UNLOAD // 60)

    def _unload_when_idle(self):
        while True:
            time.sleep(60)
            if self.model is not None and time.time() - self.last_used > IDLE_UNLOAD and not self.loading:
                self.unload()

    def bench(self):
        audio = (np.random.RandomState(0).randn(RATE * 5) * 0.01).astype(np.float32)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            self.words(audio, {"language": "en"})
            times.append(time.perf_counter() - t0)
        return statistics.median(times)


GPU = GPUModel()
