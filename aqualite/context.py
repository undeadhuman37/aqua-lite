"""Screen context: read the conversation that's visible in the app you're dictating into (a WhatsApp chat, a
Discord channel, an email thread), so the AI gets names, spellings, topic and tone right.

Off by default (Settings > Style). Read through Windows UI Automation, the accessibility API screen readers use,
when you start talking. Only what's visible on screen is read; password boxes, private/incognito windows and the
apps in `context_blocked_apps` are never read. The text is sent to your AI provider together with the dictation
and is never saved or logged.
"""
import logging
import re
import sys
import threading
import time

log = logging.getLogger("aqualite")

MAX_CHARS = 2500        # most recent visible text kept (the bottom of a chat is the newest)
DRAFT_CHARS = 600       # text already in the box you're typing into
MAX_ELEMENTS = 4000     # elements looked at, newest last
UIA_NAME, UIA_TYPE, UIA_OFFSCREEN, UIA_PASSWORD = 30005, 30003, 30022, 30019
TEXT, LISTITEM = 50020, 50007
PRIVATE_TITLES = ("inprivate", "incognito", "private browsing", "private window")
DEFAULT_BLOCKED = ["1password", "bitwarden", "keepass", "keepassxc", "lastpass", "dashlane", "enpass", "keeper",
                   "mstsc", "credentialuibroker", "consent", "logonui"]
ALWAYS_BLOCKED = {"aqualite", "pythonw", "python"}   # our own windows


def allowed(proc, title, cfg):
    """May we read this window at all?"""
    p, t = (proc or "").lower(), (title or "").lower()
    blocked = {b.lower().removesuffix(".exe") for b in cfg.get("context_blocked_apps", DEFAULT_BLOCKED)}
    blocked |= ALWAYS_BLOCKED
    return bool(p) and p not in blocked and not any(s in t for s in PRIVATE_TITLES)


def assemble(names, max_chars=MAX_CHARS):
    """Visible text pieces (in screen order) -> one tidy block: whitespace squeezed, repeats and pieces that are
    already contained in their neighbour dropped (a chat bubble and the text inside it often both show up)."""
    out = []
    for n in names:
        n = " ".join((n or "").split())
        if len(n) < 2:
            continue
        if out and (n == out[-1] or n in out[-1]):
            continue
        if out and out[-1] in n:  # the container came after its own text: keep the fuller one
            out[-1] = n
            continue
        out.append(n)
    text = "\n".join(out)
    if len(text) > max_chars:
        text = text[-max_chars:]
        nl = text.find("\n")
        if 0 <= nl < 200:
            text = text[nl + 1:]
    return text


_CAP = re.compile(r"(?<![\w'’-])([A-Z][a-z]+(?:[A-Z][a-z]+)*|[a-z]+[A-Z]\w*|[A-Z]{2,6})(?![\w'’-])")
_COMMON = set("""I I'm I'll I've I'd A An The This That These Those It Its He She We They You Your My Our Their His Her
Hi Hey Hello Thanks Thank Yes No Ok OK Okay Yeah Yep Nope Sure Please Sorry Good Great Nice Cool Lol LOL OMG BTW
And But Or So If When Then Also Just Not What Why How Who Where Which Can Could Would Should Will Did Do Does Is Are Was
Were Have Has Had Let Lets Maybe Today Tomorrow Yesterday Now Here There Well Oh Ah Um Uh Wow Haha AM PM TV ID
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September
October November December Message Messages Reply Send Sent Delivered Read Seen Online Typing Search Chat Chats Call
Video Voice New Edited Forward Copy Delete Pin Pinned Mute Unread Today's Type Write Enter Home Settings Profile""".split())


def hint_names(text, limit=20):
    """Names, brands and acronyms seen on screen (most recent first), as spelling hints for the speech model."""
    seen = {}
    for m in _CAP.finditer(text or ""):
        w = m.group(1)
        start = m.start(1)
        prev = text[:start].rstrip()
        if w in _COMMON or len(w) < 2:
            continue
        if (not prev or prev[-1] in ".!?:\n") and not (w.isupper() or any(c.isupper() for c in w[1:])):
            continue  # first word of a sentence: capitalised anyway, not necessarily a name
        seen[w] = start
    order = sorted(seen, key=seen.get, reverse=True)
    return order[:limit]


class Grab:
    """Reads one window in the background; get() waits a little for it, then gives up."""

    def __init__(self):
        self.done = threading.Event()
        self.text, self.draft, self.error = "", "", None

    def get(self, wait=0.6):
        if not self.done.wait(wait):
            log.info("context: screen read still running, dictating without it")
            return "", ""
        return self.text, self.draft


def grab(hwnd, proc, title, cfg):
    """Start reading the window `hwnd` now (call when recording starts). Returns a Grab, or None if not allowed."""
    if sys.platform != "win32" or not cfg.get("screen_context", False) or not allowed(proc, title, cfg):
        return None
    g = Grab()
    threading.Thread(target=_run, args=(g, hwnd), daemon=True, name="context").start()
    return g


def _run(g, hwnd):
    t0 = time.perf_counter()
    comtypes = uia = None
    try:
        from . import learn
        comtypes, U, uia = learn._uia()
        root = uia.ElementFromHandle(hwnd)
        cr = uia.CreateCacheRequest()
        for prop in (UIA_NAME, UIA_TYPE, UIA_OFFSCREEN, UIA_PASSWORD):
            cr.AddProperty(prop)
        cond = uia.CreateOrCondition(uia.CreatePropertyCondition(UIA_TYPE, TEXT),
                                     uia.CreatePropertyCondition(UIA_TYPE, LISTITEM))
        found = root.FindAllBuildCache(4, cond, cr)  # TreeScope_Descendants, one round trip for everything
        n = found.Length if found else 0
        names = []
        for i in range(max(0, n - MAX_ELEMENTS), n):
            el = found.GetElement(i)
            try:
                if el.CachedIsOffscreen or el.CachedIsPassword:
                    continue
                names.append(el.CachedName)
            except Exception:
                continue
        g.text = assemble(names)
        draft = learn.make_reader(U, uia)() or ""
        g.draft = draft[-DRAFT_CHARS:]
        log.info("context: read %d chars from %d elements in %.2fs", len(g.text), n, time.perf_counter() - t0)
    except ImportError:
        g.error = "comtypes missing"
    except Exception as e:
        g.error = str(e)
        log.info("context: couldn't read this window: %s", e)
    finally:
        g.done.set()
        uia = None
        if comtypes is not None:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
