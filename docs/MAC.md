# Aqua Lite on a Mac

Mac support is written but **has never been run on a Mac**. It was built on Windows without one. This page
says what's done, what has actually been checked, and what a Mac tester should try.

## How it fits together

Everything that talks to the operating system goes through `aqualite/osapi/`:

| File | Used on | What it is |
|---|---|---|
| `osapi/__init__.py` | everywhere | picks the file below for this system the first time a name is used |
| `osapi/win.py` | Windows | the existing `winapi.py` plus UI Automation, under the shared names |
| `osapi/mac.py` | macOS | PyObjC: Quartz event tap, NSPasteboard, Accessibility (AXUIElement), NSPanel |
| `osapi/other.py` | Linux (tests) | does nothing, so the app and self-test still run; the reference list of names |
| `osapi/common.py` | everywhere | pure clipboard-restore rules shared by Windows and Mac |

Windows never imports PyObjC and a Mac never imports comtypes. The self-test checks that every name in `other.py`
exists in `win.py` and `mac.py`.

The shortcut logic (`hotkeys.py`) is shared: the Mac tap turns Mac key codes into the same Windows key codes.
Command counts as the Win key, Option as Alt, and Fn (the globe key) has a code of its own.

## What has been checked, and what hasn't

Checked on Windows (self-test and a smoke run):
- The Mac file imports without PyObjC, and its pure parts work: the key-code table, reading Fn/Cmd/Option
  from event flags, the login item file, the Retina screen maths, app names (Google Chrome -> chrome).
- The Mac shortcuts in `hotkeys.py`: hold Fn to talk, Fn + Space for hands-free, Fn + Cmd for Command Mode,
  Ctrl + Option instead of Fn; modifier keys are never swallowed.
- The shared clipboard-restore rules.

**Not run at all** (each section of `osapi/mac.py` is marked UNTESTED):

| Piece | How it works |
|---|---|
| Push-to-talk shortcut | Quartz event tap on its own thread (`KeyboardHook`) |
| Pasting | NSPasteboard save, Cmd+V posted with Quartz, old clipboard put back after the paste lands |
| Instant text typing | Unicode key events (`CGEventKeyboardSetUnicodeString`), Shift+Left to select |
| Reading the text box | Accessibility: `AXSelectedTextRange` + `AXStringForRange`, `AXSecureTextField` = password |
| Screen context | walks the focused window's accessibility tree for at most a second |
| Flow bar | borderless non-activating NSPanel above all apps and Spaces; each frame becomes its layer's picture |
| Menu bar icon | pystray (its Mac backend, started with `run_detached` inside Tk's loop) |
| Start at login | a LaunchAgent in `~/Library/LaunchAgents/com.aqualite.app.plist` |
| Light/dark | `AppleInterfaceThemeChangedNotification` and the Reduce transparency / Reduce motion switches |
| Permissions | a window listing what macOS still needs, with a button to each System Settings page |
| Private mode | downloads llama.cpp's macOS build (arm64 or x64) instead of the Windows one |
| Sounds | `afplay` |
| Installer | `install-mac.sh`, `uninstall-mac.sh` and the small `Aqua Lite.app` launcher it makes |

Not done on a Mac yet:
- **Frosted glass** (blur behind the bar). The glass is drawn solid, as on Windows 11. An `NSVisualEffectView`
  under the bar could add it later.
- The NVIDIA instant-text engine (no NVIDIA cards in Macs). The quick processor model and Deepgram still work.
- Signing and notarization (see below).

## What a Mac tester should try

Set up with `bash install-mac.sh` (see the README). Then, in order:

1. **It opens.** The Aqua Lite icon appears in the menu bar, there's no Dock icon, and the "Aqua Lite is ready"
   bar slides up at the bottom middle of the screen above the Dock.
2. **Permissions.** On first start a window lists Accessibility, Input Monitoring and the microphone. Each
   "Open System Settings" button opens the right page. After allowing "Aqua Lite" and reopening it, the window
   doesn't come back.
3. **Push-to-talk.** In TextEdit, hold Fn, say a sentence, let go. The text appears where the cursor is.
   Your clipboard still holds what you copied before.
4. **The emoji picker** doesn't open when you let go of Fn (after setting "Press fn key to: Do Nothing").
5. **Hands-free and cancel.** Fn + Space, let go, talk, then press Fn again. Esc cancels a recording.
6. **Command Mode.** Select some text, hold Fn + Cmd and say "make this shorter".
7. **Other apps.** Try Safari or Chrome (a text box on a web page), Notes, Slack or Discord, Mail, and Terminal.
   In Terminal the text should go in at the end without auto-formatting.
8. **Ctrl + Option.** In Settings > Dictation, set push-to-talk to `ctrl+option`, save, and try again.
9. **Instant text.** Settings > Instant text: pick the quick processor model. Words should appear while you
   talk and get tidied sentence by sentence. Try it in TextEdit and in a browser.
10. **Undo last dictation** (Ctrl + Cmd + X) and **paste last** (Ctrl + Cmd + V).
11. **The Flow bar.** Soft rounded edges (not a box), sharp on a Retina screen, never steals focus from the app
    you're typing in, visible over a full-screen app, and clicking the idle bar (Settings: keep the bar on screen)
    starts hands-free.
12. **Themes.** Switch to Liquid Glass and between light and dark in System Settings > Appearance: the bar follows.
13. **Start at login.** Turn on "Start Aqua Lite when I log in", log out and back in.
14. **Private mode.** Settings > Private mode: download the model and dictate with private mode on.
15. **Second launch.** Open Aqua Lite again from Applications while it's running: Settings comes to the front.

For anything that goes wrong, use **Report a problem** in the menu bar menu (it leaves out what you dictated)
and open a GitHub issue with it and the Mac model and macOS version.

## Things that may need fixing first

Educated guesses about where trouble is most likely:
- **The permission goes to the wrong app.** `Aqua Lite.app` is a small script that starts Python. If macOS lists
  "Python" instead of "Aqua Lite" in the permission lists, allow that, or build a proper app with py2app.
- **The event tap needs Input Monitoring even with Accessibility on**, or vice versa, depending on the macOS
  version. The shortcut listener says which in its log line ("macOS didn't allow the shortcut listener...").
- **pystray inside Tk's loop.** If the menu bar icon doesn't appear or menu clicks do nothing, the icon may need
  to be created after Tk's first loop turn.
- **Electron apps** (Slack, Discord, VS Code) only expose their text when asked (`AXManualAccessibility`); if
  instant text never trusts the box there, it will fall back to pasting at the end, which is safe.
- **Clicks through the hidden bar.** While hidden the bar ignores the mouse; if clicks near the bottom of the
  screen stop working, that's the place to look (`Overlay.show(clickable=...)`).
- **The bar on a second screen** with a different pixel density is drawn at the main screen's density.

## Signing and notarization (later)

Without an Apple Developer account ($99/year) the app can't be signed or notarized, so it's installed from
source by `install-mac.sh`; nothing is downloaded as a ready-made app, so Gatekeeper doesn't block it.

When there is an account:
1. Build a real app with py2app (`python setup.py py2app` with `LSUIElement`, `NSMicrophoneUsageDescription`
   and the bundle id `com.aqualite.app` in the plist, as `install-mac.sh` writes today).
2. Sign it with a Developer ID Application certificate and the hardened runtime:
   `codesign --deep --force --options runtime --sign "Developer ID Application: ..." "Aqua Lite.app"`.
   Entitlements: `com.apple.security.device.audio-input`; Python needs
   `com.apple.security.cs.allow-unsigned-executable-memory` and `com.apple.security.cs.disable-library-validation`.
3. Notarize and staple: `xcrun notarytool submit AquaLite.zip --keychain-profile ... --wait`, then
   `xcrun stapler staple "Aqua Lite.app"`.
4. A signed app keeps its permissions across updates; today, replacing the files can make macOS ask again.

## Updates on a Mac

The updater works the same way (it replaces the files in `~/Library/Application Support/AquaLite/app`). It
installs from the `main` branch, which doesn't have Mac support until 2.0 is released, but it only installs a
**newer** version, so a Mac copy on 2.0.0 won't be replaced by an older Windows-only one.
