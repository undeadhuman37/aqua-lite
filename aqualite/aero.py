"""Frutiger Aero look: glossy aqua glass, sky gradients, orbs and bubbles - drawn with Pillow. The Flow bar's
pieces are drawn once here; FlowBarRenderer.scene() lists them per frame for the graphics card (glbar.py)."""
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


def _font_px(size):
    try:
        return _font(size)          # Pillow 10.1+ takes fractional sizes
    except (TypeError, ValueError):
        return _font(max(1, round(size)))


# text looks: (ink, soft shadow colour, shadow offset in px, shadow blur)
TEXT_STYLES = {
    "light": ((255, 255, 255, 255), (0, 42, 92, 175), (0, 1), 1.0),     # white words on the aqua glass
    "dark": ((12, 58, 102, 255), (255, 255, 255, 210), (0, 1), 0.7),    # navy words on the pale caption bubble
}


def text_sprite(text, font, style, anchor):
    """Words with a soft shadow, as a small RGBA image, plus where its corner sits relative to the anchor point.
    Ink and shadow are blended properly, so no see-through fringes around the letters."""
    ink, shade, (sx, sy), blur = TEXT_STYLES[style]
    l, t, r, b = font.getbbox(text, anchor=anchor)
    pad = 2 + int(blur * 2 + 0.99) + max(abs(sx), abs(sy))
    w, h = max(1, r - l + 2 * pad), max(1, b - t + 2 * pad)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).text((pad - l, pad - t), text, font=font, fill=255, anchor=anchor)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sm = m.filter(ImageFilter.GaussianBlur(blur)) if blur else m
    sh = Image.new("RGBA", (w, h), shade[:3] + (0,))
    sh.putalpha(sm.point(lambda v: v * shade[3] // 255))
    out.alpha_composite(sh, (max(0, sx), max(0, sy)), (max(0, -sx), max(0, -sy)))
    fg = Image.new("RGBA", (w, h), ink[:3] + (0,))
    fg.putalpha(m.point(lambda v: v * ink[3] // 255))
    out.alpha_composite(fg)
    return out, (l - pad, t - pad)


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


def glass_capsule(size, box, top=SKY_TOP, bottom=SKY_BOTTOM, glow=None, shadow=True, alpha=None):
    """Returns (base, overlay): base = shadow + glass body, overlay = gloss + rims (drawn over contents).
    alpha = (top, bottom) opacity makes the body see-through, for frosted glass over Windows' blur."""
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
    body = vgradient(x1 - x0, h, tuple(top[:3]) + ((alpha[0],) if alpha else ()),
                     tuple(bottom[:3]) + ((alpha[1],) if alpha else ()))
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
FROST_ALPHA = (125, 180)   # see-through glass body (top, bottom) when Windows blurs what's behind it
VIOLET = ((222, 204, 255), (104, 54, 196))   # Command Mode glass
LIGHT = {"command": (222, 186, 255), "default": (140, 255, 255)}   # the light that drifts with your voice


class FlowBarRenderer:
    """Draws every Flow bar state into an RGBA image of size (W, H) * scale."""

    W, H = 440, 118   # extra room on top for the live caption

    def __init__(self, scale=1.0, frost=False):
        self.scale, self.frost = scale, frost
        self.frame_box = None   # where the main glass is in the last frame (2x canvas), for the blur under it
        self.size = (int(self.W * scale), int(self.H * scale))
        self.big = (self.size[0] * SS, self.size[1] * SS)
        self.cache = {}
        self.bubbles = Bubbles()
        self.last_t = None
        self.font = _font_px(12.5 * scale)    # text is drawn at the final size, so the font's own hinting
        self.small = _font_px(11 * scale)     # keeps letters sharp (drawing big and shrinking smeared them)
        self.texts, self.text_cache = [], {}

    def _u(self, v):
        return int(v * self.scale * SS)

    def set_frost(self, on):
        """Switch between see-through frosted glass (Windows blurs behind it) and solid glass."""
        if bool(on) != self.frost:
            self.frost = bool(on)
            self.cache.clear()

    def blur_shape(self, inset=1.5):
        """(x, y, w, h, radius) of the main glass in the last frame, in window pixels, pulled in a little so the
        blur's hard edge hides under the glass rim. None when nothing is shown."""
        if self.frame_box is None:
            return None
        x0, y0, x1, y1 = (v / SS for v in self.frame_box)
        i = inset * self.scale
        x0, y0, x1, y1 = int(round(x0 + i)), int(round(y0 + i)), int(round(x1 - i)), int(round(y1 - i))
        return x0, y0, x1 - x0, y1 - y0, (y1 - y0) // 2

    def _light(self, layer, state, t, level, period=2.4):
        """A soft light that drifts back and forth inside the glass and brightens as you speak."""
        w, h = layer.size
        key = ("light", state, w, h)
        if key not in self.cache:
            lw, lh = int(w * 0.55), int(h * 1.5)
            m = Image.new("L", (lw, lh), 0)
            ImageDraw.Draw(m).ellipse((lw * 0.12, lh * 0.12, lw * 0.88, lh * 0.88), fill=150)
            m = m.filter(ImageFilter.GaussianBlur(min(lw, lh) * 0.16))
            sp = Image.new("RGBA", (lw, lh), LIGHT.get(state, LIGHT["default"]) + (0,))
            sp.putalpha(m)
            self.cache[key] = sp
        sp = self.cache[key]
        k = min(1.0, 0.4 + 0.75 * level)
        if k < 0.99:
            sp = sp.copy()
            sp.putalpha(sp.getchannel("A").point(lambda v: int(v * k)))
        drift = 0.5 - 0.5 * math.cos(2 * math.pi * t / period)
        cx = w * (0.18 + 0.56 * drift + 0.06 * level)
        _stamp(layer, sp, int(cx - sp.size[0] / 2), int(h * 0.72 - sp.size[1] / 2))

    def _box(self, w, h):
        W, H = self.big
        w, h = self._u(w), self._u(h)
        cx = W // 2
        y1 = H - self._u(12)
        return (cx - w // 2, y1 - h, cx + w // 2, y1)

    def _glass(self, w, h, **kw):
        """Glass at 2x size: (box, base, over). Not cached itself: callers keep only the small pieces they need
        (full 2x canvases are ~2 MB each, and toasts come in every width)."""
        box = self._box(w, h)
        if self.frost:
            kw.setdefault("alpha", FROST_ALPHA)
        return (box,) + glass_capsule(self.big, box, **kw)

    def _cap_glass(self, w, h, above_y):
        W, _H = self.big
        y1 = above_y - self._u(6)
        box = (W // 2 - self._u(w) // 2, y1 - self._u(h), W // 2 + self._u(w) // 2, y1)
        return (box,) + glass_capsule(self.big, box, (232, 248, 255), (150, 205, 240), shadow=True)

    def warm_steps(self):
        """Small jobs that pre-build the glass for the common states and caption sizes, so the first recording
        doesn't stutter while they're made. Run them one at a time while the app is idle."""
        steps = [lambda st=st: self._warm(st) for st in ("recording", "locked", "command", "processing", "idle")]
        y0 = self._box(184, 42)[1]
        for w in sorted({min(self.W - 16, k * 32 + 24) for k in range(1, 14)}):
            steps.append(lambda w=w: self._cap_img(w, 24, y0))
        return steps

    def _warm(self, state):
        saved = self.last_t, self.bubbles.items
        self.render(state, "", [0.0] * (BARS + 1), 0.0)
        self.last_t, self.bubbles.items = saved

    # ------------------------------------------------------------ static / moving split
    def _flat(self, base, over):
        """Glass with its gloss, downsampled once: everything that never moves, ready to copy each frame."""
        return Image.alpha_composite(base, over).reduce(SS)

    def _live(self, key, w, h, margin_for, **kw):
        """Only the patch around the capsule changes from frame to frame. Cache that patch's glass (2x) and the
        whole still frame (1x), so each frame redraws and shrinks just the patch instead of the full canvas.
        Returns (patch_rect, patch_base, patch_over, still_frame, box)."""
        ck = ("live", key)
        if ck not in self.cache:
            box, base, over = self._glass(w, h, **kw)
            margin = margin_for(box)
            W, H = self.big
            x0, y0, x1, y1 = box
            r = (max(0, (x0 - margin) // SS * SS), max(0, (y0 - margin) // SS * SS),
                 min(W, -(-(x1 + margin) // SS) * SS), min(H, -(-(y1 + margin) // SS) * SS))
            self.cache[ck] = (r, base.crop(r), over.crop(r), self._flat(base, over), box)
        return self.cache[ck]

    def _compose(self, live, patch):
        r, _b, _o, still, _box = live
        img = still.copy()
        img.paste(patch.reduce(SS), (r[0] // SS, r[1] // SS))
        return img

    def _cap_img(self, w, h, above_y):
        """The caption bubble, already downsampled and cropped to itself, plus where it goes."""
        key = ("capimg", w)
        if key not in self.cache:
            box, base, over = self._cap_glass(w, h, above_y)
            flat = self._flat(base, over)
            bb = flat.getbbox() or (0, 0, 1, 1)
            self.cache[key] = (box, flat.crop(bb), bb[:2])
        return self.cache[key]

    def _caption(self, img, text, above_y, alpha=1.0):
        """A small glass bubble above the bar with the newest words of what you're saying (alpha < 1 fades it).
        `img` is the final-size frame."""
        maxw = (self.W - 40) * self.scale
        words = (text or "").split()
        shown = shape_for_display(" ".join(words), self.small)
        while words and (not shown or self.small.getlength(shown) > maxw):  # keep the newest words that fit
            words = words[1:]  # trimmed in spoken order, before any right-to-left reordering
            shown = shape_for_display("\u2026 " + " ".join(words), self.small)
        if not words or not shown:
            return
        tw = self.small.getlength(shown) / self.scale
        w = min(self.W - 16, int(tw / 32 + 1) * 32 + 24)  # widths in steps, so only a few bubble sizes get cached
        box, bubble, pos = self._cap_img(w, 24, above_y)
        if alpha < 1:
            bubble = bubble.copy()
            bubble.putalpha(bubble.getchannel("A").point(lambda v: int(v * alpha + 0.5)))
        img.alpha_composite(bubble, pos)
        self._text(shown, self.small, "dark", (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, "mm", alpha)

    def _finish(self, img):
        """The words go on top of the final-size frame at full sharpness."""
        for text, font, style, x, y, anchor, alpha in self.texts:
            key = (text, font.size, style, anchor)
            if key not in self.text_cache:
                if len(self.text_cache) > 64:
                    self.text_cache.pop(next(iter(self.text_cache)))
                self.text_cache[key] = text_sprite(text, font, style, anchor)
            sp, (dx, dy) = self.text_cache[key]
            if alpha < 1:
                sp = sp.copy()
                sp.putalpha(sp.getchannel("A").point(lambda v: int(v * alpha + 0.5)))
            _stamp(img, sp, int(round(x / SS)) + dx, int(round(y / SS)) + dy)
        self.texts = []
        return img

    def _text(self, text, font, style, x, y, anchor, alpha=1.0):
        """Queue words for the sharp pass; x, y are in the 2x canvas like everything else."""
        if text:
            self.texts.append((text, font, style, x, y, anchor, alpha))

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
        self.texts = []
        if state == "hidden":
            self.frame_box = None
            return Image.new("RGBA", self.size, (0, 0, 0, 0))
        if state == "idle":
            self.frame_box = self._box(60, 15)
            if "idle_img" not in self.cache:
                box, base, over = self._glass(60, 15)
                self.cache["idle_img"] = self._flat(base, over)
            return self.cache["idle_img"].copy()
        if state in ("recording", "locked", "command"):
            wide = state != "recording"
            w = 258 if wide else 184
            glow = (170, 120, 255) if state == "command" else (90, 230, 255)
            orb_r = self._u(9)
            half = int(orb_r * 3.8)   # the pulsing glow reaches this far around the orb
            tint = dict(top=VIOLET[0], bottom=VIOLET[1]) if state == "command" else {}
            live = self._live(("rec", state), w, 42,
                              lambda b: max(SS * 2, half - self._u(22), half - (b[3] - b[1]) // 2) + SS, glow=glow,
                              **tint)
            (rx, ry, _rx1, _ry1), patch_base, patch_over, _still, box = live
            x0, y0, x1, y1 = box
            cy = (y0 + y1) // 2
            orb_x = x0 + self._u(22)
            img = patch_base.copy()               # everything below is drawn in patch coordinates
            self.frame_box = box
            lv = levels[-1] if levels else 0.0
            self.bubbles.step(box, lv, dt)
            layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            self._light(layer, state, t, lv)
            self.bubbles.draw(layer, x0, y0)
            mkey = ("mask", state)
            if mkey not in self.cache:
                self.cache[mkey] = capsule_mask(self.big, box, (box[3] - box[1]) // 2).crop(box)
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), self.cache[mkey]))
            img.alpha_composite(layer, (x0 - rx, y0 - ry))
            pulse = 0.5 + 0.5 * math.sin(t * 6.67)
            orb(img, orb_x - rx, cy - ry, orb_r, ORB["command" if state == "command" else "recording"], pulse)
            img.alpha_composite(self._bars(box, list(levels), phase), (x0 - rx, y0 - ry))
            if wide:
                tag = "Command" if state == "command" else "Hands-free"
                tx = x0 + self._u(42) + BARS * self._u(7) + self._u(6)
                self._text(tag, self.small, "light", tx, cy, "lm")
                sx = x1 - self._u(22) - rx
                orb(img, sx, cy - ry, self._u(8), ((255, 255, 255), (150, 200, 230)))
                s = self._u(3.2)
                ImageDraw.Draw(img).rounded_rectangle((sx - s, cy - ry - s, sx + s, cy - ry + s), radius=SS,
                                                      fill=(20, 90, 150, 230))
            img.alpha_composite(patch_over)
            out = self._compose(live, img)
            if caption and caption_alpha > 0:
                self._caption(out, caption, y0, min(caption_alpha, 1.0))
            return self._finish(out)
        if state == "processing":
            live = self._live("proc", 100, 36, lambda b: SS * 3, glow=(90, 230, 255))
            (rx, ry, _rx1, _ry1), patch_base, patch_over, _still, box = live
            self.frame_box = box
            x0, y0, x1, y1 = box
            cy = (y0 + y1) // 2
            img = patch_base.copy()
            layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
            self._light(layer, "processing", t, 0.3, period=1.4)
            if ("mask", "proc") not in self.cache:
                self.cache["mask", "proc"] = capsule_mask(self.big, box, (box[3] - box[1]) // 2).crop(box)
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), self.cache["mask", "proc"]))
            img.alpha_composite(layer, (x0 - rx, y0 - ry))
            for i in range(3):
                ph = t * 6.0 - i * 0.9
                dy = -abs(math.sin(ph)) * self._u(6)
                orb(img, (x0 + x1) // 2 + (i - 1) * self._u(18) - rx, cy + self._u(2) + dy - ry, self._u(5.5),
                    ((255, 255, 255), (120, 210, 255)))
            img.alpha_composite(patch_over)
            return self._compose(live, img)
        # toast: nothing in it moves, so the finished picture is kept and reused while it slides / fades
        text = label[:64]
        key = ("toastimg", text, kind)
        tw = self.font.getlength(text) / self.scale
        w = min(self.W - 16, int(tw) + 64)
        self.frame_box = self._box(w, 36)
        if key not in self.cache:
            box, base, over = self._glass(w, 36)
            img = base.copy()
            x0, y0, x1, y1 = box
            cy = (y0 + y1) // 2
            orb(img, x0 + self._u(18), cy, self._u(6.5), ORB.get(kind, ORB["info"]))
            img.alpha_composite(over)
            self._text(text, self.font, "light", x0 + self._u(32), cy, "lm")
            old = [k for k in self.cache if k[0] == "toastimg"]
            for k in old[:-7]:  # keep the last few toasts only
                del self.cache[k]
            self.cache[key] = self._finish(img.reduce(SS))
        return self.cache[key].copy()


class Scene:
    """One Flow bar frame as a list of drawing steps, for the graphics-card renderer (glbar.py).

    base: the still frame (final size), copied as is. patch: (rect, ops) - the moving part, drawn at 2x (SS) in
    the rect's own coordinates, then shrunk and copied over the still frame at rect / SS. top: steps drawn at final
    size over everything (caption bubble, words). Steps:
      ("over", img, x, y, alpha, mask)     blend an image (mask: (L image, x, y) multiplies its alpha, or None)
      ("paste", img, cov, x, y)            write an image where cov says (how orbs have always been drawn)
      ("rrect", box, radius, rgba, mode)   rounded rectangle; mode "over" blends, "paste" writes
      ("circle", cx, cy, r, fill, outline, width, mask)   a bubble, blended
    Images are Pillow RGBA images that stay alive in the renderer's caches, so the graphics card keeps each one
    after uploading it once."""

    def __init__(self, size, base, patch=None, top=()):
        self.size, self.base, self.patch, self.top = size, base, patch, list(top)


def _glow_rgba(r, color):
    key = ("glowrgba", r, color)
    if key not in _SPRITES:
        mask, layer, half = _glow_sprite(r, color)
        im = layer.copy()
        im.putalpha(mask)
        _SPRITES[key] = (im, half)
    return _SPRITES[key]


def orb_ops(ops, cx, cy, r, colors, pulse=0.0):
    """orb(), as drawing steps."""
    if pulse > 0:
        im, half = _glow_rgba(r, colors[1])
        ops.append(("over", im, int(round(cx)) - half, int(round(cy)) - half, pulse, None))
    sp, cov, pad = _orb_sprite(r, colors)
    ops.append(("paste", sp, cov, int(round(cx - r)) - pad, int(round(cy - r)) - pad))


def _scene(self, state, label="", levels=(), t=0.0, kind="info", caption="", phase=1.0, caption_alpha=1.0):
    """render(), as a Scene for the graphics card: same pieces, same places, nothing composited here."""
    if state not in ("recording", "locked", "command", "processing"):
        # still pictures: render() builds and caches them; hand over the cached image itself (not a copy), so the
        # graphics card uploads it once
        self.render(state, label, levels, t, kind, caption, phase, caption_alpha)
        if state == "hidden":
            if "hidden_img" not in self.cache:
                self.cache["hidden_img"] = Image.new("RGBA", self.size, (0, 0, 0, 0))
            return Scene(self.size, self.cache["hidden_img"])
        if state == "idle":
            return Scene(self.size, self.cache["idle_img"])
        return Scene(self.size, self.cache[("toastimg", label[:64], kind)])
    dt = 1 / 30 if self.last_t is None else min(max(t - self.last_t, 0.0), 0.1)
    self.last_t = t
    self.texts = []
    ops = []
    if state == "processing":
        live = self._live("proc", 100, 36, lambda b: SS * 3, glow=(90, 230, 255))
        (rx, ry, rx1, ry1), patch_base, patch_over, still, box = live
        self.frame_box = box
        x0, y0, x1, y1 = box
        cy = (y0 + y1) // 2
        ops.append(("paste", patch_base, None, 0, 0))
        if ("mask", "proc") not in self.cache:
            self.cache["mask", "proc"] = capsule_mask(self.big, box, (box[3] - box[1]) // 2).crop(box)
        self._light_ops(ops, (x1 - x0, y1 - y0), "processing", t, 0.3, (x0 - rx, y0 - ry),
                        (self.cache["mask", "proc"], x0 - rx, y0 - ry), period=1.4)
        for i in range(3):
            ph = t * 6.0 - i * 0.9
            dy = -abs(math.sin(ph)) * self._u(6)
            orb_ops(ops, (x0 + x1) // 2 + (i - 1) * self._u(18) - rx, cy + self._u(2) + dy - ry, self._u(5.5),
                    ((255, 255, 255), (120, 210, 255)))
        ops.append(("over", patch_over, 0, 0, 1.0, None))
        return Scene(self.size, still, ((rx, ry, rx1, ry1), ops))
    wide = state != "recording"
    w = 258 if wide else 184
    glow = (170, 120, 255) if state == "command" else (90, 230, 255)
    orb_r = self._u(9)
    half = int(orb_r * 3.8)
    tint = dict(top=VIOLET[0], bottom=VIOLET[1]) if state == "command" else {}
    live = self._live(("rec", state), w, 42,
                      lambda b: max(SS * 2, half - self._u(22), half - (b[3] - b[1]) // 2) + SS, glow=glow, **tint)
    (rx, ry, rx1, ry1), patch_base, patch_over, still, box = live
    x0, y0, x1, y1 = box
    cy = (y0 + y1) // 2
    orb_x = x0 + self._u(22)
    self.frame_box = box
    lv = levels[-1] if levels else 0.0
    self.bubbles.step(box, lv, dt)
    ops.append(("paste", patch_base, None, 0, 0))
    mkey = ("mask", state)
    if mkey not in self.cache:
        self.cache[mkey] = capsule_mask(self.big, box, (box[3] - box[1]) // 2).crop(box)
    mask = (self.cache[mkey], x0 - rx, y0 - ry)
    self._light_ops(ops, (x1 - x0, y1 - y0), state, t, lv, (x0 - rx, y0 - ry), mask)
    for bx, by, br, _vy, _p in self.bubbles.items:
        ops.append(("circle", bx - rx, by - ry, br, (255, 255, 255, 35), (255, 255, 255, 170),
                    max(1, SS // 2 + 1), mask))
        ops.append(("circle", bx - rx - br * 0.25, by - ry - br * 0.4, br * 0.2, (255, 255, 255, 220), None, 0, mask))
    pulse = 0.5 + 0.5 * math.sin(t * 6.67)
    orb_ops(ops, orb_x - rx, cy - ry, orb_r, ORB["command" if state == "command" else "recording"], pulse)
    self._bar_ops(ops, box, list(levels), phase, (x0 - rx, y0 - ry))
    if wide:
        tag = "Command" if state == "command" else "Hands-free"
        tx = x0 + self._u(42) + BARS * self._u(7) + self._u(6)
        self._text(tag, self.small, "light", tx, cy, "lm")
        sx = x1 - self._u(22) - rx
        orb_ops(ops, sx, cy - ry, self._u(8), ((255, 255, 255), (150, 200, 230)))
        sq = self._u(3.2)
        ops.append(("rrect", (sx - sq, cy - ry - sq, sx + sq, cy - ry + sq), SS, (20, 90, 150, 230), "paste"))
    ops.append(("over", patch_over, 0, 0, 1.0, None))
    top = []
    if caption and caption_alpha > 0:
        self._caption_ops(top, caption, y0, min(caption_alpha, 1.0))
    self._text_ops(top)
    return Scene(self.size, still, ((rx, ry, rx1, ry1), ops), top)


def _light_ops(self, ops, size, state, t, level, at, mask, period=2.4):
    """_light(), as a drawing step (the light sprite with its brightness as alpha)."""
    w, h = size
    key = ("light", state, w, h)
    if key not in self.cache:
        self._light(Image.new("RGBA", (w, h), (0, 0, 0, 0)), state, t, level, period)   # builds the sprite
    sp = self.cache[key]
    k = min(1.0, 0.4 + 0.75 * level)
    drift = 0.5 - 0.5 * math.cos(2 * math.pi * t / period)
    cx = w * (0.18 + 0.56 * drift + 0.06 * level)
    ops.append(("over", sp, at[0] + int(cx - sp.size[0] / 2), at[1] + int(h * 0.72 - sp.size[1] / 2), k, mask))


def _bar_ops(self, ops, box, levels, phase, at):
    """_bars(), as rounded-rectangle steps."""
    x0, y0, x1, y1 = box
    cy = (y1 - y0) / 2
    slot, half, r = self._u(7), self._u(1.6), self._u(1.6)
    bx = self._u(42)
    n = len(levels)
    for i, v in enumerate(levels):
        pos = (BARS - 1) - (n - 1 - i) + (1 - phase)
        if pos >= BARS or pos <= -1:
            continue
        a = 1.0 if 0 <= pos <= BARS - 1 else (BARS - pos if pos > BARS - 1 else 1 + pos)
        hh = self._u(3 + v * 22)
        x = at[0] + bx + pos * slot
        top = at[1] + cy - hh / 2
        ops.append(("rrect", (x - half, top + self._u(1), x + half, top + hh + self._u(1)), r,
                    (0, 70, 130, int(70 * a)), "over"))
        ops.append(("rrect", (x - half, top, x + half, top + hh), r, (255, 255, 255, int(245 * a)), "over"))


def _caption_ops(self, top, text, above_y, alpha=1.0):
    """_caption(), as drawing steps at final size."""
    maxw = (self.W - 40) * self.scale
    words = (text or "").split()
    shown = shape_for_display(" ".join(words), self.small)
    while words and (not shown or self.small.getlength(shown) > maxw):
        words = words[1:]
        shown = shape_for_display("\u2026 " + " ".join(words), self.small)
    if not words or not shown:
        return
    tw = self.small.getlength(shown) / self.scale
    w = min(self.W - 16, int(tw / 32 + 1) * 32 + 24)
    box, bubble, pos = self._cap_img(w, 24, above_y)
    top.append(("over", bubble, pos[0], pos[1], alpha, None))
    self._text(shown, self.small, "dark", (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, "mm", alpha)


def _text_ops(self, top):
    """_finish(), as drawing steps: each line of words is a cached sprite."""
    for text, font, style, x, y, anchor, alpha in self.texts:
        key = (text, font.size, style, anchor)
        if key not in self.text_cache:
            if len(self.text_cache) > 64:
                self.text_cache.pop(next(iter(self.text_cache)))
            self.text_cache[key] = text_sprite(text, font, style, anchor)
        sp, (dx, dy) = self.text_cache[key]
        top.append(("over", sp, int(round(x / SS)) + dx, int(round(y / SS)) + dy, alpha, None))
    self.texts = []


FlowBarRenderer.scene = _scene
FlowBarRenderer._light_ops = _light_ops
FlowBarRenderer._bar_ops = _bar_ops
FlowBarRenderer._caption_ops = _caption_ops
FlowBarRenderer._text_ops = _text_ops


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
    try:
        return img.tobytes("raw", "BGRa")   # Pillow premultiplies while packing: ~6x quicker than numpy
    except (ValueError, KeyError, OSError):
        pass
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
