"""The Flow bar: a glossy Frutiger Aero capsule at the bottom of the screen that never takes focus."""
import collections
import sys
import tkinter as tk

from .aero import FlowBarRenderer, premultiplied_bgra

IS_WIN = sys.platform == "win32"
ANIMATED = ("recording", "locked", "command", "processing")


class FlowBar:
    def __init__(self, root, level_fn, on_click, show_idle=True):
        self.root, self.level_fn, self.on_click = root, level_fn, on_click
        self.show_idle = show_idle
        self.state, self.label, self.kind, self.tick = "idle", "", "info", 0
        self.levels = collections.deque([0.0] * 14, maxlen=14)
        self.toast_job = None
        self.dirty = True
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
        self._loop()

    # ---------------------------------------------------------------- public
    def set_state(self, state, label=""):
        self.state, self.label = state, label
        self.dirty = True
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
            self.toast_job = None

    def toast(self, text, kind="info", seconds=2.8):
        self.set_state("toast", text)
        self.kind = kind
        self.toast_job = self.root.after(int(seconds * 1000), lambda: self.set_state("idle"))

    # ---------------------------------------------------------------- drawing
    def _position(self):
        if IS_WIN:
            from . import winapi
            l, _t, r, b = winapi.work_area_at_cursor()
        else:
            l, r, b = 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return (l + r) // 2 - self.w // 2, b - self.h

    def _loop(self):
        self.tick += 1
        try:
            if self.state in ("recording", "locked", "command"):
                self.levels.append(self.level_fn())
            if self.dirty or self.state in ANIMATED or self.tick % 30 == 0:
                self._draw()
                self.dirty = False
        except tk.TclError:
            return
        self.root.after(33, self._loop)

    def _draw(self):
        state = "hidden" if (self.state == "idle" and not self.show_idle) else self.state
        img = self.r.render(state, self.label, list(self.levels), self.tick, self.kind)
        x, y = self._position()
        if self.layered:
            from . import winapi
            if winapi.user32.IsIconic(self.hwnd):  # something minimized us (e.g. Win+D): come back quietly
                winapi.user32.ShowWindow(self.hwnd, 4)
            winapi.update_layered(self.hwnd, x, y, self.w, self.h, premultiplied_bgra(img))
            if self.tick % 30 == 0:
                winapi.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            return
        # fallback / non-Windows: composite over the key colour (hard edges) and show in the canvas
        from PIL import Image, ImageTk
        bg = Image.new("RGBA", img.size, (255, 0, 254, 255) if IS_WIN else (32, 44, 60, 255))
        a = img.getchannel("A").point(lambda v: 255 if v > 110 else 0) if IS_WIN else img.getchannel("A")
        bg.paste(img.convert("RGB"), (0, 0), a)
        self.photo = ImageTk.PhotoImage(bg)
        self.c.delete("all")
        self.c.create_image(0, 0, image=self.photo, anchor="nw")
        self.win.geometry(f"+{x}+{y}")
