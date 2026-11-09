"""Frutiger Aero pieces for the Settings window: toggles, orbs, fields, sliders, progress bars, cards,
the sidebar and its icons. All drawn with Pillow, oversampled, at the screen's scale."""
from PIL import Image, ImageDraw, ImageFilter

K = 4  # oversampling: draw 4x, shrink with LANCZOS for clean edges

INK = (11, 61, 99)
MUTED = (63, 105, 135)
PAGE = (238, 247, 253)        # content area behind the cards
CARD = (255, 255, 255)        # card surface
CARD_LINE = (191, 224, 245)
FIELD_LINE = (156, 198, 228)
FOCUS = (47, 163, 230)
LIME = ((189, 245, 138), (98, 201, 58), (58, 166, 31), (121, 217, 79))
AQUA = ((143, 220, 255), (63, 176, 238), (22, 144, 216), (70, 178, 238))
PRIMARY = ((127, 210, 255), (47, 163, 230), (15, 127, 201), (42, 155, 224))
BUTTON = ((244, 252, 255), (205, 238, 255), (143, 211, 247), (184, 230, 251))
BUTTON_HOT = ((255, 255, 255), (219, 244, 255), (158, 220, 250), (201, 238, 253))
BUTTON_DOWN = ((178, 222, 247), (140, 205, 240), (98, 180, 232), (130, 200, 240))


def hexrgb(c):
    return "#%02x%02x%02x" % tuple(c[:3])


def _canvas(w, h):
    return Image.new("RGBA", (w * K, h * K), (0, 0, 0, 0))


def _shrink(img, w, h):
    return img.resize((w, h), Image.LANCZOS)


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def _vgrad(w, h, stops):
    """Vertical gradient through (position 0..1, colour) stops."""
    col = Image.new("RGBA", (1, max(h, 1)))
    px = col.load()
    stops = [(p, tuple(c) + (255,) * (4 - len(c))) for p, c in stops]
    for y in range(max(h, 1)):
        t = y / max(h - 1, 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1 or (p1 == stops[-1][0]):
                px[0, y] = _lerp(c0, c1, 0 if p1 == p0 else min(1, max(0, (t - p0) / (p1 - p0))))
                break
    return col.resize((max(w, 1), max(h, 1)))


def gloss4(w, h, c):
    """The classic Aero glass gradient: light top half, a hard line at the middle, deeper bottom half."""
    return _vgrad(w, h, [(0, c[0]), (0.48, c[1]), (0.52, c[2]), (1, c[3])])


def _mask(size, box, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=r, fill=255)
    return m


def _fill(img, box, r, src):
    """Paint src (an image the size of box) into a rounded box."""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    if src.size != (w, h):
        src = src.resize((w, h))
    img.alpha_composite(Image.composite(src, Image.new("RGBA", src.size, (0, 0, 0, 0)),
                                        _mask((w, h), (0, 0, w - 1, h - 1), r)), (x0, y0))


def _inner_shadow(img, box, r, alpha=60, frac=0.33):
    """Darkening along the top inside edge of a rounded box: makes a track or field look pressed in."""
    w, h = int(box[2]) - int(box[0]), int(box[3]) - int(box[1])
    _fill(img, box, r, _vgrad(w, h, [(0, (0, 40, 80, alpha)), (frac, (0, 40, 80, 0)), (1, (0, 40, 80, 0))]))


def _shadow(img, box, r, blur, alpha, dy=0):
    m = _mask(img.size, (box[0], box[1] + dy, box[2], box[3] + dy), r).filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", img.size, (0, 40, 80, 0))
    layer.putalpha(m.point(lambda v: v * alpha // 255))
    img.alpha_composite(layer)


def _knob(img, cx, cy, r, rim=(120, 160, 190)):
    """Glossy white ball with a soft shadow."""
    _shadow(img, (cx - r, cy - r, cx + r, cy + r), r, r * 0.14, 100, dy=r * 0.08)
    ball = _vgrad(2 * r, 2 * r, [(0, (255, 255, 255)), (0.6, (227, 238, 246)), (1, (185, 207, 223))])
    m = Image.new("L", (2 * r, 2 * r), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
    img.paste(ball, (cx - r, cy - r), m)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=rim + (200,), width=max(1, K // 2))
    d.ellipse((cx - r * 0.55, cy - r * 0.8, cx + r * 0.25, cy - r * 0.15), fill=(255, 255, 255, 170))


# ----------------------------------------------------------------- buttons
def button(w, h, state="normal", primary=False):
    """Glossy pill button. Stretched by ttk using its rounded ends as the border."""
    if primary:
        c = {"normal": PRIMARY, "active": tuple(_lerp(x, (255, 255, 255), 0.18) for x in PRIMARY),
             "pressed": tuple(_lerp(x, (0, 60, 120), 0.18) for x in PRIMARY),
             "disabled": tuple(_lerp(x, (220, 230, 238), 0.6) for x in PRIMARY)}[state]
        line = (11, 95, 153)
    else:
        c = {"normal": BUTTON, "active": BUTTON_HOT, "pressed": BUTTON_DOWN,
             "disabled": ((245, 248, 250), (236, 242, 246), (225, 233, 239), (232, 238, 243))}[state]
        line = (42, 134, 196) if state != "disabled" else (175, 196, 212)
    img = _canvas(w, h)
    box = (K, K, w * K - K, h * K - 2 * K)
    r = (box[3] - box[1]) // 2
    _shadow(img, box, r, K * 1.2, 70, dy=K)
    _fill(img, box, r, gloss4(box[2] - box[0], box[3] - box[1], c))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=r, outline=line + (255,), width=K)
    d.rounded_rectangle((box[0] + K, box[1] + K, box[2] - K, box[3] - K), radius=r - K,
                        outline=(255, 255, 255, 150), width=K // 2 or 1)
    return _shrink(img, w, h)


# ----------------------------------------------------------------- toggles & radios
def toggle(h, on, state="normal", gap=8):
    """Switch for a Checkbutton: a glass track and a ball. gap = transparent space before the text."""
    tw = int(h * 1.8)
    img = _canvas(tw + gap, h)
    box = (K // 2, K // 2, tw * K - K // 2, h * K - K // 2)
    r = (box[3] - box[1]) // 2
    if on:
        _fill(img, box, r, gloss4(box[2] - box[0], box[3] - box[1], LIME))
        line = (46, 138, 28)
    else:
        _fill(img, box, r, _vgrad(box[2] - box[0], box[3] - box[1], [(0, (217, 233, 243)), (1, (246, 251, 255))]))
        _inner_shadow(img, box, r)
        line = (90, 156, 196) if state != "active" else FOCUS
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=r, outline=line + (255,), width=K)
    kr = (box[3] - box[1]) // 2 - 2 * K
    cx = box[2] - 2 * K - kr if on else box[0] + 2 * K + kr
    _knob(img, cx, (box[1] + box[3]) // 2, kr)
    out = _shrink(img, tw + gap, h)
    if state == "disabled":
        out.putalpha(out.getchannel("A").point(lambda v: v * 45 // 100))
    return out


def radio(h, on, state="normal", gap=8):
    """Glass orb for a Radiobutton."""
    img = _canvas(h + gap, h)
    s = h * K
    box = (K, K, s - K, s - K)
    d = ImageDraw.Draw(img)
    d.ellipse(box, fill=(255, 255, 255, 255))
    _inner_shadow(img, box, (box[2] - box[0]) // 2, alpha=55)
    line = (15, 127, 201) if on else (FOCUS if state == "active" else (127, 182, 218))
    d.ellipse(box, outline=line + (255,), width=int(K * 1.6))
    if on:
        r = int(s * 0.25)
        c = s // 2
        dot = gloss4(2 * r, 2 * r, AQUA)
        dm = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(dm).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
        img.paste(dot, (c - r, c - r), dm)
        d.ellipse((c - r, c - r, c + r, c + r), outline=(11, 95, 153, 255), width=K // 2)
        d.ellipse((c - r * 0.6, c - r * 0.85, c + r * 0.3, c - r * 0.2), fill=(255, 255, 255, 190))
    out = _shrink(img, h + gap, h)
    if state == "disabled":
        out.putalpha(out.getchannel("A").point(lambda v: v * 45 // 100))
    return out


# ----------------------------------------------------------------- fields
def field(w, h, state="normal", radius=6):
    """Rounded white text field (Entry, Combobox, Spinbox)."""
    img = _canvas(w, h)
    box = (K, K, w * K - K, h * K - K)
    r = radius * K
    d = ImageDraw.Draw(img)
    if state == "focus":
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=r + K, fill=FOCUS + (90,))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(K * 0.6)))
    fill = (240, 245, 249) if state == "disabled" else (255, 255, 255)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=r, fill=fill + (255,))
    _inner_shadow(img, box, r, alpha=34, frac=3.0 * K / (box[3] - box[1]))
    line = {"focus": FOCUS, "active": (110, 175, 222), "disabled": (196, 214, 226)}.get(state, FIELD_LINE)
    d.rounded_rectangle(box, radius=r, outline=line + (255,), width=K)
    return _shrink(img, w, h)


def arrow(w, h, state="normal"):
    """Down chevron for the Combobox button area."""
    img = _canvas(w, h)
    d = ImageDraw.Draw(img)
    col = (150, 175, 195) if state == "disabled" else (FOCUS if state == "active" else INK)
    cx, cy, s = w * K / 2 - K, h * K / 2, h * K * 0.16
    d.line((cx - s * 1.6, cy - s * 0.7, cx, cy + s * 0.8, cx + s * 1.6, cy - s * 0.7), fill=col + (255,),
           width=int(K * 1.8), joint="curve")
    return _shrink(img, w, h)


# ----------------------------------------------------------------- progress, slider, scrollbar
def progress_trough(w, h):
    img = _canvas(w, h)
    box = (0, 0, w * K - 1, h * K - 1)
    r = (h * K) // 2
    _fill(img, box, r, _vgrad(w * K, h * K, [(0, (222, 236, 246)), (1, (255, 255, 255))]))
    _inner_shadow(img, box, r)
    ImageDraw.Draw(img).rounded_rectangle(box, radius=r, outline=(90, 156, 196, 255), width=K)
    return _shrink(img, w, h)


def progress_bar(w, h):
    img = _canvas(w, h)
    box = (0, 0, w * K - 1, h * K - 1)
    r = (h * K) // 2
    _fill(img, box, r, gloss4(w * K, h * K, LIME))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=r, outline=(46, 138, 28, 230), width=K // 2)
    return _shrink(img, w, h)


def scale_trough(w, h, groove=6):
    """Slim recessed groove, centred vertically in h (h leaves room for the slider ball)."""
    img = _canvas(w, h)
    g = groove * K
    y0 = (h * K - g) // 2
    box = (K, y0, w * K - K, y0 + g)
    _fill(img, box, g // 2, _vgrad(box[2] - box[0], g, [(0, (190, 214, 232)), (1, (238, 246, 252))]))
    ImageDraw.Draw(img).rounded_rectangle(box, radius=g // 2, outline=(90, 156, 196, 255), width=K // 2 + 1)
    return _shrink(img, w, h)


def slider(h, state="normal"):
    img = _canvas(h, h)
    s = h * K
    r = s // 2 - 3 * K
    rim = {"active": FOCUS, "pressed": (15, 127, 201)}.get(state, (70, 140, 190))
    _knob(img, s // 2, s // 2, r, rim=rim)
    if state in ("active", "pressed"):
        d = ImageDraw.Draw(img)
        d.ellipse((s // 2 - r * 0.32, s // 2 - r * 0.32, s // 2 + r * 0.32, s // 2 + r * 0.32),
                  fill=(47, 163, 230, 200 if state == "pressed" else 140))
    return _shrink(img, h, h)


def thumb(w, h, state="normal"):
    """Slim rounded scrollbar thumb (vertical)."""
    img = _canvas(w, h)
    col = {"active": (111, 178, 223), "pressed": (60, 145, 205)}.get(state, (160, 203, 232))
    pad = 2 * K
    ImageDraw.Draw(img).rounded_rectangle((pad, 0, w * K - pad - 1, h * K - 1), radius=(w * K - 2 * pad) // 2,
                                          fill=col + (255,))
    return _shrink(img, w, h)


# ----------------------------------------------------------------- cards
def card(size, radius=12, fill=CARD, line=CARD_LINE, selected=False, behind=PAGE):
    """Rounded card with a soft shadow, drawn on the page colour (ttk can't see through to the page)."""
    w = h = size
    img = Image.new("RGBA", (w * K, h * K), behind + (255,))
    box = (2 * K, K, w * K - 2 * K, h * K - 3 * K)
    r = radius * K
    _shadow(img, box, r, 2.2 * K, 60, dy=1.2 * K)
    d = ImageDraw.Draw(img)
    if selected:
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(box, radius=r, outline=FOCUS + (150,), width=3 * K)
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(1.5 * K)))
    d.rounded_rectangle(box, radius=r, fill=fill + (255,), outline=(FOCUS if selected else line) + (255,),
                        width=int(K * (1.6 if selected else 1)))
    return _shrink(img, w, h)


# ----------------------------------------------------------------- sidebar
SIDEBAR = ((214, 239, 255), (189, 227, 250))
SIDEBAR_LINE = (182, 220, 243)


def sidebar(w, h):
    img = _vgrad(w, h, [(0, SIDEBAR[0]), (1, SIDEBAR[1])])
    # light sheen at the top, like the glass title area
    sheen = _vgrad(w, min(h, 140), [(0, (255, 255, 255, 120)), (1, (255, 255, 255, 0))])
    img.alpha_composite(sheen)
    ImageDraw.Draw(img).line((w - 1, 0, w - 1, h), fill=SIDEBAR_LINE + (255,))
    return img.convert("RGB")


def nav_pill(w, h, kind):
    """kind: 'selected' (glossy aqua) or 'hover' (soft white glass)."""
    img = _canvas(w, h)
    box = (K, K, w * K - K, h * K - 2 * K)
    r = 10 * K
    if kind == "selected":
        _shadow(img, box, r, K * 1.5, 80, dy=K)
        _fill(img, box, r, gloss4(box[2] - box[0], box[3] - box[1], AQUA))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, radius=r, outline=(11, 106, 168, 255), width=K)
        d.rounded_rectangle((box[0] + K, box[1] + K, box[2] - K, box[3] - K), radius=r - K,
                            outline=(255, 255, 255, 140), width=K // 2)
    else:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, radius=r, fill=(255, 255, 255, 140), outline=(120, 190, 235, 150), width=K)
    return _shrink(img, w, h)


# line icons on a 24-unit grid, mirroring the mockup
def _icon_shapes(d, name, u, col, wd):
    P = lambda *pts: [(x * u, y * u) for x, y in pts]  # noqa: E731
    if name == "home":
        d.line(P((3, 11), (12, 4), (21, 11)), fill=col, width=wd, joint="curve")
        d.line(P((5, 10), (5, 20), (10, 20), (10, 14), (14, 14), (14, 20), (19, 20), (19, 10)), fill=col, width=wd,
               joint="curve")
    elif name == "mic":
        d.rounded_rectangle((9 * u, 3 * u, 15 * u, 14 * u), radius=3 * u, outline=col, width=wd)
        d.arc((5 * u, 4 * u, 19 * u, 18 * u), 0, 180, fill=col, width=wd)
        d.line(P((12, 18), (12, 21)), fill=col, width=wd)
    elif name == "bolt":
        d.line(P((13, 2), (4, 14), (11, 14), (10, 22), (19, 10), (12, 10), (13, 2)), fill=col, width=wd,
               joint="curve")
    elif name == "sparkle":
        d.line(P((12, 3), (14.5, 8.5), (20, 11), (14.5, 13.5), (12, 19), (9.5, 13.5), (4, 11), (9.5, 8.5), (12, 3)),
               fill=col, width=wd, joint="curve")
    elif name == "lock":
        d.rounded_rectangle((5 * u, 11 * u, 19 * u, 21 * u), radius=2 * u, outline=col, width=wd)
        d.arc((8 * u, 4 * u, 16 * u, 12 * u), 180, 360, fill=col, width=wd)
        d.line(P((8, 8), (8, 11)), fill=col, width=wd)
        d.line(P((16, 8), (16, 11)), fill=col, width=wd)
    elif name == "brush":
        d.line(P((18, 4), (10, 12)), fill=col, width=wd)
        d.line(P((19.5, 2.5), (21, 4), (18, 7)), fill=col, width=wd, joint="curve")
        d.line(P((10, 12), (9, 16), (6, 19), (3, 20), (4, 17), (7, 14), (10, 12)), fill=col, width=wd,
               joint="curve")
    elif name == "lines":
        for y, x1 in ((5, 20), (12, 14), (19, 11)):
            d.line(P((4, y), (x1, y)), fill=col, width=wd)
    elif name == "music":
        d.line(P((9, 18), (9, 5), (20, 3), (20, 16)), fill=col, width=wd, joint="curve")
        d.ellipse((3 * u, 15 * u, 9 * u, 21 * u), outline=col, width=wd)
        d.ellipse((14 * u, 13 * u, 20 * u, 19 * u), outline=col, width=wd)
    elif name == "clock":
        d.ellipse((3 * u, 3 * u, 21 * u, 21 * u), outline=col, width=wd)
        d.line(P((12, 7), (12, 12), (15, 14)), fill=col, width=wd, joint="curve")


def icon(name, size, color=INK):
    img = _canvas(size, size)
    d = ImageDraw.Draw(img)
    u = size * K / 24.0
    wd = max(1, int(round(2 * u)))
    _icon_shapes(d, name, u, tuple(color[:3]) + (255,), wd)
    return _shrink(img, size, size)


PILLS = {  # fill, text
    "blue": ((223, 243, 255), (11, 95, 153)),
    "green": ((227, 249, 216), (44, 110, 20)),
    "violet": ((241, 232, 255), (91, 46, 166)),
    "amber": ((255, 241, 214), (122, 74, 0)),
}


def pill(w, h, fill, behind=CARD):
    """Rounded tag drawn on its background colour."""
    img = Image.new("RGBA", (w * K, h * K), behind + (255,))
    box = (0, 0, w * K - 1, h * K - 1)
    line = _lerp(fill, (90, 120, 150), 0.18)
    ImageDraw.Draw(img).rounded_rectangle(box, radius=(h * K) // 2, fill=fill + (255,), outline=line + (255,),
                                          width=K // 2)
    return _shrink(img, w, h)


def keycap(w, h, behind=CARD):
    """A keyboard key: white top, a thicker edge at the bottom."""
    img = Image.new("RGBA", (w * K, h * K), behind + (255,))
    d = ImageDraw.Draw(img)
    r = 5 * K
    d.rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=r, fill=(156, 198, 228, 255))
    _fill(img, (K, K, w * K - K, h * K - 3 * K), r - K,
          _vgrad(w * K - 2 * K, h * K - 4 * K, [(0, (255, 255, 255)), (1, (232, 244, 252))]))
    return _shrink(img, w, h)
