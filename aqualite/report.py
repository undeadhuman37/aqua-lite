"""'Report a problem': one text block with what's needed to track down a bug, and nothing private.

Left out: everything you dictated, API keys, your dictionary, snippets and replacements, and your Windows user
name in file paths. The report is shown to you before you share it.
"""
import os
import platform
import re
import sys

from . import config

LOG_LINES = 250
KEEP_SETTINGS = ("stt_engine", "language", "local_model", "local_device", "ai_provider", "editing_strength",
                 "code_mode", "hotkey_ptt", "hotkey_handsfree_key", "hotkey_command_key", "hotkey_paste_last",
                 "hotkey_undo_last", "hotkey_cancel", "double_tap_handsfree", "handsfree_silence_secs",
                 "max_handsfree_minutes", "voice_enter", "live_preview", "live_preview_model", "learn_corrections",
                 "music_enabled", "sounds", "show_idle_bar", "whisper_boost", "add_trailing_space",
                 "restore_clipboard", "shift_insert_in_editors", "launch_at_startup", "auto_update",
                 "instant_text_recheck", "gpu_flow_bar", "frosted_glass", "look", "look_mode")
_TEXT = re.compile(r"(\|\s*text=).*$")
_OLD_TEXT = re.compile(r"^(.* -> [^:|]*): .*$")          # dictation lines written by versions before 1.3.1
_OLD_LEARNED = re.compile(r"(learned from a correction: ).*$")
_OLD_REJECTED = re.compile(r"(formatter output rejected: ).*$")
_KEYS = re.compile(r"\b(gsk_|sk-ant-|sk-|key-)[A-Za-z0-9_\-]{8,}")


def _home_names():
    home = os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.path.basename(home)
    return home, user


def redact(line):
    line = _TEXT.sub(r"\1[removed]", line)
    line = _OLD_LEARNED.sub(r"\1[removed]", line)
    line = _OLD_REJECTED.sub(r"\1[removed]", line)
    if "| text=" not in line:
        line = _OLD_TEXT.sub(r"\1: [removed]", line)
    line = _KEYS.sub("[key removed]", line)
    home, user = _home_names()
    for variant in {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}:
        if len(variant) > 3:
            line = line.replace(variant, "%USERPROFILE%")
    if user and len(user) >= 3:
        line = re.sub(rf"(?i)\b{re.escape(user)}\b", "[user]", line)
    return line


def _tail(path, n):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except OSError:
        return []


def build(cfg, status=None):
    """status: a dict of live facts from the running app (engine, model states...)."""
    lines = [
        "Aqua Lite problem report",
        "========================",
        f"Version: {config.VERSION}",
        f"Windows: {platform.platform()}  ({platform.machine()})",
        f"Python: {sys.version.split()[0]}",
        "",
        "Status:",
    ]
    for k, v in (status or {}).items():
        lines.append(f"  {k}: {v}")
    lines += ["", "Settings (private ones left out):"]
    for k in KEEP_SETTINGS:
        if k in cfg:
            lines.append(f"  {k}: {cfg[k]}")
    lines.append(f"  API keys set: {', '.join(n for n in ('groq', 'openai', 'anthropic', 'custom', 'deepgram') if cfg.get(n + '_api_key')) or 'none'}")
    lines.append(f"  dictionary words: {len(cfg.get('dictionary', []))}, snippets: {len(cfg.get('snippets', []))}")
    d = config.data_dir()
    lines += ["", f"Recent log (last {LOG_LINES} lines, dictated text removed):"]
    lines += [redact(l.rstrip("\n")) for l in _tail(os.path.join(d, "aqualite.log"), LOG_LINES)]
    extra = _tail(os.path.join(d, "output.log"), 40)
    if extra:
        lines += ["", "Other output (last 40 lines):"] + [redact(l.rstrip("\n")) for l in extra]
    return "\n".join(lines) + "\n"


def write(cfg, status=None):
    """Writes the report next to the log and returns (path, text)."""
    text = build(cfg, status)
    path = os.path.join(config.data_dir(), "problem-report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path, text
