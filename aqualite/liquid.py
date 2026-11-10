"""Liquid Glass look for the Flow bar: clear glass with a bright rim lit from above, a soft shadow and a faint
rainbow fringe at its rounded ends, in light and dark versions.

An optional theme next to Frutiger Aero (aero.py), which stays the default. The two share only small helpers
(fonts, gradients, the Scene format), so either can be changed on its own.

Each frame is built once as a list of drawing steps (an aero.Scene). The graphics card puts it together
(glbar.GLBar); without OpenGL the same steps run here in Pillow (_run), so both ways draw the same picture.
Moving parts (light, dot, waveform, words) stay inside the glass's frosted middle, away from the rim.
"""
import math
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .aero import BARS, SS, Scene, _font_px, _stamp, capsule_mask, shape_for_display, vgradient

PALETTES = {
    "light": dict(
        frost_body=((255, 255, 255, 64), (255, 255, 255, 46)),   # see-through, over Windows' blur
        solid_body=((242, 245, 250), (228, 233, 241)),           # no blur behind: looks like frosted glass
        core=(255, 255, 255, 140),        # frosted middle under the words and waveform, so they read over anything
        edge=(255, 255, 255, 26),         # slightly brighter band along the inside of the rim: thick glass
        rim=178, shine=46, shadow=26, fringe=0,
        ink=(20, 22, 28), halo=(255, 255, 255, 200),
        bar=(30, 34, 42), bar_shade=(255, 255, 255, 110),
        light=(255, 255, 255), light_a=70,
        tint={"recording": (80, 200, 60), "locked": (80, 200, 60), "command": (140, 80, 230)}, tint_a=31,
        frost_tint=0x18FFFFFF,            # AABBGGRR: an almost clear wash in Windows' blur
        acrylic_tint=0x01A4A4A4,          # Windows 11 acrylic: a little brighter than what's behind
    ),
    "dark": dict(
        frost_body=((40, 42, 50, 70), (40, 42, 50, 52)),
        solid_body=((44, 47, 56), (30, 32, 39)),
        core=(20, 22, 28, 153),
        edge=(255, 255, 255, 15),
        rim=125, shine=30, shadow=34, fringe=0,
        ink=(245, 247, 250), halo=(0, 0, 0, 190),
        bar=(255, 255, 255), bar_shade=(0, 0, 0, 90),
        light=(200, 225, 255), light_a=50,
        tint={"recording": (110, 230, 90), "locked": (110, 230, 90), "command": (170, 120, 255)}, tint_a=38,
        frost_tint=0x14201C1A,
        acrylic_tint=0x01605854,          # a little darker than what's behind
    ),
}
LISTENING = ("recording", "locked", "command")
SHADOW_BLUR = lambda h, u: min(h * 0.25, 4 * u)   # noqa: E731  soft, close shadow (no dark halo)
DOTS = {"recording": (52, 199, 89), "command": (175, 82, 222), "ok": (52, 199, 89), "warn": (255, 159, 10),
        "error": (255, 69, 58), "info": (10, 132, 255)}


def resolve_mode(look_mode):
    """'light', 'dark', or 'system' (follow Windows' app colour setting; light elsewhere) -> 'light' | 'dark'."""
    if look_mode in PALETTES:
        return look_mode
    if sys.platform == "win32":
        try:
            from . import winapi
            return "light" if winapi.apps_light_theme() else "dark"
        except Exception:
            pass
    return "light"


# ---------------------------------------------------------------- drawing helpers
def _clip(img, mask):
    """img with its alpha multiplied by mask (same size)."""
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def _wash(size, color, mask):
    """A layer of one colour whose alpha is mask scaled by the colour's own alpha."""
    layer = Image.new("RGBA", size, tuple(color[:3]) + (0,))
    layer.putalpha(mask.point(lambda v: v * color[3] // 255))
    return layer


def _pill(size, inset, r):
    """Mask of a pill filling `size`, pulled in by `inset` pixels."""
    w, h = size
    return capsule_mask(size, (inset, inset, w - 1 - inset, h - 1 - inset), max(1, r - inset))


def glass_shape(size, box, pal, frost, u, tint=None, shadow=True, core=True):
    """Liquid Glass pill at box in a canvas of size. Returns (base, over) like aero.glass_capsule: base = shadow and
    body (drawn under the contents), over = shine, rim and fringe (drawn over them). u = canvas pixels per point."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    r = h // 2
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    if shadow:
        dy = max(SS, int(h * 0.06))
        m = capsule_mask(size, (x0, y0 + dy, x1, y1 + dy), r).filter(ImageFilter.GaussianBlur(SHADOW_BLUR(h, u)))
        base.paste((0, 0, 0, pal["shadow"]), (0, 0), m)
    top, bottom = pal["frost_body"] if frost else pal["solid_body"]
    body = vgradient(w, h, top, bottom)
    if tint:
        body.alpha_composite(Image.new("RGBA", (w, h), tuple(tint) + (pal["tint_a"],)))
    shape = _pill((w, h), 0, r)
    band = max(SS, int(r * 0.3))
    middle = _pill((w, h), band, r)
    edge = ImageChops.subtract(shape, middle).filter(ImageFilter.GaussianBlur(band / 2))
    body.alpha_composite(_wash((w, h), pal["edge"], edge))
    if core:
        body.alpha_composite(_wash((w, h), pal["core"], middle.filter(ImageFilter.GaussianBlur(band * 0.6))))
    base.alpha_composite(_clip(body, shape), (x0, y0))

    over = Image.new("RGBA", size, (0, 0, 0, 0))
    shine = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    shine.paste(vgradient(w, max(1, int(h * 0.42)), (255, 255, 255, pal["shine"]), (255, 255, 255, 0)), (0, 0))
    over.alpha_composite(_clip(shine, _pill((w, h), max(1, round(u)), r)), (x0, y0))
    # the rim, lit from above and a little from the left: brightest top-left, a quarter as bright bottom-right
    rw = max(1, round(1.25 * u))
    ring = ImageChops.subtract(shape, _pill((w, h), rw, r))
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    lit = Image.fromarray(((1.0 - 0.75 * (0.75 * ys + 0.25 * xs)) * pal["rim"]).astype(np.uint8), "L")
    over.alpha_composite(_wash((w, h), (255, 255, 255, 255), ImageChops.multiply(ring, lit)), (x0, y0))
    # faint rainbow fringe where the glass curves most (the rounded ends): red just outside, blue just inside
    if pal["fringe"]:
        f = max(1, round(u))
        outside = ImageChops.subtract(capsule_mask(size, (x0 - f, y0 - f, x1 + f, y1 + f), r + f),
                                      capsule_mask(size, box, r))
        inside = ImageChops.subtract(capsule_mask(size, (x0 + rw, y0 + rw, x1 - rw, y1 - rw), max(1, r - rw)),
                                     capsule_mask(size, (x0 + rw + f, y0 + rw + f, x1 - rw - f, y1 - rw - f),
                                                  max(1, r - rw - f)))
        cx, straight = (x0 + x1) / 2, max(1.0, w / 2 - r)
        row = Image.new("L", (size[0], 1))
        row.putdata([int(255 * min(1.0, max(0.0, (abs(x - cx) - straight) / max(r, 1)))) for x in range(size[0])])
        ends = row.resize(size)
        over.alpha_composite(_wash(size, (255, 90, 90, pal["fringe"]), ImageChops.multiply(outside, ends)))
        over.alpha_composite(_wash(size, (90, 140, 255, pal["fringe"]), ImageChops.multiply(inside, ends)))
    return base, over


def text_sprite(text, font, ink, halo, anchor, blur=1.2):
    """Words with a soft halo all round (no offset), as a small RGBA image plus where its corner sits relative to
    the anchor point."""
    l, t, r, b = font.getbbox(text, anchor=anchor)
    pad = 2 + int(blur * 2 + 0.99)
    w, h = max(1, r - l + 2 * pad), max(1, b - t + 2 * pad)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).text((pad - l, pad - t), text, font=font, fill=255, anchor=anchor)
    out = _wash((w, h), halo, m.filter(ImageFilter.GaussianBlur(blur)))
    out.alpha_composite(_wash((w, h), tuple(ink[:3]) + (255,), m))
    return out, (l - pad, t - pad)


def _dot(r, color, rim=None):
    """A small solid dot (r in canvas pixels), drawn 4x and shrunk for a clean edge, with a thin lighter rim."""
    k, size = 4, int(math.ceil(r * 2)) + 4
    img = Image.new("RGBA", (size * k, size * k), (0, 0, 0, 0))
    c, rr = size * k / 2, r * k
    d = ImageDraw.Draw(img)
    d.ellipse((c - rr, c - rr, c + rr, c + rr), fill=tuple(color[:3]) + (color[3] if len(color) > 3 else 255,))
    if rim:
        d.arc((c - rr + k, c - rr + k, c + rr - k, c + rr - k), 200, 340, fill=rim, width=k)
    return img.resize((size, size), Image.LANCZOS)


def _glow(r, color):
    half = int(r * 3)
    m = Image.new("L", (2 * half, 2 * half), 0)
    ImageDraw.Draw(m).ellipse((half - r * 1.6, half - r * 1.6, half + r * 1.6, half + r * 1.6), fill=120)
    return _wash(m.size, tuple(color) + (255,), m.filter(ImageFilter.GaussianBlur(r * 0.7))), half


# ---------------------------------------------------------------- the Pillow runner
def _run(img, ops):
    """Carry out Scene steps in Pillow, the way glbar.GLBar does on the graphics card."""
    for op in ops:
        kind = op[0]
        if kind == "paste":
            _k, sp, cov, x, y = op
            img.paste(sp, (int(x), int(y)), cov)
        elif kind == "over":
            _k, sp, x, y, alpha, mask = op
            x, y = int(x), int(y)
            if alpha < 1 or mask is not None:
                a = sp.getchannel("A")
                if alpha < 1:
                    a = a.point(lambda v: int(v * alpha + 0.5))
                if mask is not None:
                    m, mx, my = mask
                    sub = Image.new("L", sp.size, 0)
                    sub.paste(m, (int(mx) - x, int(my) - y))
                    a = ImageChops.multiply(a, sub)
                sp = sp.copy()
                sp.putalpha(a)
            _stamp(img, sp, x, y)
        elif kind == "rrect":
            _k, box, radius, rgba, mode = op
            rgba = tuple(int(c) for c in rgba)
            if mode == "paste":
                ImageDraw.Draw(img).rounded_rectangle(box, radius=radius, fill=rgba)
                continue
            ix, iy = int(math.floor(box[0])) - 1, int(math.floor(box[1])) - 1
            layer = Image.new("RGBA", (int(box[2]) - ix + 3, int(box[3]) - iy + 3), (0, 0, 0, 0))
            ImageDraw.Draw(layer).rounded_rectangle((box[0] - ix, box[1] - iy, box[2] - ix, box[3] - iy),
                                                    radius=radius, fill=rgba)
            _stamp(img, layer, ix, iy)
        else:
            raise ValueError(f"unknown drawing step {kind}")


def picture(scene):
    """A Scene drawn in Pillow: the still frame, the moving patch (drawn at 2x, then shrunk), then the top steps."""
    img = scene.base.copy()
    if scene.patch is not None:
        (rx, ry, rx1, ry1), ops = scene.patch
        patch = Image.new("RGBA", (rx1 - rx, ry1 - ry), (0, 0, 0, 0))
        _run(patch, ops)
        img.paste(patch.reduce(SS), (rx // SS, ry // SS))
    _run(img, scene.top)
    return img


# ---------------------------------------------------------------- motion
class Spring:
    """A number that follows its target the way Apple's interface springs do: quick, with a small bounce.
    response = seconds for one swing; damping < 1 lets it overshoot a little before it settles."""

    def __init__(self, value, response=0.36, damping=0.68):
        self.x = self.target = float(value)
        self.v = 0.0
        w = 2 * math.pi / response
        self.k, self.c = w * w, 2 * damping * w

    def step(self, dt):
        n = int(dt / 0.004) + 1           # small steps keep it steady at any frame rate
        h = dt / n
        for _ in range(n):
            self.v += (self.k * (self.target - self.x) - self.c * self.v) * h
            self.x += self.v * h
        if abs(self.target - self.x) < 0.08 and abs(self.v) < 2.0:
            self.x, self.v = self.target, 0.0

    def resting(self):
        return self.v == 0.0 and self.x == self.target


def _ease(a, b, x):
    """0 below a, 1 above b, smooth between."""
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- the Flow bar
class LiquidBarRenderer:
    """Draws every Flow bar state in Liquid Glass. Same methods as aero.FlowBarRenderer, so the overlay can use
    either.

    With animate on (the overlay sets it while the graphics card draws), the glass is moved by springs: it pops
    out small and grows, flows from one shape to the next, squishes when clicked (poke), breathes while
    processing, and the caption bubble grows out of the top of the bar. Those frames are drawn on the graphics card
    straight from the shape (glbar LGLASS). At rest it switches back to the cached pictures, which the Pillow
    drawing matches; settled is set for one frame at each switch so the overlay can cross-fade."""

    W, H = 440, 118   # same window as Frutiger Aero's bar, so switching needs no new window

    def __init__(self, scale=1.0, frost=False, mode="light"):
        self.scale, self.frost = scale, frost
        self.mode = mode if mode in PALETTES else "light"
        self.frame_box = None
        self.size = (int(self.W * scale), int(self.H * scale))
        self.big = (self.size[0] * SS, self.size[1] * SS)
        self.cache, self.text_cache = {}, {}
        self.last_t = None
        self.font = _font_px(12.5 * scale)
        self.small = _font_px(11 * scale)
        self.texts = []
        self.animate = False     # set by the overlay: springs and shape-morphing (graphics card only)
        self.settled = False     # one frame's flag: switched between moving and resting pictures
        self._m = None           # the springs while the glass moves
        self._moving = False
        self._extra = None       # the caption bubble's box, for the blur behind it

    @property
    def pal(self):
        return PALETTES[self.mode]

    @property
    def frost_tint(self):
        """The wash Windows mixes into its blur behind the bar (winapi.Frost)."""
        return self.pal["frost_tint"]

    @property
    def acrylic_tint(self):
        """The same for Windows 11's acrylic blur (its tint sets brightness: grey leaves it as it is)."""
        return self.pal["acrylic_tint"]

    def _u(self, v):
        return int(v * self.scale * SS)

    def set_frost(self, on):
        if bool(on) != self.frost:
            self.frost = bool(on)
            self.cache.clear()

    def set_mode(self, mode):
        mode = mode if mode in PALETTES else "light"
        if mode != self.mode:
            self.mode = mode
            self.cache.clear()
            self.text_cache.clear()

    def moving(self):
        """True while springs are moving: the overlay keeps drawing frames until they rest."""
        return self._moving

    def poke(self):
        """The bar was clicked: a quick squish that springs back, like pressing glass."""
        if self._m is not None:
            main = self._m["main"]
            main[2].v += self._u(170)
            main[3].v -= self._u(90)
            self._moving = True

    def _window_rect(self, box, inset):
        x0, y0, x1, y1 = (v / SS for v in box)
        i = inset * self.scale
        x0, y0, x1, y1 = int(round(x0 + i)), int(round(y0 + i)), int(round(x1 - i)), int(round(y1 - i))
        return x0, y0, x1 - x0, y1 - y0, (y1 - y0) // 2

    def blur_shape(self, inset=1.5):
        """(x, y, w, h, radius) of the main glass in window pixels, pulled in a little so the blur's edge hides under
        the rim. None when nothing is shown."""
        return None if self.frame_box is None else self._window_rect(self.frame_box, inset)

    def blur_extra(self, inset=1.5):
        """The caption bubble, as more shapes for the blur behind the bar (window pixels), or ()."""
        return () if self._extra is None else (self._window_rect(self._extra, inset),)

    def _box(self, w, h):
        W, H = self.big
        w, h = self._u(w), self._u(h)
        y1 = H - self._u(12)
        return (W // 2 - w // 2, y1 - h, W // 2 + w // 2, y1)

    def _glass(self, box, **kw):
        return glass_shape(self.big, box, self.pal, self.frost, self.scale * SS, **kw)

    def _live(self, key, w, h, tint=None):
        """The glass of a moving state, split for speed: the patch around the glass (2x) where things move, and the
        whole still frame (1x). Returns (patch_rect, patch_base, patch_over, still, box, mask)."""
        ck = ("live", key)
        if ck not in self.cache:
            box = self._box(w, h)
            base, over = self._glass(box, tint=tint)
            W, H = self.big
            x0, y0, x1, y1 = box
            m = 2 * SS
            r = (max(0, (x0 - m) // SS * SS), max(0, (y0 - m) // SS * SS),
                 min(W, -(-(x1 + m) // SS) * SS), min(H, -(-(y1 + m) // SS) * SS))
            mask = capsule_mask(self.big, box, (y1 - y0) // 2).crop(box)
            still = Image.alpha_composite(base, over).reduce(SS)
            self.cache[ck] = (r, base.crop(r), over.crop(r), still, box, (mask, x0 - r[0], y0 - r[1]))
        return self.cache[ck]

    def _sprite(self, key, make):
        if key not in self.cache:
            self.cache[key] = make()
        return self.cache[key]

    def warm_steps(self):
        """Small jobs that build the glass for the common states and caption sizes ahead of time."""
        steps = [lambda st=st: self._still(st, "", [0.0] * (BARS + 1), 0.0)
                 for st in ("recording", "locked", "command", "processing", "idle")]
        y0 = self._box(184, 42)[1]
        for w in sorted({min(self.W - 16, k * 32 + 24) for k in range(1, 14)}):
            steps.append(lambda w=w: self._cap_img(w, 24, y0))
        return steps

    # ------------------------------------------------------------ pieces of a frame
    def _light_ops(self, ops, box, rect, mask, color_key, t, level, period=2.6):
        """A soft light drifting inside the glass, brighter as you speak."""
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        pal = self.pal

        def make():
            lw, lh = int(w * 0.5), int(h * 1.4)
            m = Image.new("L", (lw, lh), 0)
            ImageDraw.Draw(m).ellipse((lw * 0.12, lh * 0.12, lw * 0.88, lh * 0.88), fill=pal["light_a"])
            return _wash((lw, lh), tuple(pal["light"]) + (255,), m.filter(ImageFilter.GaussianBlur(min(lw, lh) * 0.18)))
        sp = self._sprite(("light", color_key, w, h), make)
        k = min(1.0, 0.35 + 0.8 * level)
        drift = 0.5 - 0.5 * math.cos(2 * math.pi * t / period)
        cx = x0 - rect[0] + w * (0.2 + 0.6 * drift)
        cy = y0 - rect[1] + h * 0.3
        ops.append(("over", sp, int(cx - sp.size[0] / 2), int(cy - sp.size[1] / 2), k, mask))

    def _dot_ops(self, ops, cx, cy, r, color, glow=0.0, alpha=1.0):
        if alpha <= 0:
            return
        if glow > 0:
            g, half = self._sprite(("glow", r, color), lambda: _glow(r, color))
            ops.append(("over", g, int(round(cx)) - half, int(round(cy)) - half, min(1.0, glow) * alpha, None))
        sp = self._sprite(("dot", r, color), lambda: _dot(r, color, rim=(255, 255, 255, 120)))
        ops.append(("over", sp, int(round(cx - sp.size[0] / 2)), int(round(cy - sp.size[1] / 2)), alpha, None))

    def _bar_ops(self, ops, box, rect, levels, phase, alpha=1.0):
        """The waveform: plain bars with a faint shadow of the opposite colour, gliding left as samples arrive."""
        x0, y0, x1, y1 = box
        pal = self.pal
        cy = y0 - rect[1] + (y1 - y0) / 2
        slot, half, r = self._u(7), self._u(1.5), self._u(1.5)
        bx = x0 - rect[0] + self._u(42)
        n = len(levels)
        for i, v in enumerate(levels):
            pos = (BARS - 1) - (n - 1 - i) + (1 - phase)
            if pos >= BARS or pos <= -1:
                continue
            a = alpha * (1.0 if 0 <= pos <= BARS - 1 else (BARS - pos if pos > BARS - 1 else 1 + pos))
            hh = self._u(3 + v * 22)
            x = bx + pos * slot
            top = cy - hh / 2
            sh = pal["bar_shade"]
            ops.append(("rrect", (x - half, top + self._u(1), x + half, top + hh + self._u(1)), r,
                        sh[:3] + (int(sh[3] * a),), "over"))
            ops.append(("rrect", (x - half, top, x + half, top + hh), r, pal["bar"] + (int(235 * a),), "over"))

    def _listen_ops(self, ops, box, rect, state, levels, t, phase, alpha=1.0, mask=None):
        """What's inside the glass while you talk: the light, the dot, the waveform, and for hands-free and Command
        Mode a label and a stop button."""
        x0, y0, x1, y1 = box
        cy = (y0 + y1) // 2
        lv = levels[-1] if levels else 0.0
        if mask is not None:
            self._light_ops(ops, box, rect, mask, state, t, lv)
        pulse = 0.5 + 0.5 * math.sin(t * 4.2)
        self._dot_ops(ops, x0 + self._u(22) - rect[0], cy - rect[1], self._u(4.5),
                      DOTS["command" if state == "command" else "recording"], glow=0.3 + 0.5 * pulse, alpha=alpha)
        self._bar_ops(ops, box, rect, list(levels), phase, alpha)
        if state != "recording":
            tag = "Command" if state == "command" else "Hands-free"
            self._text(tag, self.small, x0 + self._u(42) + BARS * self._u(7) + self._u(6), cy, "lm", alpha)
            ink = self.pal["ink"]
            sx, sy = x1 - self._u(22) - rect[0], cy - rect[1]
            self._dot_ops(ops, sx, sy, self._u(8), ink + (34,), alpha=alpha)
            s = self._u(3)
            ops.append(("rrect", (sx - s, sy - s, sx + s, sy + s), SS, ink + (int(230 * alpha),), "over"))

    def _proc_ops(self, ops, box, rect, t, alpha=1.0):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) // 2 - rect[1]
        for i in range(3):
            dy = -abs(math.sin(t * 6.0 - i * 0.9)) * self._u(5)
            self._dot_ops(ops, (x0 + x1) // 2 + (i - 1) * self._u(14) - rect[0], cy + self._u(2) + dy,
                          self._u(3.2), self.pal["ink"], alpha=alpha)

    def _text(self, text, font, x, y, anchor, alpha=1.0):
        """Queue words for the top layer; x, y are in the 2x canvas."""
        if text and alpha > 0:
            self.texts.append((text, font, x, y, anchor, alpha))

    def _text_ops(self, top):
        pal = self.pal
        for text, font, x, y, anchor, alpha in self.texts:
            key = (text, font.size, anchor)
            if key not in self.text_cache:
                if len(self.text_cache) > 64:
                    self.text_cache.pop(next(iter(self.text_cache)))
                self.text_cache[key] = text_sprite(text, font, pal["ink"], pal["halo"], anchor)
            sp, (dx, dy) = self.text_cache[key]
            top.append(("over", sp, int(round(x / SS)) + dx, int(round(y / SS)) + dy, alpha, None))
        self.texts = []

    def _cap_box(self, w, h, above_y):
        W, _H = self.big
        y1 = above_y - self._u(6)
        return (W // 2 - self._u(w) // 2, y1 - self._u(h), W // 2 + self._u(w) // 2, y1)

    def _cap_img(self, w, h, above_y):
        """The caption bubble above the bar, already shrunk and cropped to itself, plus where it goes."""
        key = ("capimg", w)
        if key not in self.cache:
            box = self._cap_box(w, h, above_y)
            base, over = self._glass(box)
            flat = Image.alpha_composite(base, over).reduce(SS)
            bb = flat.getbbox() or (0, 0, 1, 1)
            self.cache[key] = (box, flat.crop(bb), bb[:2])
        return self.cache[key]

    def _cap_fit(self, text):
        """The newest words that fit in the bubble, and the bubble's width (in steps of 32, so few sizes)."""
        maxw = (self.W - 40) * self.scale
        words = (text or "").split()
        shown = shape_for_display(" ".join(words), self.small)
        while words and (not shown or self.small.getlength(shown) > maxw):   # keep the newest words that fit
            words = words[1:]
            shown = shape_for_display("… " + " ".join(words), self.small)
        if not words or not shown:
            return None
        tw = self.small.getlength(shown) / self.scale
        return shown, min(self.W - 16, int(tw / 32 + 1) * 32 + 24)

    def _caption_ops(self, top, text, above_y, alpha):
        fit = self._cap_fit(text)
        if fit is None:
            return
        shown, w = fit
        box, bubble, pos = self._cap_img(w, 24, above_y)
        top.append(("over", bubble, pos[0], pos[1], alpha, None))
        if alpha > 0.5:
            self._extra = box
        self._text(shown, self.small, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, "mm", alpha)

    def _toast_w(self, text):
        return min(self.W - 16, int(self.font.getlength(text) / self.scale) + 60)

    def _target(self, state, label):
        """Where the glass should be for a state: the box, as Pillow takes it (2x canvas)."""
        if state == "idle":
            return self._box(56, 14)
        if state in LISTENING:
            return self._box(184 if state == "recording" else 258, 42)
        if state == "processing":
            return self._box(100, 36)
        return self._box(self._toast_w(label[:64]), 36)

    # ------------------------------------------------------------ frames
    def scene(self, state, label="", levels=(), t=0.0, kind="info", caption="", phase=1.0, caption_alpha=1.0):
        """One frame as drawing steps (see aero.Scene)."""
        dt = 1 / 60 if self.last_t is None else min(max(t - self.last_t, 0.0), 0.05)
        self.last_t = t
        self.texts = []
        self._extra = None
        if self.animate and state != "hidden":
            sc = self._motion(state, label, levels, t, kind, caption, phase, caption_alpha, dt)
            if sc is not None:
                return sc
        else:
            self._m = None
            if self._moving:
                self._moving, self.settled = False, True
        return self._still(state, label, levels, t, kind, caption, phase, caption_alpha)

    def _still(self, state, label="", levels=(), t=0.0, kind="info", caption="", phase=1.0, caption_alpha=1.0):
        """The resting pictures, cached; the same steps run in Pillow (render) and on the graphics card."""
        self.texts = []
        if state == "hidden":
            self.frame_box = None
            return Scene(self.size, self._blank())
        if state == "idle":
            box = self.frame_box = self._box(56, 14)

            def make():
                base, over = self._glass(box, core=False)
                return Image.alpha_composite(base, over).reduce(SS)
            return Scene(self.size, self._sprite("idle", make))
        if state in LISTENING:
            rect, pb, po, still, box, mask = self._live(("rec", state), 184 if state == "recording" else 258, 42,
                                                         tint=self.pal["tint"][state])
            self.frame_box = box
            ops = [("paste", pb, None, 0, 0)]
            self._listen_ops(ops, box, rect, state, levels, t, phase, mask=mask)
            ops.append(("over", po, 0, 0, 1.0, None))
            top = []
            if caption and caption_alpha > 0:
                self._caption_ops(top, caption, box[1], min(caption_alpha, 1.0))
            self._text_ops(top)
            return Scene(self.size, still, (rect, ops), top)
        if state == "processing":
            rect, pb, po, still, box, _mask = self._live("proc", 100, 36)
            self.frame_box = box
            ops = [("paste", pb, None, 0, 0)]
            self._proc_ops(ops, box, rect, t)
            ops.append(("over", po, 0, 0, 1.0, None))
            return Scene(self.size, still, (rect, ops))
        return Scene(self.size, self._toast(label[:64], kind))

    def _blank(self):
        return self._sprite("hidden", lambda: Image.new("RGBA", self.size, (0, 0, 0, 0)))

    def _gl_params(self, tint, hh):
        """The palette as the graphics card's glass program takes it (colours 0..1)."""
        pal, u = self.pal, self.scale * SS

        def c4(c):
            return tuple(v / 255.0 for v in c[:3]) + ((c[3] if len(c) > 3 else 255) / 255.0,)
        top, bottom = pal["frost_body"] if self.frost else pal["solid_body"]
        h = 2 * hh
        r = int(h) // 2
        tint4 = (tuple(v / 255.0 for v in tint) + (pal["tint_a"] / 255.0,)) if tint else (0.0, 0.0, 0.0, 0.0)
        return dict(body_top=c4(top), body_bot=c4(bottom), tint=tint4, edge=c4(pal["edge"]), core=c4(pal["core"]),
                    rim=pal["rim"] / 255.0, shine=pal["shine"] / 255.0, shadow=pal["shadow"] / 255.0,
                    fringe=pal["fringe"] / 255.0, band=float(max(SS, int(r * 0.3))), rw=float(max(1, round(1.25 * u))),
                    u=float(max(1, round(u))), sh_dy=float(max(SS, int(h * 0.06))), sh_sigma=float(SHADOW_BLUR(h, u)),
                    k=6.0 * u)

    def _motion(self, state, label, levels, t, kind, caption, phase, caption_alpha, dt):
        """Move the springs one frame. Returns a Scene while anything moves, None once everything rests."""
        tb = self._target(state, label)
        x0, y0, x1, y1 = tb
        target = [(x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2]
        if state == "processing":   # the glass breathes while it thinks
            target[2] += self._u(2.5) * math.sin(t * 3.2)
            target[3] += self._u(0.8) * math.sin(t * 3.2 + 1.2)
        m = self._m
        if m is None:   # appearing: start small at the bottom and spring out
            cx, cy, hw, hh = target
            m = self._m = dict(main=[Spring(cx), Spring(cy + hh * 0.45), Spring(hw * 0.4), Spring(hh * 0.55)],
                               bub=None, state=state, t0=t, cap=None)
        if state != m["state"]:
            m["state"], m["t0"] = state, t
        for s, v in zip(m["main"], target):
            s.target = v
            s.step(dt)
        cx, cy, hw, hh = (s.x for s in m["main"])
        fit = self._cap_fit(caption) if (state in LISTENING and caption and caption_alpha > 0.02) else None
        btarget = None
        if fit is not None:
            bx0, by0, bx1, by1 = self._cap_box(fit[1], 24, tb[1])
            btarget = ((bx0 + bx1) / 2, (by0 + by1) / 2, (bx1 - bx0) / 2, (by1 - by0) / 2)
            if m["bub"] is None:   # grows out of the top of the bar
                m["bub"] = [Spring(v, 0.4, 0.72) for v in (cx, cy - hh + self._u(5), self._u(10), self._u(5))]
            m["cap"] = (fit[0], btarget)
        elif m["bub"] is not None:   # sinks back into the bar
            btarget = (cx, cy - hh + self._u(4), self._u(8), self._u(4))
        if m["bub"] is not None:
            for s, v in zip(m["bub"], btarget):
                s.target = v
                s.step(dt)
            if fit is None and all(s.resting() for s in m["bub"]):
                m["bub"], m["cap"] = None, None
        resting = (all(s.resting() for s in m["main"]) and (m["bub"] is None or all(s.resting() for s in m["bub"]))
                   and t - m["t0"] > 0.32 and state != "processing")
        if resting and (m["bub"] is None or caption_alpha >= 1.0):
            if self._moving:
                self._moving, self.settled = False, True
            return None
        if not self._moving:
            self._moving, self.settled = True, True
        return self._motion_scene(state, label, levels, t, kind, phase, caption_alpha, m)

    def _motion_scene(self, state, label, levels, t, kind, phase, caption_alpha, m):
        cx, cy, hw, hh = (s.x for s in m["main"])
        box = (cx - hw, cy - hh, cx + hw, cy + hh)
        self.frame_box = tuple(int(round(v)) for v in box)
        a = (cx, cy, hw, hh)
        b = tuple(s.x for s in m["bub"]) if m["bub"] is not None else None
        if b is not None and b[2] > self._u(14):
            self._extra = tuple(int(round(v)) for v in (b[0] - b[2], b[1] - b[3], b[0] + b[2], b[1] + b[3]))
        params = self._gl_params(self.pal["tint"].get(state), hh)
        ops = [("lglass", "base", (a, b), params)]
        alpha = _ease(0.08, 0.3, t - m["t0"])    # the new contents fade in as the glass takes its shape
        origin = (0, 0)
        if state in LISTENING:
            self._listen_ops(ops, box, origin, state, levels, t, phase, alpha)
        elif state == "processing":
            self._proc_ops(ops, box, origin, t, alpha)
        elif state != "idle":
            self._dot_ops(ops, box[0] + self._u(18), cy, self._u(4), DOTS.get(kind, DOTS["info"]), alpha=alpha)
            self._text(label[:64], self.font, box[0] + self._u(30), cy, "lm", alpha)
        ops.append(("lglass", "over", (a, b), params))
        if b is not None and m["cap"] is not None:
            shown, (_bx, _by, bhw, _bhh) = m["cap"]
            self._text(shown, self.small, b[0], b[1], "mm", min(1.0, caption_alpha) * _ease(0.75, 0.97, b[2] / bhw))
        top = []
        self._text_ops(top)
        return Scene(self.size, self._blank(), ((0, 0) + self.big, ops), top)

    def _toast(self, text, kind):
        """A finished message: nothing in it moves, so the whole picture is kept and reused."""
        box = self.frame_box = self._box(self._toast_w(text), 36)
        key = ("toast", text, kind)
        if key not in self.cache:
            base, over = self._glass(box)
            x0, y0, x1, y1 = box
            cy = (y0 + y1) // 2
            ops = [("paste", base, None, 0, 0)]
            self._dot_ops(ops, x0 + self._u(18), cy, self._u(4), DOTS.get(kind, DOTS["info"]))
            ops.append(("over", over, 0, 0, 1.0, None))
            img = Image.new("RGBA", self.big, (0, 0, 0, 0))
            _run(img, ops)
            img = img.reduce(SS)
            self.texts = []
            self._text(text, self.font, x0 + self._u(30), cy, "lm")
            top = []
            self._text_ops(top)
            _run(img, top)
            for k in [k for k in self.cache if k[0] == "toast"][:-7]:   # keep the last few toasts only
                del self.cache[k]
            self.cache[key] = img
        return self.cache[key]

    def render(self, state, label="", levels=(), t=0.0, kind="info", caption="", phase=1.0, caption_alpha=1.0):
        """The resting frame drawn in Pillow (when there's no graphics-card drawing; no springs here)."""
        return picture(self._still(state, label, levels, t, kind, caption, phase, caption_alpha))
