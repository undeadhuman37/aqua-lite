"""Settings / dashboard window: a glassy sidebar of pages, each page a scrolling column of cards."""
import datetime
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import aero, gpu, history, hotkeys, llm, localai, memory, music, skin, stt
from .config import APP_NAME, VERSION

LANGS = [("auto", "Auto-detect"), ("en", "English"), ("ar", "Arabic"), ("fr", "French"), ("es", "Spanish"),
         ("de", "German"), ("it", "Italian"), ("pt", "Portuguese"), ("tr", "Turkish"), ("ur", "Urdu"),
         ("hi", "Hindi"), ("fa", "Persian"), ("ru", "Russian"), ("zh", "Chinese"), ("ja", "Japanese"),
         ("ko", "Korean"), ("id", "Indonesian"), ("nl", "Dutch")]
STYLE_NAMES = [("formal", "Formal"), ("casual", "Casual"), ("very_casual", "Very casual"), ("excited", "Excited")]
STYLE_EXAMPLE = {
    "formal": "Hi Sara, are you free for lunch tomorrow? Let me know.",
    "casual": "Hey Sara, are you free for lunch tomorrow? Let me know",
    "very_casual": "hey sara are you free for lunch tomorrow let me know",
    "excited": "Hey Sara! Are you free for lunch tomorrow? Let me know!",
}
CATS = [("personal", "Personal messages", "WhatsApp, Telegram, Instagram, Discord"),
        ("work", "Work messages", "Slack, Teams, Notion, Linear"),
        ("email", "Email", "Outlook, Gmail, Thunderbird"),
        ("other", "Everything else", "Docs, browsers, notes, AI chats")]
STRENGTHS = [("verbatim", "Verbatim - punctuation only"), ("light", "Light - fillers & corrections"),
             ("medium", "Medium - also smooth grammar"), ("heavy", "Heavy - polish & tighten")]
LOOKS = [("aero", "Frutiger Aero"), ("liquid", "Liquid Glass")]
LOOK_MODES = [("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")]


def _pair_combo(parent, pairs, value, width=28):
    labels = [b for _a, b in pairs]
    var = tk.StringVar(value=dict(pairs).get(value, labels[0]))
    cb = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly", width=width)
    cb.get_key = lambda: next(a for a, b in pairs if b == var.get())
    return cb


PAGE, CARD, INK, MUTED, ACCENT = skin.hexrgb(skin.PAGE), "#ffffff", "#0b3d63", "#3f6987", "#0a84c6"
BG = PAGE
# The Settings window's look. Frutiger Aero's values are the ones it always had; Liquid Glass's come from
# liquidskin.Skin. _use_look switches them (the window is rebuilt when the look changes).
AERO_COLOURS = dict(eyebrow="#34607f", warn="#b45309", line="#cfe6f6", focus="#2fa3e6", select="#bfe6ff",
                    list_bg="white", nav_group="#34607f", nav_shade="#0b5f99", nav_on_ink="#ffffff",
                    nav_on_icon=(255, 255, 255), title=((64, 166, 229), (255, 255, 255), (11, 106, 168)),
                    dark_title=False)
SKIN, PREFIX, C, LOOK_KEY = skin, "Aero", dict(AERO_COLOURS), ("aero", None)
REPO_URL = "https://github.com/undeadhuman37/aqua-lite"

# sidebar: (group, page name, icon, the builders that fill the page)
PAGES = (
    ("General", "Home", "home", ("_home",)),
    ("General", "What's new", "star", ("_news",)),
    ("General", "Dictation", "mic", ("_general",)),
    ("General", "Instant text", "bolt", ("_instant",)),
    ("Intelligence", "Speech & AI", "sparkle", ("_ai",)),
    ("Intelligence", "Private mode", "lock", ("_private",)),
    ("Intelligence", "Style & memory", "brush", ("_style", "_memory")),
    ("Personal", "Words & snippets", "lines", ("_dictionary", "_snippets")),
    ("Personal", "Music", "music", ("_music",)),
    ("Personal", "History", "clock", ("_history",)),
)
HEADINGS = {
    "Home": ("Hold the shortcut, talk, let go", "Your words go wherever your cursor is"),
    "What's new": (f"What's new in {VERSION}", "Everything that changed in this update, and a quick way to try it"),
    "Dictation": ("Dictation", "Shortcuts, microphone and how dictating behaves"),
    "Instant text": ("Instant text", "Words appear while you talk, then the polished version replaces them when you "
                                     "let go. It's still a bit jittery: words can jump around or get corrected as you "
                                     "speak. Only pick an option if you have what it needs."),
    "Speech & AI": ("Speech & AI", "The engines that turn your voice into text and tidy it up"),
    "Private mode": ("Private mode", "Your voice and text never leave this PC. No account, no key, works offline."),
    "Style & memory": ("Style & memory", "How you sound in each kind of app, and what Aqua Lite has learned from "
                                         "your edits"),
    "Words & snippets": ("Words & snippets", "Spellings, replacements and phrases that expand into longer text"),
    "Music": ("Music", "Soft music from your own songs while you dictate"),
    "History": ("History", "Your recent dictations. Double-click one to copy it."),
}
ALIASES = {"Shortcuts & mic": "Dictation", "Private": "Private mode", "Style": "Style & memory",
           "Memory": "Style & memory", "Dictionary": "Words & snippets", "Snippets": "Words & snippets"}
CONTAINERS = ("Panel.TFrame", "Pick.TFrame", "PickOn.TFrame", "Tile.TFrame")   # white cards
_IN_CARD = {"TLabel", "TCheckbutton", "TRadiobutton", "TFrame", "TButton", "TEntry", "TCombobox", "TSpinbox",
            "TScale", "TProgressbar"}
_IMAGES = {}   # ttk image elements: created once per look and kept for the app's lifetime (ttk keeps using them)
_MADE = set()  # looks whose elements exist
_SLIDES = {}   # Liquid Glass: element set -> how many frames a switch's slide has (styles Slide0..7.TCheckbutton)
_CARD_STYLES = set()


def look_key(cfg):
    """("aero", None) or ("liquid", "light" | "dark"): the look the Settings window should have."""
    if cfg.get("look") == "liquid":
        from . import liquid
        return "liquid", liquid.resolve_mode(cfg.get("look_mode", "system"))
    return "aero", None


def _use_look(key):
    """Point the module's colours and drawings at a look."""
    global SKIN, PREFIX, C, LOOK_KEY, PAGE, CARD, INK, MUTED, ACCENT, BG
    LOOK_KEY = key
    if key[0] == "liquid":
        from . import liquidskin
        SKIN = liquidskin.Skin(key[1])
        PREFIX = "LqL" if key[1] == "light" else "LqD"
        h = skin.hexrgb
        C = {k: (h(v) if isinstance(v, tuple) and len(v) == 3 and isinstance(v[0], int) else v)
             for k, v in SKIN.ui.items()}
        C.update(nav_shade=None, focus=h(SKIN.ACCENT), nav_on_icon=SKIN.ui["nav_on_icon"])
        PAGE, CARD, INK, MUTED, ACCENT = h(SKIN.PAGE), h(SKIN.CARD), h(SKIN.INK), h(SKIN.MUTED), h(SKIN.ACCENT_TEXT)
    else:
        SKIN, PREFIX, C = skin, "Aero", dict(AERO_COLOURS)
        PAGE, CARD, INK, MUTED, ACCENT = skin.hexrgb(skin.PAGE), "#ffffff", "#0b3d63", "#3f6987", "#0a84c6"
    BG = PAGE


def _SURFACE_STATES(colour):  # noqa: N802
    return [(state, colour) for state in ("disabled", "pressed", "active", "readonly", "focus")]


def _scale(win):
    """Screen scaling (1.0 at 100 %, 1.5 at 150 %...): the art is drawn at this size so it stays crisp."""
    try:
        return max(1.0, min(3.0, win.winfo_fpixels("1i") / 96.0))
    except tk.TclError:
        return 1.0


def _grow(im, border, w=None, h=None):
    """Widen/heighten a 9-slice drawing by stretching its plain middle, so it looks the same but has a big middle.

    ttk stretches an image element by *tiling* the middle. A tiny middle means hundreds of draws per widget,
    and Tk on Windows is slow at each one, so the window lagged. With a big middle it's one draw per piece."""
    from PIL import Image
    bl, bt, br, bb = border
    W, H = im.size
    if w and w > W:
        mid = im.crop((bl, 0, W - br, H)).resize((w - bl - br, H), Image.NEAREST)
        out = Image.new(im.mode, (w, H))
        out.paste(im.crop((0, 0, bl, H)), (0, 0))
        out.paste(mid, (bl, 0))
        out.paste(im.crop((W - br, 0, W, H)), (w - br, 0))
        im, W = out, w
    if h and h > H:
        mid = im.crop((0, bt, W, H - bb)).resize((W, h - bt - bb), Image.NEAREST)
        out = Image.new(im.mode, (W, h))
        out.paste(im.crop((0, 0, W, bt)), (0, 0))
        out.paste(mid, (0, bt))
        out.paste(im.crop((0, H - bb, W, H)), (0, h - bb))
        im = out
    return im


def _flat(im, bg):
    """Lay a drawing on a solid colour (or image). Tk on Windows draws see-through images with a slow software
    blend every time; a solid image is a plain copy."""
    from PIL import Image
    under = bg.convert("RGBA") if isinstance(bg, Image.Image) else Image.new("RGBA", im.size, tuple(bg) + (255,))
    return Image.alpha_composite(under, im.convert("RGBA")).convert("RGB")


SURFACES = (("Aero", skin.PAGE), ("AeroCard", skin.CARD))   # element set -> the colour it sits on


def _surfaces():
    return SURFACES if PREFIX == "Aero" else ((PREFIX, SKIN.PAGE), (PREFIX + "Card", SKIN.CARD))


def _make_elements(st, root, sc):
    """Draw every themed piece once (at the screen's scale) and register it as a ttk image element.

    Each control gets two solid versions, one for the page and one for a white card, and every stretchable
    piece gets a wide middle. -width/-height keep the natural sizes small so short labels still get snug
    buttons."""
    from PIL import Image, ImageTk

    def s(v):
        return max(1, int(round(v * sc)))

    def P(key, im):
        key = key if PREFIX == "Aero" else f"{PREFIX}/{key}"
        _IMAGES[key] = ImageTk.PhotoImage(im, master=root)
        return _IMAGES[key]

    def el(name, base, *states, **kw):
        st.element_create(name, "image", base, *states, **kw)

    bw, bh = s(44), s(30)
    bb = (s(15), s(12), s(15), s(15))
    ph, sh = s(16), s(22)
    pb = (s(8), s(7), s(8), s(7))
    fw, fh = s(40), s(28)
    disabled_field = getattr(SKIN, "FIELD_OFF", (240, 245, 249))
    for E, bg in _surfaces():
        for kind, primary in (("button", False), ("primary", True)):
            im = {k: P(f"{E}_{kind}_{k}", _flat(_grow(SKIN.button(bw, bh, k, primary), bb, w=s(420)), bg))
                  for k in ("normal", "active", "pressed", "disabled")}
            el(f"{E}.{kind}", im["normal"], ("disabled", im["disabled"]), ("pressed", im["pressed"]),
               ("active", im["active"]), border=bb, padding=(s(2), s(1), s(2), s(3)), sticky="nsew",
               width=bw, height=bh)
        t = {(on, k): P(f"{E}_tg_{on}_{k}", _flat(SKIN.toggle(s(20), on, k, gap=s(8)), bg)) for on in (0, 1)
             for k in ("normal", "active", "disabled")}
        el(f"{E}.toggle", t[0, "normal"], ("disabled selected", t[1, "disabled"]), ("disabled", t[0, "disabled"]),
           ("selected", t[1, "normal"]), ("active", t[0, "active"]), sticky="")
        r = {(on, k): P(f"{E}_rd_{on}_{k}", _flat(SKIN.radio(s(18), on, k, gap=s(8)), bg)) for on in (0, 1)
             for k in ("normal", "active", "disabled")}
        el(f"{E}.radio", r[0, "normal"], ("disabled selected", r[1, "disabled"]), ("disabled", r[0, "disabled"]),
           ("selected", r[1, "normal"]), ("active", r[0, "active"]), sticky="")
        b8 = (s(8),) * 4
        f = {k: P(f"{E}_fld_{k}", _flat(_grow(SKIN.field(fw, fh, k), b8, w=s(600)), bg))
             for k in ("normal", "active", "focus", "disabled")}
        el(f"{E}.field", f["normal"], ("disabled", f["disabled"]), ("focus", f["focus"]), ("active", f["active"]),
           border=b8, padding=s(3), sticky="nsew", width=fw, height=fh)
        trough = _flat(_grow(SKIN.progress_trough(s(120), ph), pb, w=s(1000)), bg)
        el(f"{E}.ptrough", P(f"{E}_ptrough", trough), border=pb, padding=s(2), sticky="nsew", width=s(120),
           height=ph)
        st_b = (s(10), 0, s(10), 0)
        strough = _flat(_grow(SKIN.scale_trough(s(120), sh), st_b, w=s(1000)), bg)
        el(f"{E}.strough", P(f"{E}_strough", strough), border=st_b, sticky="nsew", width=s(120), height=sh)
        under = strough.crop((s(40), 0, s(40) + sh, sh))   # the plain groove the ball sits on
        sl = {k: P(f"{E}_sl_{k}", _flat(SKIN.slider(sh, k), under)) for k in ("normal", "active", "pressed")}
        el(f"{E}.slider", sl["normal"], ("pressed", sl["pressed"]), ("active", sl["active"]), sticky="")
    # the combobox arrow sits on the white field, whichever surface the field is on
    field_bg = getattr(SKIN, "FIELD", SKIN.CARD)
    a = {k: P(f"arr_{k}", _flat(SKIN.arrow(s(24), s(22), k), disabled_field if k == "disabled" else field_bg))
         for k in ("normal", "active", "disabled")}
    el(f"{PREFIX}.arrow", a["normal"], ("disabled", a["disabled"]), ("active", a["active"]), sticky="")
    # the progress fill sits on the trough; it's a single short run of pieces, so it keeps its soft edges
    pfill = (s(6), s(5), s(6), s(5))
    el(f"{PREFIX}.pbar", P("pbar", _grow(SKIN.progress_bar(s(40), ph - 2 * s(2)), pfill, w=s(1000))), border=pfill,
       sticky="nsew", width=s(40), height=ph - 2 * s(2))
    # the page scrollbar floats over the page
    tbb = (0, s(7), 0, s(7))
    tb = {k: P(f"th_{k}", _flat(_grow(SKIN.thumb(s(12), s(48), k), tbb, h=s(900)), SKIN.PAGE))
          for k in ("normal", "active", "pressed")}
    el(f"{PREFIX}V.thumb", tb["normal"], ("pressed", tb["pressed"]), ("active", tb["active"]), border=tbb,
       sticky="nsew", width=s(12), height=s(48))
    el(f"{PREFIX}V.trough", P("vtrough", Image.new("RGB", (s(12), s(900)), SKIN.PAGE)), sticky="nsew", width=s(12),
       height=s(12))
    # cards (already solid: drawn on the page colour)
    cs, cb = s(48), (s(18),) * 4
    pad = (s(4), s(3), s(4), s(5))   # keeps children off the rounded edge and the shadow
    for key, sel in (("card", False), ("cardsel", True)):
        im = _flat(_grow(SKIN.card(cs, selected=sel), cb, w=s(900), h=s(500)), SKIN.PAGE)
        el(f"{PREFIX}.{key}", P(key, im), border=cb, padding=pad, sticky="nsew", width=cs, height=cs)
    pill_b = (s(11), s(5), s(11), s(5))
    for name, (fill, _ink) in SKIN.PILLS.items():
        im = _flat(_grow(SKIN.pill(s(40), s(22), fill), pill_b, w=s(300)), SKIN.CARD)
        pad_l, pad_r = (s(10), s(10)) if PREFIX == "Aero" else (s(18), s(4))   # Liquid Glass: a dot, then text
        el(f"{PREFIX}.pill.{name}", P(f"pill_{name}", im), border=pill_b, padding=(pad_l, s(2), pad_r, s(3)),
           sticky="nsew", width=s(40), height=s(22))
    key_b = (s(7), s(5), s(7), s(8))
    el(f"{PREFIX}.key", P("key", _flat(_grow(SKIN.keycap(s(28), s(24)), key_b, w=s(240)), SKIN.CARD)), border=key_b,
       padding=(s(7), s(2), s(7), s(4)), sticky="nsew", width=s(28), height=s(24))
    if hasattr(SKIN, "toggle_between"):   # Liquid Glass switches slide: frames for the click
        frames = [SKIN.toggle_between(s(20), i / 7, gap=s(8)) for i in range(8)]
        for E, bg in _surfaces():
            for i, f in enumerate(frames):
                el(f"{E}.tgslide{i}", P(f"{E}_tgslide{i}", _flat(f, bg)), sticky="")
            _SLIDES[E] = len(frames)


def _layouts(E, B="Aero"):
    """The ttk layouts for the controls, built from element set E ("Aero" on the page, "AeroCard" on a card); B is
    the look's own set (for pieces that look the same on both)."""
    inner = [("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]

    def check(base, ind):
        return [(f"{base}.padding", {"sticky": "nsew", "children": [
            (f"{E}.{ind}", {"side": "left", "sticky": ""}), (f"{base}.label", {"side": "left", "sticky": "nsew"})]})]
    lay = {
        "TButton": [(f"{E}.button", {"sticky": "nsew", "children": inner})],
        "Primary.TButton": [(f"{E}.primary", {"sticky": "nsew", "children": inner})],
        "TCheckbutton": check("Checkbutton", "toggle"),
        "TRadiobutton": check("Radiobutton", "radio"),
        "TEntry": [(f"{E}.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [("Entry.textarea", {"sticky": "nsew"})]})]})],
        "TCombobox": [(f"{E}.field", {"sticky": "nsew", "children": [
            (f"{B}.arrow", {"side": "right", "sticky": ""}),
            ("Combobox.padding", {"expand": "1", "sticky": "nsew", "children": [
                ("Combobox.textarea", {"sticky": "nsew"})]})]})],
        "TSpinbox": [(f"{E}.field", {"sticky": "nsew", "children": [
            ("null", {"side": "right", "sticky": "ns", "children": [
                ("Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                ("Spinbox.downarrow", {"side": "bottom", "sticky": "e"})]}),
            ("Spinbox.padding", {"sticky": "nsew", "children": [("Spinbox.textarea", {"sticky": "nsew"})]})]})],
        "Horizontal.TProgressbar": [(f"{E}.ptrough", {"sticky": "nsew", "children": [
            (f"{B}.pbar", {"side": "left", "sticky": "ns"})]})],
        "Horizontal.TScale": [(f"{E}.strough", {"sticky": "nsew", "children": [
            (f"{E}.slider", {"side": "left", "sticky": ""})]})],
    }
    if B != "Aero":   # Liquid Glass: the switch part way through its slide, one style per frame
        for i in range(8):
            lay[f"Slide{i}.TCheckbutton"] = check("Checkbutton", f"tgslide{i}")
    return lay


_CARD_LAYOUTS = _layouts("AeroCard")


def apply_style(win, key=("aero", None)):
    """Theme the Settings window: Frutiger Aero or Liquid Glass (light or dark)."""
    global _CARD_LAYOUTS
    _use_look(key)
    _CARD_STYLES.clear()   # the 'Card.' copies are rebuilt for this look as widgets ask for them
    _CARD_LAYOUTS = _layouts(PREFIX + "Card", PREFIX)
    return apply_aero_style(win) if key[0] == "aero" else apply_liquid_style(win)


def apply_aero_style(win, keep=None):
    """Frutiger Aero ttk theme: glossy aqua buttons, glass toggles and orbs, white cards on a pale sky page."""
    st = ttk.Style(win)
    st.theme_use("clam")
    sc = _scale(win)

    def s(v):
        return max(1, int(round(v * sc)))
    font = ("Segoe UI", 10)
    semi = "Segoe UI Semibold"
    win.configure(bg=PAGE)
    st.configure(".", background=PAGE, foreground=INK, font=font, fieldbackground="white", bordercolor="#9fd0ee",
                 lightcolor="#ffffff", darkcolor="#b9dcf2", troughcolor="#d6ecfa", focuscolor=ACCENT,
                 selectbackground="#bfe6ff", selectforeground=INK, insertcolor=INK)
    st.map(".", foreground=[("disabled", "#8fa9bd")])
    for name in (".", "TButton", "Primary.TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox",
                 "TSpinbox", "Horizontal.TScale", "Horizontal.TProgressbar", "TLabel"):
        st.map(name, background=_SURFACE_STATES(PAGE))
    if "Aero" not in _MADE:
        _MADE.add("Aero")
        _make_elements(st, win._root(), sc)
    st.configure("TFrame", background=PAGE)
    st.configure("TLabel", background=PAGE, foreground=INK)
    for name, extra in (("H1.TLabel", dict(font=(semi, 19))), ("Sub.TLabel", dict(font=("Segoe UI", 11),
                                                                                    foreground=MUTED)),
                        ("CardHead.TLabel", dict(font=(semi, 11))), ("Strong.TLabel", dict(font=(semi, 10))),
                        ("Eyebrow.TLabel", dict(font=(semi, 9), foreground="#34607f")),
                        ("Stat.TLabel", dict(font=(semi, 20), foreground=ACCENT)),
                        ("Muted.TLabel", dict(foreground=MUTED)), ("Warn.TLabel", dict(foreground="#b45309"))):
        st.configure(name, **extra)
    for name in CONTAINERS[:3]:
        st.layout(name, [("Aero.cardsel" if name == "PickOn.TFrame" else "Aero.card", {"sticky": "nsew"})])
    st.layout("Tile.TFrame", [("Aero.card", {"sticky": "nsew"})])
    st.configure("Line.TFrame", background="#cfe6f6")
    for name, lay in _layouts("Aero").items():
        st.layout(name, lay)
    # buttons
    st.configure("TButton", padding=(s(16), s(4), s(16), s(6)), foreground="#063a5e", font=(semi, 10),
                 anchor="center", width=-6)   # clam forces 11-character buttons; let them fit their words
    st.configure("Primary.TButton", foreground="#ffffff", padding=(s(24), s(4), s(24), s(6)))
    st.map("Primary.TButton", foreground=[("disabled", "#e6f2fa")])
    # toggles and radio orbs
    for cls in ("TCheckbutton", "TRadiobutton"):
        st.configure(cls, background=PAGE, padding=(s(1), s(3)))
    st.configure("Title.TRadiobutton", font=(semi, 11))
    # text fields
    st.configure("TEntry", padding=(s(6), s(3)))
    st.configure("TCombobox", padding=(s(6), s(3)))
    st.map("TCombobox", fieldbackground=[("readonly", "white")], selectbackground=[("readonly", "white")],
           selectforeground=[("readonly", INK)])
    st.configure("TSpinbox", padding=(s(6), s(2)), arrowcolor=INK, arrowsize=s(10), lightcolor="white",
                 darkcolor="white", bordercolor="white")
    win.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
    win.option_add("*TCombobox*Listbox.selectBackground", "#bfe6ff")
    win.option_add("*TCombobox*Listbox.selectForeground", INK)
    win.option_add("*TCombobox*Listbox.background", "white")
    win.option_add("*TCombobox*Listbox.foreground", INK)
    # progress, slider, scrollbar
    st.layout("Page.Vertical.TScrollbar", [("AeroV.trough", {"sticky": "ns", "children": [
        ("AeroV.thumb", {"expand": "1", "sticky": "nsew"})]})])
    # lists and tables
    st.configure("Treeview", background="white", fieldbackground="white", rowheight=s(26), bordercolor="#cfe6f6",
                 lightcolor="#cfe6f6", darkcolor="#cfe6f6")
    st.configure("Treeview.Heading", background="#e3f3fd", foreground=INK, font=(semi, 9), relief="flat",
                 bordercolor="#cfe6f6", lightcolor="#f3faff", darkcolor="#cfe6f6", padding=(s(6), s(3)))
    st.map("Treeview.Heading", background=[("active", "#d2ecfb")])
    st.map("Treeview", background=[("selected", "#bfe6ff")], foreground=[("selected", INK)])
    # tags
    for name, (_fill, ink) in skin.PILLS.items():
        sty = f"{name.title()}Pill.TLabel"
        st.layout(sty, [(f"Aero.pill.{name}", {"sticky": "nsew", "children": [("Label.label", {"sticky": "nsew"})]})])
        st.configure(sty, foreground=skin.hexrgb(ink), font=(semi, 9), background=CARD)
    st.layout("Key.TLabel", [("Aero.key", {"sticky": "nsew", "children": [("Label.label", {"sticky": "nsew"})]})])
    st.configure("Key.TLabel", font=("Consolas", 10, "bold"), foreground=INK, background=CARD)
    st.configure("TLabelframe", background=PAGE, bordercolor="#bfe0f5")
    st.configure("TLabelframe.Label", background=PAGE, foreground=INK, font=(semi, 11))
    return st


def apply_liquid_style(win):
    """Liquid Glass ttk theme: glass capsule buttons, iOS-style switches, soft filled fields, cards lifted off a
    calm page by a wide faint shadow. Light or dark, from liquidskin.Skin."""
    st = ttk.Style(win)
    st.theme_use("clam")
    sc = _scale(win)

    def s(v):
        return max(1, int(round(v * sc)))
    font = ("Segoe UI", 10)
    semi = "Segoe UI Semibold"
    field = skin.hexrgb(SKIN.FIELD)
    win.configure(bg=PAGE)
    st.configure(".", background=PAGE, foreground=INK, font=font, fieldbackground=field, bordercolor=C["line"],
                 lightcolor=CARD, darkcolor=C["line"], troughcolor=skin.hexrgb(SKIN.TRACK), focuscolor=C["focus"],
                 selectbackground=C["select"], selectforeground=INK, insertcolor=INK)
    st.map(".", foreground=[("disabled", C["disabled_fg"])])
    for name in (".", "TButton", "Primary.TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox",
                 "TSpinbox", "Horizontal.TScale", "Horizontal.TProgressbar", "TLabel"):
        st.map(name, background=_SURFACE_STATES(PAGE))
    if PREFIX not in _MADE:
        _MADE.add(PREFIX)
        _make_elements(st, win._root(), sc)
    st.configure("TFrame", background=PAGE)
    st.configure("TLabel", background=PAGE, foreground=INK)
    for name, extra in (("H1.TLabel", dict(font=("Segoe UI", 24))),
                        ("Sub.TLabel", dict(font=("Segoe UI", 11), foreground=MUTED)),
                        ("CardHead.TLabel", dict(font=(semi, 11))), ("Strong.TLabel", dict(font=(semi, 10))),
                        ("Eyebrow.TLabel", dict(font=(semi, 9), foreground=C["eyebrow"])),
                        ("Stat.TLabel", dict(font=("Segoe UI", 26), foreground=INK)),
                        ("Muted.TLabel", dict(foreground=MUTED)), ("Warn.TLabel", dict(foreground=C["warn"]))):
        st.configure(name, **extra)
    for name in CONTAINERS[:3]:
        st.layout(name, [(f"{PREFIX}.cardsel" if name == "PickOn.TFrame" else f"{PREFIX}.card", {"sticky": "nsew"})])
    st.layout("Tile.TFrame", [(f"{PREFIX}.card", {"sticky": "nsew"})])
    st.configure("Line.TFrame", background=C["line"])
    for name, lay in _layouts(PREFIX, PREFIX).items():
        st.layout(name, lay)
    st.configure("TButton", padding=(s(16), s(4), s(16), s(6)), foreground=C["btn_ink"], font=(semi, 10),
                 anchor="center", width=-6)
    st.configure("Primary.TButton", foreground=C["primary_ink"], padding=(s(24), s(4), s(24), s(6)))
    st.map("Primary.TButton", foreground=[("disabled", C["primary_dis"])])
    st.map("TButton", foreground=[("disabled", C["disabled_fg"])])
    for cls in ("TCheckbutton", "TRadiobutton"):
        st.configure(cls, background=PAGE, padding=(s(1), s(3)))
    st.configure("Title.TRadiobutton", font=(semi, 11))
    st.configure("TEntry", padding=(s(8), s(3)))
    st.configure("TCombobox", padding=(s(8), s(3)), arrowcolor=INK)
    st.map("TCombobox", fieldbackground=[("readonly", field)], selectbackground=[("readonly", field)],
           selectforeground=[("readonly", INK)], foreground=[("disabled", C["disabled_fg"])])
    st.configure("TSpinbox", padding=(s(8), s(2)), arrowcolor=INK, arrowsize=s(10), lightcolor=field,
                 darkcolor=field, bordercolor=field, fieldbackground=field)
    win.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")
    win.option_add("*TCombobox*Listbox.selectBackground", C["select"])
    win.option_add("*TCombobox*Listbox.selectForeground", INK)
    win.option_add("*TCombobox*Listbox.background", C["list_bg"])
    win.option_add("*TCombobox*Listbox.foreground", INK)
    st.layout("Page.Vertical.TScrollbar", [(f"{PREFIX}V.trough", {"sticky": "ns", "children": [
        (f"{PREFIX}V.thumb", {"expand": "1", "sticky": "nsew"})]})])
    st.configure("Treeview", background=C["list_bg"], fieldbackground=C["list_bg"], foreground=INK,
                 rowheight=s(28), bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"])
    st.configure("Treeview.Heading", background=C["head_bg"], foreground=MUTED, font=(semi, 9), relief="flat",
                 bordercolor=C["line"], lightcolor=C["head_bg"], darkcolor=C["line"], padding=(s(8), s(4)))
    st.map("Treeview.Heading", background=[("active", C["head_hot"])])
    st.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", INK)])
    for name, (_fill, ink) in SKIN.PILLS.items():
        sty = f"{name.title()}Pill.TLabel"
        st.layout(sty, [(f"{PREFIX}.pill.{name}", {"sticky": "nsew", "children": [
            ("Label.label", {"sticky": "nsew"})]})])
        st.configure(sty, foreground=skin.hexrgb(ink), font=("Segoe UI", 10), background=CARD)
    st.layout("Key.TLabel", [(f"{PREFIX}.key", {"sticky": "nsew", "children": [("Label.label", {"sticky": "nsew"})]})])
    st.configure("Key.TLabel", font=("Consolas", 10, "bold"), foreground=INK, background=CARD)
    st.configure("TLabelframe", background=PAGE, bordercolor=C["line"])
    st.configure("TLabelframe.Label", background=PAGE, foreground=INK, font=(semi, 11))
    return st


def _card_restyle(st, w):
    """A widget sitting on a white card gets a 'Card.' copy of its style with a white background (ttk can't see
    through to the card, so a page-coloured label would show as a blue box)."""
    cls = w.winfo_class()
    style = str(w.cget("style"))
    if not style:
        style = f"{str(w.cget('orient')).title()}.{cls}" if cls in ("TScale", "TProgressbar") else cls
    if style.startswith("Card.") or style.endswith("Pill.TLabel") or style == "Key.TLabel":
        return
    new = "Card." + style
    if new not in _CARD_STYLES:
        lay = _CARD_LAYOUTS.get(style) or _CARD_LAYOUTS.get(cls)
        if lay:   # the same control, drawn solid on white
            st.layout(new, lay)
        st.configure(new, background=CARD)
        st.map(new, background=_SURFACE_STATES(CARD))
        _CARD_STYLES.add(new)
    w.configure(style=new)


def _blur_ok():
    """Windows can blur behind the Flow bar's rounded shape (Windows 10; not Windows 11)."""
    if sys.platform != "win32":
        return False
    try:
        from . import winapi
        return winapi.Frost.shapes_ok()
    except Exception:
        return False


def _key_name(k):
    k = k.strip().lower()
    names = {"ctrl": "Ctrl", "win": "Win", "alt": "Alt", "shift": "Shift", "space": "Space", "esc": "Esc",
             "escape": "Esc", "enter": "Enter", "tab": "Tab", "rctrl": "Right Ctrl", "lctrl": "Left Ctrl",
             "ralt": "Right Alt", "lalt": "Left Alt", "rshift": "Right Shift", "lshift": "Left Shift",
             "capslock": "Caps Lock", "backspace": "Backspace"}
    return names.get(k, k.upper() if len(k) <= 3 else k.title())


class _Pages:
    """The old Notebook calls (select, index, tabs, tab), so code that still speaks in tabs keeps working."""

    def __init__(self, window):
        self.w = window

    def select(self, tab):
        self.w.show(tab)

    def index(self, what="current"):
        names = self.w.page_names
        return names.index(self.w.current) if what == "current" else names.index(ALIASES.get(what, what))

    def tabs(self):
        return list(self.w.page_names)

    def tab(self, t, _option="text"):
        return t if isinstance(t, str) else self.w.page_names[t]


class SettingsWindow:
    def __init__(self, root, app):
        self.app, self.cfg = app, app.cfg
        self.win = tk.Toplevel(root)
        self.win.title(f"{APP_NAME} {VERSION} - Settings")
        try:
            self.win.iconbitmap(app.icon_path)
        except Exception:
            pass
        self.v = {}
        self._imgs = []
        self._pv, self._pv_running = {}, False   # live Flow bar previews: page -> what to draw
        self.look = look_key(self.cfg)
        self.style = apply_style(self.win, self.look)
        self.glide = self.look[0] == "liquid"   # Liquid Glass: things slide and spring instead of jumping
        self.sc = _scale(self.win)
        s = self._s
        self.wrap = s(640)
        w, h = s(1010), s(730)
        h = min(h, self.win.winfo_screenheight() - s(70))
        w = min(w, self.win.winfo_screenwidth() - s(40))
        self.win.geometry(f"{w}x{h}")
        self.win.minsize(min(w, s(860)), min(h, s(540)))
        self.win.columnconfigure(1, weight=1)
        self.win.rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ttk.Frame(self.win)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.pages, self.page_names, self.current = {}, [], None
        for _group, name, _icon, builders in PAGES:
            self.page_names.append(name)
            self.pages[name] = self._make_page(name, builders)
        foot = ttk.Frame(self.win)
        foot.grid(row=1, column=1, sticky="ew")
        ttk.Frame(foot, style="Line.TFrame", height=1).pack(fill="x")
        bar = ttk.Frame(foot, padding=(s(24), s(10), s(24), s(12)))
        bar.pack(fill="x")
        ttk.Button(bar, text="Save", style="Primary.TButton", command=self.save).pack(side="right")
        ttk.Button(bar, text="Close", command=self.win.destroy).pack(side="right", padx=s(8))
        self.status = ttk.Label(bar, text="", style="Muted.TLabel")
        self.status.pack(side="left")
        self._restyle(self.win)
        self.nb = _Pages(self)
        self.show(0)
        self._wheel_acc = 0
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.win.bind(seq, self._wheel, add="+")
            for cls in ("TCombobox", "TSpinbox"):   # scrolling the page must never flip a setting by accident
                self.win.bind_class(cls, seq, lambda _e: None)
        self.win.bind("<Control-Tab>", lambda _e: self._step(1))
        for seq in ("<Control-Shift-Tab>", "<Control-ISO_Left_Tab>"):
            try:
                self.win.bind(seq, lambda _e: self._step(-1))
            except tk.TclError:
                pass
        self._slide, self._slide_job = None, None
        if self.glide:   # switches slide across instead of jumping
            self.win.bind("<ButtonRelease-1>", self._slide_toggle, add="+")
        self.win.bind("<Destroy>", self._closed, add="+")
        self._tint_title()
        self.win.lift()
        self.win.focus_force()

    def _closed(self, e):
        if e.widget is self.win:
            self._pv = None   # stops the Flow bar previews

    # ------------------------------------------------------------------ theme
    def follow_look(self):
        """Windows changed light/dark: rebuild this window if it's set to match."""
        if look_key(self.app.cfg) != self.look:
            self._rebuild()

    def _rebuild(self, status=""):
        """Open this window again in the new look, on the same page (ttk styles are shared, so it's redrawn)."""
        page, app, root = self.current, self.app, self.win.master
        geo = self.win.geometry()
        self.win.destroy()

        def again():
            app.settings = None
            app.open_settings(page)
            try:
                app.settings.win.geometry(geo)
                app.settings.status.configure(text=status)
            except (tk.TclError, AttributeError):
                pass
        root.after(30, again)

    def _slide_toggle(self, e):
        """A Liquid Glass switch was clicked: run its bead across in a few frames (the clicked one only)."""
        w = e.widget
        try:
            if w.winfo_class() != "TCheckbutton" or w.instate(["disabled"]):
                return
            style = str(w.cget("style")) or "TCheckbutton"
        except (tk.TclError, AttributeError):
            return
        if style not in ("TCheckbutton", "Card.TCheckbutton"):
            return
        card = style.startswith("Card.")
        n = _SLIDES.get(PREFIX + ("Card" if card else ""))
        if not n:
            return
        if self._slide is not None:
            self._slide_end()
        if card:
            for i in range(n):
                name = f"Card.Slide{i}.TCheckbutton"
                if name not in _CARD_STYLES:
                    self.style.layout(name, _CARD_LAYOUTS[f"Slide{i}.TCheckbutton"])
                    self.style.configure(name, background=CARD)
                    self.style.map(name, background=_SURFACE_STATES(CARD))
                    _CARD_STYLES.add(name)
        self._slide = dict(w=w, style=style, on=w.instate(["selected"]), n=n, t0=time.perf_counter(),
                           prefix="Card." if card else "")
        self._slide_step()

    def _slide_step(self):
        sl = self._slide
        p = (time.perf_counter() - sl["t0"]) / 0.26
        if p >= 1:
            self._slide_end()
            return
        e = 1 - (1 - p) ** 3
        x = e if sl["on"] else 1 - e
        try:
            sl["w"].configure(style=f"{sl['prefix']}Slide{round(x * (sl['n'] - 1))}.TCheckbutton")
        except tk.TclError:
            self._slide = None
            return
        self._slide_job = self.win.after(12, self._slide_step)

    def _slide_end(self):
        sl, self._slide = self._slide, None
        if self._slide_job is not None:
            self.win.after_cancel(self._slide_job)
            self._slide_job = None
        try:
            sl["w"].configure(style=sl["style"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ frame
    def _s(self, v):
        return max(1, int(round(v * self.sc)))

    def _keep(self, img):
        self._imgs.append(img)
        return img

    def _tint_title(self):
        """Windows 11 colours the title bar to match (Windows 10 keeps its own)."""
        if sys.platform != "win32":
            return
        try:
            from . import winapi
            self.win.update_idletasks()
            hwnd = winapi.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            winapi.dark_title_bar(hwnd, C["dark_title"])
            winapi.tint_title_bar(hwnd, *C["title"])
        except Exception:
            pass

    def _build_sidebar(self):
        from PIL import ImageTk
        s = self._s
        self.side_w = sw = s(224)
        cv = tk.Canvas(self.win, width=sw, highlightthickness=0, bd=0, bg=skin.hexrgb(SKIN.SIDEBAR[1]))
        cv.grid(row=0, column=0, rowspan=2, sticky="ns")
        self.side = cv

        def P(im):
            return self._keep(ImageTk.PhotoImage(im, master=self.win))
        self.side_bg = cv.create_image(0, 0, anchor="nw")
        x, y = s(18), s(20)
        cv.create_image(x, y, image=P(aero.app_icon(s(32))), anchor="nw")
        cv.create_text(x + s(42), y + s(1), text=APP_NAME, anchor="nw", font=("Segoe UI Semibold", 13), fill=INK)
        cv.create_text(x + s(42), y + s(21), text="Settings", anchor="nw", font=("Segoe UI", 9), fill=MUTED)
        y += s(58)
        inset = s(16) if self.glide else s(12)
        pw, ph = sw - 2 * inset, s(36) if self.glide else s(38)
        sel_img, hot_img = P(SKIN.nav_pill(pw, ph, "selected")), P(SKIN.nav_pill(pw, ph, "hover"))
        self._sel_img = sel_img
        self.nav, group = [], None
        mid = ph // 2 - s(1)
        for i, (g, name, ic, _b) in enumerate(PAGES):
            if g != group:
                group = g
                y += (s(22) if self.glide else s(10)) if i else 0
                cv.create_text(s(24), y, text=g, anchor="nw", font=("Segoe UI Semibold", 9), fill=C["nav_group"])
                y += s(19)
            item = {"y0": y, "y1": y + ph,
                    "hot": cv.create_image(inset, y, image=hot_img, anchor="nw", state="hidden"),
                    "sel": cv.create_image(inset, y, image=sel_img, anchor="nw", state="hidden"),
                    "icons": (P(SKIN.icon(ic, s(18), SKIN.INK)), P(SKIN.icon(ic, s(18), C["nav_on_icon"])))}
            item["icon"] = cv.create_image(s(28), y + mid, image=item["icons"][0], anchor="w")
            item["shade"] = cv.create_text(s(56), y + mid + 1, text=name, anchor="w", fill=C["nav_shade"] or INK,
                                           font=("Segoe UI Semibold", 10), state="hidden")
            item["text"] = cv.create_text(s(56), y + mid, text=name, anchor="w", fill=INK, font=("Segoe UI", 10))
            self.nav.append(item)
            y += ph + s(2)
        self.side_need = y + s(56)
        self.side_ver = cv.create_text(s(24), 0, text=f"Version {VERSION}", anchor="sw", font=("Segoe UI", 9),
                                       fill=MUTED)
        self.side_link = cv.create_text(s(24), 0, text="Aqua Lite on GitHub", anchor="sw",
                                        font=("Segoe UI", 9, "underline"), fill=ACCENT)
        self.side_hot, self.side_sel = None, None
        # Liquid Glass: one bead of glass that glides from page to page on a spring
        self.bead_x = inset
        self.bead = cv.create_image(inset, self.nav[0]["y0"], image=sel_img, anchor="nw", state="hidden")
        self.bead_spring, self.bead_job, self.bead_t = None, None, 0.0
        cv.bind("<Configure>", self._side_resize)
        cv.bind("<Motion>", self._side_motion)
        cv.bind("<Leave>", lambda _e: self._side_hover(None))
        cv.bind("<Button-1>", self._side_click)

    def _side_resize(self, e):
        from PIL import ImageTk
        if getattr(self, "_side_h", None) == e.height:
            return
        self._side_h = h = e.height
        self._side_img = ImageTk.PhotoImage(SKIN.sidebar(self.side_w, max(h, 1)), master=self.win)
        self.side.itemconfigure(self.side_bg, image=self._side_img)
        s = self._s
        state = "normal" if h >= self.side_need else "hidden"
        self.side.coords(self.side_ver, s(24), h - s(34))
        self.side.coords(self.side_link, s(24), h - s(16))
        self.side.itemconfigure(self.side_ver, state=state)
        self.side.itemconfigure(self.side_link, state=state)

    def _side_at(self, e):
        if not (self._s(12) <= e.x <= self.side_w - self._s(12)):
            return None
        for i, item in enumerate(self.nav):
            if item["y0"] <= e.y < item["y1"]:
                return i
        return None

    def _on_link(self, e):
        if self.side.itemcget(self.side_link, "state") == "hidden":
            return False
        x0, y0, x1, y1 = self.side.bbox(self.side_link)
        return x0 <= e.x <= x1 and y0 <= e.y <= y1

    def _side_motion(self, e):
        i = self._side_at(e)
        self._side_hover(i)
        cur = "hand2" if i is not None or self._on_link(e) else ""
        if cur != getattr(self, "_side_cursor", ""):
            self._side_cursor = cur
            self.side.configure(cursor=cur)

    def _side_hover(self, i):
        if i == self.side_hot:
            return
        if self.side_hot is not None:
            self.side.itemconfigure(self.nav[self.side_hot]["hot"], state="hidden")
        self.side_hot = i
        if i is not None and i != self.side_sel:
            self.side.itemconfigure(self.nav[i]["hot"], state="normal")
            self.side.tag_raise(self.nav[i]["icon"])
            self.side.tag_raise(self.nav[i]["text"])

    def _side_click(self, e):
        i = self._side_at(e)
        if i is not None:
            self.show(i)
        elif self._on_link(e):
            import webbrowser
            webbrowser.open(REPO_URL)

    def _side_select(self, idx):
        cv = self.side
        for i, item in enumerate(self.nav):
            on = i == idx
            cv.itemconfigure(item["sel"], state="normal" if on and not self.glide else "hidden")
            if on:
                cv.itemconfigure(item["hot"], state="hidden")
            cv.itemconfigure(item["icon"], image=item["icons"][1 if on else 0])
            cv.itemconfigure(item["shade"], state="normal" if on and C["nav_shade"] else "hidden")
            cv.itemconfigure(item["text"], fill=C["nav_on_ink"] if on else INK,
                             font=("Segoe UI Semibold", 10) if on else ("Segoe UI", 10))
        self.side_sel = idx
        if self.glide:
            self._glide_to(self.nav[idx]["y0"])

    def _glide_to(self, y):
        """Move the glass bead to a page's row: a quick spring with a small overshoot, like Apple's sidebar."""
        from . import liquid
        cv = self.side
        if self.bead_spring is None or not cv.winfo_ismapped():
            self.bead_spring = liquid.Spring(y, response=0.32, damping=0.85)   # a small bounce
            cv.coords(self.bead, self.bead_x, y)
            cv.itemconfigure(self.bead, state="normal")
            cv.tag_lower(self.bead)
            cv.tag_raise(self.bead, self.side_bg)
            return
        self.bead_spring.target = y
        if self.bead_job is None:
            self.bead_t = time.perf_counter()
            self.bead_job = self.win.after(0, self._bead_step)

    def _bead_step(self):
        now = time.perf_counter()
        dt, self.bead_t = min(now - self.bead_t, 0.05), now
        sp = self.bead_spring
        sp.step(dt)
        try:
            self.side.coords(self.bead, self.bead_x, sp.x)
        except tk.TclError:
            self.bead_job = None
            return
        self.bead_job = None if sp.resting() else self.win.after(8, self._bead_step)

    def _make_page(self, name, builders):
        s = self._s
        outer = ttk.Frame(self.content)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_remove()
        page = {"outer": outer, "canvas": None}
        pad = (s(28), s(22), s(28), s(14))
        if name == "History":   # the list fills the page and scrolls by itself
            inner = ttk.Frame(outer, padding=pad)
            inner.pack(fill="both", expand=True)
        else:
            cv = tk.Canvas(outer, bg=PAGE, highlightthickness=0, bd=0, yscrollincrement=s(20))
            cv.pack(fill="both", expand=True)
            sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview, style="Page.Vertical.TScrollbar")
            cv.configure(yscrollcommand=sb.set)
            inner = ttk.Frame(cv, padding=pad)
            wid = cv.create_window(0, 0, window=inner, anchor="nw")

            def fit(_e=None, cv=cv, inner=inner, sb=sb, wid=wid):
                cw, ch = cv.winfo_width(), cv.winfo_height()
                if cw > 1 and int(float(cv.itemcget(wid, "width") or 0)) != cw:
                    cv.itemconfigure(wid, width=cw)
                need = inner.winfo_reqheight()
                cv.configure(scrollregion=(0, 0, cw, max(need, ch)))
                if need > ch + 1:   # the scrollbar floats over the margin, so showing it never re-wraps the page
                    sb.place(relx=1.0, x=-s(3), rely=0, y=s(4), relheight=1.0, height=-s(8), anchor="ne")
                else:
                    sb.place_forget()
                    cv.yview_moveto(0)
            cv.bind("<Configure>", fit)
            inner.bind("<Configure>", fit)
            page["canvas"] = cv
        title, sub = HEADINGS[name]
        ttk.Label(inner, text=title, style="H1.TLabel").pack(anchor="w")
        ttk.Label(inner, text=sub, style="Sub.TLabel", wraplength=s(700)).pack(anchor="w", pady=(s(2), s(16)))
        for b in builders:
            f = ttk.Frame(inner)
            f.pack(fill="both", expand=(name == "History"), pady=(0, s(4)))
            getattr(self, b)(f)
        return page

    def _restyle(self, w, in_card=False):
        for c in w.winfo_children():
            cls = c.winfo_class()
            if cls == "TFrame" and str(c.cget("style")) in CONTAINERS:
                self._restyle(c, True)
                continue
            if in_card and cls in _IN_CARD:
                _card_restyle(self.style, c)
            self._restyle(c, in_card)

    def show(self, tab):
        """Open a page by number or by name (old tab names still work)."""
        names = self.page_names
        if isinstance(tab, str):
            tab = ALIASES.get(tab, tab)
            idx = names.index(tab) if tab in names else 0
        else:
            idx = tab if isinstance(tab, int) and 0 <= tab < len(names) else 0
        name = names[idx]
        if name != self.current:
            if self.current:
                self.pages[self.current]["outer"].grid_remove()
            self.pages[name]["outer"].grid()
            self.current = name
        self._side_select(idx)

    def _step(self, d):
        self.show((self.page_names.index(self.current) + d) % len(self.page_names))
        return "break"

    def _wheel(self, e):
        page = self.pages.get(self.current) or {}
        cv = page.get("canvas")
        if cv is None:
            return
        try:
            if e.widget.winfo_class() in ("Text", "Listbox", "Treeview"):
                return   # those scroll themselves
        except (AttributeError, tk.TclError):
            pass
        top, bottom = cv.yview()
        if top <= 0 and bottom >= 1:
            return
        if e.num in (4, 5):
            step = -3 if e.num == 4 else 3
        else:
            self._wheel_acc += e.delta     # 120 per notch; touchpads send smaller steps
            step = int(-self._wheel_acc / 40)
            if not step:
                return
            self._wheel_acc += step * 40
        cv.yview_scroll(step, "units")

    # ------------------------------------------------------------------ helpers
    def _var(self, key, kind=tk.StringVar):
        val = self.cfg.get(key)
        var = kind(value=val)
        self.v[key] = var
        return var

    def _card(self, parent, title=None, sub=None, style="Panel.TFrame"):
        """A white card (optionally with a heading); returns the frame to put its contents in."""
        s = self._s
        card = ttk.Frame(parent, style=style, padding=(s(16), s(12), s(16), s(14)))
        card.pack(fill="x", pady=(0, s(12)))
        if title:
            ttk.Label(card, text=title, style="CardHead.TLabel").pack(anchor="w", pady=(0, s(4)))
        if sub:
            ttk.Label(card, text=sub, style="Muted.TLabel", wraplength=self.wrap).pack(anchor="w", pady=(0, s(6)))
        body = ttk.Frame(card)
        body.pack(fill="x")
        body.card = card
        return body

    def _row(self, parent, r, label, widget, hint=""):
        s = self._s
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=s(4), padx=(0, s(12)))
        widget.grid(row=r, column=1, sticky="w", pady=s(4))
        if hint:
            ttk.Label(parent, text=hint, style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=s(10))

    def _toggles(self, parent, pairs):
        for key, label in pairs:
            ttk.Checkbutton(parent, text=label, variable=self._var(key, tk.BooleanVar)).pack(anchor="w",
                                                                                           pady=self._s(1))

    def _boxed(self, widget):
        """Plain Tk lists and text boxes, dressed to match: white, a thin sky border, focus glow colour."""
        widget.configure(bg=C["list_bg"], fg=INK, relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=C["line"], highlightcolor=C["focus"], selectbackground=C["select"],
                         selectforeground=INK, font=("Segoe UI", 10))
        if isinstance(widget, tk.Text):
            widget.configure(insertbackground=INK, padx=self._s(8), pady=self._s(5))
        else:
            widget.configure(activestyle="none")
        return widget

    def _keys(self, parent, prefix, combo, suffix=""):
        s = self._s
        if prefix:
            ttk.Label(parent, text=prefix).pack(side="left", padx=(0, s(6)))
        for j, k in enumerate(p for p in combo.split("+") if p.strip()):
            if j:
                ttk.Label(parent, text="+", style="Muted.TLabel").pack(side="left", padx=s(4))
            ttk.Label(parent, text=_key_name(k), style="Key.TLabel").pack(side="left")
        if suffix:
            ttk.Label(parent, text=suffix).pack(side="left", padx=(s(6), 0))

    # ------------------------------------------------------------------ pages
    def _home(self, f):
        s = self._s
        st = history.stats()
        tiles = ttk.Frame(f)
        tiles.pack(fill="x", pady=(0, s(12)))
        for i, (val, lab) in enumerate(((f"{st['words']:,}", "words dictated"), (f"{st['wpm']:.0f}", "words / minute"),
                                        (f"{st['minutes_saved']:.0f} min", "saved vs typing"),
                                        (f"{st['week_words']:,}", "words this week"))):
            t = ttk.Frame(tiles, padding=(s(16), s(10), s(16), s(12)), style="Tile.TFrame")
            t.grid(row=0, column=i, padx=(0 if i == 0 else s(10), 0), sticky="nsew")
            tiles.columnconfigure(i, weight=1, uniform="tile")
            ttk.Label(t, text=val, style="Stat.TLabel").pack(anchor="w")
            ttk.Label(t, text=lab, style="Muted.TLabel").pack(anchor="w")
        c = self.cfg
        run = self._card(f, "Running now")
        pills = ttk.Frame(run)
        pills.pack(anchor="w")
        eng = stt.resolve_engine(c)
        prov = llm.resolve_provider(c)
        names = {"groq": "Groq", "openai": "OpenAI", "local": "this PC", "anthropic": "Anthropic",
                 "custom": "your server"}
        inst = c.get("instant_text_engine", "off")
        tags = [(f"Speech: {names.get(eng, eng)}", "blue"),
                (f"AI clean-up: {names.get(prov, prov)}" if prov else "AI clean-up: offline only",
                 "blue" if prov else "amber"),
                ("Instant text: " + {"off": "off", "preview": "quick preview", "gpu": "graphics card",
                                     "deepgram": "Deepgram"}.get(inst, inst), "blue" if inst == "off" else "green"),
                (f"Private mode: {'on' if c.get('private_mode') else 'off'}", "violet")]
        for txt, col in tags:
            ttk.Label(pills, text=txt, style=f"{col.title()}Pill.TLabel").pack(side="left", padx=(0, s(8)))
        if eng == "local":
            ttk.Label(run, text=f"Offline speech model: {stt.LOCAL.status}", style="Muted.TLabel").pack(
                anchor="w", pady=(s(8), 0))
        if eng == "local" and not prov:
            ttk.Label(run, style="Warn.TLabel", wraplength=self.wrap, text=(
                "Tip: paste a free Groq API key in Speech & AI for Wispr-level speed and AI formatting. "
                "Without it, everything runs offline on this PC.")).pack(anchor="w", pady=(s(6), 0))
        ptt = c["hotkey_ptt"]
        rows = [("Hold", ptt, "", "Push-to-talk: speak while holding, release to insert text"),
                ("", f"{ptt}+{c['hotkey_handsfree_key']}", "", "Hands-free: keeps listening until you press it again"),
                ("", f"{ptt}+{c['hotkey_command_key']}", "", "Command Mode: edit or ask by voice"),
                ("Tap", ptt, "twice", "Hands-free, without reaching for the extra key"),
                ("", c["hotkey_paste_last"], "", "Paste your last transcript again"),
                ("", c.get("hotkey_undo_last", "alt+shift+x"), "", "Undo: remove the text of your last dictation"),
                ('Say "press enter"', "", "", 'At the end of a dictation: types it, then presses Enter'),
                ("", c["hotkey_cancel"], "", "Cancel the current recording")]
        box = self._card(f, "Shortcuts")
        for i, (pre, combo, suf, desc) in enumerate(rows):
            kf = ttk.Frame(box)
            kf.grid(row=i, column=0, sticky="w", pady=s(3))
            self._keys(kf, pre, combo, suf)
            ttk.Label(box, text=desc, style="Muted.TLabel").grid(row=i, column=1, sticky="w", padx=(s(18), 0))

    # ------------------------------------------------------------------ Flow bar preview
    def _preview_look(self):
        """Show the chosen theme's Flow bar, live, over a little desktop, before saving."""
        look = self.look_box.get_key()
        self.look_mode_box.configure(state="readonly" if look == "liquid" else "disabled")
        self._preview_set("Dictation", self.preview, look, self.look_mode_box.get_key())

    def _preview_set(self, page, label, look, mode):
        """Start (or change) the live Flow bar preview shown in `label` on `page`."""
        from PIL import Image, ImageDraw
        sc = self.sc * 0.9
        if look == "liquid":
            from . import liquid, liquidskin
            mode = liquid.resolve_mode(mode)
            r = liquid.LiquidBarRenderer(sc, frost=False, mode=mode)
            back = liquidskin.Skin(mode).backdrop(*r.size)
        else:
            r = aero.FlowBarRenderer(sc)
            top, bottom = (120, 196, 245), (226, 244, 255)
            col = Image.new("RGB", (1, r.size[1]))
            col.putdata([tuple(int(a + (b - a) * y / max(1, r.size[1] - 1)) for a, b in zip(top, bottom))
                         for y in range(r.size[1])])
            back = col.resize(r.size)
        mask = Image.new("L", r.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, r.size[0] - 1, r.size[1] - 1), radius=self._s(12), fill=255)
        self._pv[page] = dict(r=r, back=back.convert("RGBA"), mask=mask, label=label, t0=time.perf_counter())
        if not self._pv_running:
            self._pv_running = True
            self._preview_step()

    def _preview_step(self):
        """One frame of the preview on the open page: listening with words, thinking, then done, round and round.
        About 15 times a second, and only while its page is showing."""
        from PIL import Image, ImageTk
        if self._pv is None:
            return
        try:
            pv = self._pv.get(self.current)
            if pv is not None and self.win.winfo_viewable():
                t = time.perf_counter() - pv["t0"]
                k = t % 6.0
                levels = [0.25 + 0.22 * math.sin(t * 5.1 + i * 0.7) + 0.18 * math.sin(t * 8.3 + i * 1.9)
                          for i in range(aero.BARS + 1)]
                levels = [max(0.0, min(1.0, v)) for v in levels]
                if k < 3.6:
                    img = pv["r"].render("recording", "", levels, t, "info", "Your words show up here as you talk",
                                         1.0, min(1.0, k / 0.5))
                elif k < 4.8:
                    img = pv["r"].render("processing", "", levels, t)
                else:
                    img = pv["r"].render("toast", "Pasted", levels, t, "ok")
                frame = pv["back"].copy()
                frame.alpha_composite(img)
                flat = Image.new("RGB", frame.size, tuple(int(CARD[i:i + 2], 16) for i in (1, 3, 5)))
                flat.paste(frame, (0, 0), pv["mask"])
                pv["img"] = ImageTk.PhotoImage(flat, master=self.win)
                pv["label"].configure(image=pv["img"])
            self.win.after(66, self._preview_step)
        except tk.TclError:
            self._pv = None

    def _news(self, f):
        """What's new: the CHANGELOG entry for this version, a card per change, and buttons to try things."""
        from . import config
        s = self._s
        name, summary, items = config.whats_new_full(VERSION)
        hero = self._card(f, f"Aqua Lite {VERSION}" + (f": {name}" if name else ""), summary.capitalize() or None)
        shot = ttk.Label(hero)
        shot.pack(anchor="w", pady=(s(2), s(8)))
        # the new Flow bar, live: Liquid Glass in the colours this window uses (or Windows' when it's Aero)
        mode = self.look[1] or "system"
        self.win.after(350, lambda: self._preview_set("What's new", shot, "liquid", mode))
        acts = ttk.Frame(hero)
        acts.pack(anchor="w", pady=(s(4), 0))
        if self.look[0] == "aero":
            ttk.Button(acts, text="Try Liquid Glass", style="Primary.TButton",
                       command=lambda: self._try_look("liquid")).pack(side="left")
        else:
            ttk.Button(acts, text="Back to Frutiger Aero", command=lambda: self._try_look("aero")).pack(side="left")
        ttk.Button(acts, text="Instant text", command=lambda: self.show("Instant text")).pack(side="left",
                                                                                          padx=(s(8), 0))
        ttk.Button(acts, text="Private mode", command=lambda: self.show("Private mode")).pack(side="left",
                                                                                          padx=(s(8), 0))
        if not items:
            return
        box = self._card(f)
        for i, (head, text) in enumerate(items):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=(0 if i == 0 else s(10), 0))
            if head:
                ttk.Label(row, text=head, style="Strong.TLabel").pack(anchor="w")
            ttk.Label(row, text=text[:1].upper() + text[1:], style="Muted.TLabel", wraplength=self.wrap).pack(
                anchor="w")

    def _try_look(self, look):
        """One click from What's new: switch theme and save, so the window and the Flow bar change right away."""
        labels = dict(LOOKS)
        self.look_box.set(labels[look])
        self.save()

    def _general(self, f):
        keys = self._card(f, "Shortcuts")
        for r, (key, label, hint) in enumerate((
                ("hotkey_ptt", "Push-to-talk (hold)", "e.g. ctrl+win, f9, right alt, rctrl"),
                ("hotkey_handsfree_key", "+ key for hands-free", "pressed while holding push-to-talk"),
                ("hotkey_command_key", "+ key for Command Mode", "pressed while holding push-to-talk"),
                ("hotkey_paste_last", "Paste last transcript", ""),
                ("hotkey_undo_last", "Undo last dictation", "removes what Aqua Lite just typed"),
                ("hotkey_cancel", "Cancel recording", ""))):
            self._row(keys, r, label, ttk.Entry(keys, textvariable=self._var(key), width=24), hint)
        mic_card = self._card(f, "Microphone & language")
        devices = ["(Windows default)"] + _safe_devices()
        mic = tk.StringVar(value=self.cfg.get("mic_device") or "(Windows default)")
        self.v["mic_device"] = mic
        mic_list = ttk.Combobox(mic_card, textvariable=mic, values=devices, state="readonly", width=44)
        self._row(mic_card, 0, "Microphone", mic_list)
        mic_list.grid_configure(columnspan=2)
        self.lang = _pair_combo(mic_card, LANGS, self.cfg.get("language", "auto"), width=22)
        self._row(mic_card, 1, "Language", self.lang, "Auto handles Arabic, English and mixing")
        self._row(mic_card, 2, "Hands-free stops after",
                  ttk.Spinbox(mic_card, from_=0, to=60, width=6, textvariable=self._var("handsfree_silence_secs")),
                  "seconds of silence (0 = never)")
        talk = self._card(f, "While you talk")
        self._toggles(talk, (
            ("live_preview", "Show my words in the bar while I talk (when instant text is off)"),
            ("learn_corrections", "Learn words I correct right after dictating"),
            ("voice_enter", 'Say "press enter" or "send it" at the end to press Enter'),
            ("double_tap_handsfree", "Tap the shortcut twice for hands-free"),
            ("sounds", "Play start/stop sounds"),
            ("show_idle_bar", "Keep the Flow bar on screen when idle (click it to start hands-free)"),
            ("frosted_glass", "Frosted glass Flow bar: see-through, with what's behind it softly blurred"
                              + ("" if _blur_ok() else " (Windows 10 only)")),
            ("gpu_flow_bar", "Draw the Flow bar on the graphics card (smoother, less processor work)"),
            ("whisper_boost", "Whisper mode (boost quiet speech)")))
        theme = self._card(f, "Theme", "The Flow bar and this window change as soon as you save, no restart "
                                       "needed. Frutiger Aero is the classic glossy sky blue; Liquid Glass is "
                                       "clear glass that flows from shape to shape.")
        self.look_box = _pair_combo(theme, LOOKS, self.cfg.get("look", "aero"), width=22)
        self._row(theme, 0, "Theme", self.look_box)
        self.look_mode_box = _pair_combo(theme, LOOK_MODES, self.cfg.get("look_mode", "system"), width=22)
        self._row(theme, 1, "Liquid Glass colours", self.look_mode_box, "Light or dark glass")
        self.preview = ttk.Label(theme)
        self.preview.grid(row=2, column=0, columnspan=3, sticky="w", pady=(self._s(10), 0))
        for box in (self.look_box, self.look_mode_box):
            box.bind("<<ComboboxSelected>>", lambda _e: self._preview_look(), add="+")
        self.win.after(300, self._preview_look)
        typing = self._card(f, "Typing & Windows")
        self._toggles(typing, (
            ("add_trailing_space", "Add a space after each dictation"),
            ("restore_clipboard", "Restore my clipboard after pasting"),
            ("shift_insert_in_editors", "Use Shift+Insert in VS Code / Cursor / Windsurf"),
            ("launch_at_startup", "Start Aqua Lite when Windows starts"),
            ("auto_update", "Update automatically when Aqua Lite starts")))

    def _ai(self, f):
        s = self._s
        top = self._card(f, "Speech to text")
        eng = self._var("stt_engine")
        radios = ttk.Frame(top)
        radios.grid(row=0, column=0, columnspan=4, sticky="w")
        for val, lab in (("auto", "Auto"), ("groq", "Groq (fast, cloud)"), ("openai", "OpenAI (cloud)"),
                         ("local", "On this PC (offline)")):
            ttk.Radiobutton(radios, text=lab, value=val, variable=eng).pack(side="left", padx=(0, s(18)))
        ttk.Label(top, text="Offline model").grid(row=1, column=0, sticky="w", pady=(s(10), 0))
        ttk.Combobox(top, textvariable=self._var("local_model"), state="readonly", width=16,
                     values=["tiny", "base", "small", "medium", "large-v3-turbo"]).grid(
            row=1, column=1, sticky="w", pady=(s(10), 0), padx=(s(10), 0))
        ttk.Combobox(top, textvariable=self._var("local_device"), state="readonly", width=8,
                     values=["auto", "cpu", "cuda"]).grid(row=1, column=2, sticky="w", pady=(s(10), 0),
                                                          padx=(s(8), 0))
        ttk.Label(top, text="small = good balance on CPU; large-v3-turbo needs an NVIDIA GPU",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w", pady=(s(4), 0))

        mid = self._card(f, "AI formatting & Command Mode")
        ttk.Label(mid, text="Provider").grid(row=0, column=0, sticky="w")
        ttk.Combobox(mid, textvariable=self._var("ai_provider"), state="readonly", width=14,
                     values=["auto", "groq", "openai", "anthropic", "custom", "off"]).grid(
            row=0, column=1, sticky="w", padx=(s(10), 0))
        self.strength = _pair_combo(mid, STRENGTHS, self.cfg.get("editing_strength", "medium"), width=30)
        ttk.Label(mid, text="Editing strength").grid(row=0, column=2, sticky="e", padx=(s(20), s(8)))
        self.strength.grid(row=0, column=3, sticky="w")

        keys = self._card(f, "API keys & models", sub=(
            "Stored only on this PC. A free Groq key (console.groq.com/keys) powers both speech and formatting."))
        rows = (("Groq key", "groq_api_key", "groq_llm_model", "groq_stt_model", ""),
                ("OpenAI key", "openai_api_key", "openai_llm_model", "openai_stt_model", ""),
                ("Anthropic key", "anthropic_api_key", "anthropic_llm_model", None, ""),
                ("Custom key", "custom_api_key", "custom_llm_model", None, "LM Studio, Ollama"))
        ttk.Label(keys, text="AI model", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=s(4))
        ttk.Label(keys, text="Speech", style="Muted.TLabel").grid(row=0, column=3, sticky="w", padx=s(4))
        for i, (lab, k, m, sm, hint) in enumerate(rows, start=1):
            ttk.Label(keys, text=lab).grid(row=i, column=0, sticky="w", pady=s(3))
            ttk.Entry(keys, textvariable=self._var(k), show="•", width=24).grid(row=i, column=1, sticky="w",
                                                                                   padx=s(4))
            ttk.Entry(keys, textvariable=self._var(m), width=16).grid(row=i, column=2, sticky="w", padx=s(4))
            if sm:
                ttk.Entry(keys, textvariable=self._var(sm), width=16).grid(row=i, column=3, sticky="w", padx=s(4))
            elif hint:
                ttk.Label(keys, text=hint, style="Muted.TLabel").grid(row=i, column=3, sticky="w", padx=s(4))
        ttk.Label(keys, text="Custom server URL").grid(row=5, column=0, sticky="w", pady=(s(8), 0))
        ttk.Entry(keys, textvariable=self._var("custom_base_url"), width=24).grid(row=5, column=1, sticky="w",
                                                                                 padx=s(4), pady=(s(8), 0))
        ttk.Button(f, text="Test AI connection", command=self._test_ai).pack(anchor="w", pady=(0, s(6)))

    INSTANT_ENGINES = [
        ("off", "Off", "Your text appears when you let go, already polished. Works on every PC."),
        ("preview", "Quick preview",
         "A small speech model on your processor types words as you talk. Rough at first: each sentence is heard "
         "again by your main speech engine and tidied as you finish it. Uses some processor power while you talk."),
        ("gpu", "Graphics card",
         "Needs an NVIDIA graphics card. A Whisper model runs on the card, so the live words are almost the "
         "final text - pick one below (the recommended one fits your card). One-time download: about 1 GB of NVIDIA "
         "libraries plus the model. The card only works while you talk."),
        ("deepgram", "Deepgram",
         "Needs a Deepgram account (console.deepgram.com: free credit when you sign up, then about $0.46 per hour "
         "of talking). Your voice streams to Deepgram while you talk and accurate words arrive in about 0.3 s. "
         "Letting go is faster too, because the transcript is already done."),
    ]
    INSTANT_TAGS = {"off": [("Every PC", "green")], "preview": [("Any PC", "green")],
                    "gpu": [("NVIDIA graphics card only", "amber")],
                    "deepgram": [("Any PC", "green"), ("Needs internet + a Deepgram key", "amber")]}

    def _instant(self, f):
        s = self._s
        var = tk.StringVar(value=self.cfg.get("instant_text_engine", "off"))
        self.v["instant_text_engine"] = var
        self.pick_cards = {}
        indent = s(28)   # lines things up under the option's name, past the radio orb
        for key, title, desc in self.INSTANT_ENGINES:
            box = self._card(f, style="Pick.TFrame")
            head = ttk.Frame(box)
            head.pack(fill="x")
            ttk.Radiobutton(head, text=title, value=key, variable=var, style="Title.TRadiobutton").pack(side="left")
            for txt, col in self.INSTANT_TAGS.get(key, ()):
                ttk.Label(head, text=txt, style=f"{col.title()}Pill.TLabel").pack(side="left", padx=(s(10), 0))
            d = ttk.Label(box, text=desc, wraplength=self.wrap - indent, style="Muted.TLabel")
            d.pack(anchor="w", padx=(indent, 0), pady=(s(2), 0))
            for w in (box.card, box, head, d):   # click anywhere on the card to pick it
                w.bind("<Button-1>", lambda _e, k=key: var.set(k), add="+")
            self.pick_cards[key] = box.card
            if key == "gpu":
                row = ttk.Frame(box)
                row.pack(fill="x", padx=(indent, 0), pady=(s(8), 0))
                ttk.Label(row, text="Model").pack(side="left")
                self.gpu_keys = list(gpu.MODELS)
                self.gpu_model = ttk.Combobox(row, state="readonly", width=40, values=["Checking your card..."])
                self.gpu_model.current(0)
                self.gpu_model.pack(side="left", fill="x", expand=True, padx=(s(10), 0))
                row2 = ttk.Frame(box)
                row2.pack(anchor="w", padx=(indent, 0), pady=(s(6), 0))
                ttk.Label(row2, text="Free the card after").pack(side="left")
                mins = tk.DoubleVar(value=float(self.cfg.get("gpu_idle_minutes", 5)))
                self.v["gpu_idle_minutes"] = mins
                idle_txt = ttk.Label(row2, width=26, style="Muted.TLabel")

                def show_idle(_v=None):
                    m = int(round(mins.get()))
                    mins.set(m)
                    idle_txt.configure(text="never (keep it loaded)" if m == 0 else
                                       f"{m} minute{'s' if m != 1 else ''} without talking")
                ttk.Scale(row2, from_=0, to=60, orient="horizontal", length=s(240), variable=mins,
                          command=show_idle).pack(side="left", padx=s(10))
                idle_txt.pack(side="left")
                show_idle()
                row3 = ttk.Frame(box)
                row3.pack(anchor="w", padx=(indent, 0), pady=(s(8), 0))
                self.gpu_btn = ttk.Button(row3, text="Set up graphics card", command=self._gpu_setup)
                self.gpu_btn.pack(side="left")
                self.gpu_status = ttk.Label(row3, text="Checking for an NVIDIA card...", style="Muted.TLabel")
                self.gpu_status.pack(side="left", padx=s(10))
            if key == "deepgram":
                row = ttk.Frame(box)
                row.pack(anchor="w", padx=(indent, 0), pady=(s(8), 0))
                ttk.Label(row, text="Deepgram API key").pack(side="left")
                ttk.Entry(row, textvariable=self._var("deepgram_api_key"), width=46, show="•").pack(
                    side="left", padx=s(10))

        def mark(*_a):
            for k, card in self.pick_cards.items():
                card.configure(style="PickOn.TFrame" if var.get() == k else "Pick.TFrame")
        var.trace_add("write", mark)
        mark()
        when = self._card(f, "When you let go", "Each sentence is tidied by the AI as soon as you finish it, so "
                          "letting go only finishes the last one.")
        ttk.Checkbutton(when, text="Double-check the whole recording instead (slower, a little more accurate)",
                        variable=self._var("instant_text_recheck", tk.BooleanVar)).pack(anchor="w")
        ttk.Label(when, text="Private mode never uses Deepgram: it types with the on-PC engine instead.",
                  style="Muted.TLabel", wraplength=self.wrap).pack(anchor="w", pady=(s(6), 0))
        self.gpu_job = None
        threading.Thread(target=self._gpu_check, daemon=True).start()

    def _gpu_say(self, text):
        try:
            self.win.after(0, lambda: self.gpu_status.winfo_exists() and self.gpu_status.configure(text=text))
        except (tk.TclError, RuntimeError):
            pass

    def _gpu_selected(self):
        """The model picked in the list, or 'auto' when it still shows the recommendation."""
        i = self.gpu_model.current()
        if i < 0 or not getattr(self, "gpu_ready_list", False):
            return self.cfg.get("gpu_model", "auto")
        key = self.gpu_keys[i]
        # still on the recommendation: keep "auto", so a new graphics card gets its own recommendation
        return "auto" if (key == self.gpu_best and self.cfg.get("gpu_model", "auto") == "auto") else key

    def _gpu_fill(self, mem):
        best = self.gpu_best = gpu.recommend(mem, self.cfg.get("language", "auto"))
        cur = self.cfg.get("gpu_model", "auto")
        cur = cur if cur in gpu.MODELS else best
        self.gpu_model.configure(values=[gpu.choice_label(k, mem, best) for k in self.gpu_keys])
        self.gpu_model.current(self.gpu_keys.index(cur))
        self.gpu_ready_list = True

    def _gpu_check(self):
        has, name, mem = gpu.detect()
        self.win.after(0, lambda: self._gpu_fill(mem if has else 0))
        if not has:
            self._gpu_say("No NVIDIA graphics card found - this option won't work on this PC.")
            self.win.after(0, lambda: self.gpu_btn.configure(state="disabled"))
            return
        card = f"{name}" + (f" ({mem / 1024:.0f} GB)" if mem else "")
        if mem and mem < 3500:
            self._gpu_say(f"{card}: probably too little graphics memory for this.")
        elif gpu.GPU.model is not None:
            self._gpu_say(f"{card}: ready.")
            self.win.after(0, lambda: self.gpu_btn.configure(text="Set up again"))
        elif gpu.libraries_installed():
            self._gpu_say(f"{card}: set up. The model loads when you next talk.")
            self.win.after(0, lambda: self.gpu_btn.configure(text="Test it"))
        else:
            self._gpu_say(f"{card} found. Pick a model and click Set up.")

    def _gpu_setup(self):
        if self.gpu_job:
            return
        self.gpu_job = True
        self.gpu_btn.configure(state="disabled")

        def run():
            try:
                has, name, mem = gpu.detect()
                if not has:
                    raise RuntimeError("no NVIDIA graphics card found")
                if not gpu.libraries_installed():
                    self._gpu_say("Installing NVIDIA's libraries (about 1 GB)...")
                    gpu.install_libraries(lambda line: self._gpu_say("Installing: " + line[:70]))
                key = self._gpu_selected()
                gpu.GPU.want = key
                size = gpu.MODELS.get(key if key in gpu.MODELS else gpu.MODEL)["size"] / 1000
                self._gpu_say(f"Loading the model onto the card (first time downloads about {size:.1f} GB)...")
                gpu.GPU.load()
                secs = gpu.GPU.bench()
                self._gpu_say(f"Ready: {gpu.GPU.key}, {secs:.2f}s per pass on {name}. Pick this option and Save.")
                self.win.after(0, lambda: self.v["instant_text_engine"].set("gpu"))
            except Exception as e:
                gpu.GPU.failed = str(e)
                self._gpu_say(f"Didn't work: {str(e)[:120]}")
            finally:
                self.gpu_job = None
                try:
                    self.win.after(0, lambda: self.gpu_btn.configure(state="normal"))
                except (tk.TclError, RuntimeError):
                    pass
        threading.Thread(target=run, daemon=True, name="gpu-setup").start()

    def _private(self, f):
        s = self._s
        dl = self._card(f, "The built-in AI", sub=(
            "AI clean-up, Command Mode and edit-by-voice run on an AI model built into Aqua Lite, and your voice is "
            "turned into text by the offline speech model. Download it once; after that it works without internet."))
        row = ttk.Frame(dl)
        row.pack(fill="x")
        ttk.Label(row, text="AI model").pack(side="left", padx=(0, s(10)))
        self.ai_keys = list(localai.MODELS)
        self.ai_model = ttk.Combobox(row, state="readonly", width=60,
                                     values=[localai.MODELS[k]["label"] for k in self.ai_keys])
        cur = self.cfg.get("local_ai_model", localai.DEFAULT_MODEL)
        self.ai_model.current(self.ai_keys.index(cur) if cur in self.ai_keys else 0)
        self.ai_model.pack(side="left")
        self.ai_model.bind("<<ComboboxSelected>>", lambda _e: self._ai_refresh())
        self.ai_bar = ttk.Progressbar(dl, length=s(560), mode="determinate", maximum=1000)
        self.ai_bar.pack(anchor="w", pady=(s(14), s(4)))
        self.ai_status = ttk.Label(dl, text="", style="Muted.TLabel")
        self.ai_status.pack(anchor="w")
        btns = ttk.Frame(dl)
        btns.pack(anchor="w", pady=(s(10), 0))
        self.ai_dl = ttk.Button(btns, text="Download", command=self._ai_download)
        self.ai_dl.pack(side="left")
        self.ai_cancel_btn = ttk.Button(btns, text="Cancel", command=self._ai_cancel, state="disabled")
        self.ai_cancel_btn.pack(side="left", padx=s(8))
        ttk.Button(btns, text="Delete the downloaded AI", command=self._ai_delete).pack(side="left")

        pm = self._card(f, "Private mode")
        ttk.Checkbutton(pm, text="Keep my voice and text on this PC", variable=self._var("private_mode", tk.BooleanVar),
                        command=self._private_toggled).pack(anchor="w")
        row = ttk.Frame(pm)
        row.pack(anchor="w", pady=(s(10), s(2)))
        ttk.Label(row, text="Free its memory after").pack(side="left")
        pmins = tk.DoubleVar(value=float(self.cfg.get("private_idle_minutes", 10)))
        self.v["private_idle_minutes"] = pmins
        ptxt = ttk.Label(row, width=30, style="Muted.TLabel")

        def show_pidle(_v=None):
            m = int(round(pmins.get()))
            pmins.set(m)
            ptxt.configure(text="never (keep it loaded)" if m == 0 else
                           f"{m} minute{'s' if m != 1 else ''} unused (restarts as you talk)")
        ttk.Scale(row, from_=0, to=60, orient="horizontal", length=s(240), variable=pmins,
                  command=show_pidle).pack(side="left", padx=s(10))
        ptxt.pack(side="left")
        show_pidle()
        ttk.Label(pm, wraplength=self.wrap, style="Muted.TLabel", text=(
            "Speech uses the offline model picked under Speech & AI (\"small\" is a good balance). With a graphics "
            "card the AI answers in about a second; on the processor alone it can take several seconds, so pick the "
            "Small model there.")).pack(anchor="w", pady=(s(8), 0))
        self.ai_job = None
        self._ai_refresh()

    def _ai_key(self):
        return self.ai_keys[max(0, self.ai_model.current())]

    def _ai_refresh(self):
        if self.ai_job:  # a download is running: its own updates own the status line
            return
        key = self._ai_key()
        ok = localai.ready(key)
        self.ai_dl.configure(text="Downloaded" if ok else "Download", state="disabled" if ok else "normal")
        self.ai_bar.configure(value=1000 if ok else 0)
        self.ai_status.configure(text="Ready to use." if ok else "Not downloaded yet.")

    def _ai_download(self):
        key = self._ai_key()
        cancel = threading.Event()
        job = {"stage": "Starting...", "done": 0, "total": None, "error": None, "finished": False, "cancel": cancel}
        self.ai_job = job

        def progress(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        def run():
            try:
                localai.install(key, progress, cancel)
            except Exception as e:
                job["error"] = str(e)
            job["finished"] = True
        self.ai_dl.configure(state="disabled")
        self.ai_cancel_btn.configure(state="normal")
        threading.Thread(target=run, daemon=True, name="ai-download").start()
        self._ai_poll()

    def _ai_poll(self):
        job = self.ai_job
        if job is None or not self.win.winfo_exists():
            return
        total, done = job["total"], job["done"]
        if total:
            self.ai_bar.configure(mode="determinate", value=int(1000 * done / total))
            self.ai_status.configure(text=f"{job['stage']}  {done / 1e6:,.0f} of {total / 1e6:,.0f} MB")
        else:
            self.ai_status.configure(text=job["stage"])
        if not job["finished"]:
            self.win.after(200, self._ai_poll)
            return
        self.ai_job = None
        self.ai_cancel_btn.configure(state="disabled")
        if job["error"]:
            self._ai_refresh()
            self.ai_status.configure(text=("Cancelled." if job["error"] == "cancelled"
                                           else f"Download failed: {job['error'][:150]}"))
            return
        self._ai_refresh()
        self.v["private_mode"].set(True)
        self.ai_status.configure(text="Downloaded and tested. Click Save to switch to private mode.")

    def _ai_cancel(self):
        if self.ai_job:
            self.ai_job["cancel"].set()

    def _private_toggled(self):
        if self.v["private_mode"].get() and not localai.ready(self._ai_key()):
            self.v["private_mode"].set(False)
            messagebox.showinfo(APP_NAME, "Download the AI model first (the Download button above).", parent=self.win)

    def _ai_delete(self):
        if self.ai_job:
            return
        if messagebox.askyesno(APP_NAME, "Delete the downloaded private AI (engine and models)?", parent=self.win):
            localai.remove_all()
            self.v["private_mode"].set(False)
            self._ai_refresh()

    def _style(self, f):
        s = self._s
        card = self._card(f, "How each kind of app should sound",
                          sub="Aqua Lite formats differently depending on where you're typing.")
        self.style_boxes = {}
        for i, (key, title, apps) in enumerate(CATS):
            cell = ttk.Frame(card)
            cell.grid(row=i, column=0, sticky="w", pady=s(5))
            ttk.Label(cell, text=title, style="Strong.TLabel").pack(anchor="w")
            ttk.Label(cell, text=apps, style="Muted.TLabel").pack(anchor="w")
            cb = _pair_combo(card, STYLE_NAMES, self.cfg["styles"].get(key, "formal"), width=14)
            cb.grid(row=i, column=1, sticky="w", padx=s(18))
            ex = ttk.Label(card, text="", style="Muted.TLabel")
            ex.grid(row=i, column=2, sticky="w")
            upd = lambda _e=None, cb=cb, ex=ex: ex.configure(text=f"“{STYLE_EXAMPLE[cb.get_key()]}”")  # noqa
            cb.bind("<<ComboboxSelected>>", upd)
            upd()
            self.style_boxes[key] = cb
        ttk.Checkbutton(card, text="Code mode: in code editors and terminals, keep file names, variables and "
                                   "commands exact", variable=self._var("code_mode", tk.BooleanVar)).grid(
            row=len(CATS), column=0, columnspan=3, sticky="w", pady=(s(10), 0))

        smart = self._card(f, "Get to know me")
        indent = s(46)   # under a toggle's text
        ttk.Checkbutton(smart, text="Learn from how I edit Aqua Lite's text (wording, punctuation, emoji, formatting)",
                        variable=self._var("learn_style", tk.BooleanVar)).grid(row=0, column=0, columnspan=3,
                                                                                sticky="w")
        self.learned_label = ttk.Label(smart, text="", style="Muted.TLabel")
        self.learned_label.grid(row=1, column=0, sticky="w", padx=(indent, 0))
        ttk.Button(smart, text="Forget what it learned", command=self._forget_edits).grid(row=1, column=1, sticky="w",
                                                                                         padx=s(10), pady=s(4))
        ttk.Checkbutton(smart, text="Read the conversation on screen so names, topic and tone fit what I'm replying to",
                        variable=self._var("screen_context", tk.BooleanVar)).grid(row=2, column=0, columnspan=3,
                                                                                    sticky="w", pady=(s(10), 0))
        ttk.Label(smart, style="Muted.TLabel", wraplength=self.wrap - indent, text=(
            "Reads only what's visible in the app you're dictating into, and sends it to your AI provider with the "
            "dictation. Never saved. Password boxes and private/incognito windows are never read.")).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=(indent, 0))
        row = ttk.Frame(smart)
        row.grid(row=4, column=0, columnspan=3, sticky="w", padx=(indent, 0), pady=(s(8), 0))
        ttk.Label(row, text="Never read these apps").pack(side="left")
        self.blocked = tk.StringVar(value=", ".join(self.cfg.get("context_blocked_apps") or []))
        ttk.Entry(row, textvariable=self.blocked, width=50).pack(side="left", padx=s(10))
        self._count_edits()

    def _memory(self, f):
        s = self._s
        card = self._card(f, "What it learned from your edits", sub=(
            "How you write, as Aqua Lite has learned it from your edits. It's used every time it formats a "
            "dictation, and rebuilt by your AI every few new edits. Change anything you like here - add or remove "
            "lines - and click Save. Only style is kept here, never what your messages were about."))
        prof = memory.load()
        self.mem_text = {}
        for key, label in memory.KINDS:
            ttk.Label(card, text=label, style="Eyebrow.TLabel").pack(anchor="w", pady=(s(8), s(3)))
            t = self._boxed(tk.Text(card, height=3, wrap="word"))
            t.insert("1.0", prof["styles"].get(key, ""))
            t.pack(fill="x")
            self.mem_text[key] = t
        self.mem_status = ttk.Label(card, text="", style="Muted.TLabel")
        self.mem_status.pack(anchor="w", pady=(s(10), s(4)))
        row = ttk.Frame(card)
        row.pack(anchor="w", pady=(s(2), 0))
        ttk.Button(row, text="Update from my edits now", command=self._mem_update).pack(side="left")
        ttk.Button(row, text="Export my memory...", command=self._mem_export).pack(side="left", padx=s(8))
        ttk.Button(row, text="Import...", command=self._mem_import).pack(side="left")
        self._mem_refresh_status(prof)

    def _mem_refresh_status(self, prof=None):
        prof = prof or memory.load()
        try:
            n = history.correction_count()
        except Exception:
            n = 0
        when = time.strftime("%d %b %Y, %H:%M", time.localtime(prof["updated"])) if prof["updated"] else "not yet"
        self.mem_status.configure(text=f"Learned from {n} edit{'s' if n != 1 else ''} - profile updated: {when}")

    def _mem_typed(self):
        return {k: memory.tidy(self.mem_text[k].get("1.0", "end")) for k, _ in memory.KINDS}

    def _mem_save_typed(self):
        prof = memory.load()
        typed = self._mem_typed()
        if typed != prof["styles"]:
            prof["styles"] = typed
            prof["updated"] = time.time()
            memory.save(prof)

    def _mem_reload(self):
        prof = memory.load()
        for k, _ in memory.KINDS:
            self.mem_text[k].delete("1.0", "end")
            self.mem_text[k].insert("1.0", prof["styles"].get(k, ""))
        self._mem_refresh_status(prof)

    def _mem_update(self):
        self._mem_save_typed()   # so the AI starts from what you wrote
        self.mem_status.configure(text="Updating from your edits...")

        def done(changed, msg):
            def ui():
                if not self.win.winfo_exists():
                    return
                self._mem_reload()
                self.mem_status.configure(text=msg + " - " + self.mem_status.cget("text"))
            self.win.after(0, ui)
        self.app.update_memory(force=True, done=done)

    def _mem_export(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.win, title="Export my Aqua Lite memory",
                                            defaultextension=".json", initialfile="aqualite-memory.json",
                                            filetypes=[("Aqua Lite memory", "*.json")])
        if not path:
            return
        self._mem_save_typed()
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(memory.export_bundle(self._collect(), history.all_corrections()), fh, indent=2,
                      ensure_ascii=False)
        messagebox.showinfo(APP_NAME, "Saved. Import it on another PC from Settings > Memory.", parent=self.win)

    def _mem_import(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.win, title="Import Aqua Lite memory",
                                          filetypes=[("Aqua Lite memory", "*.json")])
        if not path:
            return
        import json
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            cfg = self._collect()
            summary = memory.import_bundle(cfg, data, history.add_correction)
        except (OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"Couldn't import that file: {e}", parent=self.win)
            return
        self.app.apply_settings(cfg)
        messagebox.showinfo(APP_NAME, f"Imported {summary}.", parent=self.win)
        tab = self.current
        self.win.destroy()
        self.app.open_settings(tab)

    def _count_edits(self):
        try:
            n = history.correction_count()
        except Exception:
            n = 0
        self.learned_label.configure(text=f"Learned from {n} edit{'s' if n != 1 else ''} so far (kept on this PC)")

    def _forget_edits(self):
        if messagebox.askyesno(APP_NAME, "Forget everything Aqua Lite learned from your edits?", parent=self.win):
            history.clear_corrections()
            self._count_edits()

    def _music(self, f):
        s = self._s
        card = self._card(f, "Music while you talk", sub=(
            "While you dictate, Aqua Lite softly plays a random part of a song from your music folder, then fades it "
            "out when you stop. Add any songs you own: mp3, m4a, flac, ogg or wav."))
        ttk.Checkbutton(card, text="Play music while I talk", variable=self._var("music_enabled", tk.BooleanVar)).pack(
            anchor="w")
        row = ttk.Frame(card)
        row.pack(fill="x", pady=(s(10), 0))
        ttk.Label(row, text="Volume").pack(side="left")
        vol = self._var("music_volume", tk.IntVar)
        lab = ttk.Label(row, text=f"{vol.get()}%", width=5)
        ttk.Scale(row, from_=5, to=100, orient="horizontal", length=s(300),
                  command=lambda v: (vol.set(int(float(v))), lab.configure(text=f"{int(float(v))}%")),
                  value=vol.get()).pack(side="left", padx=s(10))
        lab.pack(side="left")
        ttk.Label(card, text="30% lets you hear yourself and keeps the mic clear", style="Muted.TLabel").pack(
            anchor="w", pady=(s(4), 0))
        box = self._card(f, "Music folder")
        folder = self._var("music_folder")
        if not folder.get():
            folder.set(music.default_folder())
        ttk.Entry(box, textvariable=folder, width=70).grid(row=0, column=0, columnspan=3, sticky="w")
        btns = ttk.Frame(box)
        btns.grid(row=1, column=0, columnspan=3, sticky="w", pady=s(10))
        ttk.Button(btns, text="Open folder", command=lambda: _open_folder(folder.get())).pack(side="left")
        ttk.Button(btns, text="Choose...", command=lambda: self._choose_folder(folder)).pack(side="left", padx=s(8))
        ttk.Button(btns, text="Preview", command=self._preview_music).pack(side="left")
        self.music_count = ttk.Label(box, text="", style="Muted.TLabel")
        self.music_count.grid(row=2, column=0, columnspan=3, sticky="w")
        self._count_songs(folder.get())
        ttk.Label(f, wraplength=self.wrap, style="Muted.TLabel", text=(
            "Tip: with speakers, your mic hears a little of the music. At 30% that's usually fine. "
            "Headphones keep transcripts cleanest.")).pack(anchor="w", pady=(0, s(4)))

    def _count_songs(self, folder):
        n = len(music.list_songs(folder))
        self.music_count.configure(text=f"{n} song{'s' if n != 1 else ''} found" if n else
                                   "No songs yet - click Open folder and drop some in.")

    def _choose_folder(self, var):
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=self.win, initialdir=var.get() or music.default_folder())
        if d:
            var.set(os.path.normpath(d))
            self._count_songs(var.get())

    def _preview_music(self):
        cfg = self._collect()
        self.app.music.cfg.update({k: cfg[k] for k in ("music_volume", "music_folder")})
        self.app.music.cfg["music_enabled"] = True
        ok = self.app.music.preview()
        self.app.music.cfg["music_enabled"] = self.cfg.get("music_enabled", True)
        self._count_songs(cfg["music_folder"])
        self.status.configure(text=f"Playing: {self.app.music.now_playing}" if ok else
                              "Loading songs... click Preview again in a moment (or add songs to the folder).")

    def _dictionary(self, f):
        s = self._s
        card = self._card(f, "Dictionary", sub="Words, names and jargon Aqua Lite should always spell your way "
                                               "(sent to the recognizer and the formatter).")
        row = ttk.Frame(card)
        row.pack(fill="x", pady=(0, s(8)))
        self.dict_entry = ttk.Entry(row, width=40)
        self.dict_entry.pack(side="left")
        self.dict_entry.bind("<Return>", lambda _e: self._dict_add())
        ttk.Button(row, text="Add word", command=self._dict_add).pack(side="left", padx=s(8))
        ttk.Button(row, text="Remove selected", command=self._dict_remove).pack(side="left")
        self.dict_list = self._boxed(tk.Listbox(card, height=7))
        self.dict_list.pack(fill="x")
        for w in self.cfg.get("dictionary", []):
            self.dict_list.insert("end", w)

        rep = self._card(f, "Replacements", sub="Whenever you say the left side, Aqua Lite types the right side.")
        row2 = ttk.Frame(rep)
        row2.pack(fill="x", pady=(0, s(8)))
        self.rep_from, self.rep_to = ttk.Entry(row2, width=20), ttk.Entry(row2, width=26)
        self.rep_from.pack(side="left")
        ttk.Label(row2, text="→", style="Muted.TLabel").pack(side="left", padx=s(8))
        self.rep_to.pack(side="left")
        ttk.Button(row2, text="Add", command=self._rep_add).pack(side="left", padx=s(8))
        ttk.Button(row2, text="Remove selected", command=lambda: _tree_remove(self.rep_tree)).pack(side="left")
        self.rep_tree = ttk.Treeview(rep, columns=("from", "to"), show="headings", height=5)
        self.rep_tree.heading("from", text="When I say")
        self.rep_tree.heading("to", text="Type")
        self.rep_tree.pack(fill="x")
        for r in self.cfg.get("replacements", []):
            self.rep_tree.insert("", "end", values=(r["from"], r["to"]))

    def _snippets(self, f):
        s = self._s
        card = self._card(f, "Snippets", sub="Say a trigger phrase and Aqua Lite types the full text - emails, links, "
                                             "addresses, standard replies.")
        form = ttk.Frame(card)
        form.pack(fill="x", pady=(0, s(8)))
        ttk.Label(form, text="Trigger phrase").grid(row=0, column=0, sticky="w")
        self.snip_trigger = ttk.Entry(form, width=30)
        self.snip_trigger.grid(row=0, column=1, sticky="w", padx=s(8))
        ttk.Label(form, text="Expands to").grid(row=1, column=0, sticky="nw", pady=s(6))
        self.snip_text = self._boxed(tk.Text(form, width=60, height=4, wrap="word"))
        self.snip_text.grid(row=1, column=1, sticky="w", padx=s(8), pady=s(6))
        btns = ttk.Frame(form)
        btns.grid(row=2, column=1, sticky="w", padx=s(8))
        ttk.Button(btns, text="Add / update", command=self._snip_add).pack(side="left")
        ttk.Button(btns, text="Remove selected", command=lambda: _tree_remove(self.snip_tree)).pack(side="left",
                                                                                                  padx=s(8))
        self.snip_tree = ttk.Treeview(card, columns=("trigger", "text"), show="headings", height=7)
        self.snip_tree.heading("trigger", text="Say")
        self.snip_tree.heading("text", text="Types")
        self.snip_tree.column("trigger", width=s(170))
        self.snip_tree.column("text", width=s(460))
        self.snip_tree.pack(fill="x")
        self.snip_tree.bind("<<TreeviewSelect>>", self._snip_load)
        self.snip_full = {}
        for sn in self.cfg.get("snippets", []):
            self._snip_insert(sn["trigger"], sn["text"])

    def _history(self, f):
        s = self._s
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left", padx=(0, s(8)))
        self.hq = ttk.Entry(top, width=36)
        self.hq.pack(side="left")
        self.hq.bind("<KeyRelease>", lambda _e: self._hist_load())
        ttk.Button(top, text="Copy", command=self._hist_copy).pack(side="left", padx=s(8))
        ttk.Button(top, text="Delete", command=self._hist_delete).pack(side="left")
        ttk.Button(top, text="Clear all", command=self._hist_clear).pack(side="right")
        cols = ("when", "app", "text")
        self.ht = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in zip(cols, (120, 110, 480)):
            self.ht.heading(c, text=c.title())
            self.ht.column(c, width=s(w), stretch=(c == "text"))
        self.ht.pack(fill="both", expand=True, pady=s(10))
        self.ht.bind("<Double-1>", lambda _e: self._hist_copy())
        self.hdetail = self._boxed(tk.Text(f, height=6, wrap="word"))
        self.hdetail.pack(fill="x")
        self.ht.bind("<<TreeviewSelect>>", self._hist_show)
        self._hist_rows = {}
        self._hist_load()

    # ------------------------------------------------------------------ actions
    def _dict_add(self):
        w = self.dict_entry.get().strip()
        if w and w not in self.dict_list.get(0, "end"):
            self.dict_list.insert("end", w)
        self.dict_entry.delete(0, "end")

    def _dict_remove(self):
        for i in reversed(self.dict_list.curselection()):
            self.dict_list.delete(i)

    def _rep_add(self):
        a, b = self.rep_from.get().strip(), self.rep_to.get().strip()
        if a:
            self.rep_tree.insert("", "end", values=(a, b))
            self.rep_from.delete(0, "end")
            self.rep_to.delete(0, "end")

    def _snip_insert(self, trig, text):
        iid = self.snip_tree.insert("", "end", values=(trig, text.replace("\n", " / ")[:120]))
        self.snip_full[iid] = (trig, text)

    def _snip_add(self):
        trig, text = self.snip_trigger.get().strip(), self.snip_text.get("1.0", "end").rstrip("\n")
        if not trig or not text:
            return
        for iid, (t, _x) in list(self.snip_full.items()):
            if t.lower() == trig.lower():
                self.snip_tree.delete(iid)
                del self.snip_full[iid]
        self._snip_insert(trig, text)
        self.snip_trigger.delete(0, "end")
        self.snip_text.delete("1.0", "end")

    def _snip_load(self, _e=None):
        sel = self.snip_tree.selection()
        if sel and sel[0] in self.snip_full:
            t, x = self.snip_full[sel[0]]
            self.snip_trigger.delete(0, "end")
            self.snip_trigger.insert(0, t)
            self.snip_text.delete("1.0", "end")
            self.snip_text.insert("1.0", x)

    def _hist_load(self):
        self.ht.delete(*self.ht.get_children())
        self._hist_rows = {}
        for row in history.recent(400, self.hq.get().strip()):
            rid, ts, app, mode, final, raw = row[:6]
            when = datetime.datetime.fromtimestamp(ts).strftime("%b %d  %H:%M")
            label = (("[cmd] " if mode == "command" else "") + (final or "(no speech)")).replace("\n", " ")
            iid = self.ht.insert("", "end", values=(when, app, label[:200]))
            self._hist_rows[iid] = row

    def _hist_show(self, _e=None):
        sel = self.ht.selection()
        if not sel:
            return
        rid, ts, app, mode, final, raw, secs, words, engine, lat, status = self._hist_rows[sel[0]]
        self.hdetail.delete("1.0", "end")
        self.hdetail.insert("1.0", f"{final}\n\n--- raw ({engine}, {secs:.1f}s audio, {lat:.2f}s processing, {status}) ---\n{raw}")

    def _hist_copy(self):
        sel = self.ht.selection()
        if sel:
            self.win.clipboard_clear()
            self.win.clipboard_append(self._hist_rows[sel[0]][4])
            self.status.configure(text="Copied to clipboard")

    def _hist_delete(self):
        for iid in self.ht.selection():
            history.delete(self._hist_rows[iid][0])
        self._hist_load()

    def _hist_clear(self):
        if messagebox.askyesno(APP_NAME, "Delete your whole dictation history?", parent=self.win):
            history.clear()
            self._hist_load()

    def _test_ai(self):
        cfg = self._collect()
        self.status.configure(text="Testing...")

        def run():
            try:
                out = llm.format_text(cfg, "um so I think we should uh meet at 5 no wait 6 pm tomorrow",
                                      {"app": "Slack", "title": "", "category": "work"})
                msg = f"AI OK ({llm.resolve_provider(cfg)}): {out}"
            except Exception as e:
                msg = f"AI test failed: {e}"
            self.win.after(0, lambda: self.status.configure(text=msg[:140]))
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------ save
    def _collect(self):
        cfg = dict(self.cfg)
        for k, var in self.v.items():
            cfg[k] = var.get().strip() if isinstance(var.get(), str) else var.get()
        if cfg.get("mic_device") == "(Windows default)":
            cfg["mic_device"] = ""
        cfg["language"] = self.lang.get_key()
        cfg["look"] = self.look_box.get_key()
        cfg["look_mode"] = self.look_mode_box.get_key()
        cfg["editing_strength"] = self.strength.get_key()
        cfg["styles"] = {k: cb.get_key() for k, cb in self.style_boxes.items()}
        cfg["dictionary"] = list(self.dict_list.get(0, "end"))
        cfg["local_ai_model"] = self._ai_key()
        cfg["gpu_model"] = self._gpu_selected()
        cfg["gpu_idle_minutes"] = int(round(float(cfg.get("gpu_idle_minutes", 5) or 0)))
        cfg["private_idle_minutes"] = int(round(float(cfg.get("private_idle_minutes", 10) or 0)))
        try:
            self._mem_save_typed()
        except (tk.TclError, AttributeError, OSError):
            pass
        cfg["context_blocked_apps"] = [a.strip().lower().removesuffix(".exe") for a in self.blocked.get().split(",")
                                       if a.strip()]
        cfg["replacements"] = [{"from": str(self.rep_tree.item(i)["values"][0]), "to": str(self.rep_tree.item(i)["values"][1])}
                               for i in self.rep_tree.get_children()]
        cfg["snippets"] = [{"trigger": t, "text": x} for t, x in
                           (self.snip_full[i] for i in self.snip_tree.get_children() if i in self.snip_full)]
        return cfg

    def save(self):
        cfg = self._collect()
        try:
            for k in ("hotkey_ptt", "hotkey_handsfree_key", "hotkey_command_key", "hotkey_paste_last", "hotkey_cancel",
                      "hotkey_undo_last"):
                hotkeys.parse(cfg[k])
            float(cfg.get("handsfree_silence_secs") or 0)
            if cfg.get("private_mode") and not localai.ready(cfg.get("local_ai_model", localai.DEFAULT_MODEL)):
                raise ValueError("private mode needs the selected AI model downloaded first (Private tab)")
            if cfg.get("instant_text_engine") == "gpu" and not gpu.libraries_installed():
                raise ValueError("set up the graphics card first (Instant text tab), or pick another option")
            if cfg.get("instant_text_engine") == "deepgram" and not cfg.get("deepgram_api_key", "").strip():
                raise ValueError("instant text with Deepgram needs a Deepgram API key (Instant text tab)")
        except ValueError as e:
            messagebox.showerror(APP_NAME, f"Setting problem: {e}", parent=self.win)
            return
        self.app.apply_settings(cfg)
        self.status.configure(text="Saved")
        if look_key(cfg) != self.look:   # new theme: this window is drawn again in it
            self._rebuild("Saved")


def _open_folder(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def _tree_remove(tree):
    for iid in tree.selection():
        tree.delete(iid)


def _safe_devices():
    try:
        from .audio import list_input_devices
        return list_input_devices()
    except Exception:
        return []
