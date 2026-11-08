# What's new in Aqua Lite

Headings are `## <version>` or `## <version> - <update name>`. The first line under each heading is what the app
shows once after updating (keep it under 52 characters).

## 1.3.2
smoother Flow bar and sharper text
- The Flow bar now runs at your monitor's full refresh rate (60, 144, 240 Hz and up), with every frame
  timed to land exactly when the screen refreshes.
- Sharper, cleaner text on the bar, with a soft shadow instead of a rough one.
- The waveform glides smoothly instead of jumping, and the bars no longer flicker on every sound.
- The bar fades between states (listening, thinking, done) instead of snapping, and the live-words bubble fades in and out.

## 1.3.1
new app icon and a "Report a problem" button
- **New icon** that shows up properly everywhere: the installer, Start menu, Desktop, taskbar and tray.
  The old one could appear blank in Windows Explorer.
- **Report a problem** in the tray menu: copies a report for the developer (version, settings, recent log) with
  everything you dictated, your API keys, dictionary and Windows user name removed. It opens so you can see what's in it.

## 1.3.0 - Quality of Life Update
live words, learns your fixes, undo & more
- **Live words:** see what you're saying in a small bubble above the bar while you talk (offline preview model, no API calls).
- **Learns your corrections:** fix a word right after dictating ("Patrisio" to "Patricio") and it's added to your dictionary.
- **Say "press enter" or "send it"** at the end of a dictation to send the message after it's typed.
- **Double-tap `Ctrl + Win`** for hands-free.
- **Hands-free stops by itself** after 8 seconds of silence (change it in Settings).
- **Undo last dictation:** `Alt + Shift + X` removes the text Aqua Lite just typed.
- **One-click installer:** `AquaLite-Setup.exe`, no Python needed beforehand.
- Alt + Shift shortcuts no longer switch your keyboard language.

## 1.2.1
updates show up the moment they're released
- The updater asks GitHub for the newest commit, so it never sees a stale version.

## 1.2.0
the bar slides in and out from the screen edge
- The Flow bar slides up from under the bottom of the screen and tucks back down.

## 1.1.0
auto-updates and a hidden bar
- Aqua Lite updates itself when it starts. The bar only appears while you're dictating.
