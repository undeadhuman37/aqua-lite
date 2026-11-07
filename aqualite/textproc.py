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


# ---------------------------------------------------------------- voice "press enter"
# Said at the very end of a dictation: the text is typed, then Enter is pressed (send in WhatsApp, ChatGPT, Slack...).
_ENTER_ANYWHERE = re.compile(r"[\s,;:-]*\b(?:press|hit|and press|and hit)\s+(?:the\s+)?enter(?:\s+key)?[\s.!?]*$",
                             re.IGNORECASE)
# "send it" / "send message" only count as their own sentence ("... see you then. Send it."), so
# "please review and send it" stays plain text.
_ENTER_OWN_SENTENCE = re.compile(r"(?:^|(?<=[.!?]))\s*\b(?:send it|send message|send that)[\s.!?]*$", re.IGNORECASE)
_ENTER_ARABIC = re.compile(r"[\s،,-]*(?:اضغط|إضغط)\s+(?:انتر|إنتر|enter)[\s.!?؟]*$", re.IGNORECASE)
SLOW_PASTE = ("whatsapp", "slack", "teams", "ms-teams", "discord", "messenger", "signal", "chrome", "msedge",
              "firefox", "brave", "opera", "arc", "vivaldi", "zen")


def enter_delay(proc):
    """Wait between pasting and pressing Enter. Browser/Electron chat apps insert pasted text a beat later;
    pressing Enter too soon would send an empty message."""
    return 0.5 if proc.lower().startswith(SLOW_PASTE) else 0.3


TERMINALS = ("windowsterminal", "powershell", "pwsh", "cmd", "conhost", "wezterm-gui", "alacritty", "mintty")


def split_enter_command(text):
    """'see you at 6. Press enter.' -> ('see you at 6.', True). Text without the command comes back unchanged."""
    for rx in (_ENTER_ANYWHERE, _ENTER_ARABIC, _ENTER_OWN_SENTENCE):
        m = rx.search(text or "")
        if m:
            return text[:m.start()].rstrip(" ,;:-"), True
    return text, False


# ---------------------------------------------------------------- learning from corrections
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def _ratio(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def learned_words(dictated, edited):
    """Compare what Aqua Lite typed with what the user turned it into. Returns words worth adding to the
    dictionary: one-for-one swaps that look like a mis-heard name or term ('Patrisio' -> 'Patricio'),
    not rewrites ('meeting' -> 'call')."""
    import difflib
    a, b = _WORD.findall(dictated or ""), _WORD.findall(edited or "")
    if not a or not b:
        return []
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [w.lower() for w in a], [w.lower() for w in b],
                                                     autojunk=False).get_opcodes():
        if op != "replace":
            continue
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if (i2 - i1) > 2 or (j2 - j1) > 2 or len(new) < 3 or len(new) > 40 or any(c.isdigit() for c in new):
            continue
        if old.lower().replace(" ", "") == new.lower().replace(" ", ""):
            continue  # just spacing/joining
        if _ratio(old, new) >= 0.5:
            out.append(new)
    # case-only fixes: 'patricio' -> 'Patricio', 'api' -> 'API' (names, brands, acronyms) - but not
    # capitalising the first word of a sentence, and not lower-casing
    if len(a) == len(b):
        starts = {m.start() for m in _WORD.finditer(edited)}
        sentence_starts = {next((p for p in sorted(starts) if p >= m.end()), -1)
                           for m in re.finditer(r"(?:^|[.!?\n])\s*", edited)}
        for m, old in zip(_WORD.finditer(edited), a):
            new = m.group()
            if old != new and old.lower() == new.lower() and len(new) >= 2 and new not in out \
                    and sum(c.isupper() for c in new) > sum(c.isupper() for c in old) \
                    and (m.start() not in sentence_starts or sum(c.isupper() for c in new) > 1):
                out.append(new)
    return out
