"""The Flow bar, drawn on the graphics card.

aero.FlowBarRenderer draws the bar's pieces once (glass, orbs, words, the caption bubble) and, every frame, lists
where they go (a Scene). This module keeps those pieces on the graphics card and puts each frame together there:
blending, the moving light, the waveform bars and bubbles, the pulse, cross-fades and the slide. The processor only
copies the finished frame to the screen, through the same see-through window the bar has always used.

Needs moderngl (OpenGL 3.3, which every Windows graphics card of the last ten years has). If anything is missing or
the first frame doesn't match the Pillow drawing, the bar keeps drawing with Pillow.
"""
import logging
from collections import OrderedDict

from PIL import Image

from .aero import SS

log = logging.getLogger("aqualite")

ONE, ONE_MINUS_SRC1_ALPHA = 1, 0x88FB   # GL constants: dual-source blending (core since OpenGL 3.3)

VERT = """
#version 330
in vec2 corner;
uniform vec4 rect;      // x, y, w, h in canvas pixels (top-left origin)
uniform vec2 canvas;
out vec2 px;
void main() {
    px = rect.xy + corner * rect.zw;
    gl_Position = vec4(px.x / canvas.x * 2.0 - 1.0, 1.0 - px.y / canvas.y * 2.0, 0.0, 1.0);
}
"""

# Every program writes two colours: c0 is added, and the destination is kept by (1 - c1.a). c1 = c0.a is normal
# premultiplied blending; c1 = coverage writes the source over the destination (how Pillow's paste works).
OUT = """
layout(location = 0, index = 0) out vec4 c0;
layout(location = 0, index = 1) out vec4 c1;
uniform sampler2D mask;
uniform int use_mask;
uniform vec4 mask_rect;
float mask_at(vec2 px) {
    if (use_mask == 0) return 1.0;
    vec2 mp = floor(px) - mask_rect.xy;
    if (mp.x < 0.0 || mp.y < 0.0 || mp.x >= mask_rect.z || mp.y >= mask_rect.w) return 0.0;
    return texelFetch(mask, ivec2(mp), 0).r;
}
"""

SPRITE = """
#version 330
in vec2 px;
uniform vec4 rect;
uniform sampler2D tex;      // premultiplied RGBA, top row first
uniform sampler2D cov;
uniform float alpha;
uniform int mode;           // 0 blend, 1 write where cov says, 2 write
""" + OUT + """
void main() {
    ivec2 ip = ivec2(floor(px - rect.xy));
    vec4 c = texelFetch(tex, ip, 0) * alpha * mask_at(px);
    if (mode == 0) { c0 = c; c1 = vec4(c.a); }
    else if (mode == 1) { float k = texelFetch(cov, ip, 0).r; c0 = c * k; c1 = vec4(k); }
    else { c0 = c; c1 = vec4(1.0); }
}
"""

# rounded rectangles and circles, many per draw call: one instance each
SHAPE_VERT = """
#version 330
in vec2 corner;
in vec4 i_box;          // x0, y0, x1, y1 as Pillow takes them (x1, y1 inclusive)
in vec4 i_fill;         // straight RGBA 0..1
in vec4 i_outline;
in vec4 i_misc;         // radius, outline width, kind (0 rounded rectangle, 1 circle), mode (0 blend, 1 write)
uniform vec2 canvas;
out vec2 px;
flat out vec4 box;
flat out vec4 fill;
flat out vec4 outline;
flat out vec4 misc;
void main() {
    vec2 a = i_box.xy - 2.0, b = i_box.zw + 3.0;
    px = a + corner * (b - a);
    box = i_box; fill = i_fill; outline = i_outline; misc = i_misc;
    gl_Position = vec4(px.x / canvas.x * 2.0 - 1.0, 1.0 - px.y / canvas.y * 2.0, 0.0, 1.0);
}
"""

SHAPE = """
#version 330
in vec2 px;
flat in vec4 box;
flat in vec4 fill;
flat in vec4 outline;
flat in vec4 misc;
""" + OUT + """
float rbox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
void main() {
    vec2 c = vec2(box.x + box.z + 1.0, box.y + box.w + 1.0) * 0.5;
    vec2 h = vec2(box.z - box.x + 1.0, box.w - box.y + 1.0) * 0.5;
    float d = misc.z < 0.5 ? rbox(px - c, h, min(misc.x, min(h.x, h.y))) : length(px - c) - h.x;
    float inside = clamp(0.5 - d, 0.0, 1.0);
    float m = mask_at(px);
    vec4 col = vec4(fill.rgb * fill.a, fill.a) * inside;
    if (misc.y > 0.0) {
        float ring = inside - clamp(0.5 - (d + misc.y), 0.0, 1.0);
        vec4 o = vec4(outline.rgb * outline.a, outline.a) * ring;
        col = o + col * (1.0 - o.a);
    }
    if (misc.w < 0.5) { col *= m; c0 = col; c1 = vec4(col.a); }
    else { float k = inside * m; c0 = vec4(fill.rgb * fill.a, fill.a) * k; c1 = vec4(k); }
}
"""

# the moving part is drawn at 2x; shrink it the way Pillow's reduce() does (average the straight colours)
SHRINK = """
#version 330
in vec2 px;
uniform vec4 rect;
uniform sampler2D src;      // a 2x canvas (bottom row first, as rendered)
uniform int src_h;
""" + OUT + """
void main() {
    ivec2 ip = ivec2(floor(px - rect.xy)) * 2;
    vec4 rgb = vec4(0.0);
    float a = 0.0;
    for (int dy = 0; dy < 2; dy++) for (int dx = 0; dx < 2; dx++) {
        vec4 t = texelFetch(src, ivec2(ip.x + dx, src_h - 1 - (ip.y + dy)), 0);
        if (t.a > 0.0) rgb += vec4(t.rgb / t.a, 0.0);
        a += t.a;
    }
    a *= 0.25;
    vec3 straight = rgb.rgb * 0.25;
    c0 = vec4(straight * a, a);
    c1 = vec4(1.0);
}
"""

# cross-fade (premultiplied, like aero.crossfade) into the 'last frame' canvas
FADE = """
#version 330
in vec2 px;
uniform sampler2D cur;
uniform sampler2D prev;
uniform float t;
""" + OUT + """
void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy);   // same row order in, same out
    c0 = mix(texelFetch(prev, ip, 0), texelFetch(cur, ip, 0), t);
    c1 = vec4(1.0);
}
"""

# slide down by `offset` rows and pack as premultiplied BGRA, top row first (what UpdateLayeredWindow takes)
PACK = """
#version 330
uniform sampler2D src;      // bottom row first
uniform int h;
uniform int offset;
""" + OUT + """
void main() {
    int x = int(gl_FragCoord.x), y = int(gl_FragCoord.y) - offset;   // y counts from the top here
    vec4 c = y >= 0 ? texelFetch(src, ivec2(x, h - 1 - y), 0) : vec4(0.0);
    c0 = c.bgra;
    c1 = vec4(1.0);
}
"""


# Liquid Glass while it moves (liquid.py): the glass drawn straight from its shape - one or two pills (the bar and
# its caption bubble) joined with a smooth union, so they melt together as the bubble grows out of the bar. Same
# layers as liquid.glass_shape: layer 0 = shadow and body (under the contents), layer 1 = shine, rim and fringe.
LGLASS = """
#version 330
in vec2 px;
uniform vec4 A;             // centre x, centre y, half width, half height (canvas pixels)
uniform vec4 B;             // the second pill (the bubble), used when b_on > 0.5
uniform float b_on;
uniform float k;            // how far apart the pills start to melt together
uniform int layer;
uniform vec4 body_top;      // straight RGBA 0..1
uniform vec4 body_bot;
uniform vec4 tint;
uniform vec4 edge;
uniform vec4 core;
uniform float rim;
uniform float shine;
uniform float shadow;
uniform float fringe;
uniform float band;
uniform float rw;
uniform float u;
uniform float sh_dy;
uniform float sh_sigma;
""" + OUT + """
float pill(vec2 p, vec4 s) {
    vec2 q = abs(p - s.xy) - s.zw + s.w;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - s.w;
}
float smin(float a, float b, float r) {
    float h = clamp(0.5 + 0.5 * (b - a) / r, 0.0, 1.0);
    return mix(b, a, h) - r * h * (1.0 - h);
}
float sdf(vec2 p) {
    float d = pill(p, A);
    if (b_on > 0.5) d = smin(d, pill(p, B), k);
    return d;
}
float cover(float d) { return clamp(0.5 - d, 0.0, 1.0); }
float soft(float d, float w) { return smoothstep(-w, w, d); }      // 0 well inside .. 1 well outside
vec4 pm(vec3 c, float a) { return vec4(c * a, a); }
vec4 over(vec4 top, vec4 bot) { return top + bot * (1.0 - top.a); }
void main() {
    vec2 p = px;
    float d = sdf(p);
    vec4 s = (b_on > 0.5 && pill(p, B) < pill(p, A)) ? B : A;
    vec2 lo = clamp((p - (s.xy - s.zw)) / max(2.0 * s.zw, vec2(1.0)), 0.0, 1.0);   // 0..1 across this pill
    vec4 col;
    if (layer == 0) {
        col = pm(vec3(0.0), shadow * (1.0 - soft(sdf(p - vec2(0.0, sh_dy)), 2.0 * sh_sigma)));
        vec4 body = mix(body_top, body_bot, lo.y);
        vec4 b = over(pm(tint.rgb, tint.a), pm(body.rgb, body.a));
        float e = clamp(soft(d + band, band) - soft(d, band), 0.0, 1.0);
        b = over(pm(edge.rgb, edge.a * e), b);
        b = over(pm(core.rgb, core.a * (1.0 - soft(d + band, 1.2 * band))), b);
        col = over(b * cover(d), col);
    } else {
        col = pm(vec3(1.0), shine * clamp(1.0 - lo.y / 0.42, 0.0, 1.0) * cover(d + u));
        float ring = cover(d) - cover(d + rw);
        col = over(pm(vec3(1.0), ring * (1.0 - 0.75 * (0.75 * lo.y + 0.25 * lo.x)) * rim), col);
        float ends = clamp((abs(p.x - s.x) - max(1.0, s.z - s.w)) / max(s.w, 1.0), 0.0, 1.0);
        col = over(pm(vec3(1.0, 0.353, 0.353), fringe * (cover(d - u) - cover(d)) * ends), col);
        col = over(pm(vec3(0.353, 0.549, 1.0), fringe * (cover(d + rw) - cover(d + rw + u)) * ends), col);
    }
    c0 = col * mask_at(px);
    c1 = vec4(c0.a);
}
"""


def _set(prog, **values):
    """Set uniforms; ones a shader doesn't use are compiled away, so skip those."""
    for name, v in values.items():
        if name in prog:
            prog[name].value = v


class GLBar:
    """Puts Flow bar frames together on the graphics card. frame(scene, fade, offset) -> premultiplied BGRA bytes."""

    MAX_TEXTURES = 160

    def __init__(self, size, ctx=None):
        import moderngl
        self.mgl = moderngl
        self.ctx = ctx or moderngl.create_standalone_context(require=330)
        self.w, self.h = size
        c = self.ctx
        self.progs = {name: c.program(vertex_shader=VERT, fragment_shader=src)
                      for name, src in (("sprite", SPRITE), ("shrink", SHRINK), ("fade", FADE), ("pack", PACK))}
        self.progs["shape"] = c.program(vertex_shader=SHAPE_VERT, fragment_shader=SHAPE)
        import struct
        quad = c.buffer(struct.pack("8f", 0, 0, 1, 0, 0, 1, 1, 1))
        self.quad = quad
        self.vaos = {name: c.vertex_array(p, [(quad, "2f", "corner")]) for name, p in self.progs.items()
                     if name != "shape"}
        self.shape_cap = 256
        self.shape_buf = c.buffer(reserve=self.shape_cap * 16 * 4, dynamic=True)
        self.vaos["shape"] = c.vertex_array(self.progs["shape"], [
            (quad, "2f", "corner"), (self.shape_buf, "4f 4f 4f 4f/i", "i_box", "i_fill", "i_outline", "i_misc")])
        self.textures = OrderedDict()        # id(image) -> (texture, image): each piece uploaded once
        self.blank = c.texture((1, 1), 1, b"\xff")
        self.patch_fbos = {}
        self.cur = self._canvas(size)        # this frame
        self.last = self._canvas(size)       # the last frame shown, after any cross-fade (before the slide)
        self.prev = self._canvas(size)       # what a cross-fade fades from
        self.out = c.framebuffer(color_attachments=[c.texture(size, 4)])
        c.enable(moderngl.BLEND)
        c.blend_func = ONE, ONE_MINUS_SRC1_ALPHA
        self.frames = 0

    def _canvas(self, size):
        tex = self.ctx.texture(size, 4, dtype="f4")
        tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        return self.ctx.framebuffer(color_attachments=[tex])

    # ------------------------------------------------------------ pieces
    def _tex(self, img):
        key = id(img)
        hit = self.textures.get(key)
        if hit is not None:
            self.textures.move_to_end(key)
            return hit[0]
        if img.mode == "L":
            tex = self.ctx.texture(img.size, 1, img.tobytes())
        else:
            tex = self.ctx.texture(img.size, 4, img.convert("RGBA").convert("RGBa").tobytes())
        tex.filter = (self.mgl.NEAREST, self.mgl.NEAREST)
        self.textures[key] = (tex, img)    # holding the image keeps its id from being reused
        while len(self.textures) > self.MAX_TEXTURES:
            _k, (old, _img) = self.textures.popitem(last=False)
            old.release()
        return tex

    def _mask(self, prog, mask):
        if mask is None:
            prog["use_mask"].value = 0
            self.blank.use(2)
            return
        img, mx, my = mask
        self._tex(img).use(2)
        prog["use_mask"].value = 1
        prog["mask_rect"].value = (mx, my, img.size[0], img.size[1])

    def _ops(self, ops, canvas):
        sp, sh = self.progs["sprite"], self.progs["shape"]
        _set(sp, canvas=canvas, mask=2, tex=0, cov=1)
        _set(sh, canvas=canvas, mask=2)
        batch, batch_mask = [], None
        for op in ops:
            kind = op[0]
            if kind in ("rrect", "circle"):
                if kind == "rrect":
                    _k, (x0, y0, x1, y1), radius, rgba, mode = op
                    row = (x0, y0, x1, y1, *rgba, 0, 0, 0, 0, radius, 0.0, 0.0, 0.0 if mode == "over" else 1.0)
                    mask = None
                else:
                    _k, cx, cy, r, rgba, outline, width, mask = op
                    row = (cx - r, cy - r, cx + r, cy + r, *rgba, *(outline or (0, 0, 0, 0)), r, float(width or 0),
                           1.0, 0.0)
                if batch and mask is not batch_mask:
                    self._shapes(batch, batch_mask)
                    batch = []
                batch.append(row)
                batch_mask = mask
                continue
            if batch:
                self._shapes(batch, batch_mask)
                batch = []
            if kind == "lglass":
                self._lglass(op, canvas)
                continue
            if kind == "over":
                _k, img, x, y, alpha, mask = op
                cov, mode = None, 0
            else:
                _k, img, cov, x, y = op
                alpha, mask, mode = 1.0, None, (1 if cov is not None else 2)
            self._tex(img).use(0)
            (self._tex(cov) if cov is not None else self.blank).use(1)
            self._mask(sp, mask)
            _set(sp, rect=(int(x), int(y), img.size[0], img.size[1]), alpha=float(alpha), mode=mode)
            self.vaos["sprite"].render(self.mgl.TRIANGLE_STRIP)
        if batch:
            self._shapes(batch, batch_mask)

    def _shapes(self, rows, mask):
        """Draw many rounded rectangles / circles in one call. Colours in rows are 0-255; scaled here."""
        import numpy as np
        a = np.asarray(rows, dtype="f4")
        a[:, 4:12] /= 255.0
        if len(a) > self.shape_cap:
            self.shape_cap = 1 << (len(a) - 1).bit_length()
            self.shape_buf.orphan(self.shape_cap * 16 * 4)
        self.shape_buf.write(a.tobytes())
        self._mask(self.progs["shape"], mask)
        self.vaos["shape"].render(self.mgl.TRIANGLE_STRIP, instances=len(a))

    def _lglass(self, op, canvas):
        """Liquid Glass drawn from its shape: ("lglass", layer, (pill_a, pill_b or None), params)."""
        _k, layer, (a, b), params = op
        if "lglass" not in self.progs:   # built on first use, so Frutiger Aero never depends on it
            self.progs["lglass"] = self.ctx.program(vertex_shader=VERT, fragment_shader=LGLASS)
            self.vaos["lglass"] = self.ctx.vertex_array(self.progs["lglass"], [(self.quad, "2f", "corner")])
        prog = self.progs["lglass"]
        self._mask(prog, None)
        _set(prog, mask=2, canvas=canvas, rect=(0, 0) + tuple(canvas), layer=1 if layer == "over" else 0,
             A=tuple(float(v) for v in a), B=tuple(float(v) for v in (b or (0, 0, 1, 1))), b_on=1.0 if b else 0.0,
             **{n: (tuple(float(x) for x in v) if isinstance(v, tuple) else float(v)) for n, v in params.items()})
        self.vaos["lglass"].render(self.mgl.TRIANGLE_STRIP)

    def _full(self, name, canvas):
        _set(self.progs[name], rect=(0, 0) + canvas, canvas=canvas)
        self.vaos[name].render(self.mgl.TRIANGLE_STRIP)

    # ------------------------------------------------------------ frames
    def frame(self, scene, fade=None, offset=0):
        """Draw `scene`; fade (0..1): how far a cross-fade from the frame kept by start_fade() has got (None = no
        fade); offset: rows the bar has slid down (anything below the window is cut). Returns the window's
        pixels as premultiplied BGRA, top row first."""
        size = (self.w, self.h)
        if scene.patch is not None:
            (rx, ry, rx1, ry1), ops = scene.patch
            psize = (rx1 - rx, ry1 - ry)
            fbo = self.patch_fbos.get(psize)
            if fbo is None:
                fbo = self.patch_fbos[psize] = self._canvas(psize)
            fbo.use()
            fbo.clear(0, 0, 0, 0)
            self._ops(ops, psize)
        self.cur.use()
        self.cur.clear(0, 0, 0, 0)
        self._ops([("paste", scene.base, None, 0, 0)], size)
        if scene.patch is not None:
            sk = self.progs["shrink"]
            fbo.color_attachments[0].use(3)
            _set(sk, src=3, src_h=psize[1], canvas=size, rect=(rx // SS, ry // SS, psize[0] // SS, psize[1] // SS))
            self.vaos["shrink"].render(self.mgl.TRIANGLE_STRIP)
        if scene.top:
            self._ops(scene.top, size)
        if fade is not None and fade < 1:
            self.last.use()
            fp = self.progs["fade"]
            self.cur.color_attachments[0].use(4)
            self.prev.color_attachments[0].use(5)
            _set(fp, cur=4, prev=5, t=float(max(0.0, fade)))
            self._full("fade", size)
        else:
            self.cur, self.last = self.last, self.cur   # this frame becomes the last one
        self.out.use()
        pk = self.progs["pack"]
        self.last.color_attachments[0].use(6)
        _set(pk, src=6, h=self.h, offset=int(offset))
        self._full("pack", size)
        self.frames += 1
        return self.out.read(components=4)

    def start_fade(self):
        """Keep the last frame shown, to cross-fade from (the bar is changing state)."""
        self.ctx.copy_framebuffer(self.prev, self.last)

    def close(self):
        try:
            self.ctx.release()
        except Exception:
            pass


def to_image(bgra, size):
    """Premultiplied BGRA bytes back to a Pillow RGBA image (for checks)."""
    return Image.frombytes("RGBA", size, bgra, "raw", "BGRa")


def difference(a, b):
    """Average difference per channel (0-255) between two RGBA images, as they'd look: colours weighted by how
    opaque they are, so invisible pixels don't count."""
    import numpy as np
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    pa = np.concatenate([a[..., :3] * a[..., 3:] / 255, a[..., 3:]], axis=2)
    pb = np.concatenate([b[..., :3] * b[..., 3:] / 255, b[..., 3:]], axis=2)
    vis = (a[..., 3] > 0) | (b[..., 3] > 0)
    return float(np.abs(pa - pb)[vis].mean()) if vis.any() else 0.0


def check(gl, renderer):
    """Draw the resting bar both ways and compare. Returns the average difference per channel (0-255)."""
    want = renderer.render("idle")
    return difference(want, to_image(gl.frame(renderer.scene("idle")), renderer.size))
