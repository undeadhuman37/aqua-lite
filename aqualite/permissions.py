"""A small window listing the permissions macOS still has to give Aqua Lite, in plain words, with a button that
opens the right page of System Settings. Windows never shows it (osapi.permission_problems() is empty there)."""
import tkinter as tk
from tkinter import ttk

_open = None   # the window, while it's showing


def show(root, problems, open_settings):
    """problems: [(kind, title, explanation)] from osapi.permission_problems(). open_settings(kind)."""
    global _open
    if _open is not None and _open.winfo_exists():
        _open.lift()
        return
    win = tk.Toplevel(root)
    _open = win
    win.title("Aqua Lite needs your permission")
    win.resizable(False, False)
    pad = ttk.Frame(win, padding=18)
    pad.pack(fill="both", expand=True)
    ttk.Label(pad, text="A few switches to turn on", font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
    ttk.Label(pad, wraplength=420, justify="left",
              text="macOS keeps apps from listening to your keyboard or typing into other apps until you allow it. "
                   "Turn these on, then quit and reopen Aqua Lite.").pack(anchor="w", pady=(4, 12))
    for kind, title, text in problems:
        box = ttk.Frame(pad)
        box.pack(fill="x", pady=6)
        ttk.Label(box, text=title, font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(box, text=text, wraplength=420, justify="left").pack(anchor="w", pady=(2, 4))
        if kind != "pyobjc":
            ttk.Button(box, text="Open System Settings",
                       command=lambda k=kind: open_settings(k)).pack(anchor="w")
    ttk.Button(pad, text="Done", command=win.destroy).pack(anchor="e", pady=(14, 0))
    win.lift()
    win.attributes("-topmost", True)
    win.after(400, lambda: win.winfo_exists() and win.attributes("-topmost", False))
    return win
