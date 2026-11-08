"""Speech to text: Groq / OpenAI cloud, or faster-whisper running on this PC."""
import io
import threading
import wave

import numpy as np
import requests

RATE = 16000
# Whisper invents these on silent / near-silent audio.
ALWAYS_FAKE = {"thanks for watching!", "thanks for watching.", "thank you for watching.", ".",
               "subtitles by the amara.org community", "اشتركوا في القناة", "ترجمة نانسي قنقر"}
FAKE_IF_QUIET = {"thank you.", "thank you", "you", "bye.", "bye", "شكرا", "شكراً", "شكرا لكم"}


def is_hallucination(text, speech_seconds):
    t = text.strip().lower()
    return t in ALWAYS_FAKE or (t in FAKE_IF_QUIET and speech_seconds < 0.3)


class STTError(Exception):
    pass


def to_wav(audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def vocab_prompt(cfg, hints=()):
    """Spelling hints for the speech model: your dictionary, then names seen on screen (screen context)."""
    words = [w for w in (cfg.get("dictionary") or []) if w.strip()]
    have = {w.lower() for w in words}
    words += [h for h in hints if h.strip() and h.lower() not in have]
    return (", ".join(words) + ".")[:800] if words else ""


def resolve_engine(cfg):
    if cfg.get("private_mode"):
        return "local"   # private mode: speech never leaves the PC either
    e = cfg.get("stt_engine", "auto")
    if e == "auto":
        if cfg.get("groq_api_key"):
            return "groq"
        if cfg.get("openai_api_key"):
            return "openai"
        return "local"
    return e


def _cloud(url, key, model, audio, cfg, hints=()):
    data = {"model": model, "response_format": "json", "temperature": "0"}
    if cfg.get("language", "auto") != "auto":
        data["language"] = cfg["language"]
    p = vocab_prompt(cfg, hints)
    if p:
        data["prompt"] = p
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, data=data,
                          files={"file": ("audio.wav", to_wav(audio), "audio/wav")}, timeout=30)
    except requests.RequestException as e:
        raise STTError(f"network: {e}") from e
    if r.status_code != 200:
        raise STTError(f"{r.status_code}: {r.text[:300]}")
    return (r.json().get("text") or "").strip()


class LocalWhisper:
    def __init__(self):
        self.model = None
        self.key = None
        self.lock = threading.Lock()
        self.status = "not loaded"

    def load(self, cfg):
        key = (cfg.get("local_model", "small"), cfg.get("local_device", "auto"))
        with self.lock:
            if self.model is not None and self.key == key:
                return self.model
            from faster_whisper import WhisperModel
            name, device = key
            self.status = f"loading {name}..."
            model = None
            if device in ("auto", "cuda"):
                try:
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() > 0:
                        model = WhisperModel(name, device="cuda", compute_type="float16")
                        model.transcribe(np.zeros(RATE, np.float32))  # fails here if cuDNN DLLs are missing
                except Exception:
                    model = None
                    if device == "cuda":
                        self.status = "CUDA failed, using CPU"
            if model is None:
                model = WhisperModel(name, device="cpu", compute_type="int8")
            self.model, self.key = model, key
            self.status = f"{name} ready ({'GPU' if model.model.device == 'cuda' else 'CPU'})"
            return model

    def transcribe(self, audio, cfg, hints=()):
        model = self.load(cfg)
        lang = None if cfg.get("language", "auto") == "auto" else cfg["language"]
        segs, _ = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1,
                                   initial_prompt=vocab_prompt(cfg, hints) or None,
                                   condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()


LOCAL = LocalWhisper()


def transcribe(audio, cfg, hints=()):
    """Returns (text, engine_used). `hints`: extra words to spell right (names seen on screen)."""
    engine = resolve_engine(cfg)
    try:
        if engine == "groq":
            text = _cloud("https://api.groq.com/openai/v1/audio/transcriptions", cfg["groq_api_key"],
                          cfg["groq_stt_model"], audio, cfg, hints)
        elif engine == "openai":
            text = _cloud("https://api.openai.com/v1/audio/transcriptions", cfg["openai_api_key"],
                          cfg["openai_stt_model"], audio, cfg, hints)
        else:
            text = LOCAL.transcribe(audio, cfg, hints)
    except STTError:
        if engine == "local" or LOCAL.model is None:
            raise
        text, engine = LOCAL.transcribe(audio, cfg, hints), "local (cloud failed)"
    return text, engine
