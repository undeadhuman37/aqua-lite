---
name: liquid-glass
description: Build or change Aqua Lite's optional Liquid Glass theme (Apple-style clear glass that bends what's behind it, bright rim, soft shadow, faint rainbow fringe, shape-morphing) in this codebase's Tk/ttk Settings, Pillow drawing (skin.py, aero.py) and moderngl Flow bar (glbar.py). Use for any Liquid Glass, glass theme, light/dark theme, refraction, lens shader or Flow bar morphing work. Liquid Glass sits alongside Frutiger Aero and never replaces it.
---

# Liquid Glass theme for Aqua Lite

Liquid Glass is a **second, optional look**. Frutiger Aero stays the default and stays exactly as it is. Read
`CLAUDE.md` first: its rules (work on `main`, no personal details, never touch `%APPDATA%\AquaLite`, install only when
the owner says so, self-test must pass) apply here too.

For deeper background, load the `liquid-glass-design` skill (Apple's rules for the material) and the `shader-dev`
skill (read `techniques/sdf-2d.md`, `techniques/anti-aliasing.md` and the chromatic aberration part of
`techniques/post-processing.md`). Those skills target SwiftUI and WebGL; this file turns them into Python, Pillow
and moderngl for this app.

## 1. What the look is

| Part | What it looks like | Notes |
|---|---|---|
| Clear body | Almost colourless. Whatever is behind it shows through, slightly blurred, slightly brightened | Not Aero's sky-blue gradient, and no hard gloss line across the middle |
| Lens edge | Near the rim, what's behind bends outwards, as if seen through the thick rounded edge of a glass lump | Bending only in a band about 0.25 to 0.35 of the shape's height. The middle stays undistorted |
| Rim highlight | A thin, bright line along the edge, brightest at the top-left (light from above) and fading round to the bottom | 1 to 1.5 px at 1x. White at about 0.7 alpha in light mode, 0.45 in dark |
| Inner shine | A very soft white wash in the top third | Much fainter than Aero's gloss (alpha 0.10 to 0.18) |
| Soft shadow | Wide, low, blurred, offset down a little | Blur about 0.35 of the height, alpha about 0.18 light, 0.35 dark. Neutral grey-black, not Aero's navy |
| Rainbow fringe | Faint red outside and blue inside, only where the edge bends most | Barely visible. If you notice it at a glance, it's too strong |
| Morphing | The shape flows between states (dot, pill, wider pill, small bubble) instead of jumping or cross-fading | Spring easing; neighbours melt together (smooth union) |
| Tint | Optional faint colour for meaning only: lime while listening, violet in Command Mode | Tint the glass at 0.08 to 0.15 alpha; never a solid colour |

Apple's rules that carry over (from `liquid-glass-design`):

- Glass is for controls and floating pieces (the Flow bar, sidebar, buttons, toggles), not for every surface. Page
  content sits on a plain surface underneath.
- Don't stack glass on glass. One layer of glass over content; things on the glass are plain (text, icons, bars).
- Neighbouring glass pieces belong to one group and merge when close (Apple's `GlassEffectContainer` spacing). In
  the Flow bar the caption bubble and the bar are one group.
- Only things you can press react to the pointer (`.interactive()`): buttons, toggles, the bar's stop button.
- Test light, dark and "transparency off" every time.

## 2. Where things live

Liquid Glass gets its own modules. **Do not change Aero's colours, functions or drawing to make room for it.**

| Aero file | Liquid Glass counterpart | What it holds |
|---|---|---|
| `skin.py` | `liquidskin.py` (new) | Settings controls. Same function names and arguments as `skin.py` (`button`, `toggle`, `radio`, `field`, `arrow`, `progress_trough`, `progress_bar`, `scale_trough`, `slider`, `thumb`, `card`, `sidebar`, `nav_pill`, `icon`, `pill`, `keycap`) and the same module-level colour names (`INK`, `MUTED`, `PAGE`, `CARD`, ...) so `ui.py` can take either module |
| `aero.py` (`FlowBarRenderer`, `glass_capsule`, `text_sprite`) | `liquid.py` (new) | `LiquidBarRenderer`: same public methods as `FlowBarRenderer` (`render`, `scene`, `set_frost`, `blur_shape`, `warm_steps`, `size`, `big`, `frame_box`). Reuse `aero.Scene`, `aero.SS`, `aero._font_px`, `aero.shape_for_display`, `aero.crossfade`, `aero.premultiplied_bgra` by importing them; don't copy them |
| `glbar.py` | `glbar.py` (add to it) | New programs (`lens`, `morph`) next to the existing ones. The existing programs and `check()` stay as they are |
| `winapi.Frost` | `winapi.Frost` (small change) | Take the tint as an argument: `Frost(tint=Frost.TINT)`. Aero keeps today's sky-blue wash; Liquid Glass passes a neutral one (see section 6) |
| `ui.apply_aero_style` | `ui.apply_liquid_style` (new) | Builds the ttk theme from `liquidskin`; element names prefixed `Liquid` instead of `Aero` |

**`gpu.py` is not graphics.** It's the NVIDIA speech engine for instant text (Whisper on CUDA). Nothing in this
theme touches it. All Flow bar graphics-card work goes in `glbar.py`.

Settings (in `config.py` defaults):

```python
"look": "aero",          # aero | liquid  - Frutiger Aero stays the default
"look_mode": "system",   # system | light | dark  - only used by Liquid Glass (Aero has one version)
```

Settings page label: "Look", choices "Frutiger Aero" and "Liquid Glass", then "Light", "Dark", "Match Windows".
Sentence case, no periods. Switching look rebuilds the Settings theme and the Flow bar renderer; it needs no
restart. Old settings files without these keys must still load as Aero.

Wiring: `overlay.FlowBar` picks the renderer class from `look` (one line: `aero.FlowBarRenderer` or
`liquid.LiquidBarRenderer`). Everything else in `overlay.py` (layered window, Frost placement, `set_gpu`, the slide,
cross-fades) works through the shared method names and must not need to know which look is on.

## 3. The honest limit: what can be bent

The Flow bar is a layered window. **The app cannot see the desktop behind it**, and must not try:

- No screen capture (BitBlt of the desktop, DXGI desktop duplication, `ImageGrab`) to feed refraction. It costs
  every frame, and for a dictation app reading the screen all the time is a privacy problem. Screen context
  (`context.py`) is a separate, opt-in feature; the theme must never piggyback on it.
- What's behind the bar is handled by Windows: `winapi.Frost` asks the compositor to blur it. That blur is the
  "clear body". The app never reads it.
- Refraction bends only **what the app draws itself**: inside the bar, the drifting light, the waveform, the caption
  text near the rim; in Settings, the app's own page backdrop.

So the lens effect is real for the app's own content and faked convincingly at the edge (rim highlight, fringe,
brighter band) for the desktop part. Don't promise more than that in the README or changelog.

## 4. Pillow drawing (Settings and the fallback Flow bar)

Follow the patterns already in `skin.py` and `aero.py`:

- Draw oversampled (`K = 4` in skin, `SS = 2` in aero) and shrink with LANCZOS / `reduce`.
- **Settings pieces are drawn solid on their surface with wide 9-slice middles** (`ui._flat`, `ui._grow`). See-through
  or tiny-middle images made Settings unusably slow on Windows; this applies to Liquid Glass even more, because it
  is tempting to make everything see-through. Every `liquidskin` piece gets a version per surface it sits on
  (like `SURFACES` in `ui.py`), drawn as if the glass were over that surface.
- Draw once per size and colour and cache (`_SPRITES`, `self.cache`). Never compute a blur or a displacement per
  frame in Pillow.

### Glass recipe in Pillow (`liquid.glass_shape`, counterpart of `aero.glass_capsule`)

Return `(base, over)` like `glass_capsule` does, so the static/moving split (`_live`, `_flat`, `_compose`) carries
over unchanged:

1. **Shadow** (base): the shape's mask, offset down by 0.06 of its height, `GaussianBlur(0.35 * h)`, neutral
   `(0, 0, 0)` at the mode's shadow alpha.
2. **Body** (base): in frosted mode, a near-clear fill: light `(255, 255, 255, 40..60)`, dark `(28, 30, 36, 90..120)`,
   plus the state tint at 0.08 to 0.15. Without frost (no blur behind), a solid fill that looks like frosted glass:
   light `(242, 245, 250)` to `(228, 233, 241)`, dark `(44, 47, 56)` to `(30, 32, 39)`.
3. **Edge band** (base): brighten the outer 0.3 of the shape slightly (a mask that is the shape minus the shape
   eroded by the band width, blurred, white at 0.10). This is what reads as "thick glass" where nothing is bent.
4. **Inner shine** (over): white, top third, alpha from 0.18 at the top to 0, clipped to the shape inset by 1 px.
5. **Rim highlight** (over): a 1 px (at 1x) outline, coloured by angle around the shape: brightest facing up-left,
   fading to about 0.25 of that facing down-right. Build it as an outline mask multiplied by a linear gradient at
   135 degrees.
6. **Fringe** (over): two more 1 px outlines just outside and just inside the rim, `(255, 90, 90)` outside and
   `(90, 140, 255)` inside, alpha at most 0.12 (light) / 0.18 (dark), masked to the left and right ends of a pill
   (where the curve is tightest). Static, so it costs nothing per frame.

Keep the moving content (waveform, light, orbs, text) **inside the inner safe area**: the shape inset by the edge
band. The lens in the shader does nothing there, which is what lets the Pillow and graphics-card drawings agree
(section 5, "Matching").

### Settings (Tk/ttk)

- Tk windows can't be see-through per pixel, so Settings glass is always drawn over the app's own backdrop.
- **Page:** a calm backdrop drawn once per window size (like `skin.sidebar`): light mode a soft off-white with two or
  three very blurred colour blobs (pale sky, pale lilac), dark mode near-black blue-grey with dimmer blobs. Content
  cards sit on it.
- **Sidebar:** the one large, real glass sheet. Because it's drawn per window size, it can refract the page
  backdrop properly: compute the displacement with numpy once per size (same formula as the shader, section 5) and
  remap the backdrop through it. Then rim, shine, fringe as above.
- **Cards:** frosted, not refracting: the backdrop under them blurred and washed (light: white at 0.72; dark:
  `(36, 38, 46)` at 0.78), a 1 px rim highlight, the soft shadow. They're 9-slice ttk elements, so they can't depend
  on where they sit. Draw them over the page's average colour.
- **Controls** on cards (buttons, toggles, fields, sliders): small glass pills drawn on the card colour. Toggle on
  = tinted glass with a clear knob; off = plain glass. The knob is a clear glass bead with a rim highlight, not
  Aero's white marble.
- Keep the existing layout, spacing, sizes and `ui.py` code paths. The theme changes pictures and colours only.
- Title bar: dark mode needs Windows' dark title bar (`DwmSetWindowAttribute`, attribute 20,
  `DWMWA_USE_IMMERSIVE_DARK_MODE`). Check what `winapi.py` already does for the Windows 11 title bar tint and extend
  it there rather than adding a second path.

## 5. The graphics-card Flow bar (`glbar.py`)

Read how `GLBar` works first: pieces are uploaded once, every frame is a `Scene` of ops, the moving patch is drawn
at 2x and shrunk (`SHRINK`), everything uses dual-source premultiplied blending (`c0` added, destination kept by
`1 - c1.a`), and `PACK` writes premultiplied BGRA for `UpdateLayeredWindow`. New programs must use the same `OUT`
block and the same blending, and write premultiplied colour.

### Lens pass (`LENS` program)

Runs on the 2x patch after the moving content is drawn into it and before `SHRINK`. Draw the content into the patch
FBO, then render the lens into a second patch FBO of the same size, reading the first as a texture.

```glsl
#version 330
in vec2 px;
uniform vec4 rect;          // the patch, as for the other programs
uniform sampler2D src;      // the patch with the moving content (bottom row first, as rendered)
uniform int src_h;
uniform vec4 shape;         // centre x, centre y, half width, half height (patch pixels)
uniform float radius;       // corner radius (h for a full pill)
uniform float band;         // width of the bending edge, about 0.3 * half height
uniform float strength;     // how far the edge pulls, in pixels (about 0.6 * band)
uniform float fringe;       // colour split, 0..1 of strength (about 0.08)
// + OUT (mask_at, c0, c1)
float rbox(vec2 p, vec2 b, float r) {       // same function as SHAPE uses
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
vec2 grad(vec2 p, vec2 b, float r) {        // outward direction of the shape at p
    const float e = 0.5;
    return normalize(vec2(rbox(p + vec2(e, 0), b, r) - rbox(p - vec2(e, 0), b, r),
                          rbox(p + vec2(0, e), b, r) - rbox(p - vec2(0, e), b, r)) + 1e-6);
}
vec4 at(vec2 p) {
    ivec2 ip = ivec2(floor(p));
    return texelFetch(src, ivec2(ip.x, src_h - 1 - ip.y), 0);
}
void main() {
    vec2 p = px - rect.xy;
    float d = rbox(p - shape.xy, shape.zw, radius);       // < 0 inside
    float k = clamp(1.0 + d / band, 0.0, 1.0);            // 0 in the middle, 1 at the rim
    k = k * k * (3.0 - 2.0 * k);                          // smooth: no bend in the safe area at all
    vec2 n = grad(p - shape.xy, shape.zw, radius);
    vec2 off = -n * strength * k;                         // sample further in: the edge magnifies outwards
    vec4 c = vec4(at(p + off * (1.0 + fringe)).r, at(p + off).g, at(p + off * (1.0 - fringe)).b, 0.0);
    c.a = at(p + off).a;
    float inside = clamp(0.5 - d, 0.0, 1.0);
    c0 = c * inside;
    c1 = vec4(1.0);                                       // write: this pass replaces the patch
}
```

Rules for it:

- Sample with `texelFetch` and clamp coordinates to the patch, as the existing programs do. Keep the colour split
  small and only where `k` is high; premultiplied colour means splitting r/g/b but taking alpha from the centre
  sample, as above.
- The static fringe and rim come from the Pillow `over` image (section 4), so they're identical on both paths. The
  shader's split only adds to moving content that strays into the band.
- Respect the `shader-dev` budget: no loops beyond a few taps, no noise, no multi-pass blur per frame. The blur is
  Windows' job (Frost).

### Morphing (`MORPH` program)

The shape between two states is drawn on the graphics card from a signed distance, so it can flow:

- Each state has a target shape (centre, half size, radius). Animate those numbers with a critically damped spring
  (about 0.28 s to settle, no overshoot past 4%), driven by the same clock `t` the renderer already gets. Not linear
  tweens.
- Several pieces in one group (bar and caption bubble) are drawn with a smooth union of their distances
  (polynomial `smin`, `k` about 6 px at 1x) so they melt together as they meet and pull apart as they separate.
- The morph draws body, edge band, shine and rim from the distance and its gradient (rim brightness from the angle
  of `n` against the up-left light), so it matches the Pillow pieces closely at rest.
- When the spring settles, switch back to the cached Pillow pieces for the resting state. The morph program only
  draws the in-between frames.
- `blur_shape()` must follow the morphing shape so the Frost window stays under the glass. Re-place Frost at most
  every other frame during a morph and use the union's bounding pill; it's tucked under the rim anyway.

### Matching and fallback

The app already refuses graphics-card drawing unless a test frame matches Pillow (`glbar.check`, `overlay.set_gpu`,
`selftest.check_gpu_bar`, threshold 3). Keep that for Liquid Glass:

- Resting frames (idle, recording with levels, command, processing, toast, caption) must match the Pillow drawing
  within 3, the same as Aero. That works because the lens does nothing in the safe area and the rim/fringe are the
  same cached image on both paths.
- Morph frames have no Pillow equivalent. They're not part of the check.
- Add a `check_liquid_bar()` to `selftest.py` alongside `check_gpu_bar()` (same states, same seeds, same skip when
  there's no OpenGL). **Don't change `check_gpu_bar()`**: it guards Aero.

## 6. Plain fallback when there's no OpenGL

Liquid Glass must look good with no graphics card drawing at all. When moderngl is missing, the test frame fails,
or `GLBar` raises mid-session (`overlay._drop_gl`):

- Draw with `LiquidBarRenderer.render()` (Pillow), exactly like Aero falls back today.
- No live refraction; the static edge band, rim, shine and fringe still make it read as glass.
- State changes cross-fade (`aero.crossfade`) instead of morphing. Keep the fade short (about 0.18 s).
- Log once, in plain words, as the existing code does: `"flow bar: graphics card drawing not available, the
  processor draws: ..."`.
- No Frost (non-Windows, blur refused, `frosted_glass` off): use the solid "looks like frosted glass" body from
  section 4, step 2. Frost's tint for Liquid Glass: light `0x18FFFFFF`, dark `0x40241E1C` (AABBGGRR).
- Windows "Transparency effects" switched off, or a high-contrast theme on: draw solid bodies (no Frost, no
  see-through), keep rim and shadow, drop the fringe. In high contrast, use the system colours for text.
- Windows "Animation effects" off: no morph and no spring, cross-fade only.

## 7. Readable text (this decides whether the theme ships)

Clear glass over an unknown background is the hardest case: a white app behind the bar, then a black one. Rules:

- **Never put words straight on clear glass.** Words in the Flow bar get the legibility layer: a soft
  pill-shaped wash under the text inside the glass (light mode white at 0.55, dark mode `(20, 22, 28)` at 0.6,
  blurred edge), plus the text's own halo from `text_sprite`.
- Add Liquid styles to the text styles rather than changing Aero's (`aero.TEXT_STYLES["light"]` and `["dark"]` stay):
  - `"liquid_light"` (light mode): ink `(20, 22, 28)`, halo `(255, 255, 255, 200)`, offset `(0, 0)`, blur 1.2.
  - `"liquid_dark"` (dark mode): ink `(245, 247, 250)`, halo `(0, 0, 0, 190)`, offset `(0, 0)`, blur 1.2.
- **Contrast check in the self-test:** composite each text style with its legibility layer and glass body over pure
  white and over pure black, and measure contrast between ink and the pixel under it. It must be at least 4.5:1
  for caption and toast text, 3:1 for icons and the waveform, in both modes. Fail the self-test otherwise.
- Settings text sits on cards (frosted, near solid), never on the sidebar glass without a pill behind it. Muted text
  in dark mode: `(170, 176, 188)` or lighter.
- The waveform bars are plain (white in dark mode, `(30, 34, 42)` in light mode) with a faint opposite-colour shadow,
  like Aero's `_bars` shadow.
- The refraction band never reaches text: keep text in the safe area. Bent words are unreadable.
- Arabic/Hebrew still go through `aero.shape_for_display`.

## 8. Light and dark

| | Light | Dark |
|---|---|---|
| Frosted body | white 40..60 alpha | `(28, 30, 36)` 90..120 alpha |
| Solid body | `(242, 245, 250)` -> `(228, 233, 241)` | `(44, 47, 56)` -> `(30, 32, 39)` |
| Rim highlight | white 0.7 | white 0.45 |
| Inner shine | white 0.18 -> 0 | white 0.10 -> 0 |
| Shadow | black 0.18 | black 0.35 |
| Fringe | max 0.12 | max 0.18 |
| Ink | `(20, 22, 28)` | `(245, 247, 250)` |
| Accent (focus, selected) | `(0, 122, 255)` | `(10, 132, 255)` |
| Listening tint | lime `(80, 200, 60)` at 0.12 | lime `(110, 230, 90)` at 0.15 |
| Command tint | violet `(140, 80, 230)` at 0.12 | violet `(170, 120, 255)` at 0.15 |

- "Match Windows" reads `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme`, the
  Windows-only part, in `winapi.py`; elsewhere it's light. Re-check when Windows sends `WM_SETTINGCHANGE` with
  `"ImmersiveColorSet"` and rebuild only if the answer changed.
- A mode change clears the renderer caches (like `set_frost` does) and the GL texture cache follows automatically
  because new images get new ids.
- Each piece takes the mode as an argument (`mode="light" | "dark"`); no module-level global switched at runtime.

## 9. Speed

- Settings: draw everything once at the screen's scale. Opening Settings in Liquid Glass must be as quick as in Aero
  on Windows; time both.
- Flow bar, Pillow path: per frame, only the patch work Aero already does. Displacement maps, blurs and fringes are
  built once per size and cached.
- Flow bar, GL path: one extra full-patch pass (lens) per frame, plus the morph pass only while morphing. Upload
  pieces once (`GLBar._tex`).
- Check CPU on Windows with the bar recording, both looks, GL on and off. Liquid Glass shouldn't cost noticeably more
  than Aero.

## 10. Testing

On Linux (see `CLAUDE.md`): run anything with a window under `xvfb-run -a -s "-screen 0 1280x800x24"`; Mesa gives
OpenGL there, so both paths run.

1. `python3.12 -m pyflakes aqualite` is clean, lines at most 120.
2. The self-test passes: `python3.12 -c "from aqualite import selftest; selftest.main()"`. That includes the
   unchanged Aero checks, `check_liquid_bar()` (GL against Pillow at rest, both modes, frost on and off) and the text
   contrast check.
3. Make sample images of every Flow bar state and Settings page in Aero, Liquid light and Liquid dark, over a white,
   a black and a busy photo-like background. Save them to the scratchpad and look at them. Aero's must be
   byte-for-byte what they were before your change.
4. Force the fallback (no moderngl, `gpu_flow_bar` off) and check Liquid Glass still looks right with cross-fades.
5. Old settings file without `look` loads as Aero.
6. On Windows (the owner checks): Frost lines up under the morphing shape, text readable over white and black apps,
   dark title bar in dark mode, CPU not noticeably higher than Aero.

Only install on the owner's PC or release when they say so, following `CLAUDE.md`.

## Don'ts

- Don't change Aero's look, colours, defaults, text styles or `check_gpu_bar()` to make Liquid Glass fit.
- Don't capture the screen to bend the desktop.
- Don't make Settings pieces see-through or give them small 9-slice middles.
- Don't put glass on glass, or glass on every surface.
- Don't put text in the bending band, or straight on clear glass without the legibility layer.
- Don't make the rainbow fringe obvious, or animate it.
- Don't add a per-frame Gaussian blur in Pillow or a multi-tap blur in the shader.
- Don't put any of this in `gpu.py`.
