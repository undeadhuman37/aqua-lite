"""Memory: a short, readable profile of how you write, per kind of app ("writes lowercase in WhatsApp, never uses
exclamation marks, signs emails 'Best, H'"). It's built from the edits Aqua Lite learned (history.corrections)
by your AI provider every few new edits, you can read and change it in Settings > Memory, and it goes into every
formatting request so dictations come out your way. Export/import moves it, with your dictionary, snippets and
replacements, to another PC.

Stored in profile.json in Aqua Lite's data folder. Only style goes in: the AI is told to leave out what your
messages were about.
"""
import json
import logging
import os
import re
import threading
import time

from .config import data_dir

log = logging.getLogger("aqualite")
KINDS = [("personal", "Personal messages"), ("work", "Work messages"), ("email", "Email"), ("other", "Everything else")]
EVERY = 5            # rebuild after this many new learned edits
MAX_LINES = 8
EXPORT_TAG = "aqualite-memory"

PROFILE_SYSTEM = """You keep a short writing-style profile for the user of a voice dictation app, so their dictations come out the way they write. You get their CURRENT PROFILE and EDITS: pairs where the app wrote BEFORE and the user changed it to AFTER, grouped by kind of app.

Write each kind's profile as short lines starting with "- ", each one a concrete, reusable style preference: capitalization, punctuation, emoji, contractions, abbreviations and slang, greetings and sign-offs, formality, how they write numbers, times and dates, words or phrasings they always change.
- Only add a line when the edits clearly show it. Keep the current profile's lines (the user may have written them) unless the edits clearly contradict them.
- Style only: never mention what the messages were about, and no names, places or facts from them.
- At most {max_lines} lines per kind. A kind with no evidence keeps its current text (possibly empty).

Answer with JSON only: {{"personal": "...", "work": "...", "email": "...", "other": "..."}}"""


def path():
    return os.path.join(data_dir(), "profile.json")


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError):
        p = {}
    p.setdefault("styles", {})
    p["styles"] = {k: str(p["styles"].get(k, "") or "") for k, _ in KINDS}
    p.setdefault("based_on", 0)
    p.setdefault("updated", 0)
    return p


def save(p):
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path())


def for_kind(category):
    """The profile text for a kind of app ('' if none). Code editors use none: their output is exact text."""
    if category == "code":
        return ""
    return load()["styles"].get(category if category in dict(KINDS) else "other", "").strip()


def tidy(text):
    """Keep the profile to clean '- ' lines, at most MAX_LINES."""
    lines = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = re.sub(r"^[-*•]\s*", "", ln)
        lines.append("- " + ln)
    return "\n".join(lines[:MAX_LINES])


def parse(out):
    s = re.sub(r"<think>.*?</think>", "", out or "", flags=re.S)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < i:
        raise ValueError("no JSON in the answer")
    data = json.loads(s[i:j + 1])
    return {k: tidy(str(data.get(k, "") or "")) for k, _ in KINDS}


def build_request(profile, edits_by_kind):
    current = "\n".join(f"{label} ({k}):\n{profile['styles'].get(k) or '(empty)'}" for k, label in KINDS)
    parts = []
    for k, label in KINDS:
        pairs = edits_by_kind.get(k) or []
        if pairs:
            parts.append(f"{label} ({k}):\n" + "\n".join(f"- BEFORE: {b!r}\n  AFTER: {a!r}" for b, a in pairs))
    return f"CURRENT PROFILE:\n{current}\n\nEDITS:\n" + ("\n\n".join(parts) or "(none)")


_busy = threading.Lock()


def update(cfg, chat, corrections_for, count, force=False):
    """Rebuild the profile from recent learned edits when there are EVERY new ones (or force). chat(system, user)
    -> answer. Returns True if it changed. Safe to call from any thread; overlapping calls are skipped."""
    if not _busy.acquire(blocking=False):
        return False
    try:
        p = load()
        n = count()
        if not force and n - p["based_on"] < EVERY:
            return False
        edits = {k: corrections_for(k, 12, same_only=True) for k, _ in KINDS}
        if not any(edits.values()) and not force:
            return False
        out = chat(PROFILE_SYSTEM.format(max_lines=MAX_LINES), build_request(p, edits))
        styles = parse(out)
        p.update(styles=styles, based_on=n, updated=time.time())
        save(p)
        log.info("memory: profile rebuilt from %d learned edits", n)
        return True
    finally:
        _busy.release()


# ---------------------------------------------------------------- moving to another PC
def export_bundle(cfg, corrections):
    return {"format": EXPORT_TAG, "version": 1, "exported": time.time(), "profile": load()["styles"],
            "dictionary": list(cfg.get("dictionary") or []), "replacements": list(cfg.get("replacements") or []),
            "snippets": list(cfg.get("snippets") or []), "styles": dict(cfg.get("styles") or {}),
            "corrections": [{"category": c, "before": b, "after": a} for c, b, a in corrections]}


def import_bundle(cfg, data, add_correction):
    """Merge an exported bundle into cfg (dictionary/snippets/replacements are added to, never removed) and replace
    the profile. Returns a short summary."""
    if not isinstance(data, dict) or data.get("format") != EXPORT_TAG:
        raise ValueError("this isn't an Aqua Lite memory file")
    have = {w.lower() for w in cfg.get("dictionary") or []}
    new_words = [w for w in data.get("dictionary") or [] if isinstance(w, str) and w.lower() not in have]
    cfg["dictionary"] = list(cfg.get("dictionary") or []) + new_words
    for key, ident in (("replacements", "from"), ("snippets", "trigger")):
        cur = list(cfg.get(key) or [])
        seen = {str(x.get(ident, "")).lower() for x in cur}
        for x in data.get(key) or []:
            if isinstance(x, dict) and str(x.get(ident, "")).lower() not in seen:
                cur.append(x)
                seen.add(str(x.get(ident, "")).lower())
        cfg[key] = cur
    if isinstance(data.get("styles"), dict):
        cfg["styles"] = {**dict(cfg.get("styles") or {}), **data["styles"]}
    p = load()
    if isinstance(data.get("profile"), dict):
        p["styles"] = {k: tidy(str(data["profile"].get(k, "") or "")) for k, _ in KINDS}
        p["updated"] = time.time()
        save(p)
    n = 0
    for c in data.get("corrections") or []:
        if isinstance(c, dict) and c.get("before") and c.get("after"):
            add_correction("", c.get("category", "other"), c["before"], c["after"])
            n += 1
    return f"{len(new_words)} dictionary words, your style profile and {n} learned edits"
