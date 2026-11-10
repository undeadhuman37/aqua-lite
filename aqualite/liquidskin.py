"""Liquid Glass pieces for the Settings window, in light and dark: glass buttons, switches, fields, sliders, cards,
and a sidebar that is a sheet of glass over soft colour.

The counterpart of skin.py (Frutiger Aero), which stays as it is. Skin(mode) has the same names as the skin module
(PAGE, CARD, INK, button(), toggle(), card(), sidebar()...), so ui.py can take either. Everything is drawn once with
Pillow, oversampled, at the screen's scale, and laid on a solid surface (see ui._flat for why).
"""
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .skin import K, _canvas, _fill, _lerp, _mask, _shrink, _vgrad, hexrgb
from .skin import icon as _icon

PALETTES = {
    "light": dict(
        PAGE=(242, 243, 247), CARD=(255, 255, 255), CARD_LINE=(226, 228, 234),
        INK=(29, 29, 31), MUTED=(99, 103, 112), ACCENT=(0, 122, 255), ACCENT_TEXT=(0, 102, 204),
        FIELD=(244, 245, 248), FIELD_LINE=(214, 217, 224), FIELD_OFF=(236, 237, 241),
        GREEN=(52, 199, 89), TRACK=(226, 227, 232), KNOB_RIM=(0, 0, 0, 22),
        BUTTON=((255, 255, 255), (246, 247, 250)), RIM=(0, 0, 0, 24), SHINE=(255, 255, 255, 230), SHADOW=34,
        THUMB=((196, 199, 206), (168, 172, 180), (138, 142, 151)),
        BLOBS=(((110, 175, 255), 0.85), ((200, 150, 255), 0.70), ((100, 215, 195), 0.60), ((255, 180, 140), 0.50)),
        BACK=((236, 240, 248), (242, 238, 248)), SHEET=(255, 255, 255, 140), SHEET_RIM=235,
        NAV_ON=(255, 255, 255, 225), NAV_HOT=(255, 255, 255, 105), NAV_RIM=(255, 255, 255, 255),
        KEY=((252, 252, 253), (238, 239, 243), (200, 203, 211)),
        PILLS={"blue": ((226, 238, 255), (0, 84, 180)), "green": ((222, 245, 228), (22, 112, 46)),
               "violet": ((240, 233, 255), (104, 56, 186)), "amber": ((255, 241, 220), (138, 78, 0))},
        ui=dict(eyebrow=(99, 103, 112), warn=(168, 80, 0), line=(226, 228, 234), disabled_fg=(160, 163, 170),
                select=(207, 226, 255), btn_ink=(29, 29, 31), primary_ink=(255, 255, 255),
                primary_dis=(232, 238, 248), list_bg=(255, 255, 255), head_bg=(246, 247, 250),
                head_hot=(236, 238, 243), nav_group=(110, 114, 124), nav_on_ink=(29, 29, 31),
                nav_on_icon=(0, 122, 255), title=((240, 241, 246), (29, 29, 31), (222, 224, 230)), dark_title=False),
    ),
    "dark": dict(
        PAGE=(24, 25, 29), CARD=(38, 39, 44), CARD_LINE=(56, 58, 65),
        INK=(242, 242, 247), MUTED=(160, 164, 174), ACCENT=(10, 132, 255), ACCENT_TEXT=(100, 175, 255),
        FIELD=(50, 51, 57), FIELD_LINE=(72, 74, 82), FIELD_OFF=(44, 45, 50),
        GREEN=(48, 209, 88), TRACK=(66, 67, 74), KNOB_RIM=(0, 0, 0, 60),
        BUTTON=((76, 77, 85), (62, 63, 70)), RIM=(255, 255, 255, 30), SHINE=(255, 255, 255, 70), SHADOW=90,
        THUMB=((78, 80, 88), (102, 105, 114), (128, 131, 141)),
        BLOBS=(((40, 90, 200), 0.55), ((120, 60, 190), 0.45), ((20, 130, 120), 0.38), ((160, 80, 60), 0.25)),
        BACK=((18, 20, 28), (24, 20, 30)), SHEET=(36, 38, 46, 165), SHEET_RIM=120,
        NAV_ON=(255, 255, 255, 40), NAV_HOT=(255, 255, 255, 18), NAV_RIM=(255, 255, 255, 70),
        KEY=((74, 75, 83), (62, 63, 70), (26, 27, 31)),
        PILLS={"blue": ((22, 46, 82), (130, 186, 255)), "green": ((22, 58, 34), (110, 215, 140)),
               "violet": ((50, 36, 82), (198, 166, 255)), "amber": ((70, 48, 16), (255, 192, 96))},
        ui=dict(eyebrow=(160, 164, 174), warn=(255, 172, 72), line=(52, 54, 60), disabled_fg=(104, 107, 115),
                select=(28, 70, 132), btn_ink=(242, 242, 247), primary_ink=(255, 255, 255),
                primary_dis=(120, 140, 170), list_bg=(30, 31, 36), head_bg=(46, 47, 53), head_hot=(56, 57, 64),
                nav_group=(150, 154, 164), nav_on_ink=(255, 255, 255), nav_on_icon=(100, 175, 255),
                title=((30, 31, 36), (242, 242, 247), (52, 54, 60)), dark_title=True),
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
        self.SIDEBAR = (self.BACK[0], self.BACK[1])
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
        """Soft colour behind the sidebar's glass: a pale wash with a few big blurred blobs."""
        img = _vgrad(w, h, [(0, self.BACK[0]), (1, self.BACK[1])]).convert("RGB")
        u = w / 224.0
        spots = ((0.15, 0.10, 120), (0.95, 0.38, 130), (0.10, 0.72, 140), (0.85, 0.95, 120))
        for (col, a), (fx, fy, rr) in zip(self.BLOBS, spots):
            m = Image.new("L", (w, h), 0)
            r = rr * u
            cx, cy = fx * w, fy * h
            ImageDraw.Draw(m).ellipse((cx - r, cy - r, cx + r, cy + r), fill=int(255 * a))
            m = m.filter(ImageFilter.GaussianBlur(r * 0.55))
            img = Image.composite(Image.new("RGB", (w, h), col), img, m)
        return img

    def sidebar(self, w, h):
        """A sheet of glass floating over the backdrop: the colour behind it blurred and washed, bent outwards at
        its rounded edge (refraction, computed once per size), with a bright rim and a soft shadow."""
        u = w / 224.0
        back = self.backdrop(w, h)
        m = int(round(9 * u))
        box = (m, m, w - m, h - m)
        r = int(round(18 * u))
        out = back.convert("RGBA")
        _shadow(out, box, r, 8 * u, self.SHADOW // 2, dy=int(3 * u))
        blurred = np.asarray(back.filter(ImageFilter.GaussianBlur(14 * u)), dtype=np.float32)
        # signed distance to the rounded box (negative inside), then the edge band bends the view outwards
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        bx, by = (box[2] - box[0]) / 2 - r, (box[3] - box[1]) / 2 - r
        qx, qy = np.abs(xs - cx) - bx, np.abs(ys - cy) - by
        d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
        band = 16 * u
        k = np.clip(1 + d / band, 0, 1)
        k = k * k * (3 - 2 * k)
        gy, gx = np.gradient(d)
        n = np.hypot(gx, gy) + 1e-6
        strength = 10 * u
        sx = np.clip(xs - gx / n * strength * k, 0, w - 1).astype(np.int32)
        sy = np.clip(ys - gy / n * strength * k, 0, h - 1).astype(np.int32)
        glass = blurred[sy, sx]
        wash = np.array(self.SHEET[:3], dtype=np.float32)
        a = self.SHEET[3] / 255.0
        glass = glass * (1 - a) + wash * a
        glass += (k[..., None] * (14 if self.mode == "light" else 10))   # a brighter band where the glass is thick
        sheet = Image.fromarray(np.clip(glass, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
        shape = _mask((w, h), box, r)
        out.paste(sheet, (0, 0), shape)
        # shine across the top and the rim, lit from above
        shine = _vgrad(w, int(h * 0.18) + 1, [(0, (255, 255, 255, 60 if self.mode == "light" else 22)),
                                              (1, (255, 255, 255, 0))])
        top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        top.paste(shine, (0, m))
        top.putalpha(ImageChops.multiply(top.getchannel("A"), shape))
        out.alpha_composite(top)
        _rim(out, box, r, (255, 255, 255, self.SHEET_RIM), (255, 255, 255, self.SHEET_RIM // 4),
             width=max(1, int(round(u))))
        return out.convert("RGB")

    def nav_pill(self, w, h, kind):
        """kind: 'selected' (a lighter bead of glass) or 'hover' (a faint one)."""
        img = _canvas(w, h)
        box = (K, K, w * K - K, h * K - 2 * K)
        r = 11 * K
        if kind == "selected":
            _shadow(img, box, r, K * 2, self.SHADOW // 2, dy=K)
            ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=self.NAV_ON)
            _rim(img, box, r, self.NAV_RIM, tuple(self.NAV_RIM[:3]) + (self.NAV_RIM[3] // 5,), width=K)
        else:
            ImageDraw.Draw(img).rounded_rectangle(box, radius=r, fill=self.NAV_HOT)
        return _shrink(img, w, h)

    def icon(self, name, size, color=None):
        return _icon(name, size, color or self.INK)

    # ------------------------------------------------------------ tags and keys
    def pill(self, w, h, fill, behind=None):
        img = Image.new("RGBA", (w * K, h * K), (behind or self.CARD) + (255,))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=(h * K) // 2,
                                              fill=tuple(fill) + (255,))
        return _shrink(img, w, h)

    def keycap(self, w, h, behind=None):
        img = Image.new("RGBA", (w * K, h * K), (behind or self.CARD) + (255,))
        top, bottom, edge = self.KEY
        r = 6 * K
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w * K - 1, h * K - 1), radius=r, fill=edge + (255,))
        _fill(img, (K // 2, K // 2, w * K - K // 2, h * K - 2 * K), r - K // 2,
              _vgrad(w * K, h * K, [(0, top), (1, bottom)]))
        return _shrink(img, w, h)
