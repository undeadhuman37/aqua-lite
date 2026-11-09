"""The Flow bar: a glossy Frutiger Aero capsule at the bottom of the screen that never takes focus."""
import collections
import math
import sys
import time
import tkinter as tk

from PIL import Image

from .aero import BARS, FlowBarRenderer, crossfade, premultiplied_bgra

IS_WIN = sys.platform == "win32"
LISTENING = ("recording", "locked", "command")
ANIMATED = LISTENING + ("processing",)
SHOW_SECS, HIDE_SECS = 0.30, 0.22   # slide up from / down under the bottom edge of the screen
FRAME = 1 / 60                      # frame pace when the screen's refresh rate can't be read
MAX_FPS = 500                       # follows the monitor (60, 144, 240 Hz...) up to this
REST_POLL = 0.1                     # how often to look in while nothing is moving
SAMPLE_SECS = 1 / 30                # one new waveform bar every 33 ms (the scroll speed)
FADE_SECS = 0.16                    # cross-fade when the bar changes state (recording -> processing -> toast)
CAPTION_SECS = 0.15                 # live-words bubble fades in / out


def ease_out_back(t, s=1.4):
    """0 -> 1 with a small overshoot at the end: the bar pops up and settles."""
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_cubic(t):
    return t * t * t


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def _match(amount, up):
    """Find the progress on the up (or down) curve that puts the bar at `amount` (0 hidden .. 1 shown)."""
    f = (lambda t: ease_out_back(t)) if up else (lambda t: 1 - ease_in_cubic(1 - t))
    lo, hi = 0.0, 1.0
    if up:  # the up curve overshoots past 1; search only its rising part
        hi = 0.6  # the curve peaks (~1.07) just after this
        if amount >= f(hi):
            return hi
    for _ in range(24):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < amount else (lo, mid)
    return (lo + hi) / 2


class FlowBar:
    def __init__(self, root, level_fn, on_click, show_idle=True, frost=True):
        self.root, self.level_fn, self.on_click = root, level_fn, on_click
        self.frost, self.want_frost = None, frost
        self.show_idle = show_idle
        self.state, self.label, self.kind = "idle", "", "info"
        self.caption = ""   # live words while recording
        self.levels = collections.deque([0.0] * (BARS + 1), maxlen=BARS + 1)
        self.env = 0.0      # smoothed mic level: rises instantly, falls gently, so bars don't flicker
        self.toast_job = None
        self.dirty = True
        now = time.perf_counter()
        self.last_sample, self.phase = now, 1.0
        # slide animation: shown goes 0 (tucked under the screen edge) -> 1 (fully up)
        self.shown, self.last_frame, self.going_up = 0.0, now, False
        self.face = ("idle", "", "info", "")   # what to draw while sliding away
        self.face_key = None                   # (state, label, kind) last drawn, to spot changes worth a fade
        self.last_img, self.fade_from, self.fade_t0 = None, None, 0.0
        self.cap_alpha, self.cap_text = 0.0, ""
        self.job, self.next_due, self.was_active, self.last_keep = None, now, False, 0.0
        # frame pacing: one frame per screen refresh, timed to land just before it
        self.period, self.vblank, self.timing_at = FRAME, None, -10.0
        self.cost, self.target, self.last_v = 0.004, None, 0.0
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.hwnd, self.layered, scale = None, False, 1.0
        if IS_WIN:
            from . import winapi
            self.win.update_idletasks()
            self.hwnd = winapi.user32.GetParent(self.win.winfo_id()) or self.win.winfo_id()
            scale = winapi.window_dpi_scale(self.hwnd)
        self.r = FlowBarRenderer(scale)
        self.w, self.h = self.r.size
        self.win.geometry(f"{self.w}x{self.h}+-20000+-20000")
        self.c = tk.Canvas(self.win, width=self.w, height=self.h, highlightthickness=0, bd=0, bg="#ff00fe")
        self.c.pack()
        self.c.bind("<Button-1>", lambda _e: self.on_click(self.state))
        self.photo = None
        if IS_WIN:
            from . import winapi
            winapi.make_layered(self.hwnd)
            self.layered = winapi.update_layered(self.hwnd, -20000, -20000, self.w, self.h,
                                                 premultiplied_bgra(self.r.render("hidden")))
            if not self.layered:  # fallback: colour-key transparency
                ex = winapi.user32.GetWindowLongPtrW(self.hwnd, -20)
                winapi.user32.SetWindowLongPtrW(self.hwnd, -20, ex & ~0x00080000)
                self.win.attributes("-transparentcolor", "#ff00fe")
                winapi.make_overlay_window(self.win)
        self.set_frost(frost)
        self._loop()
        self.warm = self.r.warm_steps()
        self.root.after(400, self._warm_next)

    def _warm_next(self):
        """Build one piece of cached glass, then come back later for the next, only while the bar is resting."""
        if not self.warm:
            return
        if not self.was_active:
            try:
                self.warm.pop(0)()
            except Exception:
                self.warm = []
                return
        try:
            self.root.after(40, self._warm_next)
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- public
    def set_frost(self, on):
        """Frosted glass: Windows blurs what's behind the bar and the glass turns see-through. Falls back to solid
        glass when Windows can't (older Windows, or Transparency effects switched off)."""
        self.want_frost = on
        if on and self.frost is None and IS_WIN and self.layered:
            from . import winapi
            try:
                if winapi.transparency_on():
                    self.frost = winapi.Frost()
            except Exception:
                self.frost = None
        elif not on and self.frost is not None:
            self.frost.close()
            self.frost = None
        self.r.set_frost(self.frost is not None)
        self.last_img = self.fade_from = None
        self.dirty = True
        self._wake()

    def set_caption(self, text):
        if text != self.caption:
            self.caption = text
            self.dirty = True
            self._wake()

    def set_state(self, state, label=""):
        if state in LISTENING and self.state not in LISTENING:  # fresh recording: start from a flat waveform
            self.levels.extend([0.0] * self.levels.maxlen)
            self.env, self.last_sample = 0.0, time.perf_counter()
        if state not in LISTENING:
            self.caption = ""
        self.state, self.label = state, label
        self.dirty = True
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
            self.toast_job = None
        self._wake()

    def toast(self, text, kind="info", seconds=2.8):
        self.set_state("toast", text)
        self.kind = kind
        self.toast_job = self.root.after(int(seconds * 1000), lambda: self.set_state("idle"))

    # ---------------------------------------------------------------- frame loop
    def _wake(self):
        """Something changed while the loop was resting: draw on the next turn instead of up to 100 ms later."""
        if self.job is not None and not self.was_active:
            self.root.after_cancel(self.job)
            self.job = self.root.after(1, self._loop)

    def _loop(self):
        self.job = None
        try:
            now = time.perf_counter()
            # animate for the moment this frame reaches the screen (the refresh it was timed for), so timer
            # wobble never shows up as uneven motion
            show_at = self.target if self.target is not None and abs(self.target - now) < 0.05 else now
            self.target = None
            self._sample(now)
            if self.dirty or self._active() or now - self.last_keep >= 1.0:
                self._draw(show_at)
                self.dirty = False
                spent = time.perf_counter() - now
                self.cost = min(0.05, max(0.0005, self.cost * 0.8 + spent * 0.2))
            self._schedule(self._active())
        except tk.TclError:
            return

    def _timing(self, now):
        """Re-read the screen's refresh rate and vblank time now and then (it changes when the bar moves to
        another monitor or the user switches 60/144/240 Hz)."""
        if now - self.timing_at < 1.0:
            return
        self.timing_at = now
        if IS_WIN:
            from . import winapi
            try:
                period, self.vblank = winapi.display_timing()
            except Exception:
                period, self.vblank = FRAME, None
        else:
            period, self.vblank = FRAME, None
        self.period = max(period, 1 / MAX_FPS)

    def _schedule(self, active):
        now = time.perf_counter()
        if active:
            self._timing(now)   # forced fresh on the first frame after resting (timing_at reset below)
            p = self.period
            if self.vblank is not None:
                # next refresh we can make: start early enough to draw it (cost) plus a little timer slack
                lead = self.cost + 0.0015
                v = self.vblank + math.ceil((now + lead + 0.0005 - self.vblank) / p) * p
                if v < self.last_v + p * 0.5:  # never two frames for one refresh
                    v = self.last_v + p
                self.last_v, self.target = v, v
                delay = v - lead - now
            else:
                # pace frames against a running deadline, so a slow frame doesn't push every later one back
                self.next_due = self.next_due + p if self.was_active else now + p
                if self.next_due < now:  # fell well behind (busy PC): skip ahead rather than rush to catch up
                    self.next_due = now + 0.001
                delay = self.next_due - now
        else:
            delay = REST_POLL
            self.timing_at = -10.0
        if IS_WIN and active != self.was_active:
            from . import winapi
            winapi.fine_timer(active)
        self.was_active = active
        self.job = self.root.after(max(1, int(delay * 1000)), self._loop)

    def _sample(self, now):
        """Read the mic level at a steady 30 per second, whatever the frame rate, and note how far between
        samples we are (phase) so the waveform can glide."""
        if self.state not in LISTENING:
            self.last_sample, self.phase = now, 1.0
            return
        if now - self.last_sample > 0.25:  # long gap (PC was busy): don't flood in stale samples
            self.last_sample = now - SAMPLE_SECS
        while now - self.last_sample >= SAMPLE_SECS:
            self.last_sample += SAMPLE_SECS
            raw = max(0.0, min(1.0, float(self.level_fn() or 0.0)))
            self.env = raw if raw > self.env else self.env + (raw - self.env) * 0.45
            self.levels.append(self.env)
        self.phase = min(1.0, (now - self.last_sample) / SAMPLE_SECS)

    def _active(self):
        cap_target = 1.0 if (self.state in LISTENING and self.caption) else 0.0
        return (self.state in ANIMATED or self._sliding() or self.fade_from is not None
                or self.cap_alpha != cap_target)

    def _visible(self):
        return not (self.state == "idle" and not self.show_idle)

    def _sliding(self):
        return self.shown != (1.0 if self._visible() else 0.0)

    def _slide_offset(self, dt):
        """Advance the slide; returns how many pixels to push the bar down (0 = fully shown)."""
        up = self._visible()
        if up != self.going_up:  # changed direction mid-slide: continue from where the bar is, no jump
            self.shown = _match(self._amount(self.going_up, self.shown), up)
            self.going_up = up
        if up:
            self.shown = min(1.0, self.shown + dt / SHOW_SECS)
        else:
            self.shown = max(0.0, self.shown - dt / HIDE_SECS)
        return round((1 - self._amount(up, self.shown)) * self.h)

    @staticmethod
    def _amount(up, shown):
        return ease_out_back(shown) if up else 1 - ease_in_cubic(1 - shown)

    # ---------------------------------------------------------------- drawing
    def _draw(self, now):
        dt, self.last_frame = max(0.0, min(now - self.last_frame, 0.1)), now
        if self.shown in (0.0, 1.0):  # starting from rest: the last frame may have been long ago
            dt = min(dt, self.period * 1.25)
        if self._visible():
            self.face = (self.state, self.label, self.kind, self.caption)
            key = self.face[:3]
            if key != self.face_key:
                if self.face_key is not None and self.last_img is not None and self.shown > 0:
                    self.fade_from, self.fade_t0 = self.last_img, now
                self.face_key = key
        offset = self._slide_offset(dt)
        if not self._visible() and self.shown == 0.0:
            img = self.r.render("hidden")
            self.last_img = self.fade_from = None
            self.cap_alpha, self.face_key = 0.0, None
        else:
            state, label, kind, caption = self.face
            # live-words bubble: fade in when words arrive, fade out (with the last words) when they stop
            if state in LISTENING:
                target = 1.0 if caption else 0.0
                if caption:
                    self.cap_text = caption
                step = dt / CAPTION_SECS
                self.cap_alpha = min(target, self.cap_alpha + step) if target > self.cap_alpha \
                    else max(target, self.cap_alpha - step)
            else:
                self.cap_alpha, self.cap_text = 0.0, ""
            img = self.r.render(state, label, list(self.levels), now, kind,
                                self.cap_text if self.cap_alpha > 0 else "", self.phase, ease_in_out(self.cap_alpha))
            if self.fade_from is not None:
                p = (now - self.fade_t0) / FADE_SECS
                if p >= 1:
                    self.fade_from = None
                else:
                    img = crossfade(self.fade_from, img, ease_in_out(max(0.0, p)))
            self.last_img = img
            if offset:  # slide: shift the picture down; whatever falls off the bottom is cut, so it tucks under the edge
                moved = Image.new("RGBA", img.size, (0, 0, 0, 0))
                moved.paste(img, (0, offset))
                img = moved
        x, y = self._position()
        keep = now - self.last_keep >= 1.0
        if keep:
            self.last_keep = now
        if self.layered:
            from . import winapi
            if winapi.user32.IsIconic(self.hwnd):  # something minimized us (e.g. Win+D): come back quietly
                winapi.user32.ShowWindow(self.hwnd, 4)
            winapi.update_layered(self.hwnd, x, y, self.w, self.h, premultiplied_bgra(img))
            if keep:
                winapi.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            if self.frost is not None:
                self._place_frost(x, y + offset, y + self.h, keep)
            return
        # fallback / non-Windows: composite over the key colour (hard edges) and show in the canvas
        from PIL import ImageTk
        bg = Image.new("RGBA", img.size, (255, 0, 254, 255) if IS_WIN else (32, 44, 60, 255))
        a = img.getchannel("A").point(lambda v: 255 if v > 110 else 0) if IS_WIN else img.getchannel("A")
        bg.paste(img.convert("RGB"), (0, 0), a)
        self.photo = ImageTk.PhotoImage(bg)
        self.c.delete("all")
        self.c.create_image(0, 0, image=self.photo, anchor="nw")
        self.win.geometry(f"+{x}+{y}")

    def _place_frost(self, x, y, bottom, restack):
        shape = self.r.blur_shape() if self.shown > 0 else None
        try:
            if shape is None:
                self.frost.hide()
            else:
                bx, by, bw, bh, radius = shape
                if restack:
                    self.frost.rect = None   # re-tuck it right under the bar now and then
                self.frost.place(self.hwnd, x + bx, y + by, bw, bh, radius, clip_bottom=bottom)
        except Exception:   # never let the blur break the bar: drop to solid glass
            try:
                self.frost.close()
            except Exception:
                pass
            self.frost = None
            self.r.set_frost(False)
            self.dirty = True

    def _position(self):
        if IS_WIN:
            from . import winapi
            l, _t, r, b = winapi.work_area_at_cursor()
        else:
            l, r, b = 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return (l + r) // 2 - self.w // 2, b - self.h
