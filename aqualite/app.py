"""Aqua Lite main app: hotkey -> 16 kHz mic -> speech-to-text -> AI formatting -> paste -> restore clipboard."""
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk

from . import audio, config, deps, history, hotkeys, learn, live, llm, music, report, sounds, stt, textproc, updater
from .overlay import FlowBar

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from . import winapi

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
        self.rec_started = 0.0
        self.rec_command = False
        self.settings = None
        self.icon_path = os.path.join(HERE, "assets", "aqualite.ico")

        if IS_WIN:
            winapi.set_dpi_aware()
            self.cfg["launch_at_startup"] = os.path.exists(winapi.startup_shortcut_path())
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Aqua Lite")
        self.bar = FlowBar(self.root, lambda: self.recorder.level, self._bar_clicked, self.cfg.get("show_idle_bar", False))
        self.live = live.LiveCaption(self.recorder, self.cfg, lambda text: self.post("caption", text))
        self.learner = learn.Learner(lambda words: self.post("learned", words))

        self.tray = None
        try:
            from .tray import Tray
            self.tray = Tray(self)
            self.tray.start()
        except Exception as e:
            log.warning("tray unavailable: %s", e)

        self.hook = None
        if IS_WIN:
            self.hook = winapi.KeyboardHook(self.machine.on_key)
            self.hook.start()
            self.hook.ok.wait(3)
            if self.hook.error:
                log.error(self.hook.error)

        if IS_WIN:
            winapi.watch_open_requests(lambda: self.post("open_settings"))
        threading.Thread(target=self._worker, daemon=True, name="worker").start()
        deps.ensure_in_background(lambda ok, _any: self.post(
            "toast", "New features are set up" if ok else "Couldn't install a package - some features are off",
            "ok" if ok else "warn", 4))
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
    def post(self, name, *args):
        self.events.put((name, args))

    def _on_hotkey(self, name, command):  # runs on the hook thread: must be quick
        if name == "mask" and IS_WIN:
            threading.Thread(target=winapi.send_mask, daemon=True).start()
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
        self.root.after(15, self._pump)

    def _preload(self):
        if stt.resolve_engine(self.cfg) == "local":
            threading.Thread(target=self._safe_load, daemon=True).start()
        if self.cfg.get("live_preview", True) and live.PREVIEW.model is None:
            live.PREVIEW.preload(self.cfg)

    def _safe_load(self):
        try:
            stt.LOCAL.load(self.cfg)
            log.info("local model: %s", stt.LOCAL.status)
        except Exception as e:
            log.error("local model failed: %s", e)
            self.post("toast", f"Local speech model failed to load: {e}", "error")

    # ------------------------------------------------------------------ hotkey events
    def ev_hk_start(self, command):
        try:
            self.recorder.start(self.cfg.get("mic_device", ""))
        except Exception as e:
            self.machine.reset()
            log.exception("mic")
            self.bar.toast(f"Microphone error: {e}", "error", 5)
            return
        self.rec_started, self.rec_command = time.time(), command
        self.bar.set_state("command" if command else "recording")
        self.live.start()
        self.learner.stop()
        self._sound("start")
        self._music(True)
        self._tray("recording")

    def ev_hk_command(self, _command):
        self.rec_command = True
        self.bar.set_state("command")

    def ev_hk_lock(self, command):
        self.bar.set_state("command" if (command or self.rec_command) else "locked")
        self._sound("lock")

    def ev_caption(self, text):
        if self.recorder.active:
            self.bar.set_caption(text)

    def ev_hk_cancel(self, _command):
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
        self.live.stop()
        self._music(False)
        pcm, speech = self.recorder.stop()
        mode = "command" if (command or self.rec_command) else "dictation"
        self.rec_started = 0
        self._tray("idle")
        if len(pcm) < audio.RATE * 0.3:  # a tap, not a dictation
            self.bar.set_state("idle")
            return
        self._sound("stop")
        self.bar.set_state("processing")
        self._tray("processing")
        self.jobs.put(("dictate", pcm, speech, mode))

    def ev_hk_paste_last(self, _command):
        self.jobs.put(("paste_last",))

    def ev_hk_undo_last(self, _command):
        self.jobs.put(("undo_last",))

    # ------------------------------------------------------------------ ui events
    def ev_toast(self, text, kind="info", seconds=2.8):
        self.bar.toast(text, kind, seconds)

    def ev_bar(self, state):
        self.bar.set_state(state)
        self._tray("idle" if state == "idle" else state)

    def ev_report_problem(self):
        """Build a privacy-safe report, copy it, and open it so the user sees exactly what they'd share."""
        status = {
            "speech engine": stt.resolve_engine(self.cfg),
            "local model": stt.LOCAL.status,
            "AI formatting": llm.resolve_provider(self.cfg) or "off",
            "live words model": ("failed" if live.PREVIEW.failed else
                                 f"{live.PREVIEW.name} ready" if live.PREVIEW.model else "not loaded"),
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
        if IS_WIN:
            try:
                os.startfile(path)
            except OSError:
                pass
        self.bar.toast("Problem report copied - paste it into your message", "ok", 6)

    def ev_open_settings(self, tab=0):
        self.open_settings(tab)

    def ev_open_history(self):
        self.open_settings(7)

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
                self.bar.toast("Updates only work on an installed copy (run install.bat)", "warn", 5)
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
        self.settings.nb.select(tab)
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
        self.bar.set_state(self.bar.state if self.bar.state != "toast" else "idle")
        if IS_WIN and old_startup != self.cfg.get("launch_at_startup"):
            winapi.set_startup(self.cfg["launch_at_startup"], os.path.join(HERE, "AquaLite.pyw"), self.icon_path)
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
                    if text and IS_WIN:
                        winapi.paste(text, self.cfg)
                    elif not text:
                        self.post("toast", "Nothing dictated yet", "warn")
                elif job[0] == "undo_last":
                    self._undo_last()
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
        proc, _title, pid = winapi.foreground() if IS_WIN else ("demo", "", 0)
        if pid != li["pid"]:
            self.post("toast", f"Go back to {li['proc']} to undo the last dictation", "warn")
            return
        self.learner.stop()
        how = winapi.undo_insert(li["text"], li["proc"]) if IS_WIN else "demo"
        self.last_insert = None
        log.info("undo last dictation (%s)", how)
        self.post("toast", "Removed the last dictation", "ok")

    def _context(self):
        if IS_WIN:
            proc, title, pid = winapi.foreground()
        else:
            proc, title, pid = "demo", "", 0
        return {"app": proc, "title": title, "pid": pid, "category": textproc.app_category(proc, title)}, (proc, title, pid)

    def _dictate(self, pcm, speech_secs, mode):
        cfg = self.cfg
        t0 = time.perf_counter()
        seconds = len(pcm) / audio.RATE
        if speech_secs < 0.12:
            self.post("toast", "Didn't catch that - no speech heard", "warn")
            return
        if cfg.get("whisper_boost", True):
            pcm = audio.boost(pcm)
        raw, engine = stt.transcribe(pcm, cfg)
        if stt.is_hallucination(raw, speech_secs):
            raw = ""
        if not raw.strip():
            self.post("toast", "Didn't catch that", "warn")
            history.add(app="", title="", mode=mode, raw="", final="", seconds=seconds, words=0,
                        engine=engine, latency=time.perf_counter() - t0, status="empty")
            return
        enter = False
        if mode == "dictation" and cfg.get("voice_enter", True):
            raw, enter = textproc.split_enter_command(raw)
            if enter and not raw.strip():  # just "press enter"
                if IS_WIN:
                    winapi.press_enter()
                self.post("bar", "idle")
                return
        ctx, target = self._context()
        status = "ok"
        saved = None
        if mode == "command":
            if not llm.resolve_provider(cfg):
                self.post("toast", "Command Mode needs an AI key (Settings > Speech & AI)", "warn", 5)
                return
            selection, saved = winapi.copy_selection() if IS_WIN else ("", None)
            final = llm.run_command(cfg, raw, selection, ctx)
        else:
            final = self._format(raw, ctx)
            if cfg.get("add_trailing_space", True) and final and not final[-1].isspace() and not enter:
                final += " "
        latency = time.perf_counter() - t0
        result = {"status": "demo"}
        if final.strip() and IS_WIN:
            result = winapi.paste(final, cfg, target=target, saved=saved)
            status = result["status"]
            if status == "ok":
                if enter:
                    time.sleep(textproc.enter_delay(target[0]))
                    winapi.press_enter()
                self.last_insert = {"text": final, "proc": target[0], "pid": target[2], "time": time.time(),
                                    "sent": enter, "mode": mode}
                if mode == "dictation" and cfg.get("learn_corrections", True) and not enter:
                    self._learn(final, target)
        history.add(app=ctx["app"], title=ctx["title"][:200], mode=mode, raw=raw, final=final.strip(),
                    seconds=seconds, words=textproc.word_count(final), engine=engine, latency=latency, status=status)
        log.info("%s %.1fs audio, %.2fs, %s [%s] -> %s | text=%r", mode, seconds, latency, engine, ctx["category"],
                 result.get("keys"), final)
        if status in ("elevated", "blocked"):
            self.post("toast", "Can't type into this window - text copied, press Ctrl+V", "warn", 5)
        else:
            self.post("bar", "idle")

    def _learn(self, final, target):
        self.learner.watch(final, list(self.cfg.get("dictionary", [])))

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

    def _format(self, raw, ctx):
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
    if "--wait-pid" in argv and IS_WIN:  # restarted by the updater: let the old copy exit first
        try:
            winapi.wait_for_exit(int(argv[argv.index("--wait-pid") + 1]), 20000)
        except (ValueError, IndexError):
            pass
    updated_to = argv[argv.index("--updated") + 1] if "--updated" in argv[:-1] else None
    if IS_WIN and not winapi.single_instance():
        if not winapi.ask_running_instance_to_open():
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "Aqua Lite is already running (look for its icon in the tray).",
                                             "Aqua Lite", 0x40)
        return
    App(updated_to).run()
