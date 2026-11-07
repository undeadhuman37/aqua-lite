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
    "show_idle_bar": False,              # False = the Flow bar only appears while you're dictating
    "whisper_boost": True,               # auto-gain for quiet / whispered speech
    "add_trailing_space": True,
    "launch_at_startup": False,
    "restore_clipboard": True,
    "shift_insert_in_editors": False,    # Wispr's "shift-insert" flag: Shift+Insert in Code/Cursor/Windsurf
    "max_handsfree_minutes": 10,
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
