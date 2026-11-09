"""Settings: defaults, load/save. Stored in %APPDATA%\\AquaLite\\config.json."""
import copy
import json
import os
import threading

APP_NAME = "Aqua Lite"


def _read_version():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"),
                  encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "1.0.0"


VERSION = _read_version()   # the VERSION file at the repo root; bump it to ship an update


def whats_new(version):
    """(update name, one-line summary) from the '## <version> - <name>' entry in CHANGELOG.md, shown once after
    an update. ("", "") if there's no entry."""
    import re
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md"),
                  encoding="utf-8") as f:
            lines = [line.strip() for line in f]
    except OSError:
        return "", ""
    head = re.compile(r"^##\s+" + re.escape(version) + r"(?:\s+[-\u2013\u2014]\s+(.+))?$")
    for i, line in enumerate(lines):
        m = head.match(line)
        if m:
            summary = next((x for x in lines[i + 1:] if x and not x.startswith("#")), "")
            return (m.group(1) or "").strip()[:40], summary[:52]
    return "", ""


def data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "AquaLite")
    old = os.path.join(base, "Flowlite")  # the app's previous name: carry settings and history over
    if not os.path.exists(d) and os.path.isdir(old):
        try:
            os.rename(old, d)
        except OSError:
            pass
    os.makedirs(d, exist_ok=True)
    return d


CONFIG_PATH = os.path.join(data_dir(), "config.json")

DEFAULTS = {
    # --- Shortcuts (key names joined with +; see hotkeys.KEY_NAMES) ---
    "hotkey_ptt": "ctrl+win",            # hold to talk (Wispr Flow's Windows default)
    "hotkey_handsfree_key": "space",     # add this while holding the PTT keys -> hands-free (locked) recording
    "hotkey_command_key": "alt",         # add this while holding the PTT keys -> Command Mode
    "hotkey_paste_last": "alt+shift+z",  # paste the last transcript again
    "hotkey_cancel": "esc",              # cancel while recording
    "hotkey_undo_last": "alt+shift+x",   # remove the text of the last dictation
    "double_tap_handsfree": True,        # tap the push-to-talk keys twice -> hands-free

    # --- Speech to text ---
    "stt_engine": "auto",                # auto | groq | openai | local
    "language": "auto",                  # auto, or a code like en, ar, fr...
    "local_model": "small",              # tiny | base | small | medium | large-v3-turbo
    "local_device": "auto",              # auto | cpu | cuda
    "groq_stt_model": "whisper-large-v3-turbo",
    "openai_stt_model": "gpt-4o-mini-transcribe",

    # --- AI formatting (Wispr's "formatter") ---
    "ai_provider": "auto",               # auto | groq | openai | anthropic | custom | off
    "groq_api_key": "",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "custom_base_url": "http://localhost:1234/v1",   # any OpenAI-compatible server (LM Studio, Ollama...)
    "custom_api_key": "",
    "groq_llm_model": "openai/gpt-oss-120b",
    "openai_llm_model": "gpt-5-mini",
    "anthropic_llm_model": "claude-haiku-5-5",
    "custom_llm_model": "local-model",
    "editing_strength": "medium",        # verbatim | light | medium | heavy
    "styles": {                          # per app category: formal | casual | very_casual | excited
        "personal": "casual",
        "work": "casual",
        "email": "formal",
        "other": "formal",
    },
    "code_mode": True,                   # keep identifiers/filenames exact in code editors & terminals

    # --- Personalisation ---
    "dictionary": [],
    "replacements": [],                  # [{"from": "...", "to": "..."}]
    "snippets": [],                      # [{"trigger": "my email", "text": "..."}]

    # --- Music while you talk (your own songs) ---
    "music_enabled": True,
    "music_volume": 30,                  # percent of full volume
    "music_folder": "",                  # "" = %APPDATA%\\AquaLite\\music

    # --- Behaviour ---
    "mic_device": "",                    # "" = Windows default input
    "sounds": True,
    "frosted_glass": True,
    "gpu_flow_bar": True,                # draw the Flow bar on the graphics card (falls back to the processor)               # the Flow bar is see-through glass and Windows blurs what's behind it
    "show_idle_bar": False,              # False = the Flow bar only appears while you're dictating
    "whisper_boost": True,               # auto-gain for quiet / whispered speech
    "add_trailing_space": True,
    "launch_at_startup": False,
    "restore_clipboard": True,
    "shift_insert_in_editors": False,    # Wispr's "shift-insert" flag: Shift+Insert in Code/Cursor/Windsurf
    "max_handsfree_minutes": 10,
    "handsfree_silence_secs": 8,         # hands-free finishes after this much silence (0 = never)
    "voice_enter": True,                 # end with "press enter" / "send it" to press Enter after typing
    "live_preview": True,                # show your words in the bar while you talk
    "private_mode": False,               # speech + AI formatting all on this PC (model built in, see localai.py)
    "local_ai_model": "qwen3-4b",        # which private-mode model
    "private_idle_minutes": 10,          # free the private AI's memory after this long unused (0 = keep loaded)
    "instant_text_engine": "off",        # words appear while you talk: off | preview | gpu | deepgram (see instant.py)
    "deepgram_api_key": "",              # for the Deepgram instant-text engine
    "gpu_model": "auto",                 # graphics-card engine model: auto (picked for the card) or a gpu.MODELS name
    "gpu_idle_minutes": 5,               # free the graphics card after this long without talking (0 = keep loaded)
    "instant_text_model": "auto",        # auto = "small" if this PC is fast enough, else "base"
    "instant_text_recheck": False,       # when you let go: re-run the whole recording (slower) instead of finishing the tidied text
    "instant_text_skip_apps": [],        # process names to always insert at the end instead (code editors already are)
    "live_preview_model": "base",        # small fast offline model used only for the preview
    "learn_corrections": True,           # add words you fix right after dictating to the dictionary
    "learn_style": True,                 # remember how you reword dictations (kept on this PC) and show the AI
    "screen_context": False,             # read the conversation on screen so names/topic/tone fit (sent to the AI)
    "context_blocked_apps": ["1password", "bitwarden", "keepass", "keepassxc", "lastpass", "dashlane", "enpass",
                             "keeper", "mstsc", "credentialuibroker", "consent", "logonui"],
    "last_seen_version": "",
    "auto_update": True,                 # check GitHub for a newer version every time Aqua Lite starts
    "first_run": True,
    "settings_version": 2,
}

_lock = threading.Lock()


class Config(dict):
    def save(self):
        with _lock:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_PATH)


def _merge(defaults, loaded):
    out = copy.deepcopy(defaults)
    for k, v in (loaded or {}).items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def load():
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
    cfg = Config(_merge(DEFAULTS, data))
    if data and int(data.get("settings_version", 1)) < 2:
        # v2: the bar hides when idle and only shows while dictating (it used to stay on screen)
        cfg["show_idle_bar"] = False
        cfg["settings_version"] = 2
    mf = cfg.get("music_folder") or ""
    if mf and not os.path.isdir(mf) and "Flowlite" in mf:  # path saved under the app's old name
        cfg["music_folder"] = mf.replace("Flowlite", "AquaLite")
    # Environment variables work too (handy for testing)
    for key, env in (("groq_api_key", "GROQ_API_KEY"), ("openai_api_key", "OPENAI_API_KEY"),
                     ("anthropic_api_key", "ANTHROPIC_API_KEY")):
        if not cfg.get(key) and os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg
