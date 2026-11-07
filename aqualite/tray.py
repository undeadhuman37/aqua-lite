"""System tray icon (bottom-right of the taskbar)."""
from PIL import ImageDraw


def make_icon_image(size=64, dot=None):
    from .aero import app_icon
    img = app_icon(size)
    d = ImageDraw.Draw(img)
    if dot:
        d.ellipse((size * 0.64, size * 0.02, size * 0.98, size * 0.36), fill=dot, outline=(255, 255, 255, 255), width=2)
    return img


class Tray:
    def __init__(self, app):
        import pystray
        self.app = app
        self.pystray = pystray
        M = pystray.MenuItem
        self.icon = pystray.Icon("Aqua Lite", make_icon_image(), "Aqua Lite - hold Ctrl+Win to talk", menu=pystray.Menu(
            M("Open Aqua Lite", lambda: app.post("open_settings"), default=True),
            M(lambda _i: "Stop and insert text" if app.machine.recording else "Start hands-free dictation",
              lambda: app.post("stop_recording" if app.machine.recording else "start_handsfree")),
            M("History", lambda: app.post("open_history")),
            M("Copy last transcript", lambda: app.post("copy_last")),
            M(lambda _i: "Resume" if app.paused else "Pause shortcuts", lambda: app.post("toggle_pause")),
            M("Check for updates", lambda: app.post("check_updates")),
            M("Report a problem", lambda: app.post("report_problem")),
            pystray.Menu.SEPARATOR,
            M("Quit Aqua Lite", lambda: app.post("quit")),
        ))

    def start(self):
        self.icon.run_detached()

    def set_state(self, state, title=None):
        dot = {"recording": (255, 77, 79, 255), "processing": (96, 165, 250, 255),
               "paused": (251, 191, 36, 255)}.get(state)
        try:
            self.icon.icon = make_icon_image(dot=dot)
            if title:
                self.icon.title = title
            self.icon.update_menu()
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
