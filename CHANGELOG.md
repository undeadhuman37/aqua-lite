# What's new in Aqua Lite

Headings are `## <version>` or `## <version> - <update name>`. The first line under each heading is what the app
shows once after updating (keep it under 52 characters).

## 2.1.0
voice commands: "go to Google", hands-free
- **Voice commands:** press `Alt + Shift + C` (Mac: `Ctrl + Cmd + C`) and talk to your computer. "Go to YouTube",
  "open Spotify", "search for cheap flights", "new tab", "scroll down", "type hello", "write an email to Sam saying I'll be late",
  "make it shorter". It keeps listening after each command until you press the shortcut again or say "stop
  listening". With an AI key (or private mode) it also understands commands said in your own words.

## 2.0.0 - New Generation Update
now on Mac, with a new look and words as you talk
- **Now on Mac:** download `AquaLite-Mac.zip` and double-click **Install Aqua Lite**. It sets up everything, Python
  included, and puts Aqua Lite in your menu bar. Hold Fn (the globe key) and talk. Mac support is brand new, so tell
  us if anything feels off.
- **Two looks:** keep the classic Frutiger Aero, or switch to Liquid Glass in Settings > Dictation > Theme. Liquid
  Glass is clear glass with a bright rim, in light, dark or matching Windows, and the preview shows it before you save.
- **The Flow bar flows:** in Liquid Glass it springs open, melts from shape to shape, breathes while it thinks, and the
  live-words bubble grows out of it. Turn off Windows' animation effects and it fades instead.
- **A new Settings window:** a sidebar of pages, and in Liquid Glass a sheet of glass with a highlight that glides
  between them, switches that slide, and a dark mode with a dark title bar.
- **Instant text (optional, off by default):** your words are typed while you talk and each sentence is tidied as you
  go. It's still a bit jittery, so turn it on in Settings > Instant text if you'd like to try it.
- **Edit by voice:** hold the Command Mode shortcut with nothing selected and say "delete the last sentence" or
  "change Thursday to Friday".
- **Private mode:** an AI model that runs on your PC does the formatting, Command Mode and voice editing, and speech
  stays on your PC too. Nothing you say leaves it.
- **Your style, written down:** what Aqua Lite learns from your edits becomes a short style profile per kind of app
  that you can read, change, and take to another PC.
- **Follows Windows:** Liquid Glass switches light or dark with Windows right away. On Windows 10 the Flow bar
  softly blurs what's behind it; Windows 11 can't blur a rounded shape, so there the glass is drawn on its own.
- **Fixes:** long dictations no longer paste your old clipboard, and the Flow bar draws on the graphics card for
  smoother motion with less work for your processor.

## 1.5.0 - Gets To Know You Update
learns how you write and reads the chat you reply to
- **Learns how you write:** when you reword what Aqua Lite typed (lowercase, no full stops, "5:30pm", fewer
  exclamation marks), it remembers and writes that way next time. See what it learned, or forget it, in Settings > Style.
- **Understands the conversation (optional, off by default):** turn it on in Settings > Style and Aqua Lite reads
  the chat you're replying to, so names, spellings, topic and tone fit.
- **Command Mode can reply:** with the conversation option on, say "reply to this saying I'm in" with nothing selected.

## 1.4.0 - High Hertz Update
silky Flow bar at your monitor's full refresh rate
- **Runs at your monitor's refresh rate:** 60, 144, 240, 360 Hz and up. Every frame is timed to land exactly
  when your screen refreshes, so motion stays smooth on any display.
- **Draws about 3x faster,** so even 240 and 360 Hz screens get a fresh frame on (almost) every refresh.
- **Sharper text** on the bar, with a soft shadow instead of a rough one.
- **The waveform glides** instead of jumping, and the bars no longer flicker on every sound.
- **Smooth fades** between listening, thinking and done, and the live-words bubble fades in and out.

## 1.3.1
new app icon and a "Report a problem" button
- **New icon** that shows up properly everywhere: the installer, Start menu, Desktop, taskbar and tray.
  The old one could appear blank in Windows Explorer.
- **Report a problem** in the tray menu: copies a report for the developer (version, settings, recent log) with
  everything you dictated, your API keys, dictionary and Windows user name removed. It opens so you can see what's in it.

## 1.3.0 - Quality of Life Update
live words, learns your fixes, undo & more
- **Live words:** see what you're saying in a small bubble above the bar while you talk (offline preview model, no API calls).
- **Learns your corrections:** fix a word right after dictating ("Kaitlin" to "Kaitlyn") and it's added to your dictionary.
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
