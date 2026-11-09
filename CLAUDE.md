# Aqua Lite - notes for Claude Code

Aqua Lite is a free, open-source voice dictation app for Windows (a Wispr Flow-style tool), styled Frutiger Aero:
glossy sky-blue glass. Python with Tk/ttk and Pillow; the Flow bar can also draw through OpenGL (moderngl).

## Rules

- `v2` is the 2.0 work branch: commit there freely. Push or release to `main` only when the owner says so.
- Keep the owner's name and personal details out of code, commits and docs.
- Never read or ask for `%APPDATA%\AquaLite` (logs, settings and API keys). The owner declined access to it. For a
  log, ask them to use **Report a problem** in the app (it strips dictated text).
- Changes go onto the owner's PC (installed copy at `%LOCALAPPDATA%\AquaLite\app`) only after they say so. Before
  overwriting a file there, check it still matches what you expect (mtime guard), and check the result byte for byte.
- Line length 120. User-facing text: sentence case, plain words, no periods on short labels.

## Testing on Linux

- `python3-tk` (apt) gives tkinter for `/usr/bin/python3.12`; `pip install -r requirements.txt` plus `pyflakes`.
- Run anything that opens a window under `xvfb-run -a -s "-screen 0 1280x800x24"` (Mesa's llvmpipe provides
  OpenGL 4.5 there, so the graphics-card Flow bar runs and can be compared with the Pillow drawing).
- Self-test: `python3.12 -c "from aqualite import selftest; selftest.main()"` from the repo root. It must pass
  before anything is installed or released. Windows-only checks (clipboard, keyboard hook) run only on Windows.
- `winapi.py` only imports on Windows; test its pure functions by exec'ing them alone or with injected helpers.

## What 2.0 contains (on `v2`, not released)

1. **Instant text** (`instant.py`): words are typed while you talk (engines: quick processor model `live.py`,
   NVIDIA `gpu.py`, Deepgram). `Polisher` tidies each finished sentence with the AI (the next sentence is passed as
   context so "actually, make that Thursday" still corrects it) and swaps it in place; with the quick model each
   sentence's audio is first re-heard by the main speech engine (`App._rehear`). Letting go runs `App._quick_finish`:
   a last pass over the end, tidy the last sentence, `LiveTyper.settle` changes only what differs. Option
   `instant_text_recheck` restores the old full re-transcription. Every edit is guarded by reading the box through UI
   Automation (`text_before_caret`); `_box_matches` waits for busy web editors to catch up before deciding the user
   changed the box.
2. **Edit by voice** (`edits.py`, `App._voice_edit`): Command Mode with nothing selected edits the text box.
3. **Private mode** (`localai.py`): a llama.cpp model run by the app; formatting, style memory, screen context,
   Command Mode and voice editing all go to it. Speech is local too, and Deepgram is never used in private mode.
4. **Memory profile** (`memory.py`): learned edits become a readable, editable per-category style profile;
   export/import moves it to another PC.
5. **New look** (`skin.py`, `ui.py`, `aero.py`, `overlay.py`, `glbar.py`, `winapi.Frost`): sidebar Settings with
   Pillow-drawn controls (drawn solid on their surface with wide 9-slice middles: see-through or tiny-middle images
   made Settings unusably slow on Windows); frosted Flow bar with Windows blur behind it; the bar's frames are put
   together on the graphics card (`FlowBarRenderer.scene()` -> `glbar.GLBar`), falling back to Pillow if a test frame
   doesn't match or anything fails.

Also on `v2`: the clipboard is restored only after the paste has landed (`winapi._restore_when_pasted`), which fixed
long dictations pasting the user's old clipboard.

## Still open before releasing 2.0

- The owner hasn't yet dictated with private mode switched on (the model download itself works).
- Confirm on Windows: blur lines up behind the Flow bar, white text readable over white apps, title bar tinted on
  Windows 11, graphics-card Flow bar active (and CPU lower) once `moderngl` has installed itself.
- Release only when the owner approves: set `VERSION` to 2.0.0, write the CHANGELOG entry (first line 52 characters
  or fewer), update the README (mention instant text can be a bit jittery and is off by default), run the self-test,
  push to `main`, confirm the installer build.
