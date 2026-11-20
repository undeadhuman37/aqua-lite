# Aqua Lite - notes for Claude Code

Aqua Lite is a free, open-source voice dictation app (a Wispr Flow-style tool) for Windows, with a first macOS port
(untested on a real Mac). Styled Frutiger Aero: glossy sky-blue glass (optional Liquid Glass theme). Python with Tk/ttk
and Pillow; the Flow bar can also draw through OpenGL (moderngl).

## Rules

- Work on `main` (`v2` was the 2.0 branch; it's merged and retired). Commit freely; push only when the owner says
  so. A VERSION change pushed to `main` publishes a release to every user (see Release), so change it only for a
  release the owner approved.
- Keep the owner's name and personal details out of code, commits and docs.
- Never read or ask for `%APPDATA%\AquaLite` (logs, settings and API keys). The owner declined access to it. For a
  log, ask them to use **Report a problem** in the app (it strips dictated text).
- Changes go onto the owner's PC (installed copy at `%LOCALAPPDATA%\AquaLite\app`) only after they say so. Before
  overwriting a file there, check it still matches what you expect (mtime guard), and check the result byte for byte.
- Line length 120. User-facing text: sentence case, plain words, no periods on short labels.

## Code map (`aqualite/`)

Every module starts with a docstring saying what it does; big files are split by `# ----- name` section headers
(`grep -n "# ---" aqualite/app.py` gives a table of contents).

| Area | Modules |
|---|---|
| Entry and wiring | `AquaLite.pyw` (starts it), `app.py` (`App`: events from the hotkey thread go through `post()` -> `ev_*` on the Tk thread; slow work goes to the `_worker` thread via `self.jobs`) |
| Shortcuts | `hotkeys.py` (pure state machine on Windows VK codes; the Mac tap translates into them) |
| Recording and speech | `audio.py` (16 kHz mic), `stt.py` (Groq/OpenAI/local Whisper), `live.py` (live words + quick instant-text model), `gpu.py` (NVIDIA engine) |
| Instant text and editing | `instant.py` (typing while you talk, `Polisher`, `safe_to_replace`), `edits.py` (edit by voice), `voicecmd.py` (voice commands, run by `App._voice_*`) |
| AI | `llm.py` (prompts and providers), `localai.py` (private mode, llama.cpp), `memory.py` (style profile), `learn.py` (learning from corrections), `context.py` (screen context) |
| Text rules | `textproc.py` (pure: paste keys, app categories by process name, cleanup, snippets) |
| Flow bar | `overlay.py` (`FlowBar`: state, animation, frame pacing), `aero.py` / `liquid.py` (Pillow drawing per theme), `glbar.py` (same frames on the graphics card) |
| Settings window | `ui.py` (`SettingsWindow`; `PAGES` maps each sidebar page to its builder method, e.g. "Dictation" -> `_general`), `skin.py` / `liquidskin.py` (drawn controls per theme), `permissions.py` (Mac permissions window) |
| Other UI | `tray.py` (tray / menu bar icon), `sounds.py`, `music.py` |
| Storage and upkeep | `config.py` (`DEFAULTS`, `MAC_DEFAULTS`, data folder), `history.py` (SQLite), `updater.py`, `deps.py`, `report.py` |
| Operating system | `osapi/` (see below), `winapi.py` (raw Windows calls, used only by `osapi/win.py`) |
| Checks | `selftest.py` (one `check_*` function per area, listed in `main()`) |

Outside `aqualite/`: `install.bat` / `uninstall.bat` and `installer/` (Windows), `install-mac.sh` / `uninstall-mac.sh`
(Mac), `docs/MAC.md` (Mac status and tester checklist), `.claude/skills/liquid-glass/` (theme guide).

## Where to change what

| To change... | Look in |
|---|---|
| A default setting | `config.DEFAULTS` (Mac-only defaults: `config.MAC_DEFAULTS`); its Settings control in `ui.py` |
| A shortcut name or rule | `hotkeys.KEY_NAMES` / `HotkeyMachine`; Mac key codes in `osapi/mac.py` `MAC_TO_VK` |
| Anything that touches the OS (keys, clipboard, focused app, windows, theme) | add it to `osapi/other.py`, `win.py` and `mac.py` (the self-test fails if one lacks a name) |
| How an app is treated (terminal, email, slow paste) | `textproc.py` lists (Windows process names; `mac.py` `BUNDLE_NAMES` maps Mac apps onto them) |
| AI wording | `llm.py` prompts |
| A voice command | `voicecmd.py` (`SITES`, `SEARCH`, `KEYS`, the regexes; `parse` is pure and self-tested); what the AI may answer: `llm.VOICE_COMMAND_SYSTEM`; running it: `App._voice_command` |
| The Flow bar's look | `aero.FlowBarRenderer` / `liquid.LiquidBarRenderer` (`render()` for Pillow, `scene()` for `glbar`) |
| A Settings page | the builder named in `ui.PAGES` |

## Testing

- Self-test: `python -c "from aqualite import selftest; selftest.main()"` from the repo root. It must pass before
  anything is installed or released. It compiles every file, but doesn't run `app.py`: also run
  `python -m pyflakes aqualite/` (that's how a broken `if/else` in `app.py` was caught).
- On Windows: the installed venv `%LOCALAPPDATA%\AquaLite\venv\Scripts\python.exe` has every package. Use it to run
  things, never install into it. The self-test's Windows checks briefly use the real clipboard (and put it back).
- On Linux: `python3-tk` (apt) gives tkinter for `/usr/bin/python3.12`; `pip install -r requirements.txt` plus
  `pyflakes`. Run anything that opens a window under `xvfb-run -a -s "-screen 0 1280x800x24"` (Mesa's llvmpipe gives
  OpenGL 4.5, so the graphics-card Flow bar runs and can be compared with the Pillow drawing).
- `winapi.py` only imports on Windows; test its pure functions by exec'ing them alone or with injected helpers.
- Files are stored with LF, checked out CRLF on Windows (`core.autocrlf`); `*.sh` stay LF (`.gitattributes`).

## Platform layer (`aqualite/osapi/`)

- App code does `from . import osapi` and calls `osapi.paste(...)`, `osapi.foreground()`, `osapi.Overlay(...)`.
  `osapi/__init__.py` picks `win.py`, `mac.py` or `other.py` the first time a name is used, so Windows never loads
  PyObjC. Flags: `osapi.SUPPORTED` (can type into other apps), `IS_WIN`, `IS_MAC`, `CAN_RELEASE_KEYS`, `PASTE_KEYS`.
- `other.py` is the interface list (does nothing; Linux). `win.py` = `winapi.py` + UI Automation (moved there from
  instant/learn/context). `common.py` = pure clipboard-restore rules shared by both.
- `mac.py` has never run on a Mac: each section is marked `UNTESTED`. It imports anywhere (PyObjC optional), so the
  self-test checks its pure parts on Windows. Don't call `winapi` from app code.

## What's in the app beyond plain dictation (2.0 and 2.1)

1. **Instant text** (`instant.py`): words are typed while you talk (engines: quick processor model `live.py`,
   NVIDIA `gpu.py`, Deepgram). `Polisher` tidies each finished sentence with the AI (the next sentence is passed as
   context so "actually, make that Thursday" still corrects it) and swaps it in place; with the quick model each
   sentence's audio is first re-heard by the main speech engine (`App._rehear`). Letting go runs `App._quick_finish`:
   a last pass over the end, tidy the last sentence, `LiveTyper.settle` changes only what differs. Option
   `instant_text_recheck` restores the old full re-transcription. Every edit is guarded by reading the box
   (`text_before_caret`, through `osapi`); `_box_matches` waits for busy web editors to catch up before deciding the
   user changed the box.
2. **Edit by voice** (`edits.py`, `App._voice_edit`): Command Mode with nothing selected edits the text box.
3. **Private mode** (`localai.py`): a llama.cpp model run by the app; formatting, style memory, screen context,
   Command Mode and voice editing all go to it. Speech is local too, and Deepgram is never used in private mode.
4. **Memory profile** (`memory.py`): learned edits become a readable, editable per-category style profile;
   export/import moves it to another PC.
5. **New look** (`skin.py`, `ui.py`, `aero.py`, `overlay.py`, `glbar.py`, `winapi.Frost`): sidebar Settings with
   Pillow-drawn controls (drawn solid on their surface with wide 9-slice middles: see-through or tiny-middle images
   made Settings unusably slow on Windows); frosted Flow bar with Windows blur behind it (Windows 10 only: Windows 11
   draws the glass itself); the bar's frames are put together on the graphics card (`FlowBarRenderer.scene()` ->
   `glbar.GLBar`), falling back to Pillow if a test frame doesn't match or anything fails.
6. **Liquid Glass theme** (optional; Frutiger Aero stays the default and unchanged): Settings > Dictation > Theme
   (`look` aero | liquid, `look_mode` system | light | dark). Flow bar: `liquid.LiquidBarRenderer` (springs and
   shape-morphing drawn by `glbar` LGLASS while moving, cached pictures at rest; Pillow fallback). Settings window:
   `liquidskin.Skin(mode)` mirrors `skin.py`, `ui.apply_style`/`apply_liquid_style`, a glass sidebar with a gliding
   bead, sliding switches (styles `Slide0..7.TCheckbutton`), dark title bar, live Flow bar preview. The window is
   rebuilt when the look changes. `osapi.watch_theme` follows light/dark and transparency without polling.
   Guide: `.claude/skills/liquid-glass/SKILL.md`.
7. **What's new page** (Settings and tray): built from the CHANGELOG entry (`config.whats_new_full`); opens by itself
   once after a major update.
8. **Voice commands** (2.1, `voicecmd.py`, `App._voice_*`): `hotkey_voice_commands` toggles hands-free listening.
   `_voice_listen` (on each `_pump`) hands each pause-ended utterance to the worker with `Recorder.take()`, so the
   mic never stops. `voicecmd.parse` turns it into open a site/search, open an app (`osapi.installed_apps` /
   `launch_app`, matched by `voicecmd.find_app`), press keys (`osapi.press_shortcut`), type, write (AI) or edit
   (`_voice_edit`); anything else goes through `llm.voice_command` and is parsed again. The Flow bar stays in the
   "command" state (`FlowBar.rest`, so toasts return to it).

Also: the clipboard is restored only after the paste has landed (`osapi/common.restore_when_pasted`), which
fixed long dictations pasting the user's old clipboard.

## Release

Released so far: 2.0.0 "New Generation Update", 2.1.0 (voice commands). To release (only with the owner's OK):
add a `## <version>` or `## <version> - <name>` entry at the top of `CHANGELOG.md` (its first line is the in-app
"what's new" toast, under 52 characters), set `VERSION`, self-test, push `main`. A VERSION change on `main` runs
`.github/workflows/installer.yml`: the Windows installer plus `AquaLite-Mac.zip`, with fixed-name copies
(`AquaLite-Setup.exe`, `AquaLite-Mac.zip`) that the README buttons link to through `releases/latest/download/`.
`mac-check.yml` runs the Mac installer and self-test on GitHub's macOS runner.

Still to confirm: dictating with private mode on (the download works since the llama.cpp pre-release fix). Windows 11
can't blur behind a rounded shape, so the Flow bar has no blur window there (`winapi.Frost.shapes_ok`).
