"""Pure text + rule helpers (no Windows calls, so they can be unit tested anywhere)."""
import re

# ---------------------------------------------------------------- paste rules
# From the Ghidra pass on Wispr Flow Helper.exe (teardown section 7).
SHIFT_INSERT_APPS = ("code", "cursor", "windsurf")
RESTORE_DELAYS = (
    (5.0, ("vncviewer", "tvnviewer", "mstsc", "msrdc", "wfica32", "vmware-view", "rdcman",
           "anydesk", "teamviewer")),
    (3.0, ("outlook", "olk", "winword", "whatsapp")),
)


def pick_paste_keys(proc, shift_insert_flag):
    if shift_insert_flag and proc.lower() in SHIFT_INSERT_APPS:
        return ("shift", "insert")
    return ("ctrl", "v")


def restore_delay(proc):
    p = proc.lower()
    return next((d for d, names in RESTORE_DELAYS if p.startswith(names)), 0.5)


# ---------------------------------------------------------------- app categories
# Wispr Flow groups apps into Personal messages / Work messages / Email / Other for styles.
_PERSONAL = ("whatsapp", "telegram", "signal", "messenger", "instagram", "discord", "snapchat",
             "imessage", "line", "viber", "wechat")
_WORK = ("slack", "teams", "ms-teams", "zoom", "google chat", "mattermost", "linear", "notion",
         "asana", "jira", "clickup", "monday", "trello", "basecamp")
_EMAIL = ("outlook", "olk", "thunderbird", "hxoutlook", "mailspring", "spark", "gmail",
          "inbox", "mail -", "proton mail", "superhuman")
_CODE_PROCS = ("code", "cursor", "windsurf", "idea64", "pycharm64", "webstorm64", "rider64",
               "clion64", "goland64", "devenv", "sublime_text", "notepad++", "windowsterminal",
               "powershell", "pwsh", "cmd", "wezterm-gui", "alacritty", "zed", "android studio",
               "studio64")
_BROWSERS = ("chrome", "msedge", "firefox", "brave", "opera", "arc", "vivaldi", "zen")


def app_category(proc, title=""):
    p, t = (proc or "").lower(), (title or "").lower()
    if p in _CODE_PROCS:
        return "code"
    hay = t if p in _BROWSERS else f"{p} {t}"
    if p in _BROWSERS and any(s in t for s in ("github", "replit", "codesandbox", "stackblitz")):
        return "code"
    for cat, words in (("email", _EMAIL), ("personal", _PERSONAL), ("work", _WORK)):
        if any(w in hay for w in words):
            return cat
    return "other"


# ---------------------------------------------------------------- local cleanup
_FILLERS = re.compile(r"(?<![\w'])(?:u+m+|u+h+m*|e+r+m+|h+m+|m{2,})(?![\w'])[,.]?\s*", re.I)
_NEW_PARA = re.compile(r"[,.]?\s*\bnew paragraph\b[,.]?\s*", re.I)
_NEW_LINE = re.compile(r"[,.]?\s*\bnew line\b[,.]?\s*", re.I)
_SCRATCH = re.compile(r"^(.*?)([^.!?\n]*)\bscratch that\b[,.]?\s*", re.I | re.S)


def local_cleanup(text):
    """Offline formatter: fillers out, 'new line'/'new paragraph'/'scratch that', tidy case."""
    t = text.strip()
    while _SCRATCH.search(t):
        t = _SCRATCH.sub(lambda m: (m.group(1).rstrip() + " ") if m.group(1).strip() else "", t, count=1)
    t = _FILLERS.sub("", t)
    t = _NEW_PARA.sub("\n\n", t)
    t = _NEW_LINE.sub("\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"(^|[.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = t.strip(" ,")
    if t and t[-1].isalnum() and len(t.split()) > 2:
        t += "."
    return t


# ---------------------------------------------------------------- snippets & replacements
def _phrase_regex(phrase):
    words = [re.escape(w) for w in re.findall(r"[\w']+", phrase)]
    if not words:
        return None
    return re.compile(r"(?<![\w'])" + r"[\s,.\-]+".join(words) + r"(?![\w'])", re.I)


def _norm(s):
    return " ".join(re.findall(r"[\w']+", s.lower()))


def whole_snippet(text, snippets):
    """If the whole utterance is a snippet trigger, return its expansion."""
    n = _norm(text)
    for s in snippets:
        if s.get("trigger") and _norm(s["trigger"]) == n:
            return s.get("text", "")
    return None


def protect_snippets(text, snippets):
    """Swap trigger phrases for tokens the AI formatter will keep untouched."""
    mapping = {}
    for i, s in enumerate(snippets):
        rx = _phrase_regex(s.get("trigger", ""))
        if rx and rx.search(text):
            tok = f"[[S{i}]]"
            text = rx.sub(tok, text)
            mapping[tok] = s
    return text, mapping


_TOKEN = re.compile(r"\[\[\s*s(\d+)\s*\]\]", re.I)


def expand_snippets(text, mapping):
    def tok(m):
        s = mapping.get(f"[[S{m.group(1)}]]")
        return s.get("text", "") if s else ""
    found = {f"[[S{n}]]" for n in _TOKEN.findall(text)}
    text = _TOKEN.sub(tok, text)
    for key, s in mapping.items():
        if key not in found:  # the formatter dropped the token: match the spoken trigger instead
            rx = _phrase_regex(s.get("trigger", ""))
            if rx:
                text = rx.sub(lambda _m, s=s: s.get("text", ""), text)
    return text


def apply_replacements(text, replacements):
    for r in replacements:
        rx = _phrase_regex(r.get("from", ""))
        if rx:
            text = rx.sub(lambda _m, to=r.get("to", ""): to, text)
    return text


def looks_like_an_answer(raw, cleaned):
    """Guard: a formatter that answers the dictation instead of formatting it."""
    if not cleaned.strip():
        return True
    return len(cleaned) > 2.2 * len(raw) + 60


def word_count(text):
    return len(re.findall(r"\w+", text))
