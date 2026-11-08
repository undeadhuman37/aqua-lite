"""Frutiger Aero look: glossy aqua glass, sky gradients, orbs and bubbles - all drawn with Pillow."""
import math
import os
import random
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SS = 2  # supersampling for smooth edges

# palette: sky, aqua, lime and white gloss
SKY_TOP, SKY_BOTTOM = (156, 226, 255), (18, 132, 210)
RIM = (8, 74, 132)
ORB = {
    "recording": ((190, 255, 120), (40, 160, 20)),   # lime orb = listening
    "command": ((236, 200, 255), (128, 60, 210)),    # violet orb = Command Mode
    "info": ((190, 235, 255), (20, 120, 220)),
    "ok": ((190, 255, 170), (30, 160, 70)),
    "warn": ((255, 236, 160), (230, 150, 20)),
    "error": ((255, 190, 180), (210, 40, 40)),
}


def _font(size):
    for name in ("segoeuisb.ttf", "segoeui.ttf", "seguisb.ttf", "DejaVuSans.ttf", "arial.ttf"):
        for base in (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"), "/usr/share/fonts/truetype/dejavu", ""):
            try:
                return ImageFont.truetype(os.path.join(base, name) if base else name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def vgradient(w, h, top, bottom):
    """Vertical gradient image (RGBA). Colours may be RGB or RGBA tuples."""
    top = tuple(top) + (255,) * (4 - len(top))
    bottom = tuple(bottom) + (255,) * (4 - len(bottom))
    col = Image.new("RGBA", (1, max(h, 1)))
    px = col.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4))
    return col.resize((max(w, 1), max(h, 1)))


def capsule_mask(size, box, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def glass_capsule(size, box, top=SKY_TOP, bottom=SKY_BOTTOM, glow=None, shadow=True):
    """Returns (base, overlay): base = shadow + glass body, overlay = gloss + rims (drawn over contents)."""
    W, H = size
    x0, y0, x1, y1 = box
    h = y1 - y0
    r = h // 2
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    if shadow:
        sh = capsule_mask(size, (x0, y0 + 3 * SS, x1, y1 + 3 * SS), r).filter(ImageFilter.GaussianBlur(5 * SS))
        base.paste((0, 30, 60, 110), (0, 0), sh)
    if glow:
        g = capsule_mask(size, (x0 - 2 * SS, y0 - 2 * SS, x1 + 2 * SS, y1 + 2 * SS), r + 2 * SS)
        g = g.filter(ImageFilter.GaussianBlur(6 * SS))
        layer = Image.new("RGBA", size, glow + (0,))
        layer.putalpha(g.point(lambda v: int(v * 0.75)))
        base = Image.alpha_composite(base, layer)
    body = vgradient(x1 - x0, h, top, bottom)
    base.paste(body, (x0, y0), capsule_mask((x1 - x0, h), (0, 0, x1 - x0 - 1, h - 1), r))
    # soft light bouncing up from the bottom (the "water" reflection)
    refl = vgradient(x1 - x0, h // 2, (120, 255, 255, 0), (170, 255, 255, 120))
    rm = capsule_mask((x1 - x0, h), (0, 0, x1 - x0 - 1, h - 1), r).crop((0, h - h // 2, x1 - x0, h))
    base.alpha_composite(Image.composite(refl, Image.new("RGBA", refl.size, (0, 0, 0, 0)), rm), (x0, y0 + h - h // 2))

    over = Image.new("RGBA", size, (0, 0, 0, 0))
    inset = max(2 * SS, h // 14)
    gh = int(h * 0.5)
    gloss = vgradient(x1 - x0 - 2 * inset, gh, (255, 255, 255, 215), (255, 255, 255, 35))
    gm = capsule_mask(gloss.size, (0, 0, gloss.size[0] - 1, gh * 2), max(r - inset, 1))
    over.paste(gloss, (x0 + inset, y0 + inset // 2 + SS), gm)
    d = ImageDraw.Draw(over)
    d.rounded_rectangle(box, radius=r, outline=RIM + (210,), width=SS)
    d.rounded_rectangle((x0 + SS, y0 + SS, x1 - SS, y1 - SS), radius=r - SS, outline=(255, 255, 255, 110), width=SS)
    return base, over


_SPRITES = {}   # orbs and glows are drawn once per size/colour, then stamped every frame


def _orb_sprite(r, colors):
    key = ("orb", r, colors)
    if key not in _SPRITES:
        top, bottom = colors
        pad = 2 * SS
        size = int(r * 2)
        S = size + 2 * pad
        # pixels are written (not blended) exactly as the orb has always been drawn; `cov` marks which ones
        sp = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        cov = Image.new("L", (S, S), 0)
        body = vgradient(size, size, top, bottom)
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).ellipse((0, 0, size - 1, size - 1), fill=255)
        sp.paste(body, (pad, pad), m)
        cov.paste(255, (pad, pad), m)
        ring = (pad, pad, pad + 2 * r, pad + 2 * r)
        ImageDraw.Draw(sp).ellipse(ring, width=SS,
                                   outline=(0, 60, 40, 160) if colors == ORB["recording"] else (20, 40, 90, 150))
        ImageDraw.Draw(cov).ellipse(ring, width=SS, outline=255)
        hl = vgradient(int(r * 1.3), int(r * 0.8), (255, 255, 255, 235), (255, 255, 255, 30))
        hm = Image.new("L", hl.size, 0)
        ImageDraw.Draw(hm).ellipse((0, 0, hl.size[0] - 1, hl.size[1] - 1), fill=255)
        at = (pad + int(r * 0.35), pad + int(r * 0.1))
        sp.paste(hl, at, hm)
        cov.paste(255, at, hm)
        _SPRITES[key] = (sp, cov, pad)
    return _SPRITES[key]


def _glow_sprite(r, color):
    key = ("glow", r, color)
    if key not in _SPRITES:
        half = int(r * 3.8)
        m = Image.new("L", (2 * half, 2 * half), 0)
        ImageDraw.Draw(m).ellipse((half - r * 1.8, half - r * 1.8, half + r * 1.8, half + r * 1.8), fill=140)
        _SPRITES[key] = (m.filter(ImageFilter.GaussianBlur(r * 0.6)), Image.new("RGBA", m.size, color + (0,)), half)
    return _SPRITES[key]


def orb(img, cx, cy, r, colors, pulse=0.0):
    """Glossy marble with a highlight, like an Aero button. `pulse` (0..1) adds a soft breathing glow."""
    if pulse > 0:
        mask, layer, half = _glow_sprite(r, colors[1])
        layer = layer.copy()
        layer.putalpha(mask.point(lambda v: int(v * pulse + 0.5)))
        x, y = int(round(cx)) - half, int(round(cy)) - half
        _stamp(img, layer, x, y)
    sp, cov, pad = _orb_sprite(r, colors)
    img.paste(sp, (int(round(cx - r)) - pad, int(round(cy - r)) - pad), cov)


def _stamp(img, sprite, x, y):
    """alpha_composite a small image at (x, y), clipping whatever hangs off the edges."""
    sx, sy = max(0, -x), max(0, -y)
    w, h = min(sprite.width, img.width - x) - sx, min(sprite.height, img.height - y) - sy
    if w > 0 and h > 0:
        img.alpha_composite(sprite, (x + sx, y + sy), (sx, sy, sx + w, sy + h))


class Bubbles:
    def __init__(self):
        self.items = []

    def step(self, box, level, dt=1 / 30, rate=1.0):
        """Move by real time passed (speeds are per 1/30 s), so bubbles rise at the same pace at any frame rate."""
        x0, y0, x1, y1 = box
        f = dt * 30
        if random.random() < min(1.0, (0.08 + level * 0.9) * rate * f):
            r = random.uniform(1.6, 4.2) * SS
            self.items.append([random.uniform(x0 + 20 * SS, x1 - 20 * SS), y1 - r, r,
                               random.uniform(0.5, 1.4) * SS * (1 + level * 2), random.uniform(0, 6.28)])
        alive = []
        for b in self.items:
            b[1] -= b[3] * f
            b[0] += math.sin(b[4] + b[1] / (9 * SS)) * 0.4 * SS * f
            if b[1] > y0 + b[2]:
                alive.append(b)
        self.items = alive[-40:]

    def draw(self, img, ox=0, oy=0):
        d = ImageDraw.Draw(img)
        for x, y, r, _vy, _p in self.items:
            x, y = x - ox, y - oy
            d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 170), width=max(1, SS // 2 + 1),
                      fill=(255, 255, 255, 35))
            d.ellipse((x - r * 0.45, y - r * 0.6, x - r * 0.05, y - r * 0.2), fill=(255, 255, 255, 220))


BARS = 14   # waveform slots in the Flow bar


class FlowBarRenderer:
    """Draws every Flow bar state into an RGBA image of size (W, H) * scale."""

    W, H = 440, 118   # extra room on top for the live caption

    def __init__(self, scale=1.0):
        self.scale = scale
        self.size = (int(self.W * scale), int(self.H * scale))
        self.big = (self.size[0] * SS, self.size[1] * SS)
        self.cache = {}
        self.bubbles = Bubbles()
        self.last_t = None
        self.font = _font(int(12.5 * scale * SS))
        self.small = _font(int(11 * scale * SS))

    def _u(self, v):
        return int(v * self.scale * SS)

    def _box(self, w, h):
        W, H = self.big
        w, h = self._u(w), self._u(h)
        cx = W // 2
        y1 = H - self._u(12)
        return (cx - w // 2, y1 - h, cx + w // 2, y1)

    def _glass(self, key, w, h, **kw):
        if key not in self.cache:
            box = self._box(w, h)
            self.cache[key] = (box,) + glass_capsule(self.big, box, **kw)
        return self.cache[key]

    def _cap_glass(self, w, h, above_y):
        key = ("cap", w)
        if key not in self.cache:
            W, _H = self.big
            y1 = above_y - self._u(6)
            box = (W // 2 - self._u(w) // 2, y1 - self._u(h), W // 2 + self._u(w) // 2, y1)
            self.cache[key] = (box,) + glass_capsule(self.big, box, (232, 248, 255), (150, 205, 240), shadow=True)
        return self.cache[key]

    def warm_steps(self):
        """Small jobs that pre-build the glass for the common states and caption sizes, so the first recording
        doesn't stutter while they're made. Run them one at a time while the app is idle."""
        steps = [lambda st=st: self._warm(st) for st in ("recording", "locked", "command", "processing", "idle")]
        y0 = self._box(184, 42)[1]
        for w in sorted({min(self.W - 16, k * 32 + 24) for k in range(1, 14)}):
            steps.append(lambda w=w: self._cap_glass(w, 24, y0))
        return steps

    def _warm(self, state):
        saved = self.last_t, self.bubbles.items
        self.render(state, "", [0.0] * (BARS + 1), 0.0)
        self.last_t, self.bubbles.items = saved

    def _caption(self, img, text, above_y, alpha=1.0):
        """A small glass bubble above the bar with the newest words of what you're saying (alpha < 1 fades it)."""
        maxw = (self.W - 40) * self.scale * SS
        words = (text or "").split()
        shown = shape_for_display(" ".join(words), self.small)
        while words and (not shown or self.small.getlength(shown) > maxw):  # keep the newest words that fit
            words = words[1:]  # trimmed in spoken order, before any right-to-left reordering
            shown = shape_for_display("\u2026 " + " ".join(words), self.small)
        if not words or not shown:
            return
        tw = self.small.getlength(shown) / (self.scale * SS)
        w = min(self.W - 16, int(tw / 32 + 1) * 32 + 24)  # widths in steps, so only a few bubble sizes get cached
        h = 24
        box, base, over = self._cap_glass(w, h, above_y)
        target = img if alpha >= 1 else Image.new("RGBA", self.big, (0, 0, 0, 0))
        target.alpha_composite(base)
        d = ImageDraw.Draw(target)
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        d.text((cx, cy + SS), shown, font=self.small, fill=(255, 255, 255, 160), anchor="mm")
        d.text((cx, cy), shown, font=self.small, fill=(10, 60, 105, 255), anchor="mm")
        target.alpha_composite(over)
        if target is not img:
            target.putalpha(target.getchannel("A").point(lambda v: int(v * alpha + 0.5)))
            img.alpha_composite(target)

    def _down(self, img):
        """Supersampled canvas -> final size. A plain 2x2 average: smooth edges, and far quicker than Lanczos."""
        return img.reduce(SS) if img.size == self.big and SS > 1 else img.resize(self.size, Image.LANCZOS)

    def _bars(self, box, levels, phase):
        """The waveform: one bar per level sample, newest on the right. `phase` (0..1) is how far the newest bar has
        slid in, so the bars glide left continuously instead of jumping a whole slot each sample."""
        x0, y0, x1, y1 = box
        layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cy = (y1 - y0) / 2
        slot, half, r = self._u(7), self._u(1.6), self._u(1.6)
        bx = self._u(42)
        n = len(levels)
        for i, v in enumerate(levels):
            pos = (BARS - 1) - (n - 1 - i) + (1 - phase)   # phase 1 -> newest sits in the last slot
            if pos >= BARS or pos <= -1:
                continue
            a = 1.0 if 0 <= pos <= BARS - 1 else (BARS - pos if pos > BARS - 1 else 1 + pos)  # fade at both ends
            hh = self._u(3 + v * 22)
            x = bx + pos * slot
            d.rounded_rectangle((x - half, cy - hh / 2 + self._u(1), x + half, cy + hh / 2 + self._u(1)),
                                radius=r, fill=(0, 70, 130, int(70 * a)))
            d.rounded_rectangle((x - half, cy - hh / 2, x + half, cy + hh / 2),
                                radius=r, fill=(255, 255, 255, int(245 * a)))
        return layer

    def render(self, state, label="", levels=(), t=0.0, kind="info", caption="", phase=1.0, caption_alpha=1.0):
        """`t` is a clock in seconds: pulses, bouncing dots and bubbles move by real time, not by frames drawn."""
        dt = 1 / 30 if self.last_t is None else min(max(t - self.last_t, 0.0), 0.1)
        self.last_t = t
        if state == "hidden":
            return Image.new("RGBA", self.size, (0, 0, 0, 0))
        if state == "idle":
            if "idle_img" not in self.cache:
                box, base, over = self._glass("idle", 60, 15)
                self.cache["idle_img"] = self._down(Image.alpha_composite(base, over))
            return self.cache["idle_img"].copy()
        if state in ("recording", "locked", "command"):
            wide = state != "recording"
            w = 258 if wide else 184
            glow = (170, 120, 255) if state == "command" else (90, 230, 255)
            box, base, over = self._glass(("rec", state), w, 42, glow=glow)
            img = base.copy()
            x0, y0, x1, y1 = box
            lv = levels[-1] if levels else 0.0
            self.bubbles.step(box, lv, dt)
            layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            self.bubbles.draw(layer, x0, y0)
            mkey = ("mask", state)
            if mkey not in self.cache:
                self.cache[mkey] = capsule_mask(self.big, box, (box[3] - box[1]) // 2).crop(box)
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), self.cache[mkey]))
            img.alpha_composite(layer, (x0, y0))
            cy = (y0 + y1) // 2
            pulse = 0.5 + 0.5 * math.sin(t * 6.67)
            orb(img, x0 + self._u(22), cy, self._u(9), ORB["command" if state == "command" else "recording"], pulse)
            img.alpha_composite(self._bars(box, list(levels), phase), (x0, y0))
            d = ImageDraw.Draw(img)
            if wide:
                tag = "Command" if state == "command" else "Hands-free"
                tx = x0 + self._u(42) + BARS * self._u(7) + self._u(6)
                d.text((tx + SS, cy + SS), tag, font=self.small, fill=(0, 60, 110, 120), anchor="lm")
                d.text((tx, cy), tag, font=self.small, fill=(255, 255, 255, 250), anchor="lm")
                orb(img, x1 - self._u(22), cy, self._u(8), ((255, 255, 255), (150, 200, 230)))
                d = ImageDraw.Draw(img)
                s = self._u(3.2)
                d.rounded_rectangle((x1 - self._u(22) - s, cy - s, x1 - self._u(22) + s, cy + s), radius=SS,
                                    fill=(20, 90, 150, 230))
            img.alpha_composite(over)
            if caption and caption_alpha > 0:
                self._caption(img, caption, y0, min(caption_alpha, 1.0))
            return self._down(img)
        if state == "processing":
            box, base, over = self._glass("proc", 100, 36, glow=(90, 230, 255))
            img = base.copy()
            x0, y0, x1, y1 = box
            cy = (y0 + y1) // 2
            for i in range(3):
                ph = t * 6.0 - i * 0.9
                dy = -abs(math.sin(ph)) * self._u(6)
                orb(img, (x0 + x1) // 2 + (i - 1) * self._u(18), cy + self._u(2) + dy, self._u(5.5),
                    ((255, 255, 255), (120, 210, 255)))
            img.alpha_composite(over)
            return self._down(img)
        # toast
        text = label[:64]
        tw = self.font.getlength(text) / (self.scale * SS)
        w = min(self.W - 16, int(tw) + 64)
        box, base, over = self._glass(("toast", w), w, 36)
        img = base.copy()
        x0, y0, x1, y1 = box
        cy = (y0 + y1) // 2
        orb(img, x0 + self._u(18), cy, self._u(6.5), ORB.get(kind, ORB["info"]))
        d = ImageDraw.Draw(img)
        tx = x0 + self._u(32)
        d.text((tx + SS, cy + SS), text, font=self.font, fill=(0, 50, 100, 140), anchor="lm")
        d.text((tx, cy), text, font=self.font, fill=(255, 255, 255, 255), anchor="lm")
        img.alpha_composite(over)
        return self._down(img)


def crossfade(a, b, t):
    """Blend two RGBA frames (t: 0 = all a, 1 = all b) in premultiplied space, so edges don't go dark mid-fade."""
    if t <= 0:
        return a
    if t >= 1 or a.size != b.size:
        return b
    return Image.blend(a.convert("RGBa"), b.convert("RGBa"), t).convert("RGBA")


_ARABIC = re.compile("[\u0590-\u08ff\ufb1d-\ufefc]")


def shape_for_display(text, font):
    """Arabic/Hebrew need joined letters and right-to-left order. Pillow does it itself when it was built with
    libraqm; otherwise use arabic-reshaper + python-bidi if installed, else don't show (better than garbled)."""
    text = " ".join((text or "").split())
    if not _ARABIC.search(text):
        return text
    try:
        if ImageFont.core.HAVE_RAQM and font.layout_engine == ImageFont.Layout.RAQM:
            return text
    except AttributeError:
        pass
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return ""


def premultiplied_bgra(img):
    import numpy as np
    a = np.asarray(img, dtype=np.uint16)
    alpha = a[..., 3:4]
    rgb = (a[..., :3] * alpha + 127) // 255
    out = np.concatenate([rgb[..., ::-1], alpha], axis=2).astype(np.uint8)
    return out.tobytes()


# ---------------------------------------------------------------- app art
def sky_banner(w, h, title="Aqua Lite", subtitle="Speak anywhere you can type"):
    """Header art: sky -> aqua water, sun glow, bubbles, glossy title."""
    W, H = w * SS, h * SS
    img = vgradient(W, H, (120, 205, 255), (0, 150, 210))
    # horizon water
    water = vgradient(W, H // 2, (40, 190, 230, 0), (0, 120, 190, 200))
    img.alpha_composite(water, (0, H - H // 2))
    # sun glow
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.62, -H * 0.6, W * 1.1, H * 0.9), fill=200)
    glow = glow.filter(ImageFilter.GaussianBlur(H * 0.25))
    sun = Image.new("RGBA", (W, H), (255, 255, 230, 0))
    sun.putalpha(glow)
    img.alpha_composite(sun)
    # swooshes
    sw = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sw)
    for i, a in enumerate((70, 45, 30)):
        d.arc((-W * 0.2, H * (0.35 + i * 0.12), W * 1.2, H * (1.9 + i * 0.12)), 190, 350, fill=(255, 255, 255, a), width=6 * SS)
    img.alpha_composite(sw.filter(ImageFilter.GaussianBlur(SS)))
    # bubbles
    rnd = random.Random(7)
    bub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(bub)
    for _ in range(26):
        r = rnd.uniform(4, 22) * SS
        x, y = rnd.uniform(W * 0.35, W), rnd.uniform(0, H)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 150), width=SS, fill=(255, 255, 255, 28))
        d.ellipse((x - r * 0.55, y - r * 0.65, x - r * 0.1, y - r * 0.25), fill=(255, 255, 255, 190))
    img.alpha_composite(bub)
    # the app icon + title
    icon = app_icon(int(h * 0.7)).resize((int(H * 0.7), int(H * 0.7)), Image.LANCZOS)
    img.alpha_composite(icon, (int(H * 0.15), int(H * 0.15)))
    d = ImageDraw.Draw(img)
    f1, f2 = _font(int(h * 0.36 * SS)), _font(int(h * 0.17 * SS))
    tx = int(H * 0.95)
    d.text((tx + 2 * SS, H * 0.42 + 2 * SS), title, font=f1, fill=(0, 60, 110, 120), anchor="lm")
    d.text((tx, H * 0.42), title, font=f1, fill=(255, 255, 255, 255), anchor="lm")
    d.text((tx + 2, H * 0.73), subtitle, font=f2, fill=(235, 250, 255, 240), anchor="lm")
    gloss = vgradient(W, H // 2, (255, 255, 255, 90), (255, 255, 255, 0))
    img.alpha_composite(gloss)
    return img.resize((w, h), Image.LANCZOS)


def glossy_button(w, h, state="normal"):
    tops = {"normal": (215, 245, 255), "active": (235, 252, 255), "pressed": (120, 200, 240)}
    bottoms = {"normal": (60, 165, 225), "active": (90, 195, 245), "pressed": (30, 120, 190)}
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base, over = glass_capsule((W, H), (SS, SS, W - SS - 1, H - 2 * SS), tops[state], bottoms[state], shadow=False)
    img = Image.alpha_composite(Image.alpha_composite(img, base), over)
    return img.resize((w, h), Image.LANCZOS)


def app_icon(size=256):
    """Glossy aqua rounded square with a white waveform."""
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    r = S // 4
    body = vgradient(S - 4 * SS, S - 4 * SS, (150, 230, 255), (0, 120, 205))
    img.paste(body, (2 * SS, 2 * SS), capsule_mask(body.size, (0, 0, body.size[0] - 1, body.size[1] - 1), r))
    # glass shine on the top half: blended (its own transparency times the rounded mask), not pasted solid
    gloss = vgradient(S - 10 * SS, int(S * 0.46), (255, 255, 255, 150), (255, 255, 255, 20))
    gmask = capsule_mask(gloss.size, (0, 0, gloss.size[0] - 1, gloss.size[1] * 2), r - 3 * SS)
    gloss.putalpha(Image.composite(gloss.getchannel("A"), Image.new("L", gloss.size, 0), gmask))
    shine = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shine.paste(gloss, (5 * SS, 4 * SS))
    img.alpha_composite(shine)
    # waveform with a soft shadow so it stays readable over the shine, even at 16 px
    heights = (0.26, 0.5, 0.74, 0.5, 0.26)
    bw = S / 10
    bars = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    db, ds = ImageDraw.Draw(bars), ImageDraw.Draw(shadow)
    off = max(SS, S // 80)
    for i, hh in enumerate(heights):
        x = S / 2 + (i - 2) * bw * 1.8
        H = hh * S * 0.62
        box = (x - bw / 2, S / 2 - H / 2, x + bw / 2, S / 2 + H / 2)
        ds.rounded_rectangle((box[0], box[1] + off, box[2], box[3] + off), radius=bw / 2, fill=(0, 60, 120, 110))
        db.rounded_rectangle(box, radius=bw / 2, fill=(255, 255, 255, 255))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, S // 70))))
    img.alpha_composite(bars)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * SS, 2 * SS, S - 2 * SS - 1, S - 2 * SS - 1), radius=r, outline=RIM + (220,), width=max(SS, S // 90))
    return img.resize((size, size), Image.LANCZOS)


def write_icon(path):
    """Write a Windows .ico the way Windows' own icons are built: classic 32-bit bitmap entries for 16-128 px and a
    PNG entry for 256 px. Explorer, shortcuts and exe resources don't reliably show PNG entries below 256 px, so
    an all-PNG .ico (Pillow's default) can come out as a blank icon."""
    import io
    import struct
    sizes = [16, 24, 32, 48, 64, 128, 256]
    blobs = []
    for size in sizes:
        img = app_icon(size).convert("RGBA")
        if size == 256:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            blobs.append(buf.getvalue())
            continue
        w = h = size
        px = img.tobytes("raw", "BGRA")
        rows = [px[y * w * 4:(y + 1) * w * 4] for y in range(h)][::-1]  # bitmaps are stored bottom-up
        mask_stride = ((w + 31) // 32) * 4
        alpha = img.getchannel("A").tobytes()
        mask = bytearray()
        for y in reversed(range(h)):  # AND mask: 1 = transparent (ignored for 32-bit, but must be present)
            row = bytearray(mask_stride)
            for x in range(w):
                if alpha[y * w + x] == 0:
                    row[x // 8] |= 0x80 >> (x % 8)
            mask += row
        xor = b"".join(rows)
        header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor) + len(mask), 0, 0, 0, 0)
        blobs.append(header + xor + bytes(mask))
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for size, blob in zip(sizes, blobs):
        d = size if size < 256 else 0  # 0 means 256
        out += struct.pack("<BBBBHHII", d, d, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(out + b"".join(blobs))


if __name__ == "__main__" and len(sys.argv) > 1:
    write_icon(sys.argv[1])
