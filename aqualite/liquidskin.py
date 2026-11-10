"""Liquid Glass pieces for the Settings window, in light and dark: glass buttons, switches, fields, sliders, cards,
and a sidebar that is one quiet sheet of glass on the page colour.

The counterpart of skin.py (Frutiger Aero), which stays as it is. Skin(mode) has the same names as the skin module
(PAGE, CARD, INK, button(), toggle(), card(), sidebar()...), so ui.py can take either. Everything is drawn once with
Pillow, oversampled, at the screen's scale, and laid on a solid surface (see ui._flat for why).
"""
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .skin import K, _canvas, _fill, _lerp, _mask, _shrink, _vgrad, hexrgb
from .skin import icon as _icon

PALETTES = {   # graphite neutrals; colour lives in the Flow bar preview, the accent and the green listening dot
    "light": dict(
        PAGE=(242, 242, 244), CARD=(255, 255, 255), CARD_LINE=(228, 228, 232),
        INK=(23, 23, 25), MUTED=(100, 100, 106), ACCENT=(0, 122, 255), ACCENT_TEXT=(0, 102, 204),
        FIELD=(245, 245, 247), FIELD_LINE=(216, 216, 222), FIELD_OFF=(238, 238, 241),
        GREEN=(52, 199, 89), TRACK=(226, 226, 230), KNOB_RIM=(0, 0, 0, 22),
        BUTTON=((255, 255, 255), (247, 247, 249)), RIM=(0, 0, 0, 24), SHINE=(255, 255, 255, 230), SHADOW=30,
        THUMB=((198, 198, 204), (170, 170, 177), (140, 140, 148)),
        SHEET=(249, 249, 250), SHEET_LINE=(0, 0, 0, 16), SHEET_RIM=255,
        NAV_ON=(255, 255, 255, 255), NAV_LINE=(0, 0, 0, 18), NAV_HOT=(0, 0, 0, 10), NAV_RIM=(255, 255, 255, 255),
        SKY=((205, 220, 238), (236, 241, 247)),   # the little desktop behind the Flow bar preview
        KEY=((252, 252, 253), (239, 239, 242), (202, 202, 209)),
        PILLS={"blue": ((150, 150, 158), (60, 60, 66)), "green": ((52, 199, 89), (60, 60, 66)),
               "violet": ((150, 150, 158), (60, 60, 66)), "amber": ((230, 150, 30), (60, 60, 66))},
        ui=dict(eyebrow=(100, 100, 106), warn=(160, 82, 0), line=(228, 228, 232), disabled_fg=(162, 162, 168),
                select=(210, 228, 255), btn_ink=(23, 23, 25), primary_ink=(255, 255, 255),
                primary_dis=(232, 238, 248), list_bg=(255, 255, 255), head_bg=(247, 247, 249),
                head_hot=(238, 238, 241), nav_group=(110, 110, 116), nav_on_ink=(23, 23, 25),
                nav_on_icon=(0, 122, 255), title=((242, 242, 244), (23, 23, 25), (224, 224, 228)), dark_title=False),
    ),
    "dark": dict(
        PAGE=(20, 20, 21), CARD=(29, 29, 31), CARD_LINE=(44, 44, 47),
        INK=(237, 237, 237), MUTED=(161, 161, 166), ACCENT=(10, 132, 255), ACCENT_TEXT=(100, 175, 255),
        FIELD=(38, 38, 41), FIELD_LINE=(60, 60, 64), FIELD_OFF=(33, 33, 35),
        GREEN=(48, 209, 88), TRACK=(58, 58, 62), KNOB_RIM=(0, 0, 0, 60),
        BUTTON=((56, 56, 60), (46, 46, 50)), RIM=(255, 255, 255, 26), SHINE=(255, 255, 255, 60), SHADOW=80,
        THUMB=((70, 70, 75), (95, 95, 101), (122, 122, 129)),
        SHEET=(27, 27, 29), SHEET_LINE=(255, 255, 255, 20), SHEET_RIM=60,
        NAV_ON=(255, 255, 255, 26), NAV_LINE=(255, 255, 255, 0), NAV_HOT=(255, 255, 255, 12),
        NAV_RIM=(255, 255, 255, 46),
        SKY=((28, 34, 46), (16, 18, 24)),
        KEY=((58, 58, 62), (48, 48, 52), (16, 16, 18)),
        PILLS={"blue": ((110, 110, 118), (200, 200, 205)), "green": ((48, 209, 88), (200, 200, 205)),
               "violet": ((110, 110, 118), (200, 200, 205)), "amber": ((240, 165, 50), (200, 200, 205))},
        ui=dict(eyebrow=(161, 161, 166), warn=(240, 165, 72), line=(44, 44, 47), disabled_fg=(100, 100, 106),
                select=(24, 62, 120), btn_ink=(237, 237, 237), primary_ink=(255, 255, 255),
                primary_dis=(110, 130, 160), list_bg=(24, 24, 26), head_bg=(33, 33, 35), head_hot=(42, 42, 45),
                nav_group=(140, 140, 146), nav_on_ink=(255, 255, 255), nav_on_icon=(100, 175, 255),
                title=((20, 20, 21), (237, 237, 237), (44, 44, 47)), dark_title=True),
    ),
}


def _shadow(img, box, r, blur, alpha, dy=0):
    """Neutral, soft shadow (Aero's is navy)."""
    m = _mask(img.size, (box[0], box[1] + dy, box[2], box[3] + dy), r).filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.putalpha(m.point(lambda v: v * alpha // 255))
    img.alpha_composite(layer)


def _rim(img, box, r, top, bottom=None, width=K):
    """A thin edge, brighter at the top than the bottom: light falling on glass from above."""
    w, h = img.size
    ring = ImageChops.subtract(_mask((w, h), box, r), _mask((w, h), (box[0] + width, box[1] + width,
                                                                     box[2] - width, box[3] - width),
                                                              max(1, r - width)))
    bottom = top if bottom is None else bottom
    col = _vgrad(w, h, [(0, top), (1, bottom)])
    col.putalpha(ImageChops.multiply(col.getchannel("A"), ring))
    img.alpha_composite(col)


def _fade(img, keep):
    img.putalpha(img.getchannel("A").point(lambda v: v * keep // 100))
    return img


def _ball(img, cx, cy, r, rim, shadow=60):
    """The white bead of a switch or slider, with a soft shadow below it."""
    _shadow(img, (cx - r, cy - r, cx + r, cy + r), r, r * 0.22, shadow, dy=r * 0.12)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255), outline=rim, width=max(1, K // 2))


class Skin:
    """The Liquid Glass drawings for one mode ('light' or 'dark'), with skin.py's names."""

    def __init__(self, mode="light"):
        self.mode = mode if mode in PALETTES else "light"
        for k, v in PALETTES[self.mode].items():
            setattr(self, k, v)
        self.SIDEBAR = (self.PAGE, self.PAGE)
        self.hexrgb = hexrgb

    # ------------------------------------------------------------ buttons
    def button(self, w, h, state="normal", primary=False):
        """A glass capsule; the main button is filled with the accent colour."""
        img = _canvas(w, h)
        box = (K, K, w * K - K, h * K - 2 * K)
        r = (box[3] - box[1]) // 2
        _shadow(img, box, r, K * 1.4, self.SHADOW if state != "disabled" else self.SHADOW // 3, dy=K)
        if primary:
            base = self.ACCENT
            top, bottom = _lerp(base, (255, 255, 255), 0.14), base
            rim_top, rim_bottom = (255, 255, 255, 150), _lerp(base, (0, 0, 0), 0.25) + (120,)
        else:
            top, bottom = self.BUTTON
            rim_top, rim_bottom = self.SHINE, self.RIM
        shift = {"active": (255, 255, 255, 0.10), "pressed": (0, 0, 0, 0.10)}.get(state)
        if shift:
            top, bottom = (_lerp(c, shift[:3], shift[3]) for c in (top, bottom))
        _fill(img, box, r, _vgrad(box[2] - box[0], box[3] - box[1], [(0, top), (1, bottom)]))
        ImageDraw.Draw(img).rounded_rectangle(box, radius=r, outline=self.RIM if not primary else rim_bottom,
                                              width=max(1, K // 2))
        _rim(img, (box[0] + K // 2, box[1] + K // 2, box[2] - K // 2, box[3] - K // 2), r - K // 2,
             rim_top, tuple(rim_top[:3]) + (0,), width=max(1, K // 2))
        out = _shrink(img, w, h)
        return _fade(out, 45) if state == "disabled" else out

    # ------------------------------------------------------------ switches and radios
    def toggle(self, h, on, state="normal", gap=8):
        """An iOS-style switch: green track when on, a white bead that sits at the end."""
        tw = int(h * 1.8)
        img = _canvas(tw + gap, h)
        box = (K // 2, K // 2, tw * K - K // 2, h * K - K // 2)
        r = (box[3] - box[1]) // 2
        track = self.GREEN if on else (_lerp(self.TRACK, (0, 0, 0) if self.mode == "light" else (255, 255, 255),
                                              0.07) if state == "active" else self.TRACK)
        ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=track + (255,))
        kr = r - 2 * K
        cx = box[2] - 2 * K - kr if on else box[0] + 2 * K + kr
        _ball(img, cx, (box[1] + box[3]) // 2, kr, self.KNOB_RIM)
        out = _shrink(img, tw + gap, h)
        return _fade(out, 45) if state == "disabled" else out

    def toggle_between(self, h, x, gap=8):
        """A switch part of the way from off (0) to on (1), for the slide when it's clicked."""
        tw = int(h * 1.8)
        img = _canvas(tw + gap, h)
        box = (K // 2, K // 2, tw * K - K // 2, h * K - K // 2)
        r = (box[3] - box[1]) // 2
        ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=_lerp(self.TRACK, self.GREEN, x) + (255,))
        kr = r - 2 * K
        x0, x1 = box[0] + 2 * K + kr, box[2] - 2 * K - kr
        stretch = int(kr * 0.35 * (1 - abs(2 * x - 1)))   # the bead stretches a little mid-slide, like liquid
        cx, cy = int(x0 + (x1 - x0) * x), (box[1] + box[3]) // 2
        _shadow(img, (cx - kr - stretch, cy - kr, cx + kr + stretch, cy + kr), kr, kr * 0.22, 60, dy=kr * 0.12)
        ImageDraw.Draw(img).rounded_rectangle((cx - kr - stretch, cy - kr, cx + kr + stretch, cy + kr), radius=kr,
                                              fill=(255, 255, 255, 255), outline=self.KNOB_RIM, width=max(1, K // 2))
        return _shrink(img, tw + gap, h)

    def radio(self, h, on, state="normal", gap=8):
        img = _canvas(h + gap, h)
        s = h * K
        box = (K, K, s - K, s - K)
        d = ImageDraw.Draw(img)
        if on:
            d.ellipse(box, fill=self.ACCENT + (255,))
            r = int(s * 0.17)
            c = s // 2
            d.ellipse((c - r, c - r, c + r, c + r), fill=(255, 255, 255, 255))
        else:
            line = self.ACCENT if state == "active" else self.FIELD_LINE
            d.ellipse(box, fill=self.FIELD + (255,), outline=line + (255,), width=int(K * 1.4))
        out = _shrink(img, h + gap, h)
        return _fade(out, 45) if state == "disabled" else out

    # ------------------------------------------------------------ fields
    def field(self, w, h, state="normal", radius=8):
        """A soft filled field with a hairline; focus adds an accent ring."""
        img = _canvas(w, h)
        box = (K, K, w * K - K, h * K - K)
        r = radius * K
        if state == "focus":
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=r + K,
                                                   fill=self.ACCENT + (110,))
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(K * 0.5)))
        fill = self.FIELD_OFF if state == "disabled" else self.FIELD
        line = {"focus": self.ACCENT, "active": _lerp(self.FIELD_LINE, self.ACCENT, 0.35)}.get(state, self.FIELD_LINE)
        ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=fill + (255,), outline=line + (255,),
                                              width=K if state == "focus" else max(1, K // 2 + 1))
        return _shrink(img, w, h)

    def arrow(self, w, h, state="normal"):
        img = _canvas(w, h)
        col = self.ui["disabled_fg"] if state == "disabled" else (self.ACCENT if state == "active" else self.MUTED)
        cx, cy, s = w * K / 2 - K, h * K / 2, h * K * 0.14
        ImageDraw.Draw(img).line((cx - s * 1.6, cy - s * 0.7, cx, cy + s * 0.8, cx + s * 1.6, cy - s * 0.7),
                                 fill=col + (255,), width=int(K * 1.7), joint="curve")
        return _shrink(img, w, h)

    # ------------------------------------------------------------ progress, slider, scrollbar
    def progress_trough(self, w, h):
        img = _canvas(w, h)
        g = max(2 * K, int(h * K * 0.42))
        y0 = (h * K - g) // 2
        ImageDraw.Draw(img).rounded_rectangle((0, y0, w * K - 1, y0 + g), radius=g // 2, fill=self.TRACK + (255,))
        return _shrink(img, w, h)

    def progress_bar(self, w, h):
        img = _canvas(w, h)
        g = max(2 * K, int((h + 4) * K * 0.42))
        y0 = (h * K - g) // 2
        box = (0, y0, w * K - 1, y0 + g)
        _fill(img, box, g // 2, _vgrad(w * K, g, [(0, _lerp(self.ACCENT, (255, 255, 255), 0.18)),
                                                   (1, self.ACCENT)]))
        return _shrink(img, w, h)

    def scale_trough(self, w, h, groove=5):
        img = _canvas(w, h)
        g = groove * K
        y0 = (h * K - g) // 2
        ImageDraw.Draw(img).rounded_rectangle((K, y0, w * K - K, y0 + g), radius=g // 2, fill=self.TRACK + (255,))
        return _shrink(img, w, h)

    def slider(self, h, state="normal"):
        img = _canvas(h, h)
        s = h * K
        r = s // 2 - 3 * K + (K // 2 if state in ("active", "pressed") else 0)
        _ball(img, s // 2, s // 2, r, self.KNOB_RIM, shadow=80 if state == "pressed" else 60)
        if state == "pressed":
            d = ImageDraw.Draw(img)
            d.ellipse((s // 2 - r * 0.3, s // 2 - r * 0.3, s // 2 + r * 0.3, s // 2 + r * 0.3),
                      fill=self.ACCENT + (200,))
        return _shrink(img, h, h)

    def thumb(self, w, h, state="normal"):
        img = _canvas(w, h)
        col = self.THUMB[{"active": 1, "pressed": 2}.get(state, 0)]
        pad = 3 * K
        ImageDraw.Draw(img).rounded_rectangle((pad, 0, w * K - pad - 1, h * K - 1), radius=(w * K - 2 * pad) // 2,
                                              fill=col + (255,))
        return _shrink(img, w, h)

    # ------------------------------------------------------------ cards
    def card(self, size, radius=14, fill=None, line=None, selected=False, behind=None):
        """A rounded card lifted off the page by a wide, faint shadow."""
        fill, line, behind = fill or self.CARD, line or self.CARD_LINE, behind or self.PAGE
        w = h = size
        img = Image.new("RGBA", (w * K, h * K), behind + (255,))
        box = (2 * K, K, w * K - 2 * K, h * K - 3 * K)
        r = radius * K
        _shadow(img, box, r, 2.4 * K, self.SHADOW // 2, dy=K)
        if selected:
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle(box, radius=r, outline=self.ACCENT + (120,), width=3 * K)
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(1.5 * K)))
        ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=fill + (255,),
                                              outline=(self.ACCENT if selected else line) + (255,),
                                              width=int(K * (1.6 if selected else 0.75)))
        return _shrink(img, w, h)

    # ------------------------------------------------------------ sidebar
    def backdrop(self, w, h):
        """The little desktop behind the Flow bar preview: plain daylight (or night) sky, one tone shift."""
        return _vgrad(w, h, [(0, self.SKY[0]), (1, self.SKY[1])]).convert("RGB")

    def sidebar(self, w, h):
        """One sheet of glass on the page colour: a quiet raised panel with a hairline, a soft top highlight and a
        soft shadow."""
        u = w / 224.0
        m = int(round(8 * u))
        box = (m, m, w - m, h - m)
        r = int(round(20 * u))
        out = Image.new("RGBA", (w, h), self.PAGE + (255,))
        _shadow(out, box, r, 6 * u, self.SHADOW // 3, dy=int(2 * u))
        ImageDraw.Draw(out).rounded_rectangle(box, radius=r, fill=self.SHEET + (255,))
        line = Image.new("RGBA", (w, h), (0, 0, 0, 0))   # the hairline is see-through: blend it, don't paint it
        ImageDraw.Draw(line).rounded_rectangle(box, radius=r, outline=self.SHEET_LINE, width=max(1, int(round(u))))
        out.alpha_composite(line)
        _rim(out, (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), r - 1, (255, 255, 255, self.SHEET_RIM),
             (255, 255, 255, 0), width=max(1, int(round(u))))
        return out.convert("RGB")

    def nav_pill(self, w, h, kind):
        """kind: 'selected' (a lighter bead of glass) or 'hover' (a faint one)."""
        img = _canvas(w, h)
        box = (K, K, w * K - K, h * K - 2 * K)
        r = 12 * K   # the sheet's 20 less the 8 between them
        if kind == "selected":
            _shadow(img, box, r, K * 1.5, self.SHADOW // 3, dy=K // 2)
            ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=self.NAV_ON, outline=self.NAV_LINE,
                                                  width=max(1, K // 2))
            _rim(img, box, r, self.NAV_RIM, tuple(self.NAV_RIM[:3]) + (0,), width=max(1, K // 2))
        else:
            ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=self.NAV_HOT)
        return _shrink(img, w, h)

    def icon(self, name, size, color=None):
        return _icon(name, size, color or self.INK)

    # ------------------------------------------------------------ tags and keys
    def pill(self, w, h, fill, behind=None):
        """A status as quiet text with a small dot in front (the dot colour says on, off or needs attention)."""
        img = Image.new("RGBA", (w * K, h * K), (behind or self.CARD) + (255,))
        r = h * K * 0.15
        cx, cy = h * K * 0.3, h * K / 2
        ImageDraw.Draw(img).ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(fill) + (255,))
        return _shrink(img, w, h)

    def keycap(self, w, h, behind=None):
        img = Image.new("RGBA", (w * K, h * K), (behind or self.CARD) + (255,))
        top, bottom, edge = self.KEY
        r = 6 * K
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=r, fill=edge + (255,))
        _fill(img, (K // 2, K // 2, w * K - K // 2, h * K - 2 * K), r - K // 2,
              _vgrad(w * K, h * K, [(0, top), (1, bottom)]))
        return _shrink(img, w, h)
