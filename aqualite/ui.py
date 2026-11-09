"""Settings / dashboard window."""
import datetime
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import aero, gpu, history, hotkeys, llm, localai, memory, music, stt
from .config import APP_NAME, VERSION

LANGS = [("auto", "Auto-detect"), ("en", "English"), ("ar", "Arabic"), ("fr", "French"), ("es", "Spanish"),
         ("de", "German"), ("it", "Italian"), ("pt", "Portuguese"), ("tr", "Turkish"), ("ur", "Urdu"),
         ("hi", "Hindi"), ("fa", "Persian"), ("ru", "Russian"), ("zh", "Chinese"), ("ja", "Japanese"),
         ("ko", "Korean"), ("id", "Indonesian"), ("nl", "Dutch")]
STYLE_NAMES = [("formal", "Formal"), ("casual", "Casual"), ("very_casual", "Very casual"), ("excited", "Excited")]
STYLE_EXAMPLE = {
    "formal": "Hi Sara, are you free for lunch tomorrow? Let me know.",
    "casual": "Hey Sara, are you free for lunch tomorrow? Let me know",
    "very_casual": "hey sara are you free for lunch tomorrow let me know",
    "excited": "Hey Sara! Are you free for lunch tomorrow? Let me know!",
}
CATS = [("personal", "Personal messages", "WhatsApp, Telegram, Instagram, Discord"),
        ("work", "Work messages", "Slack, Teams, Notion, Linear"),
        ("email", "Email", "Outlook, Gmail, Thunderbird"),
        ("other", "Everything else", "Docs, browsers, notes, AI chats")]
STRENGTHS = [("verbatim", "Verbatim - punctuation only"), ("light", "Light - fillers & corrections"),
             ("medium", "Medium - also smooth grammar"), ("heavy", "Heavy - polish & tighten")]


def _pair_combo(parent, pairs, value, width=28):
    labels = [b for _a, b in pairs]
    var = tk.StringVar(value=dict(pairs).get(value, labels[0]))
    cb = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly", width=width)
    cb.get_key = lambda: next(a for a, b in pairs if b == var.get())
    return cb


BG, PANEL, INK, MUTED, ACCENT = "#eaf6ff", "#f7fcff", "#0b3d63", "#4d7391", "#0a84c6"
_BUTTON_IMAGES = {}


def apply_aero_style(win, keep):
    """Frutiger Aero ttk theme: sky-tinted panels, glossy aqua buttons, Segoe UI."""
    from PIL import ImageTk
    st = ttk.Style(win)
    st.theme_use("clam")
    font = ("Segoe UI", 10)
    win.configure(bg=BG)
    st.configure(".", background=BG, foreground=INK, font=font, fieldbackground="white", bordercolor="#9fd0ee",
                 lightcolor="#ffffff", darkcolor="#b9dcf2", troughcolor="#d6ecfa", focuscolor=ACCENT)
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=INK)
    st.configure("TLabelframe", background=BG, bordercolor="#9fd0ee", relief="solid")
    st.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 10))
    st.configure("TCheckbutton", background=BG)
    st.configure("TRadiobutton", background=BG)
    st.map("TCheckbutton", background=[("active", BG)])
    st.map("TRadiobutton", background=[("active", BG)])
    st.configure("TNotebook", background=BG, bordercolor="#9fd0ee", tabmargins=(6, 6, 6, 0))
    st.configure("TNotebook.Tab", background="#cfe9fa", foreground=INK, padding=(12, 5), bordercolor="#9fd0ee")
    st.map("TNotebook.Tab", background=[("selected", "white"), ("active", "#e3f4ff")],
           foreground=[("selected", ACCENT)])
    st.configure("Treeview", background="white", fieldbackground="white", rowheight=24, bordercolor="#9fd0ee")
    st.configure("Treeview.Heading", background="#d9effc", foreground=INK, font=("Segoe UI Semibold", 9))
    st.map("Treeview", background=[("selected", "#bfe6ff")], foreground=[("selected", INK)])
    st.configure("Horizontal.TScale", background=BG, troughcolor="#cde9fb")
    st.configure("Tile.TFrame", background="white", bordercolor="#9fd0ee", relief="solid")
    st.configure("Tile.TLabel", background="white")
    st.configure("Muted.TLabel", foreground=MUTED)
    # The button images must live as long as the app: ttk keeps using them for every later window,
    # so they are created once and held at module level (not by the window, which gets garbage-collected).
    if not _BUTTON_IMAGES:
        root = win._root()
        _BUTTON_IMAGES.update({k: ImageTk.PhotoImage(aero.glossy_button(96, 30, k), master=root)
                               for k in ("normal", "active", "pressed")})
        imgs = _BUTTON_IMAGES
        st.element_create("Aero.button", "image", imgs["normal"], ("pressed", imgs["pressed"]),
                          ("active", imgs["active"]), border=(15, 14, 15, 14), sticky="nsew")
    st.layout("TButton", [("Aero.button", {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})])
    st.configure("TButton", padding=(16, 3), foreground="#063a5e", font=("Segoe UI Semibold", 10), anchor="center")


class SettingsWindow:
    def __init__(self, root, app):
        self.app, self.cfg = app, app.cfg
        self.win = tk.Toplevel(root)
        self.win.title(f"{APP_NAME} {VERSION}")

        try:
            self.win.iconbitmap(app.icon_path)
        except Exception:
            pass
        self.v = {}
        self._imgs = []
        apply_aero_style(self.win, self._imgs)
        # size for the screen's scaling (125%, 150%...) so the bottom buttons are never cut off
        sc = max(1.0, self.win.winfo_fpixels("1i") / 96.0)
        w, h = int(820 * sc), int(720 * sc)  # noqa: re-checked against content size below
        h = min(h, self.win.winfo_screenheight() - int(60 * sc))
        self.win.geometry(f"{w}x{h}")
        self.win.minsize(int(700 * sc), int(560 * sc))
        try:
            from PIL import ImageTk
            ban = ImageTk.PhotoImage(aero.sky_banner(820, 96), master=self.win)
            self._imgs.append(ban)
            tk.Label(self.win, image=ban, bd=0, bg=BG).pack(fill="x")
        except Exception:
            pass
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=10, pady=(8, 0))
        self.nb = nb
        for title, build in (("Home", self._home), ("Shortcuts & mic", self._general),
                             ("Speech & AI", self._ai), ("Instant text", self._instant), ("Private", self._private),
                             ("Style", self._style), ("Memory", self._memory),
                             ("Music", self._music),
                             ("Dictionary", self._dictionary), ("Snippets", self._snippets),
                             ("History", self._history)):
            f = ttk.Frame(nb, padding=14)
            nb.add(f, text=title)
            build(f)
        bar = ttk.Frame(self.win, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="Save", command=self.save).pack(side="right")
        ttk.Button(bar, text="Close", command=self.win.destroy).pack(side="right", padx=6)
        self.status = ttk.Label(bar, text="", foreground="#666")
        self.status.pack(side="left")
        # grow the window to fit its content (fonts are bigger on 125%/150% scaled screens)
        self.win.update_idletasks()
        need_w, need_h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        max_h = self.win.winfo_screenheight() - 80
        self.win.geometry(f"{max(w, need_w)}x{min(max(h, need_h + 10), max_h)}")
        self.win.lift()
        self.win.focus_force()

    # ------------------------------------------------------------------ helpers
    def _var(self, key, kind=tk.StringVar):
        val = self.cfg.get(key)
        var = kind(value=val)
        self.v[key] = var
        return var

    def _row(self, parent, r, label, widget, hint=""):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
        widget.grid(row=r, column=1, sticky="w", pady=4)
        if hint:
            ttk.Label(parent, text=hint, foreground="#777").grid(row=r, column=2, sticky="w", padx=8)

    # ------------------------------------------------------------------ tabs
    def _home(self, f):
        s = history.stats()
        ttk.Label(f, text="Hold the shortcut, talk, let go.", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        tiles = ttk.Frame(f)
        tiles.pack(fill="x", pady=4)
        for i, (val, lab) in enumerate(((f"{s['words']:,}", "words dictated"), (f"{s['wpm']:.0f}", "words / minute"),
                                        (f"{s['minutes_saved']:.0f} min", "saved vs typing"),
                                        (f"{s['week_words']:,}", "words this week"))):
            t = ttk.Frame(tiles, padding=10, style="Tile.TFrame")
            t.grid(row=0, column=i, padx=4, sticky="nsew")
            tiles.columnconfigure(i, weight=1)
            ttk.Label(t, text=val, font=("Segoe UI Semibold", 17), foreground=ACCENT, style="Tile.TLabel").pack(anchor="w")
            ttk.Label(t, text=lab, foreground=MUTED, style="Tile.TLabel").pack(anchor="w")
        c = self.cfg
        ptt = c["hotkey_ptt"].upper().replace("+", " + ")
        rows = [
            (f"Hold {ptt}", "Push-to-talk: speak while holding, release to insert text"),
            (f"{ptt} + {c['hotkey_handsfree_key'].upper()}", "Hands-free: keeps listening; press the shortcut again to finish"),
            (f"{ptt} + {c['hotkey_command_key'].upper()}", "Command Mode: select text, then say what to do with it"),
            (f"Tap {ptt} twice", "Hands-free, without reaching for the extra key"),
            (c["hotkey_paste_last"].upper().replace("+", " + "), "Paste your last transcript again"),
            (c.get("hotkey_undo_last", "alt+shift+x").upper().replace("+", " + "), "Undo: remove the text of your last dictation"),
            ('Say "press enter"', 'At the end of a dictation: types it, then presses Enter (also "send it")'),
            (c["hotkey_cancel"].upper(), "Cancel the current recording"),
        ]
        box = ttk.LabelFrame(f, text="Shortcuts", padding=10)
        box.pack(fill="x", pady=12)
        for i, (k, d) in enumerate(rows):
            ttk.Label(box, text=k, font=("Consolas", 10, "bold")).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(box, text=d).grid(row=i, column=1, sticky="w", padx=14)
        eng = stt.resolve_engine(c)
        prov = llm.resolve_provider(c) or "off (offline cleanup only)"
        info = ttk.LabelFrame(f, text="Engines", padding=10)
        info.pack(fill="x")
        ttk.Label(info, text=f"Speech to text: {eng}" + (f"  -  local model {stt.LOCAL.status}" if eng == "local" else "")).pack(anchor="w")
        ttk.Label(info, text=f"AI formatting: {prov}").pack(anchor="w")
        if eng == "local" and prov.startswith("off"):
            ttk.Label(info, foreground="#b45309", wraplength=700, text=(
                "Tip: paste a free Groq API key in Speech & AI for Wispr-level speed and AI formatting. "
                "Without it, everything runs offline on this PC.")).pack(anchor="w", pady=(6, 0))

    def _general(self, f):
        r = 0
        for key, label, hint in (("hotkey_ptt", "Push-to-talk (hold)", "e.g. ctrl+win, f9, right alt, rctrl"),
                                 ("hotkey_handsfree_key", "+ key for hands-free", "pressed while holding push-to-talk"),
                                 ("hotkey_command_key", "+ key for Command Mode", "pressed while holding push-to-talk"),
                                 ("hotkey_paste_last", "Paste last transcript", ""),
                                 ("hotkey_undo_last", "Undo last dictation", "removes what Aqua Lite just typed"),
                                 ("hotkey_cancel", "Cancel recording", "")):
            self._row(f, r, label, ttk.Entry(f, textvariable=self._var(key), width=24), hint)
            r += 1
        ttk.Separator(f).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1
        self._row(f, r, "Hands-free stops after", ttk.Spinbox(f, from_=0, to=60, width=6,
                                                              textvariable=self._var("handsfree_silence_secs")),
                  "seconds of silence (0 = never)")
        r += 1
        devices = ["(Windows default)"] + _safe_devices()
        mic = tk.StringVar(value=self.cfg.get("mic_device") or "(Windows default)")
        self.v["mic_device"] = mic
        self._row(f, r, "Microphone", ttk.Combobox(f, textvariable=mic, values=devices, state="readonly", width=40))
        r += 1
        self.lang = _pair_combo(f, LANGS, self.cfg.get("language", "auto"), width=22)
        self._row(f, r, "Language", self.lang, "Auto handles Arabic, English and mixing")
        r += 1
        for key, label in (("live_preview", "Show my words in the bar while I talk (when instant text is off)"),
                           ("learn_corrections", "Learn words I correct right after dictating"),
                           ("voice_enter", 'Say "press enter" or "send it" at the end to press Enter'),
                           ("double_tap_handsfree", "Tap the shortcut twice for hands-free"),
                           ("sounds", "Play start/stop sounds"), ("show_idle_bar", "Keep the Flow bar on screen when idle (click it to start hands-free)"),
                           ("whisper_boost", "Whisper mode (boost quiet speech)"),
                           ("add_trailing_space", "Add a space after each dictation"),
                           ("restore_clipboard", "Restore my clipboard after pasting"),
                           ("shift_insert_in_editors", "Use Shift+Insert in VS Code / Cursor / Windsurf"),
                           ("launch_at_startup", "Start Aqua Lite when Windows starts"),
                           ("auto_update", "Update automatically when Aqua Lite starts")):
            ttk.Checkbutton(f, text=label, variable=self._var(key, tk.BooleanVar)).grid(
                row=r, column=0, columnspan=3, sticky="w", pady=1)
            r += 1

    def _ai(self, f):
        top = ttk.LabelFrame(f, text="Speech to text", padding=10)
        top.pack(fill="x")
        eng = self._var("stt_engine")
        for i, (val, lab) in enumerate((("auto", "Auto"), ("groq", "Groq (fast, cloud)"),
                                        ("openai", "OpenAI (cloud)"), ("local", "On this PC (offline)"))):
            ttk.Radiobutton(top, text=lab, value=val, variable=eng).grid(row=0, column=i, sticky="w", padx=(0, 14))
        ttk.Label(top, text="Local model").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(top, textvariable=self._var("local_model"), state="readonly", width=16,
                     values=["tiny", "base", "small", "medium", "large-v3-turbo"]).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Combobox(top, textvariable=self._var("local_device"), state="readonly", width=8,
                     values=["auto", "cpu", "cuda"]).grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(top, text="small = good balance on CPU; large-v3-turbo needs an NVIDIA GPU",
                  foreground="#777").grid(row=2, column=0, columnspan=4, sticky="w")

        mid = ttk.LabelFrame(f, text="AI formatting & Command Mode", padding=10)
        mid.pack(fill="x", pady=10)
        ttk.Label(mid, text="Provider").grid(row=0, column=0, sticky="w")
        ttk.Combobox(mid, textvariable=self._var("ai_provider"), state="readonly", width=14,
                     values=["auto", "groq", "openai", "anthropic", "custom", "off"]).grid(row=0, column=1, sticky="w")
        self.strength = _pair_combo(mid, STRENGTHS, self.cfg.get("editing_strength", "medium"), width=30)
        ttk.Label(mid, text="Editing strength").grid(row=0, column=2, sticky="e", padx=(16, 6))
        self.strength.grid(row=0, column=3, sticky="w")

        keys = ttk.LabelFrame(f, text="API keys & models (stored only on this PC)", padding=10)
        keys.pack(fill="x")
        rows = (("Groq key", "groq_api_key", "groq_llm_model", "groq_stt_model", "free key: console.groq.com/keys"),
                ("OpenAI key", "openai_api_key", "openai_llm_model", "openai_stt_model", ""),
                ("Anthropic key", "anthropic_api_key", "anthropic_llm_model", None, ""),
                ("Custom key", "custom_api_key", "custom_llm_model", None, "LM Studio / Ollama / any OpenAI-compatible"))
        ttk.Label(keys, text="AI model", foreground="#777").grid(row=0, column=2, sticky="w")
        ttk.Label(keys, text="Speech model", foreground="#777").grid(row=0, column=3, sticky="w")
        for i, (lab, k, m, sm, hint) in enumerate(rows, start=1):
            ttk.Label(keys, text=lab).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(keys, textvariable=self._var(k), show="•", width=30).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Entry(keys, textvariable=self._var(m), width=20).grid(row=i, column=2, sticky="w", padx=4)
            if sm:
                ttk.Entry(keys, textvariable=self._var(sm), width=22).grid(row=i, column=3, sticky="w", padx=4)
            elif hint:
                ttk.Label(keys, text=hint, foreground="#777").grid(row=i, column=3, sticky="w", padx=4)
        ttk.Label(keys, text="Custom server URL").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(keys, textvariable=self._var("custom_base_url"), width=30).grid(row=5, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(keys, text="Get a free Groq key at console.groq.com/keys - it powers both speech and formatting.",
                  foreground="#777").grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(f, text="Test AI connection", command=self._test_ai).pack(anchor="w", pady=10)

    INSTANT_ENGINES = [
        ("off", "Off", "Your text appears when you let go, already polished. Works on every PC."),
        ("preview", "Quick preview - any PC",
         "A small speech model on your processor types words as you talk. Fast but rough: expect wrong words until "
         "you let go and the polished version replaces them. Uses some processor power while you talk."),
        ("gpu", "Graphics card - NVIDIA only",
         "REQUIRES an NVIDIA graphics card with 4 GB or more of graphics memory. Whisper large-v3-turbo runs on the "
         "card, so the live words are almost the final text. One-time download of about 2.6 GB. The card only works "
         "while you talk, and its memory is freed after 15 minutes without dictating."),
        ("deepgram", "Deepgram - any PC, needs internet",
         "REQUIRES a Deepgram account (console.deepgram.com: free credit when you sign up, then about $0.46 per hour "
         "of talking). Your voice streams to Deepgram while you talk and accurate words arrive in about 0.3 s. "
         "Letting go is faster too, because the transcript is already done."),
    ]

    def _instant(self, f):
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "Instant text types your words into the app while you're still talking. When you let go, they're replaced "
            "with the polished version, like always. Pick how the live words are made - only choose an option if you "
            "have what it needs.")).pack(anchor="w", pady=(0, 8))
        var = tk.StringVar(value=self.cfg.get("instant_text_engine", "off"))
        self.v["instant_text_engine"] = var
        for key, title, desc in self.INSTANT_ENGINES:
            box = ttk.Frame(f)
            box.pack(fill="x", pady=(6, 0))
            ttk.Radiobutton(box, text=title, value=key, variable=var).pack(anchor="w")
            ttk.Label(box, text=desc, wraplength=700, style="Muted.TLabel").pack(anchor="w", padx=(24, 0))
            if key == "gpu":
                row = ttk.Frame(box)
                row.pack(anchor="w", padx=(24, 0), pady=(4, 0))
                self.gpu_btn = ttk.Button(row, text="Set up graphics card", command=self._gpu_setup)
                self.gpu_btn.pack(side="left")
                self.gpu_status = ttk.Label(row, text="Checking for an NVIDIA card...", style="Muted.TLabel")
                self.gpu_status.pack(side="left", padx=10)
            if key == "deepgram":
                row = ttk.Frame(box)
                row.pack(anchor="w", padx=(24, 0), pady=(4, 0))
                ttk.Label(row, text="Deepgram API key").pack(side="left")
                ttk.Entry(row, textvariable=self._var("deepgram_api_key"), width=46, show="\u2022").pack(
                    side="left", padx=8)
        self.gpu_job = None
        threading.Thread(target=self._gpu_check, daemon=True).start()

    def _gpu_say(self, text):
        try:
            self.win.after(0, lambda: self.gpu_status.winfo_exists() and self.gpu_status.configure(text=text))
        except (tk.TclError, RuntimeError):
            pass

    def _gpu_check(self):
        has, name, mem = gpu.detect()
        if not has:
            self._gpu_say("No NVIDIA graphics card found - this option won't work on this PC.")
            self.win.after(0, lambda: self.gpu_btn.configure(state="disabled"))
            return
        card = f"{name}" + (f" ({mem / 1024:.0f} GB)" if mem else "")
        if mem and mem < 3500:
            self._gpu_say(f"{card}: probably too little graphics memory for this.")
        elif gpu.GPU.model is not None:
            self._gpu_say(f"{card}: ready.")
            self.win.after(0, lambda: self.gpu_btn.configure(text="Set up again"))
        elif gpu.libraries_installed():
            self._gpu_say(f"{card}: set up. The model loads when you next talk.")
            self.win.after(0, lambda: self.gpu_btn.configure(text="Test it"))
        else:
            self._gpu_say(f"{card} found. Click Set up (about 2.6 GB download).")

    def _gpu_setup(self):
        if self.gpu_job:
            return
        self.gpu_job = True
        self.gpu_btn.configure(state="disabled")

        def run():
            try:
                has, name, mem = gpu.detect()
                if not has:
                    raise RuntimeError("no NVIDIA graphics card found")
                if not gpu.libraries_installed():
                    self._gpu_say("Installing NVIDIA's libraries (about 1 GB)...")
                    gpu.install_libraries(lambda line: self._gpu_say("Installing: " + line[:70]))
                self._gpu_say("Loading the model onto the card (first time downloads about 1.6 GB)...")
                gpu.GPU.load()
                secs = gpu.GPU.bench()
                self._gpu_say(f"Ready: {secs:.2f}s per pass on {name}. Pick this option and click Save.")
                self.win.after(0, lambda: self.v["instant_text_engine"].set("gpu"))
            except Exception as e:
                gpu.GPU.failed = str(e)
                self._gpu_say(f"Didn't work: {str(e)[:120]}")
            finally:
                self.gpu_job = None
                try:
                    self.win.after(0, lambda: self.gpu_btn.configure(state="normal"))
                except (tk.TclError, RuntimeError):
                    pass
        threading.Thread(target=run, daemon=True, name="gpu-setup").start()

    def _private(self, f):
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "Private mode keeps everything on this PC. Your voice is turned into text by the offline speech model, "
            "and the AI clean-up, Command Mode and edit-by-voice run on an AI model built into Aqua Lite. No account, "
            "no API key, nothing sent out, and it works without internet once it's downloaded.")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(14, 4))
        ttk.Label(row, text="AI model").pack(side="left", padx=(0, 8))
        self.ai_keys = list(localai.MODELS)
        self.ai_model = ttk.Combobox(row, state="readonly", width=62,
                                     values=[localai.MODELS[k]["label"] for k in self.ai_keys])
        cur = self.cfg.get("local_ai_model", localai.DEFAULT_MODEL)
        self.ai_model.current(self.ai_keys.index(cur) if cur in self.ai_keys else 0)
        self.ai_model.pack(side="left")
        self.ai_model.bind("<<ComboboxSelected>>", lambda _e: self._ai_refresh())
        btns = ttk.Frame(f)
        btns.pack(anchor="w", pady=(8, 4))
        self.ai_dl = ttk.Button(btns, text="Download", command=self._ai_download)
        self.ai_dl.pack(side="left")
        self.ai_cancel_btn = ttk.Button(btns, text="Cancel", command=self._ai_cancel, state="disabled")
        self.ai_cancel_btn.pack(side="left", padx=6)
        self.ai_bar = ttk.Progressbar(f, length=560, mode="determinate", maximum=1000)
        self.ai_bar.pack(anchor="w", pady=(4, 2))
        self.ai_status = ttk.Label(f, text="", style="Muted.TLabel")
        self.ai_status.pack(anchor="w")
        ttk.Checkbutton(f, text="Private mode: keep my voice and text on this PC",
                        variable=self._var("private_mode", tk.BooleanVar),
                        command=self._private_toggled).pack(anchor="w", pady=(14, 2))
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "Speech uses the offline model picked under Speech & AI (\"small\" is a good balance). With a graphics "
            "card the AI answers in about a second; on the processor alone it can take several seconds, so pick the "
            "Small model there.")).pack(anchor="w", padx=(22, 0))
        ttk.Button(f, text="Delete the downloaded AI", command=self._ai_delete).pack(anchor="w", pady=(16, 0))
        self.ai_job = None
        self._ai_refresh()

    def _ai_key(self):
        return self.ai_keys[max(0, self.ai_model.current())]

    def _ai_refresh(self):
        if self.ai_job:  # a download is running: its own updates own the status line
            return
        key = self._ai_key()
        ok = localai.ready(key)
        self.ai_dl.configure(text="Downloaded" if ok else "Download", state="disabled" if ok else "normal")
        self.ai_bar.configure(value=1000 if ok else 0)
        self.ai_status.configure(text="Ready to use." if ok else "Not downloaded yet.")

    def _ai_download(self):
        key = self._ai_key()
        cancel = threading.Event()
        job = {"stage": "Starting...", "done": 0, "total": None, "error": None, "finished": False, "cancel": cancel}
        self.ai_job = job

        def progress(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        def run():
            try:
                localai.install(key, progress, cancel)
            except Exception as e:
                job["error"] = str(e)
            job["finished"] = True
        self.ai_dl.configure(state="disabled")
        self.ai_cancel_btn.configure(state="normal")
        threading.Thread(target=run, daemon=True, name="ai-download").start()
        self._ai_poll()

    def _ai_poll(self):
        job = self.ai_job
        if job is None or not self.win.winfo_exists():
            return
        total, done = job["total"], job["done"]
        if total:
            self.ai_bar.configure(mode="determinate", value=int(1000 * done / total))
            self.ai_status.configure(text=f"{job['stage']}  {done / 1e6:,.0f} of {total / 1e6:,.0f} MB")
        else:
            self.ai_status.configure(text=job["stage"])
        if not job["finished"]:
            self.win.after(200, self._ai_poll)
            return
        self.ai_job = None
        self.ai_cancel_btn.configure(state="disabled")
        if job["error"]:
            self._ai_refresh()
            self.ai_status.configure(text=("Cancelled." if job["error"] == "cancelled"
                                           else f"Download failed: {job['error'][:150]}"))
            return
        self._ai_refresh()
        self.v["private_mode"].set(True)
        self.ai_status.configure(text="Downloaded and tested. Click Save to switch to private mode.")

    def _ai_cancel(self):
        if self.ai_job:
            self.ai_job["cancel"].set()

    def _private_toggled(self):
        if self.v["private_mode"].get() and not localai.ready(self._ai_key()):
            self.v["private_mode"].set(False)
            messagebox.showinfo(APP_NAME, "Download the AI model first (the Download button above).", parent=self.win)

    def _ai_delete(self):
        if self.ai_job:
            return
        if messagebox.askyesno(APP_NAME, "Delete the downloaded private AI (engine and models)?", parent=self.win):
            localai.remove_all()
            self.v["private_mode"].set(False)
            self._ai_refresh()

    def _style(self, f):
        ttk.Label(f, text="Aqua Lite formats differently depending on where you're typing.",
                  foreground="#555").pack(anchor="w", pady=(0, 10))
        self.style_boxes = {}
        for key, title, apps in CATS:
            box = ttk.LabelFrame(f, text=f"{title}   ({apps})", padding=8)
            box.pack(fill="x", pady=4)
            cb = _pair_combo(box, STYLE_NAMES, self.cfg["styles"].get(key, "formal"), width=14)
            cb.pack(side="left")
            ex = ttk.Label(box, text="", foreground="#555")
            ex.pack(side="left", padx=14)
            upd = lambda _e=None, cb=cb, ex=ex: ex.configure(text=f"“{STYLE_EXAMPLE[cb.get_key()]}”")
            cb.bind("<<ComboboxSelected>>", upd)
            upd()
            self.style_boxes[key] = cb
        ttk.Checkbutton(f, text="Code mode: in code editors and terminals, keep file names, variables and commands exact",
                        variable=self._var("code_mode", tk.BooleanVar)).pack(anchor="w", pady=10)

        smart = ttk.LabelFrame(f, text="Get to know me", padding=10)
        smart.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(smart, text="Learn from how I edit Aqua Lite's text (wording, punctuation, emoji, formatting)",
                        variable=self._var("learn_style", tk.BooleanVar)).grid(row=0, column=0, columnspan=3, sticky="w")
        self.learned_label = ttk.Label(smart, text="", style="Muted.TLabel")
        self.learned_label.grid(row=1, column=0, sticky="w", padx=(22, 0))
        ttk.Button(smart, text="Forget what it learned", command=self._forget_edits).grid(row=1, column=1, sticky="w",
                                                                                         padx=10)
        ttk.Checkbutton(smart, text="Read the conversation on screen so names, topic and tone fit what I'm replying to",
                        variable=self._var("screen_context", tk.BooleanVar)).grid(row=2, column=0, columnspan=3,
                                                                                    sticky="w", pady=(10, 0))
        ttk.Label(smart, style="Muted.TLabel", wraplength=700, text=(
            "Reads only what's visible in the app you're dictating into, and sends it to your AI provider with the "
            "dictation. Never saved. Password boxes and private/incognito windows are never read.")).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=(22, 0))
        ttk.Label(smart, text="Never read these apps").grid(row=4, column=0, sticky="w", padx=(22, 0), pady=(6, 0))
        self.blocked = tk.StringVar(value=", ".join(self.cfg.get("context_blocked_apps") or []))
        ttk.Entry(smart, textvariable=self.blocked, width=60).grid(row=4, column=1, columnspan=2, sticky="w",
                                                                   pady=(6, 0))
        self._count_edits()

    def _memory(self, f):
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "How you write, as Aqua Lite has learned it from your edits. It's used every time it formats a "
            "dictation, and rebuilt by your AI every few new edits. Change anything you like here - add or remove "
            "lines - and click Save. Only style is kept here, never what your messages were about.")).pack(anchor="w")
        prof = memory.load()
        self.mem_text = {}
        for key, label in memory.KINDS:
            box = ttk.LabelFrame(f, text=label, padding=(8, 4))
            box.pack(fill="x", pady=3)
            t = tk.Text(box, height=3, wrap="word", relief="flat", font=("Segoe UI", 10))
            t.insert("1.0", prof["styles"].get(key, ""))
            t.pack(fill="x")
            self.mem_text[key] = t
        self.mem_status = ttk.Label(f, text="", style="Muted.TLabel")
        self.mem_status.pack(anchor="w", pady=(4, 2))
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=4)
        ttk.Button(row, text="Update from my edits now", command=self._mem_update).pack(side="left")
        ttk.Button(row, text="Export my memory...", command=self._mem_export).pack(side="left", padx=6)
        ttk.Button(row, text="Import...", command=self._mem_import).pack(side="left")
        self._mem_refresh_status(prof)

    def _mem_refresh_status(self, prof=None):
        prof = prof or memory.load()
        try:
            n = history.correction_count()
        except Exception:
            n = 0
        when = time.strftime("%d %b %Y, %H:%M", time.localtime(prof["updated"])) if prof["updated"] else "not yet"
        self.mem_status.configure(text=f"Learned from {n} edit{'s' if n != 1 else ''} - profile updated: {when}")

    def _mem_typed(self):
        return {k: memory.tidy(self.mem_text[k].get("1.0", "end")) for k, _ in memory.KINDS}

    def _mem_save_typed(self):
        prof = memory.load()
        typed = self._mem_typed()
        if typed != prof["styles"]:
            prof["styles"] = typed
            prof["updated"] = time.time()
            memory.save(prof)

    def _mem_reload(self):
        prof = memory.load()
        for k, _ in memory.KINDS:
            self.mem_text[k].delete("1.0", "end")
            self.mem_text[k].insert("1.0", prof["styles"].get(k, ""))
        self._mem_refresh_status(prof)

    def _mem_update(self):
        self._mem_save_typed()   # so the AI starts from what you wrote
        self.mem_status.configure(text="Updating from your edits...")

        def done(changed, msg):
            def ui():
                if not self.win.winfo_exists():
                    return
                self._mem_reload()
                self.mem_status.configure(text=msg + " - " + self.mem_status.cget("text"))
            self.win.after(0, ui)
        self.app.update_memory(force=True, done=done)

    def _mem_export(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self.win, title="Export my Aqua Lite memory",
                                            defaultextension=".json", initialfile="aqualite-memory.json",
                                            filetypes=[("Aqua Lite memory", "*.json")])
        if not path:
            return
        self._mem_save_typed()
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(memory.export_bundle(self._collect(), history.all_corrections()), fh, indent=2,
                      ensure_ascii=False)
        messagebox.showinfo(APP_NAME, "Saved. Import it on another PC from Settings > Memory.", parent=self.win)

    def _mem_import(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.win, title="Import Aqua Lite memory",
                                          filetypes=[("Aqua Lite memory", "*.json")])
        if not path:
            return
        import json
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            cfg = self._collect()
            summary = memory.import_bundle(cfg, data, history.add_correction)
        except (OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"Couldn't import that file: {e}", parent=self.win)
            return
        self.app.apply_settings(cfg)
        messagebox.showinfo(APP_NAME, f"Imported {summary}.", parent=self.win)
        tab = self.nb.index("current")
        self.win.destroy()
        self.app.open_settings(tab)

    def _count_edits(self):
        try:
            n = history.correction_count()
        except Exception:
            n = 0
        self.learned_label.configure(text=f"Learned from {n} edit{'s' if n != 1 else ''} so far (kept on this PC)")

    def _forget_edits(self):
        if messagebox.askyesno(APP_NAME, "Forget everything Aqua Lite learned from your edits?", parent=self.win):
            history.clear_corrections()
            self._count_edits()

    def _music(self, f):
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "While you dictate, Aqua Lite softly plays a random part of a song from your music folder, then fades it "
            "out when you stop. Add any songs you own: mp3, m4a, flac, ogg or wav.")).pack(anchor="w")
        ttk.Checkbutton(f, text="Play music while I talk", variable=self._var("music_enabled", tk.BooleanVar)).pack(
            anchor="w", pady=(10, 4))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Volume").pack(side="left")
        vol = self._var("music_volume", tk.IntVar)
        lab = ttk.Label(row, text=f"{vol.get()}%", width=5)
        ttk.Scale(row, from_=5, to=100, orient="horizontal", length=320,
                  command=lambda v: (vol.set(int(float(v))), lab.configure(text=f"{int(float(v))}%")),
                  value=vol.get()).pack(side="left", padx=10)
        lab.pack(side="left")
        ttk.Label(row, text="30% lets you hear yourself and keeps the mic clear", style="Muted.TLabel").pack(side="left", padx=8)
        box = ttk.LabelFrame(f, text="Music folder", padding=10)
        box.pack(fill="x", pady=10)
        folder = self._var("music_folder")
        if not folder.get():
            folder.set(music.default_folder())
        ttk.Entry(box, textvariable=folder, width=70).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(box, text="Open folder", command=lambda: _open_folder(folder.get())).grid(row=1, column=0, sticky="w", pady=8)
        ttk.Button(box, text="Choose...", command=lambda: self._choose_folder(folder)).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(box, text="Preview", command=self._preview_music).grid(row=1, column=2, sticky="w")
        self.music_count = ttk.Label(box, text="", style="Muted.TLabel")
        self.music_count.grid(row=2, column=0, columnspan=3, sticky="w")
        self._count_songs(folder.get())
        ttk.Label(f, wraplength=740, style="Muted.TLabel", text=(
            "Tip: with speakers, your mic hears a little of the music. At 30% that's usually fine. "
            "Headphones keep transcripts cleanest.")).pack(anchor="w", pady=(4, 0))

    def _count_songs(self, folder):
        n = len(music.list_songs(folder))
        self.music_count.configure(text=f"{n} song{'s' if n != 1 else ''} found" if n else
                                   "No songs yet - click Open folder and drop some in.")

    def _choose_folder(self, var):
        from tkinter import filedialog
        d = filedialog.askdirectory(parent=self.win, initialdir=var.get() or music.default_folder())
        if d:
            var.set(os.path.normpath(d))
            self._count_songs(var.get())

    def _preview_music(self):
        cfg = self._collect()
        self.app.music.cfg.update({k: cfg[k] for k in ("music_volume", "music_folder")})
        self.app.music.cfg["music_enabled"] = True
        ok = self.app.music.preview()
        self.app.music.cfg["music_enabled"] = self.cfg.get("music_enabled", True)
        self._count_songs(cfg["music_folder"])
        self.status.configure(text=f"Playing: {self.app.music.now_playing}" if ok else
                              "Loading songs... click Preview again in a moment (or add songs to the folder).")

    def _dictionary(self, f):
        ttk.Label(f, text="Words, names and jargon Aqua Lite should always spell your way "
                          "(sent to the recognizer and the formatter).", foreground="#555").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        self.dict_entry = ttk.Entry(row, width=40)
        self.dict_entry.pack(side="left")
        self.dict_entry.bind("<Return>", lambda _e: self._dict_add())
        ttk.Button(row, text="Add word", command=self._dict_add).pack(side="left", padx=6)
        ttk.Button(row, text="Remove selected", command=self._dict_remove).pack(side="left")
        self.dict_list = tk.Listbox(f, height=8)
        self.dict_list.pack(fill="both", expand=True)
        for w in self.cfg.get("dictionary", []):
            self.dict_list.insert("end", w)

        ttk.Label(f, text="Replacements - whenever you say the left side, type the right side",
                  foreground="#555").pack(anchor="w", pady=(12, 0))
        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=6)
        self.rep_from, self.rep_to = ttk.Entry(row2, width=22), ttk.Entry(row2, width=30)
        self.rep_from.pack(side="left")
        ttk.Label(row2, text="  ->  ").pack(side="left")
        self.rep_to.pack(side="left")
        ttk.Button(row2, text="Add", command=self._rep_add).pack(side="left", padx=6)
        ttk.Button(row2, text="Remove selected", command=lambda: _tree_remove(self.rep_tree)).pack(side="left")
        self.rep_tree = ttk.Treeview(f, columns=("from", "to"), show="headings", height=5)
        self.rep_tree.heading("from", text="When I say")
        self.rep_tree.heading("to", text="Type")
        self.rep_tree.pack(fill="both", expand=True)
        for r in self.cfg.get("replacements", []):
            self.rep_tree.insert("", "end", values=(r["from"], r["to"]))

    def _snippets(self, f):
        ttk.Label(f, text="Say a trigger phrase and Aqua Lite types the full text - emails, links, addresses, "
                          "standard replies.", foreground="#555", wraplength=720).pack(anchor="w")
        form = ttk.Frame(f)
        form.pack(fill="x", pady=8)
        ttk.Label(form, text="Trigger phrase").grid(row=0, column=0, sticky="w")
        self.snip_trigger = ttk.Entry(form, width=30)
        self.snip_trigger.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Expands to").grid(row=1, column=0, sticky="nw", pady=4)
        self.snip_text = tk.Text(form, width=70, height=4, wrap="word")
        self.snip_text.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        btns = ttk.Frame(form)
        btns.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Button(btns, text="Add / update", command=self._snip_add).pack(side="left")
        ttk.Button(btns, text="Remove selected", command=lambda: _tree_remove(self.snip_tree)).pack(side="left", padx=6)
        self.snip_tree = ttk.Treeview(f, columns=("trigger", "text"), show="headings", height=8)
        self.snip_tree.heading("trigger", text="Say")
        self.snip_tree.heading("text", text="Types")
        self.snip_tree.column("trigger", width=180)
        self.snip_tree.column("text", width=520)
        self.snip_tree.pack(fill="both", expand=True)
        self.snip_tree.bind("<<TreeviewSelect>>", self._snip_load)
        self.snip_full = {}
        for s in self.cfg.get("snippets", []):
            self._snip_insert(s["trigger"], s["text"])

    def _history(self, f):
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.hq = ttk.Entry(top, width=36)
        self.hq.pack(side="left")
        self.hq.bind("<KeyRelease>", lambda _e: self._hist_load())
        ttk.Button(top, text="Copy", command=self._hist_copy).pack(side="left", padx=6)
        ttk.Button(top, text="Delete", command=self._hist_delete).pack(side="left")
        ttk.Button(top, text="Clear all", command=self._hist_clear).pack(side="right")
        cols = ("when", "app", "text")
        self.ht = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in zip(cols, (120, 110, 480)):
            self.ht.heading(c, text=c.title())
            self.ht.column(c, width=w, stretch=(c == "text"))
        self.ht.pack(fill="both", expand=True, pady=8)
        self.ht.bind("<Double-1>", lambda _e: self._hist_copy())
        self.hdetail = tk.Text(f, height=6, wrap="word")
        self.hdetail.pack(fill="x")
        self.ht.bind("<<TreeviewSelect>>", self._hist_show)
        self._hist_rows = {}
        self._hist_load()

    # ------------------------------------------------------------------ actions
    def _dict_add(self):
        w = self.dict_entry.get().strip()
        if w and w not in self.dict_list.get(0, "end"):
            self.dict_list.insert("end", w)
        self.dict_entry.delete(0, "end")

    def _dict_remove(self):
        for i in reversed(self.dict_list.curselection()):
            self.dict_list.delete(i)

    def _rep_add(self):
        a, b = self.rep_from.get().strip(), self.rep_to.get().strip()
        if a:
            self.rep_tree.insert("", "end", values=(a, b))
            self.rep_from.delete(0, "end")
            self.rep_to.delete(0, "end")

    def _snip_insert(self, trig, text):
        iid = self.snip_tree.insert("", "end", values=(trig, text.replace("\n", " / ")[:120]))
        self.snip_full[iid] = (trig, text)

    def _snip_add(self):
        trig, text = self.snip_trigger.get().strip(), self.snip_text.get("1.0", "end").rstrip("\n")
        if not trig or not text:
            return
        for iid, (t, _x) in list(self.snip_full.items()):
            if t.lower() == trig.lower():
                self.snip_tree.delete(iid)
                del self.snip_full[iid]
        self._snip_insert(trig, text)
        self.snip_trigger.delete(0, "end")
        self.snip_text.delete("1.0", "end")

    def _snip_load(self, _e=None):
        sel = self.snip_tree.selection()
        if sel and sel[0] in self.snip_full:
            t, x = self.snip_full[sel[0]]
            self.snip_trigger.delete(0, "end")
            self.snip_trigger.insert(0, t)
            self.snip_text.delete("1.0", "end")
            self.snip_text.insert("1.0", x)

    def _hist_load(self):
        self.ht.delete(*self.ht.get_children())
        self._hist_rows = {}
        for row in history.recent(400, self.hq.get().strip()):
            rid, ts, app, mode, final, raw = row[:6]
            when = datetime.datetime.fromtimestamp(ts).strftime("%b %d  %H:%M")
            label = (("[cmd] " if mode == "command" else "") + (final or "(no speech)")).replace("\n", " ")
            iid = self.ht.insert("", "end", values=(when, app, label[:200]))
            self._hist_rows[iid] = row

    def _hist_show(self, _e=None):
        sel = self.ht.selection()
        if not sel:
            return
        rid, ts, app, mode, final, raw, secs, words, engine, lat, status = self._hist_rows[sel[0]]
        self.hdetail.delete("1.0", "end")
        self.hdetail.insert("1.0", f"{final}\n\n--- raw ({engine}, {secs:.1f}s audio, {lat:.2f}s processing, {status}) ---\n{raw}")

    def _hist_copy(self):
        sel = self.ht.selection()
        if sel:
            self.win.clipboard_clear()
            self.win.clipboard_append(self._hist_rows[sel[0]][4])
            self.status.configure(text="Copied to clipboard")

    def _hist_delete(self):
        for iid in self.ht.selection():
            history.delete(self._hist_rows[iid][0])
        self._hist_load()

    def _hist_clear(self):
        if messagebox.askyesno(APP_NAME, "Delete your whole dictation history?", parent=self.win):
            history.clear()
            self._hist_load()

    def _test_ai(self):
        cfg = self._collect()
        self.status.configure(text="Testing...")

        def run():
            try:
                out = llm.format_text(cfg, "um so I think we should uh meet at 5 no wait 6 pm tomorrow",
                                      {"app": "Slack", "title": "", "category": "work"})
                msg = f"AI OK ({llm.resolve_provider(cfg)}): {out}"
            except Exception as e:
                msg = f"AI test failed: {e}"
            self.win.after(0, lambda: self.status.configure(text=msg[:140]))
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------ save
    def _collect(self):
        cfg = dict(self.cfg)
        for k, var in self.v.items():
            cfg[k] = var.get().strip() if isinstance(var.get(), str) else var.get()
        if cfg.get("mic_device") == "(Windows default)":
            cfg["mic_device"] = ""
        cfg["language"] = self.lang.get_key()
        cfg["editing_strength"] = self.strength.get_key()
        cfg["styles"] = {k: cb.get_key() for k, cb in self.style_boxes.items()}
        cfg["dictionary"] = list(self.dict_list.get(0, "end"))
        cfg["local_ai_model"] = self._ai_key()
        try:
            self._mem_save_typed()
        except (tk.TclError, AttributeError, OSError):
            pass
        cfg["context_blocked_apps"] = [a.strip().lower().removesuffix(".exe") for a in self.blocked.get().split(",")
                                       if a.strip()]
        cfg["replacements"] = [{"from": str(self.rep_tree.item(i)["values"][0]), "to": str(self.rep_tree.item(i)["values"][1])}
                               for i in self.rep_tree.get_children()]
        cfg["snippets"] = [{"trigger": t, "text": x} for t, x in
                           (self.snip_full[i] for i in self.snip_tree.get_children() if i in self.snip_full)]
        return cfg

    def save(self):
        cfg = self._collect()
        try:
            for k in ("hotkey_ptt", "hotkey_handsfree_key", "hotkey_command_key", "hotkey_paste_last", "hotkey_cancel",
                      "hotkey_undo_last"):
                hotkeys.parse(cfg[k])
            float(cfg.get("handsfree_silence_secs") or 0)
            if cfg.get("private_mode") and not localai.ready(cfg.get("local_ai_model", localai.DEFAULT_MODEL)):
                raise ValueError("private mode needs the selected AI model downloaded first (Private tab)")
            if cfg.get("instant_text_engine") == "gpu" and not gpu.libraries_installed():
                raise ValueError("set up the graphics card first (Instant text tab), or pick another option")
            if cfg.get("instant_text_engine") == "deepgram" and not cfg.get("deepgram_api_key", "").strip():
                raise ValueError("instant text with Deepgram needs a Deepgram API key (Instant text tab)")
        except ValueError as e:
            messagebox.showerror(APP_NAME, f"Setting problem: {e}", parent=self.win)
            return
        self.app.apply_settings(cfg)
        self.status.configure(text="Saved")


def _open_folder(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


def _tree_remove(tree):
    for iid in tree.selection():
        tree.delete(iid)


def _safe_devices():
    try:
        from .audio import list_input_devices
        return list_input_devices()
    except Exception:
        return []
