"""Aqua Lite main app: hotkey -> 16 kHz mic -> speech-to-text -> AI formatting -> paste -> restore clipboard."""
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser

from . import (audio, config, context, deps, edits, gpu, history, hotkeys, instant, learn, live, llm, localai, memory,
               music, osapi, report, sounds, stt, textproc, updater, voicecmd)
from .overlay import FlowBar

ON = osapi.SUPPORTED   # this system lets us type into other apps (Windows, macOS)

log = logging.getLogger("aqualite")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class App:
    def __init__(self, updated_to=None):
        self.cfg = config.load()
        self.updating = False
        self.last_insert = None   # what the last dictation typed, for "undo last dictation"
        self.events = queue.Queue()
        self.jobs = queue.Queue()
        self.recorder = audio.Recorder()
        self.music = music.MusicPlayer(self.cfg)
        self.machine = hotkeys.HotkeyMachine(self.cfg, self._on_hotkey)
        self.paused = False
        self.voice = False        # voice commands are listening (hands-free, until the shortcut is pressed again)
        self.voice_last = 0.0
        self.apps, self.apps_at = {}, 0.0   # installed apps for "open spotify" (read when voice commands start)
        self.rec_started = 0.0
        self.rec_command = False
        self.settings = None
        self.icon_path = os.path.join(HERE, "assets", "aqualite.ico")

        gpu.prepare()   # NVIDIA's libraries (if installed for instant text) must be findable before CUDA starts
        if ON:
            osapi.prepare_process()   # Windows: our own taskbar identity and logo, sharp on high-DPI screens
            self.cfg["launch_at_startup"] = osapi.startup_enabled()
        self.root = tk.Tk()
        self.root.withdraw()
        osapi.tk_ready(self.root)   # macOS: no Dock icon (the app lives in the menu bar)
        self.root.title("Aqua Lite")
        try:  # every window we open (Settings, History, dialogs) gets the Aqua Lite logo
            self.root.iconbitmap(default=self.icon_path)
        except tk.TclError as e:
            log.info("window icon not set: %s", e)
        self.bar = FlowBar(self.root, lambda: self.recorder.level, self._bar_clicked, self.cfg.get("show_idle_bar", False),
                           self.cfg.get("frosted_glass", True), self.cfg.get("gpu_flow_bar", True),
                           look=self.cfg.get("look", "aero"), look_mode=self.cfg.get("look_mode", "system"))
        self.live = live.LiveCaption(self.recorder, self.cfg, lambda text: self.post("caption", text))
        self.learner = learn.Learner(lambda words: self.post("learned", words), on_edited=self._edited)
        self.edit_where = ("", "other")   # app + category of the dictation being watched for edits
        self.grab = None                  # screen context being read for the current recording
        self.instant = None               # instant text: (streamer, (hwnd, proc, title, pid)) while typing live
        self.user_typed = False           # keys pressed by the user while instant text was typing

        self.tray = None
        try:
            from .tray import Tray
            self.tray = Tray(self)
            self.tray.start()
        except Exception as e:
            log.warning("tray unavailable: %s", e)

        self.hook = None
        if ON:
            self.hook = osapi.KeyboardHook(self._on_key)
            self.hook.start()
            self.hook.ok.wait(3)
            if self.hook.error:
                log.error(self.hook.error)

        if ON:
            osapi.watch_open_requests(lambda: self.post("open_settings"))
            osapi.watch_theme(lambda: self.post("windows_colours"))
            self.root.after(1200, self._check_permissions)
        threading.Thread(target=self._worker, daemon=True, name="worker").start()
        deps.ensure_in_background(self._deps_done)
        self._preload()
        self.root.after(15, self._pump)
        if self.cfg.get("first_run", True):
            self.cfg["first_run"] = False
            self.cfg.save()
            self.root.after(600, self.open_settings)
        ptt = self.cfg["hotkey_ptt"].upper().replace("+", " + ")
        ready, secs = f"Aqua Lite is ready - hold {ptt} and talk", 4
        if updated_to:
            ready = f"Updated to {updated_to} - hold {ptt} and talk"
        follow_up = None
        seen = self.cfg.get("last_seen_version")
        if seen and seen.split(".")[0] != config.VERSION.split(".")[0]:   # a big update: show what's new once
            self.root.after(1500, lambda: self.open_settings("What's new"))
        if self.cfg.get("last_seen_version") != config.VERSION:
            name, news = config.whats_new(config.VERSION)
            if news and self.cfg.get("last_seen_version"):
                if name:  # "Aqua Lite 1.3.0: Quality of Life Update", then what's in it
                    ready, secs, follow_up = f"Aqua Lite {config.VERSION}: {name}", 3.5, f"New: {news}"
                else:
                    ready, secs = f"New in {config.VERSION}: {news}", 7
            self.cfg["last_seen_version"] = config.VERSION
            self.cfg.save()
        self.root.after(900, lambda: self.bar.toast(ready, "ok", secs))
        if follow_up:
            self.root.after(900 + int(secs * 1000) + 150, lambda: self.bar.toast(follow_up, "ok", 6))
        if self.cfg.get("auto_update", True):
            self.root.after(5000, lambda: self.check_for_updates(manual=False))

    # ------------------------------------------------------------------ plumbing
    def _deps_done(self, ok, _any):   # background thread
        self.post("toast", "New features are set up" if ok else "Couldn't install a package - some features are off",
                  "ok" if ok else "warn", 4)
        if ok:
            self.post("gpu_bar")   # the graphics-card library may have just arrived: start using it now

    def ev_gpu_bar(self):
        if self.cfg.get("gpu_flow_bar", True) and self.bar.gl is None:
            self.bar.set_gpu(True)

    def post(self, name, *args):
        self.events.put((name, args))

    def _check_permissions(self):
        """macOS: say in plain words which permissions are still missing, with a button to each setting.
        Windows needs none, so this does nothing there."""
        try:
            problems = osapi.permission_problems()
        except Exception as e:
            log.info("permissions: couldn't check: %s", e)
            return
        if problems:
            log.warning("permissions missing: %s", ", ".join(p[0] for p in problems))
            from . import permissions
            permissions.show(self.root, problems, osapi.open_permission_settings)

    def ev_windows_colours(self):
        """Windows switched light/dark or transparency: the Flow bar follows now; an open Settings window set to
        Match Windows is rebuilt in the new colours. Several changes in a row are handled once."""
        if getattr(self, "_colours_job", None):
            self.root.after_cancel(self._colours_job)

        def apply():
            self._colours_job = None
            self.bar.windows_changed()
            s = self.settings
            if s and s.win.winfo_exists():
                s.follow_look()
        self._colours_job = self.root.after(300, apply)

    def _on_key(self, vk, is_down):  # runs on the hook thread: must be quick
        swallowed = self.machine.on_key(vk, is_down)
        if is_down and not swallowed and self.instant is not None and vk not in hotkeys.MODIFIER_VKS:
            self.user_typed = True   # they typed while words were going in live: don't trust the box blindly
            self.instant[0].stop_event.set()   # and stop typing into it right away
        return swallowed

    def _on_hotkey(self, name, command):  # runs on the hook thread: must be quick
        if name == "mask" and ON:
            threading.Thread(target=osapi.send_mask, daemon=True).start()
            return
        self.events.put(("hk_" + name, (command,)))

    def _pump(self):
        try:
            while True:
                name, args = self.events.get_nowait()
                try:
                    getattr(self, "ev_" + name)(*args)
                except Exception:
                    log.exception("event %s failed", name)
        except queue.Empty:
            pass
        if self.machine.recording and self.machine.locked and self.rec_started and \
                time.time() - self.rec_started > 60 * float(self.cfg.get("max_handsfree_minutes", 10)):
            self.machine.reset()
            self.ev_hk_stop(self.rec_command)
        quiet = float(self.cfg.get("handsfree_silence_secs", 8) or 0)
        if quiet > 0 and self.machine.recording and self.machine.locked and self.recorder.silent_for > quiet:
            log.info("hands-free: %.0fs of silence, finishing", quiet)
            self.machine.reset()
            self.ev_hk_stop(self.rec_command)
        if self.voice:
            self._voice_listen()
        self.root.after(15, self._pump)

    def _preload(self):
        if stt.resolve_engine(self.cfg) == "local":
            threading.Thread(target=self._safe_load, daemon=True).start()
        engine = self.cfg.get("instant_text_engine", "off")
        if self.cfg.get("live_preview", True) and engine == "off" and live.PREVIEW.model is None:
            live.PREVIEW.preload(self.cfg)   # with instant text on, the bubble only shows in code editors: load then
        if engine == "preview" and live.INSTANT.model is None:
            live.INSTANT.preload(self.cfg)
        elif engine == "gpu" and gpu.libraries_installed():
            gpu.GPU.preload(self.cfg)
        gpu.GPU.configure(self.cfg)   # model choice + idle time (frees the card if the engine was switched off)
        if engine != "gpu" and gpu.GPU.model is not None:
            gpu.GPU.unload("instant text switched to another option")
        localai.idle_secs = max(0.0, float(self.cfg.get("private_idle_minutes", 10) or 0)) * 60
        if llm.resolve_provider(self.cfg) == "local":  # load the private AI now, so the first dictation isn't slow
            threading.Thread(target=self._warm_local_ai, daemon=True, name="local-ai").start()
        elif not self.cfg.get("private_mode") and localai.running():
            threading.Thread(target=localai.stop, daemon=True).start()

    def _warm_local_ai(self):
        try:
            localai.ensure(llm._local_model(self.cfg))
        except Exception as e:
            log.warning("private mode: AI didn't start: %s", e)
            self.post("toast", "Private AI couldn't start - see Settings > Private", "error", 5)

    def _safe_load(self):
        try:
            stt.LOCAL.load(self.cfg)
            log.info("local model: %s", stt.LOCAL.status)
        except Exception as e:
            log.error("local model failed: %s", e)
            self.post("toast", f"Local speech model failed to load: {e}", "error")

    # ------------------------------------------------------------------ hotkey events
    def ev_hk_start(self, command):
        if self.voice:   # dictating takes the microphone over from voice commands
            self._voice_off()
        try:
            self.recorder.start(self.cfg.get("mic_device", ""))
        except Exception as e:
            self.machine.reset()
            log.exception("mic")
            self.bar.toast(f"Microphone error: {e}", "error", 5)
            return
        self.rec_started, self.rec_command = time.time(), command
        self.grab = None
        if llm.resolve_provider(self.cfg) == "local" and not localai.running():
            # the private AI was freed while idle: start it now, so it's ready by the time you finish talking
            threading.Thread(target=self._warm_local_ai, daemon=True, name="local-ai").start()
        if ON and self.cfg.get("screen_context", False):
            try:
                proc, title, _pid = osapi.foreground()
                self.grab = context.grab(osapi.foreground_window(), proc, title, self.cfg)
            except Exception as e:
                log.info("context: not started: %s", e)
        self.bar.set_state("command" if command else "recording")
        self.instant, self.user_typed = None, False
        if not command:
            self._start_instant()
        if self.instant is None:
            self.live.start()
        self.learner.stop()
        self._sound("start")
        self._music(True)
        self._tray("recording")

    def ev_hk_command(self, _command):
        self.rec_command = True
        self.bar.set_state("command")
        self._drop_instant()  # it's an instruction now, not text: take back anything typed live

    # ------------------------------------------------------------------ instant text
    def _start_instant(self):
        """Type words into the focused app while the user talks (see instant.py)."""
        cfg = self.cfg
        engine = cfg.get("instant_text_engine", "off")
        if engine == "deepgram" and cfg.get("private_mode"):
            engine = "preview"   # private mode: your voice never leaves this PC, so the on-PC engine types instead
        if not ON or engine not in ("preview", "gpu", "deepgram"):
            return
        model = None
        if engine == "preview":
            if live.INSTANT.failed:
                return
            if live.INSTANT.model is None or live.INSTANT.loading:  # still loading / picking: not this time
                live.INSTANT.preload(cfg)
                return
            model = live.INSTANT
        elif engine == "gpu":
            gpu.GPU.touch()
            if gpu.GPU.model is None:   # first time, or freed after a long idle: load now, live from the next one
                if gpu.libraries_installed():
                    gpu.GPU.preload(cfg)
                return
            model = gpu.GPU
        elif not cfg.get("deepgram_api_key"):
            return
        try:
            proc, title, pid = osapi.foreground()
            hwnd = osapi.foreground_window()
            p = proc.lower()
            if (textproc.app_category(proc, title) == "code" or p in textproc.TERMINALS
                    or p in context.ALWAYS_BLOCKED or p in {a.lower() for a in cfg.get("instant_text_skip_apps", [])}):
                return  # editors auto-complete and auto-close brackets while you type: insert at the end there
            if osapi.process_elevated(pid) and not osapi.self_elevated():
                return  # Windows blocks typing into admin windows
        except Exception as e:
            log.info("instant text: not started: %s", e)
            return

        def before_first():  # Ctrl+Win may still be held: let Windows think they're up, or letters become shortcuts
            if not osapi.CAN_RELEASE_KEYS:
                return   # macOS: typed keys carry no modifiers of their own, nothing to release
            held = self.machine.release_held()
            if held:
                osapi.release_keys(sorted(held))
                time.sleep(0.03)

        def type_here(text):  # only ever into the window the dictation started in
            return osapi.foreground_window() == hwnd and osapi.type_text(text)

        def backspace_here(n):
            if osapi.foreground_window() != hwnd:
                return False
            osapi.tap_key("backspace", n)
            return True

        def box_ends_with(text):  # True / False, or None if this box can't be read
            before, exact = instant.text_before_caret(len(text))
            if before is None:
                return None
            return instant.safe_to_replace(text, before, exact, False) if text else True

        # no live-words bubble here: the words are going straight into the text box
        common = dict(before_first=before_first, allow=lambda: not instant.is_password_box(),
                      delete_fn=backspace_here, check=box_ends_with)
        if engine == "deepgram":
            st = instant.DeepgramStreamer(self.recorder, cfg, cfg["deepgram_api_key"], type_here,
                                          on_error=lambda msg: self.post("toast", msg, "warn", 5), **common)
        else:
            st = instant.Streamer(self.recorder, cfg, model, type_here, **common)
        if not cfg.get("instant_text_recheck", False):
            # the quick model's words are rough: hear each sentence again with the main engine before tidying it
            st.polisher = instant.Polisher(self._live_polish(proc, title, self.grab, rehear=engine == "preview"))
        self.instant = (st, (hwnd, proc, title, pid))
        st.start()

    def _live_polish(self, proc, title, grab, rehear=False):
        """The tidy function for instant text: one sentence at a time, with the same style, learned edits and
        screen context as a normal dictation, and the text already written as the box it continues. rehear: run
        each sentence's audio through the main speech engine first (the quick model's words are rough)."""
        cfg = self.cfg
        ctx = {"app": proc, "title": title, "category": textproc.app_category(proc, title)}
        if cfg.get("learn_style", True):
            try:
                ctx["profile"] = memory.for_kind(ctx["category"])
                ctx["examples"] = history.corrections_for(ctx["category"], 4 if ctx["profile"] else 6)
            except Exception as e:
                log.warning("learned edits unavailable: %s", e)
        seen = {}
        recorder = self.recorder

        def polish(raw, before, after, span=None):
            if not seen:
                screen, draft = grab.get(1.0) if grab else ("", "")
                seen.update(screen=screen, draft=draft)
            if rehear and span:
                raw = self._rehear(span, recorder, polish.pcm, seen["screen"]) or raw
            c = dict(ctx, screen=seen["screen"], draft=(seen["draft"] + before)[-1500:], piece=True, next=after)
            return self._format(raw, c, toast=False)
        polish.pcm = None   # the finished recording, once you let go (the recorder's buffer is gone by then)
        return polish

    def _rehear(self, span, recorder, pcm, screen):
        """One sentence's audio through the main speech engine. Returns its text, or None (then the live words
        are used: a failed or rate-limited request never holds anything up)."""
        cfg = self.cfg
        start, end = span
        try:
            if pcm is not None:
                clip = pcm[int(start * audio.RATE):(int(end * audio.RATE) if end is not None else len(pcm))]
            else:
                clip = recorder.audio_from(start)
                if end is not None:
                    clip = clip[:int((end - start) * audio.RATE)]
            if len(clip) < audio.RATE * 0.4:
                return None
            if cfg.get("whisper_boost", True):
                clip = audio.boost(clip)
            text, engine = stt.transcribe(clip, cfg, context.hint_names(screen))
            if not text.strip() or stt.is_hallucination(text, len(clip) / audio.RATE):
                return None
            return text.strip()
        except Exception as e:
            log.info("instant text: couldn't hear a sentence again: %s", e)
            return None

    def _take_instant(self):
        """Stop live typing now (main thread, doesn't wait). Returns what the worker needs to finish up."""
        if self.instant is None:
            return None
        st, where = self.instant
        self.instant = None
        st.stop_event.set()
        return st, where, self.user_typed

    def _drop_instant(self):
        live_info = self._take_instant()
        if live_info:
            self.jobs.put(("discard_live", live_info))

    def _swap_live(self, live_info, final, target=None, saved=None):
        """Replace the words typed live with `final` ("" = just remove them). Returns the paste result, or None if
        nothing was typed live (then the caller pastes as usual)."""
        st, (hwnd, proc, _title, _pid), user_typed = live_info
        typed = st.finish()
        if not typed:
            return None
        cfg = self.cfg
        osapi.wait_modifiers_released()
        if osapi.foreground_window() != hwnd:
            ok = False
            log.info("instant text: window changed, not touching it")
        else:
            before, exact = instant.text_before_caret(len(typed))
            ok = instant.safe_to_replace(typed, before, exact, user_typed)
            if not ok:
                log.info("instant text: live text changed (readable=%s), not touching it", before is not None)
        if not ok:
            if final.strip():
                osapi.set_text(final, private=True)
                self.post("toast", f"Your live words were changed - polished text copied, press {osapi.PASTE_KEYS}",
                          "warn", 5)
            return {"proc": proc, "keys": "none", "status": "kept"}
        n = instant.presses(typed)
        osapi.select_left(n)
        time.sleep(0.03)
        # a long paragraph is hundreds of Shift+Left presses: wait until the app has selected the live words
        caught_up = instant.wait_selected(typed, timeout=min(10.0, 0.3 + 0.01 * n))
        if caught_up is not True:
            log.info("instant text: selection after %d presses: %s", n, caught_up)
        if final.strip():   # unless the selection matched, keep the clipboard a good while longer
            res = osapi.paste(final, cfg, target=target, saved=saved, queued=0 if caught_up is True else n)
        else:
            osapi.tap_key("delete")
            res = {"proc": proc, "keys": "delete", "status": "ok"}
        res["live"] = True
        log.info("instant text: swapped %d live chars for %d polished", len(typed), len(final))
        return res

    def ev_hk_lock(self, command):
        self.bar.set_state("command" if (command or self.rec_command) else "locked")
        self._sound("lock")

    def ev_caption(self, text):
        if self.recorder.active:
            self.bar.set_caption(text)

    def ev_hk_cancel(self, _command):
        self._drop_instant()
        self.live.stop()
        self._music(False)
        if self.recorder.active:
            self.recorder.stop()
        self.rec_started = 0
        self.bar.set_state("idle")
        self._tray("idle")

    def ev_hk_stop(self, command):
        if not self.recorder.active:
            return
        live_info = self._take_instant()
        self.live.stop()
        self._music(False)
        pcm, speech = self.recorder.stop()
        mode = "command" if (command or self.rec_command) else "dictation"
        self.rec_started = 0
        self._tray("idle")
        if len(pcm) < audio.RATE * 0.3:  # a tap, not a dictation
            if live_info:
                self.jobs.put(("discard_live", live_info))
            self.bar.set_state("idle")
            return
        self._sound("stop")
        self.bar.set_state("processing")
        self._tray("processing")
        self.jobs.put(("dictate", pcm, speech, mode, live_info))

    def ev_hk_paste_last(self, _command):
        self.jobs.put(("paste_last",))

    def ev_hk_undo_last(self, _command):
        self.jobs.put(("undo_last",))

    # ------------------------------------------------------------------ voice commands
    def ev_hk_voice_commands(self, _command):
        if self.voice:
            self._voice_off("Voice commands off")
        elif not (self.paused or self.machine.recording):
            self._voice_on()

    def ev_voice_off(self, why="Voice commands off"):
        if self.voice:
            self._voice_off(why)

    def _voice_on(self):
        try:
            self.recorder.start(self.cfg.get("mic_device", ""))
        except Exception as e:
            log.exception("mic")
            self.bar.toast(f"Microphone error: {e}", "error", 5)
            return
        self.voice, self.voice_last = True, time.time()
        if ON and not self.apps:
            self.jobs.put(("read_apps",))   # so the first "open ..." doesn't wait for the list
        self.bar.rest = "command"
        self.live.stop()
        self._sound("lock")
        self._tray("recording")
        key = self.cfg.get("hotkey_voice_commands", "").upper().replace("+", " + ")
        self.bar.toast(f'Voice commands on - say "go to Google" ({key} to stop)', "ok", 3)
        log.info("voice commands on")

    def _voice_off(self, why=None):
        self.voice = False
        self.bar.rest = "idle"
        if self.recorder.active:
            self.recorder.stop()
        self._sound("stop")
        self._tray("idle")
        if why:
            self.bar.toast(why, "info", 2)
        else:
            self.bar.set_state("idle")
        log.info("voice commands off")

    def _voice_listen(self):
        """Every pump while voice commands are on: a pause after some speech = one command, sent to the worker
        while the microphone keeps listening for the next."""
        rec = self.recorder
        heard = rec.speech_frames / max(rec.rate, 1)
        if heard >= 0.25 and (rec.silent_for > 0.9 or rec.duration > 30):
            self.voice_last = time.time()
            self.jobs.put(("voice_command",) + rec.take())
        elif rec.duration > 30:   # only noise so far: drop it so the recording stays small
            rec.take()
        if time.time() - self.voice_last > 60 * float(self.cfg.get("max_handsfree_minutes", 10)):
            self._voice_off("Voice commands off - nothing said for a while")

    # ------------------------------------------------------------------ ui events
    def ev_toast(self, text, kind="info", seconds=2.8):
        self.bar.toast(text, kind, seconds)

    def ev_bar(self, state):
        if state == "idle" and self.voice:
            state = "command"   # a command finished: keep listening for the next one
        self.bar.set_state(state)
        self._tray("recording" if self.voice else state)

    def ev_report_problem(self):
        """Build a privacy-safe report, copy it, and open it so the user sees exactly what they'd share."""
        status = {
            "speech engine": stt.resolve_engine(self.cfg),
            "local model": stt.LOCAL.status,
            "AI formatting": llm.resolve_provider(self.cfg) or "off",
            "private mode": (f"on, {llm._local_model(self.cfg)}, server {'running' if localai.running() else 'stopped'}"
                             if self.cfg.get("private_mode") else "off"),
            "live words model": ("failed" if live.PREVIEW.failed else
                                 f"{live.PREVIEW.name} ready" if live.PREVIEW.model else "not loaded"),
            "instant text": self.cfg.get("instant_text_engine", "off"),
            "instant text model": ("failed" if live.INSTANT.failed else
                                   f"{live.INSTANT.name} ({live.INSTANT.threads} threads)" if live.INSTANT.model
                                   else "not loaded"),
            "instant text GPU": (f"{gpu.GPU.name}" if gpu.GPU.model else
                                 f"failed: {gpu.GPU.failed[:80]}" if gpu.GPU.failed else
                                 "libraries installed" if gpu.libraries_installed() else "not set up"),
            "learning corrections": "off (UI Automation unavailable)" if self.learner.disabled else "available",
            "packages up to date": deps.up_to_date() if deps.in_private_env() else "n/a (not an installed copy)",
            "keyboard hook": (self.hook.error or "ok") if self.hook else "n/a",
            "shortcuts paused": self.paused,
            "self-update possible": updater.can_self_update(),
        }
        try:
            path, text = report.write(self.cfg, status)
        except Exception as e:
            log.exception("report")
            self.bar.toast(f"Couldn't build the report: {str(e)[:50]}", "error", 5)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if ON:
            try:
                osapi.open_path(path)
            except OSError:
                pass
        self.bar.toast("Problem report copied - paste it into your message", "ok", 6)

    def ev_open_settings(self, tab=0):
        self.open_settings(tab)

    def ev_open_history(self):
        self.open_settings("History")

    def ev_copy_last(self):
        text = history.last_text()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.bar.toast("Last transcript copied", "ok")

    def ev_toggle_pause(self):
        self.paused = not self.paused
        self.machine.paused = self.paused
        self._tray("paused" if self.paused else "idle")
        self.bar.toast("Shortcuts paused" if self.paused else "Shortcuts back on", "warn" if self.paused else "ok")

    def ev_quit(self):
        localai.stop()
        if self.hook:
            self.hook.stop()
        if self.tray:
            self.tray.stop()
        self.root.after(50, self.root.destroy)

    def ev_start_handsfree(self):
        """Start hands-free dictation without the keyboard (tray menu, or clicking the idle bar)."""
        if self.paused or self.machine.recording:
            return
        self.machine.recording = self.machine.locked = True
        self.ev_hk_start(False)
        if self.recorder.active:
            self.bar.set_state("locked")
        else:
            self.machine.reset()

    def ev_stop_recording(self):
        if self.machine.recording:
            self.machine.reset()
            self.ev_hk_stop(self.rec_command)

    # ------------------------------------------------------------------ updates
    def ev_check_updates(self):
        self.check_for_updates(manual=True)

    def check_for_updates(self, manual=False):
        if self.updating:
            return
        if not updater.can_self_update():
            if manual:
                script = "install-mac.sh" if osapi.IS_MAC else "install.bat"
                self.bar.toast(f"Updates only work on an installed copy (run {script})", "warn", 5)
            return
        self.updating = True
        if manual:
            self.bar.toast("Checking for updates...", "info", 3)
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True, name="updater").start()

    def _update_worker(self, manual):
        try:
            new = updater.update_now(on_found=lambda v: self.post("toast", f"Updating Aqua Lite to {v}...", "info", 6))
            if new:
                log.info("updated to %s, restarting", new)
                self.post("restart_for_update", new)
                return
            if manual:
                self.post("toast", f"You're on the latest version ({config.VERSION})", "ok")
        except Exception as e:
            log.warning("update failed: %s", e)
            if manual:
                self.post("toast", f"Update failed: {str(e)[:70]}", "error", 5)
        self.updating = False

    def ev_restart_for_update(self, version):
        if self.machine.recording or self.bar.state == "processing":  # never cut off a dictation
            self.root.after(2000, lambda: self.ev_restart_for_update(version))
            return
        try:
            updater.restart(version)
        except Exception as e:
            log.error("restart after update failed: %s", e)
            self.bar.toast(f"Updated to {version} - restart Aqua Lite to finish", "ok", 6)
            self.updating = False
            return
        self.ev_quit()

    def _bar_clicked(self, state):
        if state == "idle":
            self.ev_start_handsfree()  # click the idle bar = start hands-free dictation
        elif state in ("locked", "recording", "command"):
            self.ev_stop_recording()

    def open_settings(self, tab=0):
        from .ui import SettingsWindow
        if self.settings and self.settings.win.winfo_exists():
            self.settings.win.deiconify()
            self.settings.win.lift()
        else:
            self.settings = SettingsWindow(self.root, self)
        osapi.activate_app()   # macOS: a menu bar app's window must ask to come in front
        self.settings.show(tab)   # a page number or name; old tab names still work
        w = self.settings.win  # bring it to the front even when opened from the tray / Start menu
        w.attributes("-topmost", True)
        w.after(400, lambda: w.attributes("-topmost", False))
        w.focus_force()

    def apply_settings(self, new):
        old_startup = self.cfg.get("launch_at_startup")
        self.cfg.clear()
        self.cfg.update(new)
        self.cfg.save()
        self.machine.configure(self.cfg)
        self.bar.show_idle = self.cfg.get("show_idle_bar", False)
        self.bar.set_look(self.cfg.get("look", "aero"), self.cfg.get("look_mode", "system"))
        if self.cfg.get("frosted_glass", True) != self.bar.want_frost:
            self.bar.set_frost(self.cfg.get("frosted_glass", True))
        if self.cfg.get("gpu_flow_bar", True) != (self.bar.gl is not None):
            self.bar.set_gpu(self.cfg.get("gpu_flow_bar", True))
        self.bar.set_state(self.bar.state if self.bar.state != "toast" else "idle")
        if ON and old_startup != self.cfg.get("launch_at_startup"):
            osapi.set_startup(self.cfg["launch_at_startup"], os.path.join(HERE, "AquaLite.pyw"), self.icon_path)
        self._preload()

    def _music(self, on):
        try:
            self.music.start() if on else self.music.stop()
        except Exception as e:
            log.warning("music: %s", e)

    def _sound(self, name):
        if self.cfg.get("sounds", True):
            sounds.play(name)

    def _tray(self, state):
        if self.tray:
            self.tray.set_state("paused" if self.paused and state == "idle" else state)

    # ------------------------------------------------------------------ the pipeline (worker thread)
    def _worker(self):
        while True:
            job = self.jobs.get()
            try:
                if job[0] == "dictate":
                    self._dictate(*job[1:])
                elif job[0] == "paste_last":
                    text = history.last_text()
                    if text and ON:
                        osapi.paste(text, self.cfg)
                    elif not text:
                        self.post("toast", "Nothing dictated yet", "warn")
                elif job[0] == "undo_last":
                    self._undo_last()
                elif job[0] == "read_apps":
                    self._installed_apps(0)
                elif job[0] == "voice_command":
                    self._voice_command(*job[1:])
                elif job[0] == "discard_live":
                    if ON:
                        self._swap_live(job[1], "")
            except stt.STTError as e:
                log.error("stt: %s", e)
                self.post("toast", f"Transcription failed: {str(e)[:70]}", "error", 5)
                self._sound("error")
            except Exception as e:
                log.exception("job failed")
                self.post("toast", f"Error: {str(e)[:70]}", "error", 5)
                self._sound("error")
            finally:
                if self.bar.state == "processing":
                    self.post("bar", "idle")

    def _undo_last(self):
        li = self.last_insert
        if not li or time.time() - li["time"] > 300:
            self.post("toast", "Nothing to undo", "warn")
            return
        if li["sent"]:
            self.post("toast", "That message was already sent - can't undo it", "warn")
            return
        proc, _title, pid = osapi.foreground() if ON else ("demo", "", 0)
        if pid != li["pid"]:
            self.post("toast", f"Go back to {li['proc']} to undo the last dictation", "warn")
            return
        self.learner.stop()
        how = None
        if ON and li.get("live"):
            # it replaced live words, so Ctrl+Z would bring those back: select exactly what was pasted instead
            osapi.wait_modifiers_released()
            text = li["text"].replace("\r\n", "\n")
            before, exact = instant.text_before_caret(len(text))
            if before is not None and instant.safe_to_replace(text, before, exact, False):
                osapi.select_left(instant.presses(text))
                osapi.tap_key("delete")
                how = "select+delete"
        if how is None:
            how = osapi.undo_insert(li["text"], li["proc"]) if ON else "demo"
        self.last_insert = None
        log.info("undo last dictation (%s)", how)
        self.post("toast", "Removed the last dictation", "ok")

    def _context(self):
        if ON:
            proc, title, pid = osapi.foreground()
        else:
            proc, title, pid = "demo", "", 0
        return {"app": proc, "title": title, "pid": pid, "category": textproc.app_category(proc, title)}, (proc, title, pid)

    def _dictate(self, pcm, speech_secs, mode, live_info=None):
        cfg = self.cfg
        t0 = time.perf_counter()
        seconds = len(pcm) / audio.RATE
        if live_info and (mode == "command" or not ON):
            if ON:
                self._swap_live(live_info, "")
            live_info = None
        if speech_secs < 0.12:
            if live_info:
                self._swap_live(live_info, "")
            self.post("toast", "Didn't catch that - no speech heard", "warn")
            return
        if (live_info and mode == "dictation" and ON and live_info[0].polisher is not None
                and live_info[0].fixing and not cfg.get("instant_text_recheck", False)):
            if self._quick_finish(pcm, speech_secs, seconds, t0, live_info):
                return
            log.info("instant text: quick finish not possible, formatting the whole recording")
        if cfg.get("whisper_boost", True):
            pcm = audio.boost(pcm)
        screen, draft = self.grab.get(0.6) if self.grab else ("", "")
        self.grab = None
        streamed = ""
        if live_info and isinstance(live_info[0], instant.DeepgramStreamer):
            streamed = live_info[0].final_transcript()   # Deepgram already transcribed it while you talked
        if streamed and not cfg.get("private_mode"):
            raw, engine = streamed, "deepgram (live)"
        else:
            raw, engine = stt.transcribe(pcm, cfg, context.hint_names(screen))
        if stt.is_hallucination(raw, speech_secs):
            raw = ""
        if not raw.strip():
            if live_info:
                self._swap_live(live_info, "")
            self.post("toast", "Didn't catch that", "warn")
            history.add(app="", title="", mode=mode, raw="", final="", seconds=seconds, words=0,
                        engine=engine, latency=time.perf_counter() - t0, status="empty")
            return
        enter = False
        if mode == "dictation" and cfg.get("voice_enter", True):
            raw, enter = textproc.split_enter_command(raw)
            if enter and not raw.strip():  # just "press enter"
                if live_info:
                    self._swap_live(live_info, "")
                if ON:
                    osapi.press_enter()
                self.post("bar", "idle")
                return
        ctx, target = self._context()
        ctx.update(screen=screen, draft=draft)
        if mode == "dictation" and cfg.get("learn_style", True):
            try:
                ctx["profile"] = memory.for_kind(ctx["category"])
                ctx["examples"] = history.corrections_for(ctx["category"], 4 if ctx["profile"] else 6)
            except Exception as e:
                log.warning("learned edits unavailable: %s", e)
        status = "ok"
        saved = None
        if mode == "command":
            if not llm.resolve_provider(cfg):
                self.post("toast", "Command Mode needs an AI key (Settings > Speech & AI)", "warn", 5)
                return
            selection, saved = osapi.copy_selection() if ON else ("", None)
            final = None
            if not selection.strip() and ON and target[0].lower() not in textproc.TERMINALS:
                final = self._voice_edit(raw, ctx, target, saved)   # edit what's already in the box
                if final is None:  # done: the box was edited in place
                    self.post("bar", "idle")
                    return
            if final is None or final is False:
                final = llm.run_command(cfg, raw, selection, ctx)
        else:
            final = self._format(raw, ctx)
            if cfg.get("add_trailing_space", True) and final and not final[-1].isspace() and not enter:
                final += " "
        latency = time.perf_counter() - t0
        result = {"status": "demo"}
        swapped = self._swap_live(live_info, final, target, saved) if (live_info and ON) else None
        if swapped is not None:  # instant text: the live words were replaced with the polished version
            result = swapped
            status = result["status"]
        elif final.strip() and ON:
            result = osapi.paste(final, cfg, target=target, saved=saved)
            status = result["status"]
        self._after_insert(final, result, status, enter, target, ctx, mode, raw, seconds, engine, latency, screen)

    def _voice_command(self, pcm, speech_secs):
        """Voice commands (worker thread): hear one command and do it - open a site, press keys, type, write."""
        cfg = self.cfg
        if not self.voice:
            return   # switched off while it was being said
        t0 = time.perf_counter()
        said, engine = stt.transcribe(audio.boost(pcm) if cfg.get("whisper_boost", True) else pcm, cfg)
        if not said.strip() or stt.is_hallucination(said, speech_secs):
            return
        action = voicecmd.parse(said)
        if action[0] == "unknown" and llm.resolve_provider(cfg):
            try:
                action = voicecmd.parse(llm.voice_command(cfg, said))
            except Exception as e:
                log.warning("voice commands: AI didn't answer: %s", e)
        kind, arg = action[0], action[-1]
        log.info("voice command: %s | text=%r", kind, said)
        self.post("caption", said)
        if kind == "stop":
            self.post("voice_off")
        elif kind == "unknown":
            self.post("toast", f'Not a command: "{said[:40]}"', "warn", 3)
        elif kind == "open":
            webbrowser.open(arg)
        elif not ON:
            return
        elif kind == "app":
            self._open_app(arg)
        elif kind == "keys":
            if not osapi.press_shortcut(arg):
                self.post("toast", f"Don't know the key {arg}", "warn")
        else:
            self._voice_write(kind, arg, said, len(pcm) / audio.RATE, engine, t0)

    def _installed_apps(self, max_age):
        if time.time() - self.apps_at > max_age:
            try:
                self.apps, self.apps_at = osapi.installed_apps(), time.time()
                log.info("voice commands: %d apps found", len(self.apps))
            except Exception as e:
                log.warning("voice commands: couldn't list apps: %s", e)
        return self.apps

    def _open_app(self, name):
        """ "open spotify": the installed app, else the website of that name, else a web search for it."""
        key = voicecmd.find_app(name, self._installed_apps(3600))
        if key is None:   # maybe installed since the list was read
            key = voicecmd.find_app(name, self._installed_apps(60))
        if key is None:
            webbrowser.open(voicecmd.url_for(name))
            return
        log.info("voice commands: opening %s", key)
        osapi.launch_app(self.apps[key])

    def _voice_write(self, kind, arg, said, seconds, engine, t0):
        """Voice commands that put text in: type (as said), write (composed by the AI), edit (what's there)."""
        cfg = self.cfg
        ctx, target = self._context()
        text, saved = None, None
        if kind == "type":
            text = self._format(arg, ctx)
            if cfg.get("add_trailing_space", True) and text and not text[-1].isspace():
                text += " "
        elif not llm.resolve_provider(cfg):
            self.post("toast", "Writing by voice needs an AI key (Settings > Speech & AI)", "warn", 5)
            return
        else:
            selection = ""
            if kind == "edit":
                selection, saved = osapi.copy_selection()
                if not selection.strip() and target[0].lower() not in textproc.TERMINALS:
                    text = self._voice_edit(arg, ctx, target, saved)
                    if text is None:
                        return   # edited in place, or it said why not
                    text = text or None
            if text is None:
                text = llm.run_command(cfg, arg, selection, ctx)
        if not text or not text.strip():
            return
        result = osapi.paste(text, cfg, target=target, saved=saved)
        self._after_insert(text, result, result["status"], False, target, ctx, "command", said, seconds, engine,
                           time.perf_counter() - t0, "")

    def _quick_finish(self, pcm, speech_secs, seconds, t0, live_info):
        """Instant text with sentence tidying: when you let go, most of the text is already tidied in the box.
        Hear the last bit, tidy the last sentence, change only what differs. Returns False (having typed nothing
        new) when that isn't possible, so the caller formats the whole recording the normal way."""
        cfg = self.cfg
        st, (hwnd, proc, title, pid), _user_typed = live_info
        if isinstance(st, instant.DeepgramStreamer):
            raw, engine = st.final_transcript(), "deepgram (live)"
        else:
            raw, engine = st.final_text(pcm), f"instant ({getattr(st.model, 'name', 'local')})"
        if not raw.strip() or stt.is_hallucination(raw, speech_secs):
            return False
        enter = False
        if cfg.get("voice_enter", True):
            raw, enter = textproc.split_enter_command(raw)
            if enter and not raw.strip():
                return False
        st.polisher.polish.pcm = pcm
        final = st.polisher.finish(raw, spans=st.word_spans() if hasattr(st, "word_spans") else None)
        if not final or not final.strip():
            return False
        if cfg.get("add_trailing_space", True) and not final[-1].isspace() and not enter:
            final += " "
        target = (proc, title, pid)
        ctx = {"app": proc, "title": title, "category": textproc.app_category(proc, title)}
        osapi.wait_modifiers_released()
        if osapi.foreground_window() == hwnd and st.settle(final):
            result = {"proc": proc, "keys": "typed", "status": "ok", "live": True}
        else:   # couldn't just finish it in place: select what was typed live and paste (or copy, if unsafe)
            result = self._swap_live(live_info, final, target) or osapi.paste(final, cfg, target=target)
        latency = time.perf_counter() - t0
        self._after_insert(final, result, result["status"], enter, target, ctx, "dictation", raw, seconds,
                           engine, latency, "")
        return True

    def _after_insert(self, final, result, status, enter, target, ctx, mode, raw, seconds, engine, latency, screen):
        cfg = self.cfg
        if final.strip() and ON:
            if status == "ok":
                if enter:
                    time.sleep(textproc.enter_delay(target[0]))
                    osapi.press_enter()
                self.last_insert = {"text": final, "proc": target[0], "pid": target[2], "time": time.time(),
                                    "sent": enter, "mode": mode, "live": bool(result.get("live"))}
                if mode == "dictation" and not enter and (cfg.get("learn_corrections", True)
                                                          or cfg.get("learn_style", True)):
                    self.edit_where = (ctx["app"], ctx["category"])
                    self._learn(final, target)
        history.add(app=ctx["app"], title=ctx["title"][:200], mode=mode, raw=raw, final=final.strip(),
                    seconds=seconds, words=textproc.word_count(final), engine=engine, latency=latency, status=status)
        log.info("%s %.1fs audio, %.2fs, %s [%s] -> %s, context %d chars, %d learned edits | text=%r", mode, seconds,
                 latency, engine, ctx["category"], result.get("keys"), len(screen), len(ctx.get("examples") or []), final)
        if status in ("elevated", "blocked"):
            self.post("toast", f"Can't type into this window - text copied, press {osapi.PASTE_KEYS}", "warn", 5)
        else:
            self.post("bar", "idle")

    def _voice_edit(self, instruction, ctx, target, saved):
        """Command Mode with nothing selected. Returns None when it edited the box in place, the text to insert
        when the instruction asks for new text, or False when there's nothing to edit (insert as before)."""
        before, exact = instant.text_before_caret(edits.BOX_CHARS)
        if not before or not before.strip():
            return False
        box = before[-edits.BOX_CHARS:]
        t0 = time.perf_counter()
        try:
            answer = edits.parse_answer(llm.voice_edit(self.cfg, instruction, box, ctx))
        except edits.EditError as e:
            log.warning("voice edit: %s", e)
            self.post("toast", "Didn't get that edit - try saying it another way", "warn")
            return None
        if answer["type"] == "insert":
            return answer["text"]
        li = self.last_insert
        caret_known = exact or (li and li["pid"] == target[2] and time.time() - li["time"] < 300
                                and box.endswith(li["text"].replace("\r\n", "\n")))
        if not caret_known:
            self.post("toast", "Can't edit by voice in this app - select the text first", "warn", 5)
            return None
        try:
            steps, result = edits.plan(box, answer["edits"])
        except edits.EditError as e:
            log.warning("voice edit: %s", e)
            self.post("toast", "Couldn't find that text to change", "warn")
            return None
        cfg = self.cfg

        class Keys:
            left = staticmethod(lambda n: osapi.tap_key("left", n))
            right = staticmethod(lambda n: osapi.tap_key("right", n))
            select_left = staticmethod(osapi.select_left)
            put = staticmethod(lambda text: osapi.paste(text, cfg, target=target, saved=saved))
            delete = staticmethod(lambda: osapi.tap_key("delete"))

        osapi.wait_modifiers_released()
        edits.apply(steps, Keys)
        time.sleep(0.1)
        after, _exact = instant.text_before_caret(len(result))
        clean = after is None or after.replace("\u00a0", " ").endswith(result[-200:])
        if not clean:
            self.post("toast", "That edit may not have gone in cleanly - Ctrl+Z undoes it", "warn", 5)
        self.last_insert = None   # the box changed: "undo last dictation" no longer knows what's there
        history.add(app=ctx["app"], title=ctx["title"][:200], mode="edit", raw=instruction,
                    final=" | ".join(f"{o} -> {n}" for o, n in answer["edits"])[:500], seconds=0,
                    words=0, engine="", latency=time.perf_counter() - t0, status="ok" if clean else "unsure")
        log.info("voice edit: %d change(s) applied in %s, clean=%s", len(steps), ctx["app"], clean)
        return None

    def _learn(self, final, target):
        known = list(self.cfg.get("dictionary", []))
        if not self.cfg.get("learn_corrections", True):
            known = None  # words off: watch only for phrasing edits
        self.learner.watch(final, known if known is not None else [], edits=self.cfg.get("learn_style", True),
                           words=known is not None)

    def _edited(self, dictated, edited):
        """Called from the learner's thread when you've reworded a dictation and left it that way."""
        pair = textproc.style_edit(dictated, edited)
        if not pair:
            return
        app, cat = self.edit_where
        history.add_correction(app, cat, *pair)
        log.info("learned an edit in %s (%s), %d chars -> %d chars", app, cat, len(pair[0]), len(pair[1]))
        self.update_memory()

    def update_memory(self, force=False, done=None):
        """Rebuild the style profile in the background (every few new learned edits, or now when forced)."""
        cfg = self.cfg
        if not llm.resolve_provider(cfg):
            if done:
                done(False, "Needs AI formatting (an API key, or private mode)")
            return

        def run():
            try:
                changed = memory.update(cfg, lambda s, u: llm.chat(cfg, s, u, max_tokens=900, timeout=60),
                                        history.corrections_for, history.correction_count, force)
                if done:
                    done(changed, "Updated" if changed else "Nothing new to learn yet")
            except Exception as e:
                log.warning("memory: profile not rebuilt: %s", e)
                if done:
                    done(False, f"Couldn't update: {str(e)[:80]}")
        threading.Thread(target=run, daemon=True, name="memory").start()

    def ev_learned(self, words):
        dic = list(self.cfg.get("dictionary", []))
        added = [w for w in words if w.lower() not in {d.lower() for d in dic}]
        if not added:
            return
        self.cfg["dictionary"] = dic + added
        self.cfg.save()
        s = self.settings
        if s and s.win.winfo_exists():  # keep an open Settings window in sync so Save doesn't drop them
            for w in added:
                s.dict_list.insert("end", w)
        log.info("learned from a correction | text=%s", added)
        self.bar.toast(f'Learned "{", ".join(added)[:34]}" - added to your dictionary', "ok", 4)

    def _format(self, raw, ctx, toast=True):
        cfg = self.cfg
        whole = textproc.whole_snippet(raw, cfg.get("snippets", []))
        if whole is not None:
            return whole
        protected, mapping = textproc.protect_snippets(raw, cfg.get("snippets", []))
        text = None
        if llm.resolve_provider(cfg) and cfg.get("editing_strength") != "off":
            try:
                out = llm.format_text(cfg, protected, ctx)
                if not textproc.looks_like_an_answer(protected, out):
                    text = out
                else:
                    log.warning("formatter output rejected | text=%r", out)
            except Exception as e:
                log.warning("AI formatting failed, using offline cleanup: %s", e)
                if toast:
                    self.post("toast", "AI formatting unavailable - used offline cleanup", "warn")
        if text is None:
            text = textproc.local_cleanup(protected)
        text = textproc.expand_snippets(text, mapping)
        return textproc.apply_replacements(text, cfg.get("replacements", []))

    def run(self):
        self.root.mainloop()


def main():
    logdir = config.data_dir()
    handlers = [logging.FileHandler(os.path.join(logdir, "aqualite.log"), encoding="utf-8")]
    if sys.stdout is None or sys.stderr is None:  # pythonw: give libraries somewhere to write
        f = open(os.path.join(logdir, "output.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    else:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(message)s")
    argv = sys.argv[1:]
    if "--wait-pid" in argv and ON:  # restarted by the updater: let the old copy exit first
        try:
            osapi.wait_for_exit(int(argv[argv.index("--wait-pid") + 1]), 20000)
        except (ValueError, IndexError):
            pass
    updated_to = argv[argv.index("--updated") + 1] if "--updated" in argv[:-1] else None
    if ON and not osapi.single_instance():
        if not osapi.ask_running_instance_to_open():
            where = "menu bar" if osapi.IS_MAC else "tray"
            osapi.show_message(f"Aqua Lite is already running (look for its icon in the {where}).", "Aqua Lite")
        return
    App(updated_to).run()
