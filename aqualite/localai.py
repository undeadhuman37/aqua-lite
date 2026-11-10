"""Private mode: an AI model running on this PC, built into Aqua Lite - no account, no API key, nothing sent out.

It's the same engine Ollama and LM Studio use underneath (llama.cpp's llama-server), downloaded from llama.cpp's
official GitHub releases, plus a small open model from Hugging Face. The Vulkan build runs on NVIDIA, AMD and Intel
graphics cards; PCs without a usable graphics driver get the plain processor build. The server listens only on
127.0.0.1 (this PC) and is tied to Aqua Lite's process, so it closes when Aqua Lite does.

Files live in %LOCALAPPDATA%\\AquaLite\\ai (outside the app folder, so updates don't download them again).
"""
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile

import requests

log = logging.getLogger("aqualite")
IS_WIN = sys.platform == "win32"

RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"
ENGINES = {"vulkan": "-bin-win-vulkan-x64.zip", "cpu": "-bin-win-cpu-x64.zip"}

# Small open models, all Apache 2.0. Each lists a few GGUF repos to try, newest-trusted first; the exact file is
# looked up when downloading (the Q4_K_M quantization: the usual balance of size and quality).
MODELS = {
    "qwen3-4b": {"label": "Standard - Qwen3 4B (2.5 GB, best with a graphics card)", "quant": "Q4_K_M",
                 "repos": ["unsloth/Qwen3-4B-Instruct-2507-GGUF", "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF",
                           "MaziyarPanahi/Qwen3-4B-Instruct-2507-GGUF"], "thinking": False},
    "qwen3-1.7b": {"label": "Small - Qwen3 1.7B (1.1 GB, for PCs without a graphics card)", "quant": "Q4_K_M",
                   "repos": ["unsloth/Qwen3-1.7B-GGUF", "bartowski/Qwen_Qwen3-1.7B-GGUF", "Qwen/Qwen3-1.7B-GGUF"],
                   "thinking": True},   # hybrid model: thinking gets switched off per request
}
DEFAULT_MODEL = "qwen3-4b"
CONTEXT = 6144          # tokens: room for a 10-minute dictation plus instructions; less memory reserved than 8k
idle_secs = 10 * 60     # free the model's memory after this long unused (0 = keep it); set from Settings
UA = {"User-Agent": "AquaLite-private-mode"}


class LocalAIError(Exception):
    pass


def base_dir():
    root = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(root, "AquaLite", "ai")
    os.makedirs(d, exist_ok=True)
    return d


def _state_path():
    return os.path.join(base_dir(), "installed.json")


def installed():
    """What's downloaded: {"engines": {"vulkan": exe_path, ...}, "models": {"qwen3-4b": gguf_path, ...}}."""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("engines", {})
    st.setdefault("models", {})
    st["engines"] = {k: v for k, v in st["engines"].items() if os.path.isfile(v)}
    st["models"] = {k: v for k, v in st["models"].items() if os.path.isfile(v)}
    return st


def _save_state(st):
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, _state_path())


def ready(model_key):
    st = installed()
    return bool(st["engines"]) and model_key in st["models"]


# ---------------------------------------------------------------- downloads
def download(url, dest, size=None, sha256=None, progress=None, cancel=None):
    """Download to dest with resume (.part file), size and checksum checks. progress(done, total)."""
    part = dest + ".part"
    done = os.path.getsize(part) if os.path.exists(part) else 0
    if size and done > size:
        os.remove(part)
        done = 0
    headers = dict(UA)
    if done:
        headers["Range"] = f"bytes={done}-"
    with requests.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True) as r:
        if r.status_code == 416 and size and done == size:
            pass   # already complete
        elif r.status_code not in (200, 206):
            raise LocalAIError(f"download failed ({r.status_code}): {url}")
        else:
            if r.status_code == 200:
                done = 0   # the server ignored the resume request: start over
            total = size or (done + int(r.headers.get("Content-Length") or 0)) or None
            with open(part, "ab" if done else "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if cancel and cancel.is_set():
                        raise LocalAIError("cancelled")
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    if size and os.path.getsize(part) != size:
        raise LocalAIError(f"download incomplete ({os.path.getsize(part)} of {size} bytes)")
    if sha256:
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 22), b""):
                h.update(block)
        if h.hexdigest().lower() != sha256.lower():
            os.remove(part)
            raise LocalAIError("downloaded file is damaged (checksum mismatch), please try again")
    os.replace(part, dest)
    return dest


def pick_release(releases, variant):
    """llama.cpp publishes several builds a day, and the newest is often still uploading its files: take the newest
    release that already has the Windows build we need. Returns (name, url, size, sha256 or None)."""
    if isinstance(releases, dict):
        releases = [releases]
    for rel in releases:
        if rel.get("draft"):   # (llama.cpp marks every build as a pre-release, so that can't be a reason to skip)
            continue
        try:
            return find_engine_asset(rel, variant)
        except LocalAIError:
            continue
    raise LocalAIError(f"no finished Windows {variant} build in llama.cpp's recent releases, try again in a while")


def find_engine_asset(release, variant):
    """The Windows zip for `variant` in a GitHub release listing: (name, url, size, sha256 or None)."""
    suffix = ENGINES[variant]
    for a in release.get("assets", []):
        name = a.get("name", "")
        if name.startswith("llama-") and name.endswith(suffix) and a.get("state", "uploaded") == "uploaded":
            digest = a.get("digest") or ""
            return name, a["browser_download_url"], a.get("size"), (digest[7:] if digest.startswith("sha256:") else None)
    raise LocalAIError(f"no {variant} build in llama.cpp release {release.get('tag_name')}")


def find_model_file(listing, quant):
    """The single-file GGUF of `quant` in a Hugging Face model listing: (name, size, sha256 or None)."""
    best = None
    for s in listing.get("siblings", []):
        name = s.get("rfilename", "")
        low = name.lower()
        if not low.endswith(".gguf") or "/" in name or "mmproj" in low or f"{quant.lower()}.gguf" not in low:
            continue
        if low.startswith("ud-") or "-ud-" in low:
            continue   # unsloth's dynamic variants: fine, but the plain file is the predictable one
        lfs = s.get("lfs") or {}
        cand = (name, s.get("size") or lfs.get("size"), lfs.get("sha256"))
        if best is None or len(name) < len(best[0]):
            best = cand
    if not best:
        raise LocalAIError(f"no {quant} file in this repository")
    return best


def install(model_key, progress=None, cancel=None, variant="vulkan"):
    """Download the engine (if needed) and the model. progress(stage_text, done, total)."""
    model = MODELS[model_key]
    st = installed()
    say = progress or (lambda *a: None)
    if variant not in st["engines"]:
        say("Finding the AI engine...", 0, None)
        r = requests.get(RELEASES, headers={**UA, "Accept": "application/vnd.github+json"}, timeout=20)
        if r.status_code != 200:
            raise LocalAIError(f"couldn't reach GitHub ({r.status_code})")
        name, url, size, sha = pick_release(r.json(), variant)
        zpath = os.path.join(base_dir(), name)
        download(url, zpath, size, sha, lambda d, t: say("Downloading the AI engine...", d, t), cancel)
        target = os.path.join(base_dir(), "engine-" + variant)
        shutil.rmtree(target, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(target)
        os.remove(zpath)
        exe = next((os.path.join(dp, f) for dp, _d, fs in os.walk(target) for f in fs
                    if f.lower() == "llama-server.exe"), None)
        if not exe:
            raise LocalAIError("the AI engine download didn't contain llama-server.exe")
        st["engines"][variant] = exe
        _save_state(st)
        log.info("private mode: engine %s installed (%s)", variant, name)
    if model_key not in st["models"]:
        last = None
        for repo in model["repos"]:
            try:
                say("Finding the AI model...", 0, None)
                r = requests.get(f"https://huggingface.co/api/models/{repo}", params={"blobs": "true"},
                                 headers=UA, timeout=20)
                if r.status_code != 200:
                    raise LocalAIError(f"{repo}: {r.status_code}")
                fname, size, sha = find_model_file(r.json(), model["quant"])
                dest = os.path.join(base_dir(), fname)
                download(f"https://huggingface.co/{repo}/resolve/main/{fname}", dest, size, sha,
                         lambda d, t: say("Downloading the AI model...", d, t), cancel)
                st = installed()
                st["models"][model_key] = dest
                _save_state(st)
                log.info("private mode: model %s installed from %s (%s)", model_key, repo, fname)
                break
            except (LocalAIError, requests.RequestException) as e:
                if cancel and cancel.is_set():
                    raise LocalAIError("cancelled")
                last = e
                log.info("private mode: %s", e)
        else:
            raise LocalAIError(f"couldn't download the model: {last}")
    # first start: if the graphics-card build can't run here (no usable Vulkan driver), use the processor build
    say("Starting the AI for the first time...", 0, None)
    try:
        ensure(model_key)
    except LocalAIError as e:
        st = installed()
        if "cpu" in st["engines"]:
            raise
        log.info("private mode: graphics build didn't start (%s), getting the processor build", e)
        install(model_key, progress, cancel, variant="cpu")
        st = installed()
        st["prefer"] = "cpu"
        _save_state(st)
        return
    say("Ready", 1, 1)


def remove_all():
    stop()
    shutil.rmtree(base_dir(), ignore_errors=True)


# ---------------------------------------------------------------- the server
_lock = threading.Lock()
_server = {"proc": None, "port": None, "model": None, "variant": None}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alive():
    p = _server["proc"]
    return p is not None and p.poll() is None


def _wait_healthy(port, proc, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.25)
    return False


def server_command(exe, model_path, port):
    # only long-standing options, so any recent build accepts them (an unknown option makes the server quit)
    # -np 1: one request at a time is all a dictation app needs, and one slot reserves the least memory
    return [exe, "-m", model_path, "--host", "127.0.0.1", "--port", str(port), "-c", str(CONTEXT), "-ngl", "99",
            "-np", "1"]


def ensure(model_key, timeout=120):
    """Start the server for `model_key` if it isn't running. Returns the base URL. Thread-safe."""
    with _lock:
        _touch()
        if _alive() and _server["model"] == model_key:
            return f"http://127.0.0.1:{_server['port']}"
        _stop_locked()
        st = installed()
        model_path = st["models"].get(model_key)
        if not model_path:
            raise LocalAIError("the private AI model isn't downloaded yet (Settings > Private)")
        if not st["engines"]:
            raise LocalAIError("the private AI engine isn't downloaded yet (Settings > Private)")
        errors = []
        order = ["cpu", "vulkan"] if st.get("prefer") == "cpu" else ["vulkan", "cpu"]
        for variant in [v for v in order if v in st["engines"]]:
            if True:
                port = _free_port()
                cmd = server_command(st["engines"][variant], model_path, port)
                logf = open(os.path.join(base_dir(), "server.log"), "w", encoding="utf-8", errors="replace")
                try:
                    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            cwd=os.path.dirname(st["engines"][variant]),
                                            creationflags=0x08000000 if IS_WIN else 0)  # CREATE_NO_WINDOW
                except OSError as e:
                    logf.close()
                    errors.append(f"{variant}: {e}")
                    continue
                if IS_WIN:
                    try:
                        from . import winapi
                        winapi.close_with_us(proc)
                    except Exception as e:
                        log.info("private mode: couldn't tie the server to Aqua Lite: %s", e)
                t0 = time.time()
                if _wait_healthy(port, proc, timeout):
                    _server.update(proc=proc, port=port, model=model_key, variant=variant, log=logf)
                    log.info("private mode: %s server ready on port %d in %.1fs", variant, port, time.time() - t0)
                    return f"http://127.0.0.1:{port}"
                proc.kill()
                logf.close()
                errors.append(f"{variant}: didn't start (see {os.path.join(base_dir(), 'server.log')})")
                log.info("private mode: %s server didn't start", variant)
        raise LocalAIError("; ".join(errors) or "no engine")


def stop():
    with _lock:
        _stop_locked()


_last_used = [0.0]


def _touch():
    _last_used[0] = time.time()


touch = _touch


def _idle_watch():
    """Close the server (freeing its memory) after idle_secs without a request; it restarts when needed."""
    while True:
        time.sleep(20)
        if idle_secs > 0 and _alive() and time.time() - _last_used[0] > idle_secs and not _lock.locked():
            with _lock:
                if _alive() and time.time() - _last_used[0] > idle_secs:
                    log.info("private mode: freed the AI's memory after %d idle minutes", idle_secs // 60)
                    _stop_locked()


threading.Thread(target=_idle_watch, daemon=True, name="local-ai-idle").start()


def _stop_locked():
    p = _server.get("proc")
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    lf = _server.get("log")
    if lf:
        try:
            lf.close()
        except Exception:
            pass
    _server.update(proc=None, port=None, model=None, variant=None, log=None)


def running():
    return _alive()


def request_extras(model_key):
    """Extra request fields: hybrid models get thinking switched off (we want the answer, fast)."""
    if MODELS.get(model_key, {}).get("thinking"):
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}
