"""Keep the private Python environment's packages in step with requirements.txt.

New features sometimes need a new package. The updater installs them before switching versions, but if the
app files were replaced another way, this catches up in the background on the next start.
"""
import hashlib
import logging
import os
import subprocess
import sys

log = logging.getLogger("aqualite")
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQS = os.path.join(APP_DIR, "requirements.txt")
STAMP = os.path.join(sys.prefix, "aqualite-requirements.sha256")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _digest(path=REQS):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def in_private_env():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) and not os.path.isdir(os.path.join(APP_DIR, ".git"))


def up_to_date():
    try:
        with open(STAMP, encoding="ascii") as f:
            return f.read().strip() == _digest()
    except OSError:
        return False


def mark_installed(reqs=REQS):
    try:
        with open(STAMP, "w", encoding="ascii") as f:
            f.write(_digest(reqs))
    except OSError:
        pass


def install(timeout=900):
    """pip install -r requirements.txt with the environment's own (windowless) python. Raises on failure."""
    from .updater import console_python
    p = subprocess.run([console_python(), "-m", "pip", "install", "-r", REQS, "--quiet", "--disable-pip-version-check"],
                       capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError((p.stdout + p.stderr).strip()[-300:])
    mark_installed()


def ensure_in_background(on_done):
    """on_done(ok: bool, installed_something: bool) is called from a background thread."""
    if not in_private_env() or up_to_date():
        return
    import threading

    def run():
        try:
            log.info("packages: requirements changed, installing")
            install()
            on_done(True, True)
        except Exception as e:
            log.warning("packages: install failed: %s", e)
            on_done(False, True)
    threading.Thread(target=run, daemon=True, name="deps").start()
