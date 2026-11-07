"""Self-updater: when Aqua Lite starts, compare our VERSION with the one on GitHub. If GitHub is newer,
download it, self-test it, install it over the app folder (with a backup), and restart.

Only runs from an installed copy (%LOCALAPPDATA%\\AquaLite\\app) - never touches a git checkout.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

log = logging.getLogger("aqualite")

REPO = "undeadhuman37/aqua-lite"
BRANCH = "main"
HEAD_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"            # newest commit id (not CDN-cached)
VERSION_URL = "https://raw.githubusercontent.com/" + REPO + "/{ref}/VERSION"  # a commit id never goes stale
ZIP_URL = "https://codeload.github.com/" + REPO + "/zip/{ref}"
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
SKIP = {".git", "__pycache__", ".venv", "venv"}


class UpdateError(Exception):
    pass


def parse_version(text):
    """'1.2.3' -> (1, 2, 3). Anything unreadable -> (0, 0, 0)."""
    nums = re.findall(r"\d+", text or "")[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums)) if nums else (0, 0, 0)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


def local_version(app_dir=APP_DIR):
    try:
        with open(os.path.join(app_dir, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


def can_self_update(app_dir=APP_DIR):
    """Only update installed copies: not a developer's git checkout, and only if we can write there."""
    return (not os.path.isdir(os.path.join(app_dir, ".git"))
            and os.path.isfile(os.path.join(app_dir, "AquaLite.pyw"))
            and os.access(app_dir, os.W_OK))


def latest_ref():
    """The newest commit on main. Asking for a commit id (instead of 'main') sidesteps GitHub's 5-minute file cache,
    so an update is seen the moment it's pushed. Falls back to 'main' if the API is unavailable (e.g. rate limit)."""
    try:
        r = requests.get(HEAD_URL, timeout=8, headers={"Accept": "application/vnd.github.sha",
                                                       "User-Agent": "AquaLite-updater"})
        sha = r.text.strip()
        if r.ok and re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
        log.info("update: GitHub API said %s, falling back to the branch", r.status_code)
    except requests.RequestException as e:
        log.info("update: GitHub API unreachable (%s), falling back to the branch", e)
    return BRANCH


def check(ref=None):
    """Returns (newer version, commit) from GitHub, or None if we're up to date."""
    ref = ref or latest_ref()
    url = VERSION_URL.format(ref=ref) + (f"?nocache={os.getpid()}{id(ref)}" if ref == BRANCH else "")
    r = requests.get(url, timeout=8, headers={"Cache-Control": "no-cache"})
    r.raise_for_status()
    remote = r.text.strip()
    if parse_version(remote) == (0, 0, 0):
        raise UpdateError(f"unreadable version on GitHub: {remote[:40]!r}")
    log.info("update: installed %s, GitHub %s (%s)", local_version(), remote, ref[:7])
    return (remote, ref) if is_newer(remote, local_version()) else None


def console_python():
    """python.exe next to pythonw.exe, so pip and the self-test can run (hidden) without a GUI interpreter."""
    exe = sys.executable
    alt = os.path.join(os.path.dirname(exe), "python.exe")
    return alt if os.path.basename(exe).lower() == "pythonw.exe" and os.path.isfile(alt) else exe


def _run(label, args, cwd, timeout):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise UpdateError(f"{label} failed: {(p.stdout + p.stderr).strip()[-300:]}")
    return p


def download(ref=BRANCH, work=None, url=None):
    """Download and unpack the repo zip. Returns the folder that contains AquaLite.pyw."""
    work = work or tempfile.mkdtemp(prefix="aqualite-update-")
    zpath = os.path.join(work, "update.zip")
    with requests.get(url or ZIP_URL.format(ref=ref), timeout=30, stream=True) as r:
        r.raise_for_status()
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    out = os.path.join(work, "src")
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():  # refuse anything that would land outside the folder
            target = os.path.realpath(os.path.join(out, name))
            if not target.startswith(os.path.realpath(out) + os.sep) and target != os.path.realpath(out):
                raise UpdateError(f"unsafe path in update: {name}")
        z.extractall(out)
    roots = [os.path.join(out, d) for d in os.listdir(out)]
    for root in [out] + roots:
        if all(os.path.exists(os.path.join(root, p)) for p in ("AquaLite.pyw", "VERSION", "aqualite/__init__.py")):
            return root
    raise UpdateError("the download doesn't look like Aqua Lite")


def _same_file(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _copy_tree(src, dst):
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP]
        rel = os.path.relpath(base, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for name in files:
            shutil.copy2(os.path.join(base, name), os.path.join(dst, rel, name))


def install(staged, app_dir=APP_DIR, py=None):
    """Packages (if requirements changed) -> self-test the new code -> back up -> copy over. Restores on failure."""
    py = py or console_python()
    if not _same_file(os.path.join(staged, "requirements.txt"), os.path.join(app_dir, "requirements.txt")):
        log.info("update: requirements changed, installing packages")
        _run("installing packages", [py, "-m", "pip", "install", "-r", os.path.join(staged, "requirements.txt"),
              "--quiet", "--disable-pip-version-check"], staged, 900)
        from . import deps
        deps.mark_installed(os.path.join(staged, "requirements.txt"))
    _run("the new version's self-test", [py, "-I", os.path.join(staged, "AquaLite.pyw"), "--selftest"], staged, 180)

    backup = os.path.join(os.path.dirname(app_dir), "app.backup")
    shutil.rmtree(backup, ignore_errors=True)
    shutil.copytree(app_dir, backup, ignore=shutil.ignore_patterns(*SKIP))
    try:
        _copy_tree(staged, app_dir)
    except Exception:
        log.exception("update: copy failed, restoring the previous version")
        _copy_tree(backup, app_dir)
        raise
    return local_version(app_dir)


def restart(new_version):
    """Start the freshly installed copy; it waits for this process to exit before taking over."""
    flags = (0x00000008 | 0x00000200) if sys.platform == "win32" else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, os.path.join(APP_DIR, "AquaLite.pyw"), "--wait-pid", str(os.getpid()),
                      "--updated", new_version], cwd=APP_DIR, creationflags=flags, close_fds=True)


def update_now(on_found=None):
    """Full run. Returns the installed version, or None when already up to date."""
    if not can_self_update():
        raise UpdateError("this copy isn't an installed copy (run install.bat to install it)")
    found = check()
    if not found:
        return None
    newer, ref = found
    if on_found:
        on_found(newer)
    work = tempfile.mkdtemp(prefix="aqualite-update-")
    try:
        staged = download(ref, work=work)
        if not is_newer(local_version(staged), local_version()):
            return None  # GitHub's zip lagged behind its VERSION file; try again next launch
        return install(staged)
    finally:
        shutil.rmtree(work, ignore_errors=True)
