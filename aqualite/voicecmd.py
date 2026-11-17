"""Voice commands (hands-free): turn one spoken command into an action. Pure: app.py runs the actions.

parse("Go to Google.") -> ("open", "https://www.google.com")
Actions: ("stop",), ("open", url), ("app", name), ("type", text), ("write", instruction), ("edit", instruction),
("keys", "ctrl+t"), ("unknown", text). ("app", name) opens an installed app (find_app), or the site of that name. Anything the rules don't know can be put into one of these forms by the
AI (llm.voice_command) and parsed again.
"""
import difflib
import re
from urllib.parse import quote_plus

SITES = {
    "google": "https://www.google.com", "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com", "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com", "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com", "github": "https://github.com",
    "reddit": "https://www.reddit.com", "twitter": "https://x.com", "x": "https://x.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com", "amazon": "https://www.amazon.com", "netflix": "https://www.netflix.com",
    "wikipedia": "https://www.wikipedia.org", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "outlook": "https://outlook.live.com", "spotify": "https://open.spotify.com", "twitch": "https://www.twitch.tv",
    "tiktok": "https://www.tiktok.com", "whatsapp": "https://web.whatsapp.com", "discord": "https://discord.com/app",
    "stack overflow": "https://stackoverflow.com", "ebay": "https://www.ebay.com",
}
SEARCH = {
    "google": "https://www.google.com/search?q=", "youtube": "https://www.youtube.com/results?search_query=",
    "amazon": "https://www.amazon.com/s?k=", "wikipedia": "https://en.wikipedia.org/w/index.php?search=",
    "reddit": "https://www.reddit.com/search/?q=", "github": "https://github.com/search?q=",
}
KEYS = {   # spoken -> shortcut (Windows names; the Mac layer turns ctrl into Cmd)
    "enter": "enter", "press enter": "enter", "hit enter": "enter", "send": "enter", "send it": "enter",
    "submit": "enter", "new line": "shift+enter", "tab": "tab", "press tab": "tab", "escape": "esc",
    "press escape": "esc", "cancel": "esc", "undo": "ctrl+z", "undo that": "ctrl+z", "redo": "ctrl+y",
    "copy": "ctrl+c", "copy that": "ctrl+c", "paste": "ctrl+v", "paste it": "ctrl+v", "cut": "ctrl+x",
    "cut that": "ctrl+x", "select all": "ctrl+a", "save": "ctrl+s", "save it": "ctrl+s", "new tab": "ctrl+t",
    "open a new tab": "ctrl+t", "open new tab": "ctrl+t", "close tab": "ctrl+w", "close the tab": "ctrl+w",
    "close this tab": "ctrl+w", "reopen tab": "ctrl+shift+t", "next tab": "ctrl+tab",
    "previous tab": "ctrl+shift+tab", "refresh": "ctrl+r", "reload": "ctrl+r", "refresh the page": "ctrl+r",
    "go back": "alt+left", "back": "alt+left", "go forward": "alt+right", "forward": "alt+right",
    "scroll down": "pagedown", "page down": "pagedown", "scroll up": "pageup", "page up": "pageup",
    "go to the top": "home", "go to the bottom": "end", "backspace": "backspace", "delete": "backspace",
    "space": "space", "find": "ctrl+f", "find on page": "ctrl+f", "address bar": "ctrl+l",
    "zoom in": "ctrl+=", "zoom out": "ctrl+-", "bold": "ctrl+b", "italic": "ctrl+i", "underline": "ctrl+u",
}
STOP = re.compile(r"^(?:stop|exit|quit|end|close|turn off|cancel|leave)(?: the)? (?:listening|voice commands?|"
                  r"commands?|command mode|voice mode)$|^(?:stop listening|that'?s all|goodbye|bye)$")
GO = re.compile(r"^(?:go to|goto|navigate to|visit|take me to) (.+)$")
LAUNCH = re.compile(r"^(?:open(?: up)?|launch|start|run|bring up|pull up|show me|switch to) (.+)$")
APP_ALIASES = {"vs code": "visual studio code", "vscode": "visual studio code", "explorer": "file explorer",
               "files": "file explorer", "cmd": "command prompt", "control panel": "control panel",
               "the store": "microsoft store", "store": "microsoft store", "word": "word", "excel": "excel"}
FIND = re.compile(r"^(?:search(?: the web| online)?(?: for)?|google|look up|look for)"
                  r" (.+)$")
FIND_ON = re.compile(r"^search (\w+) for (.+)$|^(?:search for|look up|find) (.+?) on (\w+)$")
TYPE = re.compile(r"^(?:type|write|dictate|say|enter|put)(?: out| in| down)? (.+)$", re.S)
COMPOSE = re.compile(r"^(?:compose|draft|reply|respond|answer)\b", re.I)
WRITTEN = re.compile(r"^(?:(?:an?|the|some|me an?|me some|up an?|out an?) )(?:[\w'-]+ ){0,3}?(?:e-?mails?|messages?|"
                     r"repl(?:y|ies)|responses?|notes?|texts?|letters?|tweets?|posts?|paragraphs?|summary|"
                     r"list|bio|description|story|poem|essay|caption|comment|review|intro|introduction|"
                     r"thank you|apology|invitation|announcement|outline|agenda|pitch|cover letter|joke)\b")
EDIT = re.compile(r"^(?:make (?:it|that|this)|change|replace|rewrite|rephrase|fix|translate|shorten|"
                  r"delete the|remove the|edit)\b")
DOMAIN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?$")
FILLER = re.compile(r"^(?:(?:hey|okay|ok|um+|uh+|so|now|and|then|please|can you|could you|would you|will you|"
                    r"i want to|i'd like to|let's|lets)[ ,]+)+", re.I)


def _clean(text):
    t = text.strip().strip("\"'").strip()
    t = re.sub(r"[.!?,;:]+$", "", t).strip()
    return t


def parse(text):
    """One spoken command -> an action tuple (see the module docstring)."""
    said = _clean(text)
    rest = re.sub(r"[ ,]+please$", "", FILLER.sub("", said), flags=re.I).strip()   # keeps the user's casing
    low = rest.lower()
    if not low:
        return ("unknown", said)
    if STOP.match(low):
        return ("stop",)
    if low in KEYS:
        return ("keys", KEYS[low])
    m = re.match(r"^(?:press|hit|push) (.+)$", low)
    if m:
        keys = m.group(1).replace(" plus ", "+").replace("control", "ctrl").replace(" ", "+")
        return ("keys", KEYS.get(m.group(1), keys))
    m = FIND_ON.match(low)
    if m:
        site, query = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if site in SEARCH:
            return ("open", SEARCH[site] + quote_plus(query))
    m = FIND.match(low)
    if m:
        return ("open", SEARCH["google"] + quote_plus(m.group(1)))
    m = GO.match(low)
    if m:
        return ("open", url_for(m.group(1)))
    m = LAUNCH.match(low)
    if m:
        url = url_for(m.group(1))
        site = re.search(r" (?:website|web site|site|page)$", m.group(1))   # "open the youtube website"
        if site or (not url.startswith(SEARCH["google"]) and _name(m.group(1)) not in SITES):
            return ("open", url)   # a web address
        return ("app", _name(m.group(1)))   # a name: the app, or else the site of that name
    m = TYPE.match(low)
    if m:
        body = rest[m.start(1):]
        if WRITTEN.match(body.lower()):
            return ("write", rest)
        typed = FILLER.sub("", text.strip())   # with its own punctuation: "type how are you?" keeps the "?"
        return ("type", typed[m.start(1):].strip() if typed.lower().startswith(low[:m.start(1)]) else body)
    if COMPOSE.match(low):
        return ("write", rest)
    if EDIT.match(low):
        return ("edit", rest)
    return ("unknown", said)


def url_for(name):
    """'google' -> Google; 'bbc dot co dot uk' -> https://bbc.co.uk; anything else -> a web search for it."""
    n = re.sub(r"^(?:the|my) ", "", name.strip())
    n = re.sub(r" (?:website|web site|site|page|homepage|home page|app)$", "", n).strip()
    n = re.sub(r"^(?:www )", "www.", n)
    if n in SITES:
        return SITES[n]
    dotted = re.sub(r"\s*\b(?:dot|period)\b\s*", ".", n).replace(" ", "")
    if DOMAIN.match(dotted):
        return "https://" + dotted
    return SEARCH["google"] + quote_plus(n)


def _name(spoken):
    n = re.sub(r"^(?:the|my) ", "", spoken.strip().lower())
    n = re.sub(r" (?:app|application|program|website|web site|site|page)$", "", n).strip()
    return APP_ALIASES.get(n, n)


def find_app(name, apps):
    """The installed app the user means ({shown name: launch id} -> a key of apps), or None. An app called
    exactly that wins; then a website of that name ("open google" is the site, not Google Chrome); then the
    closest app name ("chrome" -> "Google Chrome"). Never an uninstaller."""
    n = _name(name)
    names = {re.sub(r"\s+", " ", k.lower()).strip(): k for k in apps if "uninstall" not in k.lower()}
    if n in names:
        return names[n]
    if n in SITES:
        return None
    words = [k for k in names if re.search(r"(?:^|\W)" + re.escape(n) + r"(?:$|\W)", k)]
    if words:
        return names[min(words, key=len)]
    close = difflib.get_close_matches(n, list(names), 1, 0.8)
    return names[close[0]] if close else None

