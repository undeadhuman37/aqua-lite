"""python AquaLite.pyw --selftest   (no microphone, no network, no model needed)"""
import sys

from . import hotkeys, llm, stt, textproc


def check_rules():
    pk = textproc.pick_paste_keys
    assert pk("Code", True) == ("shift", "insert") and pk("Cursor", True) == ("shift", "insert")
    assert pk("Code", False) == ("ctrl", "v") and pk("chrome", True) == ("ctrl", "v")
    rd = textproc.restore_delay
    assert rd("mstsc") == 5.0 and rd("AnyDesk") == 5.0 and rd("WINWORD") == 3.0 and rd("olk") == 3.0
    assert rd("notepad") == 0.5 and rd("unknown") == 0.5
    ac = textproc.app_category
    assert ac("WhatsApp") == "personal" and ac("chrome", "WhatsApp - Google Chrome") == "personal"
    assert ac("slack") == "work" and ac("OUTLOOK") == "email" and ac("msedge", "Inbox (3) - Gmail") == "email"
    assert ac("Code") == "code" and ac("WindowsTerminal") == "code" and ac("notepad") == "other"
    assert ac("chrome", "Claude") == "other"


def check_text():
    lc = textproc.local_cleanup
    assert lc("um so I think uh we should go") == "So I think we should go.", lc("um so I think uh we should go")
    assert lc("first line new line second line") == "First line\nSecond line."
    assert lc("meet at five scratch that meet at six") == "Meet at six."
    assert lc("hello there. call me at five scratch that six") == "Hello there. Six."
    assert lc("yes") == "Yes"
    snippets = [{"trigger": "my email", "text": "you@example.com"}, {"trigger": "sign off", "text": "Best,\nAlex"}]
    assert textproc.whole_snippet("My email.", snippets) == "you@example.com"
    p, m = textproc.protect_snippets("send it to my email please", snippets)
    assert p == "send it to [[S0]] please"
    assert textproc.expand_snippets("Send it to [[S0]], please.", m) == "Send it to you@example.com, please."
    assert textproc.expand_snippets("Send it to my email, please.", m) == "Send it to you@example.com, please."
    assert textproc.expand_snippets("AI: please send to [[s0]].", m) == "AI: please send to you@example.com."
    reps = [{"from": "aqua light", "to": "Aqua Lite"}]
    assert textproc.apply_replacements("try aqua light today", reps) == "try Aqua Lite today"
    assert textproc.looks_like_an_answer("what is the capital of france", "The capital of France is Paris. " * 5)
    assert not textproc.looks_like_an_answer("what is the capital of france", "What is the capital of France?")


class Rec:
    def __init__(self):
        self.ev = []

    def __call__(self, name, cmd=False):
        self.ev.append(name + ("*" if cmd else ""))


def check_hotkeys():
    LC, LW, SP, ALT, D, ESC, Z, SH = 0xA2, 0x5B, 0x20, 0xA4, 0x44, 0x1B, 0x5A, 0xA0
    cfg = {"hotkey_ptt": "ctrl+win"}
    # push to talk
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); m.on_key(LW, True); m.on_key(LW, True)  # auto-repeat ignored
    m.on_key(LW, False); m.on_key(LC, False)
    assert r.ev == ["start", "mask", "stop"], r.ev
    # ctrl+win+d (virtual desktop) must cancel, not dictate
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); m.on_key(LW, True); m.on_key(D, True)
    assert r.ev == ["start", "mask", "cancel"], r.ev
    m.on_key(D, False); m.on_key(LW, False); m.on_key(LC, False)
    assert r.ev[-1] == "cancel"
    # hands-free: space is swallowed, releases ignored, shortcut again stops
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); m.on_key(LW, True)
    assert m.on_key(SP, True) is True
    m.on_key(SP, False); m.on_key(LW, False); m.on_key(LC, False)
    assert r.ev == ["start", "mask", "lock"], r.ev
    m.on_key(0x41, True); m.on_key(0x41, False)  # typing while hands-free is fine
    m.on_key(LC, True); m.on_key(LW, True)
    assert r.ev[-2:] == ["mask", "stop"], r.ev
    # command mode: alt while holding
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); m.on_key(LW, True); m.on_key(ALT, True); m.on_key(ALT, False)
    m.on_key(LW, False)
    assert r.ev == ["start", "mask", "command*", "mask*", "stop*"], r.ev
    # alt held first also = command mode
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(ALT, True); m.on_key(LC, True); m.on_key(LW, True); m.on_key(LC, False)
    assert r.ev[0] == "start*" and r.ev[-1] == "stop*", r.ev
    # esc cancels
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); m.on_key(LW, True); m.on_key(ESC, True)
    assert r.ev[-1] == "cancel"
    # paste last
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(ALT, True); m.on_key(SH, True)
    assert m.on_key(Z, True) is True and r.ev == ["paste_last", "mask"], r.ev
    # undo last
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(ALT, True); m.on_key(SH, True)
    assert m.on_key(0x58, True) is True and r.ev == ["undo_last", "mask"], r.ev
    # double-tap Ctrl+Win -> hands-free; a slow second press is a normal push-to-talk
    t = [0.0]
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r, clock=lambda: t[0])
    m.on_key(LC, True); m.on_key(LW, True); t[0] += 0.12; m.on_key(LW, False); m.on_key(LC, False)
    t[0] += 0.15
    m.on_key(LC, True); m.on_key(LW, True); t[0] += 0.1; m.on_key(LW, False); m.on_key(LC, False)
    assert r.ev == ["start", "mask", "stop", "start", "lock", "mask"] and m.locked, r.ev
    t[0] += 3; m.on_key(LC, True); m.on_key(LW, True)
    assert r.ev[-1] == "stop" and not m.recording, r.ev
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r, clock=lambda: t[0])
    m.on_key(LC, True); m.on_key(LW, True); t[0] += 0.12; m.on_key(LW, False); m.on_key(LC, False)
    t[0] += 0.8
    m.on_key(LC, True); m.on_key(LW, True); t[0] += 2; m.on_key(LW, False)
    assert "lock" not in r.ev and r.ev[-1] == "stop", r.ev
    r = Rec(); m = hotkeys.HotkeyMachine({**cfg, "double_tap_handsfree": False}, r, clock=lambda: t[0])
    m.on_key(LC, True); m.on_key(LW, True); t[0] += 0.1; m.on_key(LW, False); m.on_key(LC, False)
    t[0] += 0.1; m.on_key(LC, True); m.on_key(LW, True)
    assert "lock" not in r.ev, r.ev
    # Ctrl+C etc. untouched
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r)
    m.on_key(LC, True); assert m.on_key(0x43, True) is False; m.on_key(0x43, False); m.on_key(LC, False)
    assert r.ev == []
    # single-key push-to-talk (F9) is swallowed so the app never sees it
    r = Rec(); m = hotkeys.HotkeyMachine({"hotkey_ptt": "f9"}, r)
    assert m.on_key(0x78, True) is True and m.on_key(0x78, True) is True and m.on_key(0x78, False) is True
    assert r.ev == ["start", "stop"], r.ev
    # pause
    r = Rec(); m = hotkeys.HotkeyMachine(cfg, r); m.paused = True
    m.on_key(LC, True); m.on_key(LW, True)
    assert r.ev == []
    for bad in ("ctrl+wn", ""):
        try:
            hotkeys.parse(bad)
            raise AssertionError("parse should fail")
        except ValueError:
            pass


def check_prompts():
    seen = {}

    def fake_chat(cfg, system, user, **kw):
        seen["system"], seen["user"] = system, user
        return '"Let\'s meet at 6 PM."'

    real = llm.chat
    llm.chat = fake_chat
    try:
        cfg = {"dictionary": ["Kubernetes"], "editing_strength": "light", "styles": {"work": "casual", "other": "formal"},
               "code_mode": True}
        out = llm.format_text(cfg, "um lets meet at 5 no 6", {"app": "slack", "title": "", "category": "work"})
        assert out == "Let's meet at 6 PM.", out
        assert "Kubernetes" in seen["system"] and "LIGHT" in seen["system"] and "CASUAL" in seen["system"]
        llm.format_text(cfg, "open app dot py", {"app": "Code", "title": "", "category": "code"})
        assert "code editor" in seen["system"]
        llm.run_command(cfg, "make it formal", "hey whats up", {"app": "OUTLOOK", "title": ""})
        assert "hey whats up" in seen["user"]
    finally:
        llm.chat = real
    assert llm.resolve_provider({"ai_provider": "auto"}) is None
    assert llm.resolve_provider({"ai_provider": "auto", "groq_api_key": "x"}) == "groq"
    assert stt.resolve_engine({"stt_engine": "auto"}) == "local"
    assert stt.resolve_engine({"stt_engine": "auto", "groq_api_key": "x"}) == "groq"
    import numpy as np
    wav = stt.to_wav(np.zeros(16000, np.float32))
    assert wav[:4] == b"RIFF" and len(wav) == 44 + 32000
    assert stt.is_hallucination("Thank you.", 0.1) and not stt.is_hallucination("Thank you.", 2.0)


def check_music():
    import random
    from . import music
    rng = random.Random(1)
    recent = []
    for _ in range(10):  # a 7-hour mix: ten dictations, all at least 6 minutes apart
        st = music.pick_start(7 * 3600, recent, rng=rng)
        assert all(abs(st - r) >= 360 for r in recent), (st, recent)
        recent.append(st)
    assert music.pick_start(30, []) == 0.0
    assert 0 <= music.pick_start(200, [50.0], rng=rng) <= 200


def check_windows():
    from . import winapi
    proc, title, pid = winapi.foreground()
    print(f"  focused app: {proc} (pid {pid})")
    saved = winapi.snapshot()
    seq = winapi.set_text("Aqua Lite clipboard test ✓ عربي\nline 2")
    assert winapi.get_text() == "Aqua Lite clipboard test ✓ عربي\nline 2", repr(winapi.get_text())
    assert winapi.sequence() == seq
    winapi.restore(saved)
    print(f"  clipboard: write/read/restore ok ({len(saved or [])} formats saved)")
    # the old clipboard must not come back before the app has pasted (long dictations pasted the old copy)
    assert winapi.restore_budget(0.5, 600, 600) > 5 and winapi.restore_budget(0.5) == 0.5
    t, waits, answers = [0.0], [], iter([False, False, True])
    seq = winapi.set_text("Aqua Lite restore test")
    winapi._restore_when_pasted(saved, seq, "x", 0.5, 5.0, check=lambda _t: next(answers),
                                sleep=lambda d: (waits.append(d), t.__setitem__(0, t[0] + d)), clock=lambda: t[0])
    assert t[0] >= 0.5, "restored before the app's usual delay"
    print("  clipboard: waits for the paste before restoring")
    hook = winapi.KeyboardHook(lambda vk, down: False)
    hook.start()
    hook.ok.wait(3)
    assert not hook.error, hook.error
    hook.stop()
    print("  keyboard hook: ok")
    from . import audio
    devs = audio.list_input_devices()
    print(f"  microphones: {len(devs)} found" + (f" (e.g. {devs[0]})" if devs else " - plug one in!"))
    print(f"  running as admin: {winapi.self_elevated()}")


def check_new_features():
    se = textproc.split_enter_command
    assert se("See you at 6. Press enter.") == ("See you at 6.", True)
    assert se("Ok see you then. Send it.") == ("Ok see you then.", True) and se("press enter") == ("", True)
    assert se("Please review and send it.") == ("Please review and send it.", False)
    assert se("مرحبا. اضغط انتر") == ("مرحبا.", True)
    lw = textproc.learned_words
    assert lw("Tell Kaitlin hi.", "Tell Kaitlyn hi.") == ["Kaitlyn"] and lw("the api is down", "the API is down") == ["API"]
    assert lw("have a meeting", "have a call") == [] and lw("hello there", "Hello there") == []
    from . import learn, live
    t = [0.0]
    d, states = "Tell Kaitlin hi. ", [(0, "Hey! Tell Kaitlin hi. "), (3, "Hey! Tell Kaitlyn hi. "), (8, "")]
    read = lambda: [x for at, x in states if t[0] >= at][-1]
    w = learn.CorrectionWatcher(d, read, lambda: 1, lambda _w: None, clock=lambda: t[0],
                                sleep=lambda secs: t.__setitem__(0, t[0] + secs))
    assert w.run() == ["Kaitlyn"]
    assert live.tidy("Thanks for watching!", False) == "" and live.tidy("lo there friend", True) == "there friend"
    from .config import VERSION, whats_new
    assert whats_new(VERSION)[1], "CHANGELOG.md has no entry for this version"


def check_learning():
    se = textproc.style_edit
    assert se("Hey, I'm going to be late.", "hey im gonna be late") == ("Hey, I'm going to be late.", "hey im gonna be late")
    assert se("See you at 5:30 PM.", "See you at 5:30pm") == ("See you at 5:30 PM.", "See you at 5:30pm")
    assert se("Hey, how are you?", "hey, how are you?")                               # case-only style counts
    assert se("Late. ", "Late. Also bring the charger") is None                          # kept typing after it
    assert se("Launch on Friday.", "Quick note: Launch on Friday.") is None              # typed before it
    assert se("Send it to Kaitlin.", "Send it to Kaitlyn.") is None                    # a name: dictionary's job
    assert se("Thanks for the update.", "Completely different message about lunch plans") is None
    assert se("Hello  world.", "Hello world.") is None and se("Same.", "Same.") is None
    from . import learn
    t, got = [0.0], []
    d = "Hey, I'm going to be late. "
    states = [(0, d), (3, "hey im gonna be late "), (10, "")]
    read = lambda: [x for at, x in states if t[0] >= at][-1]
    w = learn.CorrectionWatcher(d, read, lambda: 1, lambda _w: None, clock=lambda: t[0],
                                sleep=lambda secs: t.__setitem__(0, t[0] + secs), on_edited=lambda a, b: got.append((a, b)))
    w.run()
    assert got and se(*got[-1]) == ("Hey, I'm going to be late.", "hey im gonna be late"), got
    from . import context, llm
    assert context.assemble(["Kaitlyn", "Kaitlyn: are the samples in?", "  ", "Kaitlyn: are the samples in?",
                             "Yes, Marco sent them"]) == "Kaitlyn: are the samples in?\nYes, Marco sent them"
    names = context.hint_names("Kaitlyn: did Marco ship? Yes. Ask Kaitlyn about the DHL tracking")
    assert names[:3] == ["DHL", "Kaitlyn", "Marco"] and "Yes" not in names and "Ask" not in names, names
    cfg = {"context_blocked_apps": ["bitwarden"]}
    assert context.allowed("whatsapp", "Chat", cfg) and not context.allowed("Bitwarden", "", cfg)
    assert not context.allowed("chrome", "New Tab - InPrivate", cfg) and not context.allowed("pythonw", "", cfg)
    ctx = {"app": "WhatsApp", "examples": [("Okay, see you.", "ok see u")], "screen": "Sara: lunch?", "draft": "so "}
    x = llm._extras(ctx)
    assert "ok see u" in x and "Sara: lunch?" in x and "so " in x and "never reply" in x
    xc = llm._extras(ctx, command=True)
    assert "ok see u" not in xc and "Sara: lunch?" in xc and llm._extras({"app": "x"}) == ""
    assert stt.vocab_prompt({"dictionary": ["Kaitlyn"]}, ["kaitlyn", "Marco"]) == "Kaitlyn, Marco."


def check_instant():
    from . import instant
    a = instant.Agreement()
    w = lambda t, s: (" " + t, s, s + 0.3)
    assert a.insert([w("Hey", 0.1), w("Kaitlin", 0.5)]) == []                     # first pass: nothing is sure yet
    assert [x[0] for x in a.insert([w("hey", 0.1), w("Kaitlyn", 0.5), w("the", 0.9)])] == [" Hey"]  # keeps on-screen form
    assert [x[0] for x in a.insert([w("Hey", 0.1), w("Kaitlyn,", 0.5), w("the", 0.9)])] == [" Kaitlyn", " the"]
    assert a.insert([w("the", 0.92), w("samples", 1.3)]) == []                     # re-heard 'the' isn't doubled
    assert [x[0] for x in a.insert([w("samples", 1.31), w("arrived", 1.7)])] == [" samples"]
    assert a.text() == "Hey Kaitlyn the samples"
    # word by word: guesses go in at once and get fixed when re-heard, only after checking the box
    box, words = ["Re: "], [[("Hey", 0.1, 0.4), ("Kaitlin", 0.5, 0.9)], [("Hey", 0.1, 0.4), ("Kaitlyn", 0.5, 0.9)]]

    class Rec:
        duration, speech_frames = 2.0, 1

        def audio_from(self, off):
            return [0.0] * 32000

    class Model:
        def words(self, audio, cfg, prompt=""):
            return words.pop(0)

    def typer(t):
        box[0] += t
        return True

    def eraser(n):
        box[0] = box[0][:-n]
        return True
    st = instant.Streamer(Rec(), {}, Model(), typer, delete_fn=eraser, check=lambda t: box[0].endswith(t))
    st.step()
    assert box[0] == "Re: Hey Kaitlin"
    st.step()
    assert box[0] == "Re: Hey Kaitlyn" and st.typed == "Hey Kaitlyn"
    assert instant.common_prefix("abc", "abd") == 2
    dg = instant.DeepgramStreamer(Rec(), {"dictionary": ["Marco"], "language": "ar"}, "k", typer).params()
    assert "model=nova-3" in dg and "language=ar" in dg and "keyterm=Marco" in dg and "encoding=linear16" in dg
    from . import gpu
    assert isinstance(gpu.lib_dirs(), list) and gpu.MODEL == "large-v3-turbo"
    assert gpu.recommend(2048) == "small" and gpu.recommend(8192) == "large-v3-turbo" and gpu.recommend(0) == gpu.MODEL
    assert gpu.compute_for("large-v3", 4096) == "int8_float16" and gpu.compute_for("small", 4096) == "float16"
    assert not gpu.fits("large-v3", 2048) and "recommended" in gpu.choice_label("small", 2048, "small")
    assert instant.join_words([(" Hello", 0, 1), ("world.", 1, 2)], first=False) == " Hello world."
    assert instant.presses("caf\u00e9") == 4 and instant.presses("cafe\u0301") == 4 and instant.presses("") == 0
    ok = instant.safe_to_replace
    assert ok("see you", "Hi, see you", True, False) and ok("hello there", "Hello there", True, False)
    assert ok("a b", "x a\u00a0b", True, False) and not ok("see you", "see you!", True, False)
    assert not ok("see you", "see yo", True, False) and ok("x", None, False, False) and not ok("x", None, False, True)
    t, ev = [0.0], []
    m = hotkeys.HotkeyMachine({}, lambda n, c: ev.append(n), clock=lambda: t[0])
    m.on_key(0xA2, True), m.on_key(0x5B, True)
    t[0] = 1.0
    assert m.release_held() == {0xA2, 0x5B} and m.on_key(0x5B, True) is True       # repeats swallowed
    assert m.on_key(0x5B, False) is True and "stop" in ev and m.on_key(0xA2, False) is True
    assert m.on_key(0xA2, True) is False and m.released_mods == set()               # next press is normal again


def check_sentence_tidy():
    import threading
    import time as _t
    from . import instant
    assert instant.sentence_ends("Dr. Lee is here. Ok then") == [16]
    assert instant.is_correction("Actually, make that Thursday.") and not instant.is_correction("I like Thursdays.")
    box = {"text": ""}
    lock = threading.Lock()

    def typ(t):
        with lock:
            box["text"] += t
        return True

    def back(n):
        with lock:
            box["text"] = box["text"][:-n]
        return True

    def tidy(raw, before, after, span=None):
        if raw.lower().startswith("actually"):
            return ""
        t = raw.replace("friday", "Thursday" if "thursday" in after.lower() else "Friday")
        return ". ".join(x[:1].upper() + x[1:] for x in t.split(". "))

    lt = instant.LiveTyper(typ, delete_fn=back, check=lambda t: box["text"].endswith(t))
    lt.polisher = instant.Polisher(tidy)
    raw = ""
    for w in "see you on friday at noon. actually make that thursday. bring the deck please. thanks a lot".split():
        raw = (raw + " " + w).strip()
        lt.feed_polisher(raw)
        lt.show(lt.view(raw))
        _t.sleep(0.01)
    end = _t.monotonic() + 3
    while lt.polisher.segs and lt.polisher.segs[0][1] is None and _t.monotonic() < end:
        _t.sleep(0.02)
    lt.show(lt.view(raw))
    assert box["text"].startswith("See you on Thursday at noon."), box["text"]
    final = lt.polisher.finish(raw)
    assert final == "See you on Thursday at noon. Bring the deck please. Thanks a lot", final
    assert lt.settle(final) and box["text"] == final, box["text"]
    assert not lt.settle("two\nlines")   # line breaks are pasted, never typed (Enter would send a chat message)
    # a busy app shows the old text for a moment after a burst of keys: wait for it, don't give up on the box
    slow = {"text": "", "behind": 3}

    def slow_check(t):
        if slow["behind"]:
            slow["behind"] -= 1
            return False
        return slow["text"].endswith(t)
    lag = instant.LiveTyper(lambda t: slow.update(text=slow["text"] + t) or True,
                            delete_fn=lambda n: slow.update(text=slow["text"][:-n]) or True, check=slow_check)
    lag.show("hello wrold")
    slow["behind"] = 3
    lag.show("hello world")
    assert slow["text"] == "hello world" and not lag.stop_event.is_set(), slow
    spans = [(0, 2, 0.0, 0.3), (3, 6, 0.5, 0.9), (7, 9, 1.5, 1.8), (10, 14, 2.0, 2.4)]   # "hi you. ok then"
    assert instant.Polisher.span_of(spans, 0, 7) == (0.0, 1.2)       # cut halfway into the pause after "you."
    assert instant.Polisher.span_of(spans, 7, None) == (1.2, None)


def check_gpu_bar():
    """The Flow bar on the graphics card must look like the Pillow drawing. Skipped where there's no OpenGL."""
    import random
    from . import aero
    try:
        from . import glbar
        a, b = aero.FlowBarRenderer(1.0), aero.FlowBarRenderer(1.0)
        gl = glbar.GLBar(b.size)
    except Exception as e:
        print(f"  (graphics card drawing not checked here: {str(e)[:60]})")
        return
    lv = [0.2, 0.5, 0.8, 0.4, 0.6, 0.3, 0.7, 0.5, 0.9, 0.2, 0.4, 0.6, 0.8, 0.3, 0.5]
    for st, kw in (("idle", {}), ("recording", dict(levels=lv, t=1.0, caption="hello there", caption_alpha=1.0)),
                   ("command", dict(levels=lv, t=0.4, phase=0.5)), ("processing", dict(t=0.8)),
                   ("toast", dict(label="Copied", kind="ok"))):
        random.seed(5)
        want = a.render(st, **kw)
        random.seed(5)
        diff = glbar.difference(want, glbar.to_image(gl.frame(b.scene(st, **kw)), b.size))
        assert diff < 3, f"graphics-card Flow bar differs in {st}: {diff:.2f}"
    gl.close()


def _contrast(a, b):
    """Contrast ratio between two RGB colours, the WCAG way (1 to 21)."""
    def lum(c):
        ch = [v / 255 for v in c[:3]]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_liquid_look():
    """Liquid Glass Flow bar: optional (Frutiger Aero stays the default), every state draws, and words and the
    waveform stay readable over a white and a black screen, in light and dark, frosted or solid."""
    from PIL import Image
    from . import aero, config, liquid, overlay
    assert config.DEFAULTS["look"] == "aero" and config.DEFAULTS["look_mode"] == "system"
    assert type(overlay.make_renderer("aero", 1.0)) is aero.FlowBarRenderer
    assert type(overlay.make_renderer("something old", 1.0)) is aero.FlowBarRenderer, "unknown theme must be Aero"
    assert type(overlay.make_renderer("liquid", 1.0, "dark")) is liquid.LiquidBarRenderer
    assert liquid.resolve_mode("dark") == "dark" and liquid.resolve_mode("light") == "light"
    assert liquid.resolve_mode("system") in ("light", "dark")
    lv = [0.5] * (aero.BARS + 1)
    for mode in ("light", "dark"):
        for frost in (False, True):
            r = liquid.LiquidBarRenderer(1.0, frost=frost, mode=mode)
            assert r.size == aero.FlowBarRenderer(1.0).size, "both themes must use the same window"
            for st in ("idle", "recording", "locked", "command", "processing"):
                im = r.render(st, "", lv, 1.0, caption="hello there")
                assert im.size == r.size and im.getbbox(), f"Liquid Glass {st} came out empty"
                x, y, w, h, rad = r.blur_shape()
                assert 0 <= x and 0 <= y and x + w <= r.size[0] and y + h <= r.size[1] and rad == h // 2
            assert r.render("toast", "Copied", kind="ok").getbbox()
            r.render("hidden")
            assert r.blur_shape() is None
            box = r._box(258, 42)
            base, over = r._glass(box, tint=r.pal["tint"]["command"])
            glass = Image.alpha_composite(base, over)
            _cbox, bubble, _pos = r._cap_img(120, 24, box[1])
            spots = [(glass, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)),
                     (glass, (box[0] + r._u(150), (box[1] + box[3]) // 2)),
                     (bubble, (bubble.size[0] // 2, bubble.size[1] // 2))]
            for under in ((255, 255, 255), (0, 0, 0)):
                for img, at in spots:
                    bg = Image.new("RGBA", img.size, under + (255,))
                    bg.alpha_composite(img)
                    px = bg.getpixel(at)[:3]
                    c = _contrast(r.pal["ink"], px)
                    assert c >= 4.5, f"Liquid Glass {mode} words too faint over {under}: {c:.1f}"
                    c = _contrast(r.pal["bar"], px)
                    assert c >= 3, f"Liquid Glass {mode} waveform too faint over {under}: {c:.1f}"
    r = liquid.LiquidBarRenderer(1.0)
    r.render("recording", "", lv, 0.0)
    r.set_mode("dark")
    assert not r.cache, "switching light/dark must redraw the glass"


def check_liquid_settings():
    """Liquid Glass Settings window: every piece draws in light and dark, text is readable on the page and on cards,
    the look follows the settings, and Frutiger Aero's colours come back unchanged."""
    from . import config, liquidskin, skin, ui
    for mode in ("light", "dark"):
        k = liquidskin.Skin(mode)
        for im in (k.button(44, 30, "pressed", True), k.button(44, 30), k.toggle(20, 1), k.toggle(20, 0, "disabled"),
                   k.toggle_between(20, 0.5), k.radio(18, 1), k.field(40, 28, "focus"), k.arrow(24, 22),
                   k.progress_trough(120, 16), k.progress_bar(40, 12), k.scale_trough(120, 22), k.slider(22, "pressed"),
                   k.thumb(12, 48), k.card(48, selected=True), k.nav_pill(200, 38, "selected"), k.icon("star", 18),
                   k.pill(40, 22, k.PILLS["blue"][0]), k.keycap(28, 24)):
            assert im.getbbox(), f"a Liquid Glass Settings drawing came out empty ({mode})"
        side = k.sidebar(224, 600)
        assert side.size == (224, 600) and side.mode == "RGB"
        for surface in (k.CARD, k.PAGE):
            for name, ink, need in (("text", k.INK, 7), ("muted text", k.MUTED, 4.5), ("links and numbers",
                                                                                        k.ACCENT_TEXT, 4.5),
                                    ("warnings", k.ui["warn"], 4.5)):
                c = _contrast(ink, surface)
                assert c >= need, f"Liquid Glass {mode}: {name} contrast {c:.1f} < {need}"
        for _dot, ink in k.PILLS.values():   # statuses are text with a dot, straight on the card
            assert _contrast(k.CARD, ink) >= 4.5, f"Liquid Glass {mode}: a status is hard to read"
        edge = k.sidebar(224, 600).getpixel((0, 300))   # no colour behind the glass: just the page (and shadow)
        assert max(abs(a - b) for a, b in zip(edge, k.PAGE)) <= 4, "the sidebar should sit on the page colour"
        side_px = side.getpixel((112, 300))   # the nav text sits on the glass sheet
        assert _contrast(k.INK, side_px) >= 4.5, f"Liquid Glass {mode}: sidebar text contrast too low"
    assert ui.look_key({"look": "liquid", "look_mode": "dark"}) == ("liquid", "dark")
    assert ui.look_key({}) == ("aero", None) and ui.look_key({"look": "aero", "look_mode": "dark"}) == ("aero", None)
    ui._use_look(("liquid", "dark"))
    assert ui.PREFIX == "LqD" and ui.PAGE != skin.hexrgb(skin.PAGE)
    lay = ui._layouts("LqD", "LqD")
    assert all(f"Slide{i}.TCheckbutton" in lay for i in range(8)) and "Slide0.TCheckbutton" not in ui._layouts("Aero")
    ui._use_look(("aero", None))
    assert (ui.PAGE, ui.CARD, ui.INK, ui.MUTED, ui.ACCENT) == (skin.hexrgb(skin.PAGE), "#ffffff", "#0b3d63", "#3f6987",
                                                              "#0a84c6") and ui.C == ui.AERO_COLOURS
    name, summary, items = config.whats_new_full(config.VERSION)
    assert items and all(text for _h, text in items), "What's new has nothing to show for this version"
    assert "What's new" in {p[1] for p in ui.PAGES}


def check_liquid_bar():
    """Liquid Glass on the graphics card must look like its Pillow drawing. Skipped where there's no OpenGL."""
    from . import aero, liquid
    try:
        from . import glbar
        gl = glbar.GLBar(liquid.LiquidBarRenderer(1.0).size)
    except Exception as e:
        print(f"  (graphics card drawing not checked here: {str(e)[:60]})")
        return
    lv = [0.2, 0.5, 0.8, 0.4, 0.6, 0.3, 0.7, 0.5, 0.9, 0.2, 0.4, 0.6, 0.8, 0.3, 0.5]
    for mode in ("light", "dark"):
        for frost in (False, True):
            a = liquid.LiquidBarRenderer(1.0, frost=frost, mode=mode)
            b = liquid.LiquidBarRenderer(1.0, frost=frost, mode=mode)
            assert glbar.check(gl, b) < 3
            for st, kw in (("idle", {}), ("recording", dict(levels=lv, t=1.0, caption="hello there")),
                           ("locked", dict(levels=lv, t=0.7)), ("command", dict(levels=lv, t=0.4, phase=0.5)),
                           ("processing", dict(t=0.8)), ("toast", dict(label="Copied", kind="ok"))):
                want = a.render(st, **kw)
                diff = glbar.difference(want, glbar.to_image(gl.frame(b.scene(st, **kw)), b.size))
                assert diff < 3, f"Liquid Glass on the graphics card differs in {mode} {st}: {diff:.2f}"
    gl.close()
    assert aero.BARS == liquid.BARS


def check_paste_wait():
    from . import instant
    t = [0.0]
    clk, slp = (lambda: t[0]), (lambda d: t.__setitem__(0, t[0] + d))
    grow = iter(["H", "He", "Hel", "Hello world"])
    assert instant.wait_selected("Hello\u00a0world", 5, read=lambda: next(grow), clock=clk, sleep=slp) is True
    stuck = iter(["Hi", "Hi \U0001f600"] + ["Hi \U0001f600"] * 99)
    assert instant.wait_selected("Hi :)", 5, read=lambda: next(stuck), clock=clk, sleep=slp) == "settled"
    assert instant.wait_selected("Hi", 5, read=lambda: None) is None
    assert instant.pasted("One.\nTwo", read=lambda n: ("x One.\r\nTwo ", True)) is True
    assert instant.pasted("One", read=lambda n: ("what you had copied", True)) is False
    assert instant.pasted("One", read=lambda n: (None, False)) is None


def check_voice_edit():
    from . import edits
    pa = edits.parse_answer
    assert pa('```json\n{"type": "edit", "edits": [{"old": "Friday", "new": "Thursday"}]}\n```') == \
        {"type": "edit", "edits": [("Friday", "Thursday")]}
    assert pa('{"type": "insert", "text": "See you!"}') == {"type": "insert", "text": "See you!"}
    assert pa("Sure thing!") == {"type": "insert", "text": "Sure thing!"}
    for bad in ('{"type": "edit", "edits": []}', '{"type": "edit", "edits": [}', '{"type": "fly"}', ""):
        try:
            pa(bad)
            raise AssertionError(f"accepted {bad!r}")
        except edits.EditError:
            pass
    steps, result = edits.plan("Hi Sara. Meet Friday? Friday works.", [("Friday?", "Thursday?"), (" Friday works.", "")])
    assert result == "Hi Sara. Meet Thursday?" and steps == [(14, 7, "Thursday?"), (0, 14, "")], steps
    try:
        edits.plan("Hello", [("nope", "x")])
        raise AssertionError("planned an edit for text that isn't there")
    except edits.EditError:
        pass


def check_private_mode():
    from . import localai
    engines = localai.ENGINES
    localai.ENGINES = {"vulkan": "-bin-win-vulkan-x64.zip", "cpu": "-bin-win-cpu-x64.zip"}   # the Windows builds
    try:
        _check_private_mode(localai)
    finally:
        localai.ENGINES = engines
    mac = {"tag_name": "b4", "assets": [{"name": "llama-b4-bin-win-cpu-x64.zip", "browser_download_url": "w"},
                                        {"name": "llama-b4-bin-macos-arm64.zip", "browser_download_url": "a"},
                                        {"name": "llama-b4-bin-macos-x64.zip", "browser_download_url": "i"}]}
    if sys.platform == "darwin":
        assert localai.find_engine_asset(mac, "vulkan")[1] in ("a", "i") and localai.SERVER_EXE == "llama-server"
    else:
        assert localai.find_engine_asset(mac, "cpu")[1] == "w" and localai.SERVER_EXE == "llama-server.exe"


def _check_private_mode(localai):
    rel = {"tag_name": "b1", "assets": [{"name": "llama-b1-bin-win-cuda-12.4-x64.zip", "browser_download_url": "c"},
                                        {"name": "llama-b1-bin-win-vulkan-x64.zip", "browser_download_url": "v",
                                         "size": 5, "digest": "sha256:ab"},
                                        {"name": "llama-b1-bin-win-cpu-x64.zip", "browser_download_url": "p"}]}
    assert localai.find_engine_asset(rel, "vulkan") == ("llama-b1-bin-win-vulkan-x64.zip", "v", 5, "ab")
    assert localai.find_engine_asset(rel, "cpu")[1] == "p"
    still_uploading = {"tag_name": "b2", "assets": [{"name": "llama-b2-bin-macos-arm64.zip", "browser_download_url": "m"}]}
    assert localai.pick_release([still_uploading, rel], "vulkan")[1] == "v"           # newest complete release
    assert localai.pick_release([dict(rel, prerelease=True)], "vulkan")[1] == "v"     # llama.cpp marks all as pre
    half = {"tag_name": "b3", "assets": [{"name": "llama-b3-bin-win-vulkan-x64.zip", "browser_download_url": "h",
                                          "state": "starter"}]}
    assert localai.pick_release([half, rel], "vulkan")[1] == "v"                     # file still uploading
    sib = {"siblings": [{"rfilename": "x-UD-Q4_K_XL.gguf"}, {"rfilename": "x-Q4_K_M.gguf", "lfs": {"sha256": "s", "size": 7}},
                        {"rfilename": "mmproj-x-Q4_K_M.gguf"}, {"rfilename": "x-Q8_0.gguf"}]}
    assert localai.find_model_file(sib, "Q4_K_M") == ("x-Q4_K_M.gguf", 7, "s")
    assert localai.request_extras("qwen3-1.7b") and not localai.request_extras("qwen3-4b")
    assert "--port" in localai.server_command("e", "m", 1) and "127.0.0.1" in localai.server_command("e", "m", 1)
    assert llm._tidy("<think>x</think>Hello.") == "Hello."
    assert stt.resolve_engine({"private_mode": True, "groq_api_key": "k"}) == "local"


def check_platform():
    """The platform layer (osapi): every system offers the same names, Windows never loads the Mac code, and the
    Mac layer's pure parts (key codes, Fn, the login item, screen coordinates) work without a Mac."""
    import ast
    import os
    from . import config, osapi
    from .osapi import common
    here = os.path.dirname(osapi.__file__)

    def names(mod):
        tree = ast.parse(open(os.path.join(here, mod + ".py"), encoding="utf-8").read())
        out = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                out.add(node.name)
            elif isinstance(node, ast.Assign):
                out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            elif isinstance(node, ast.ImportFrom):
                out |= {a.asname or a.name for a in node.names}
        return {n for n in out if not n.startswith("_")}
    want = names("other") - {"subprocess", "threading"}
    for mod in ("win", "mac"):
        missing = want - names(mod)
        assert not missing, f"osapi/{mod}.py lacks {sorted(missing)}"
    assert osapi.NAME == {"win32": "win", "darwin": "mac"}.get(sys.platform, "other")
    if osapi.IS_WIN:
        osapi.impl()
        assert "AppKit" not in sys.modules and "Quartz" not in sys.modules, "Windows loaded the Mac libraries"
    # shared clipboard rules
    assert common.restore_budget(0.5, 600, 600) > 5 and common.restore_budget(0.5) == 0.5
    t, put_back, answers = [0.0], [], iter([False, True])
    assert common.restore_when_pasted("old", 7, "x", 0.5, 5.0, lambda: 7, put_back.append,
                                      check=lambda _t: next(answers), sleep=lambda d: t.__setitem__(0, t[0] + d),
                                      clock=lambda: t[0])
    assert put_back == ["old"] and t[0] >= 0.5
    assert not common.restore_when_pasted("old", 7, "x", 0.5, 1.0, lambda: 8, put_back.append, check=lambda _t: None,
                                          sleep=lambda d: None, clock=lambda: 0.0), "restored over a newer copy"
    assert common.utf16_slice("a😀bc", 1, 3) == "😀" and common.utf16_len("a😀") == 3
    # the Mac layer imports anywhere (PyObjC only loads on a Mac) and its pure parts work
    from .osapi import mac
    if sys.platform != "darwin":
        assert mac.OBJC_ERROR and mac.permission_problems()[0][0] == "pyobjc"
    assert mac.vk_for(0) == 0x41 and mac.vk_for(9) == 0x56 and mac.vk_for(49) == 0x20 and mac.vk_for(53) == 0x1B
    assert mac.vk_for(63) in hotkeys.FN and mac.vk_for(55) in hotkeys.WIN and mac.vk_for(58) in hotkeys.ALT
    assert mac.vk_for(59) in hotkeys.CTRL and mac.vk_for(56) in hotkeys.SHIFT and mac.vk_for(54) in hotkeys.WIN
    assert mac.vk_for(200) >= 0x1000 and mac.vk_for(200) not in hotkeys.MODIFIER_VKS
    assert len(set(mac.MAC_TO_VK.values())) == len(mac.MAC_TO_VK) - 1, "two Mac keys share a code (only Return)"
    assert mac.modifier_down(63, 0x800000) is True and mac.modifier_down(63, 0) is False
    assert mac.modifier_down(55, 0x100008) is True and mac.modifier_down(54, 0x100008) is False
    assert mac.modifier_down(0, 0xFFFFFF) is None
    import plistlib
    agent = plistlib.loads(mac.agent_plist("/Apps/Aqua Lite/AquaLite.pyw"))
    assert agent["RunAtLoad"] and agent["ProgramArguments"][-1] == "/Apps/Aqua Lite/AquaLite.pyw"
    assert mac.agent_path().endswith("LaunchAgents/com.aqualite.app.plist".replace("/", os.sep))
    # Retina: a 400x100-pixel bar at the bottom of a 1440x900-point screen (2x) sits at Cocoa y=0
    assert mac.to_cocoa(1240, 1700, 400, 100, 2.0, 900) == (620.0, 0.0)
    assert mac.from_cocoa_rect(0, 80, 1440, 795, 2.0, 900) == (0, 50, 2880, 1640)   # menu bar on top, Dock below
    assert mac.app_name("com.google.Chrome", "Google Chrome", "Chrome") == "chrome"
    assert textproc.app_category(mac.app_name("com.microsoft.VSCode", "Electron", "Code")) == "code"
    assert mac.app_name("com.apple.Terminal", "Terminal", "Terminal").lower() in textproc.TERMINALS
    assert textproc.app_category(mac.app_name("com.apple.mail", "Mail", "Mail")) == "email"
    # Mac shortcuts: hold Fn to talk, Fn+Space for hands-free; modifier keys are never swallowed
    FN, SP, LC, LO = 0x100, 0x20, 0xA2, 0xA4
    mac_keys = {k: config.MAC_DEFAULTS[k] for k in config.MAC_DEFAULTS if k.startswith("hotkey")}
    r = Rec(); m = hotkeys.HotkeyMachine(mac_keys, r)
    assert m.on_key(FN, True) is False
    assert m.on_key(SP, True) is True, "the space that starts hands-free must not reach the app"
    m.on_key(SP, False); m.on_key(FN, False)
    assert r.ev == ["start", "lock"], r.ev
    r = Rec(); m = hotkeys.HotkeyMachine(mac_keys, r)
    m.on_key(FN, True); m.on_key(0x5B, True); m.on_key(0x5B, False); m.on_key(FN, False)
    assert r.ev == ["start", "command*", "mask*", "stop*"], r.ev   # Fn + Cmd = Command Mode
    r = Rec(); m = hotkeys.HotkeyMachine({**mac_keys, "hotkey_ptt": "ctrl+option"}, r)
    assert m.on_key(LC, True) is False and m.on_key(LO, True) is False
    m.on_key(LO, False); m.on_key(LC, False)
    assert r.ev == ["start", "mask", "stop"], r.ev   # (mask does nothing on a Mac)
    for spec in ("fn", "globe", "ctrl+option", "cmd+shift+space", "right cmd", "ctrl+cmd+v"):
        hotkeys.parse(spec)


def check_report():
    from . import report
    r = report.redact
    assert r("dictation 2.1s audio, 0.9s, groq [personal] -> ctrl+v | text='call mom at 6 '").endswith("| text=[removed]")
    assert r("INFO dictation 1.0s audio, 0.5s, local [other] -> ctrl+v: 'secret words'").endswith(": [removed]")
    assert r("learned from a correction | text=['Kaitlyn']").endswith("text=[removed]")
    assert r("learned from a correction: ['Kaitlyn']").endswith(": [removed]")
    assert "gsk_" not in r("auth failed for gsk_abcdefghijklmnop1234")
    assert r("update: installed 1.3.1, GitHub 1.3.1 (abc1234)") == "update: installed 1.3.1, GitHub 1.3.1 (abc1234)"
    text = report.build({"groq_api_key": "gsk_secretsecret", "dictionary": ["Kaitlyn"], "language": "auto"}, {"x": 1})
    assert "gsk_secret" not in text and "Kaitlyn" not in text and "language: auto" in text and "API keys set: groq" in text


def check_updater():
    from . import updater
    pv, new = updater.parse_version, updater.is_newer
    assert pv("1.2.3") == (1, 2, 3) and pv("1.10") == (1, 10, 0) and pv("v2.0.1\n") == (2, 0, 1) and pv("x") == (0, 0, 0)
    assert new("1.10.0", "1.9.9") and new("1.1.0", "1.0.0") and not new("1.0.0", "1.0.0") and not new("0.9", "1.0")
    assert updater.parse_version(updater.local_version()) > (0, 0, 0), "VERSION file missing"


def check_look():
    from . import aero, skin, ui
    for maker in (lambda: skin.toggle(20, 1), lambda: skin.radio(18, 0), lambda: skin.field(40, 28, "focus"),
                  lambda: skin.card(48, selected=True), lambda: skin.nav_pill(200, 38, "selected"),
                  lambda: skin.icon("mic", 18), lambda: skin.button(44, 30, "pressed", True)):
        im = maker()
        assert im.mode == "RGBA" and im.getbbox(), "a Settings drawing came out empty"
    assert {p[1] for p in ui.PAGES} >= {"Home", "History", "Instant text", "Private mode"}
    assert all(ui.ALIASES[k] in {p[1] for p in ui.PAGES} for k in ui.ALIASES), "an old tab name points nowhere"
    assert set(ui.HEADINGS) == {p[1] for p in ui.PAGES}
    for frost in (False, True):
        r = aero.FlowBarRenderer(1.0, frost=frost)
        for st in ("idle", "recording", "command", "processing"):
            r.render(st, "", [0.5] * (aero.BARS + 1), 1.0)
            x, y, w, h, rad = r.blur_shape()
            assert 0 <= x and 0 <= y and x + w <= r.size[0] and y + h <= r.size[1] and rad == h // 2
        r.render("hidden")
        assert r.blur_shape() is None
    solid = aero.FlowBarRenderer(1.0).render("recording", "", [0.0] * 15, 0.0)
    see = aero.FlowBarRenderer(1.0, frost=True).render("recording", "", [0.0] * 15, 0.0)
    cx, cy = solid.size[0] // 2 + 40, solid.size[1] - 33
    assert see.getpixel((cx, cy))[3] < solid.getpixel((cx, cy))[3] == 255, "frosted glass should be see-through"


def main():
    for name, fn in (("paste rules & app styles", check_rules), ("text cleanup & snippets", check_text),
                     ("shortcuts", check_hotkeys), ("AI prompts & engines", check_prompts),
                     ("music shuffle", check_music), ("updater", check_updater), ("new features", check_new_features),
                     ("learning & screen context", check_learning), ("instant text", check_instant), ("paste waits for the app", check_paste_wait), ("instant text tidies each sentence", check_sentence_tidy), ("edit by voice", check_voice_edit),
                     ("private mode", check_private_mode), ("new look", check_look), ("flow bar on the graphics card", check_gpu_bar),
                     ("liquid glass theme", check_liquid_look),
                     ("liquid glass on the graphics card", check_liquid_bar),
                     ("liquid glass settings window", check_liquid_settings),
                     ("platform layer (Windows, Mac)", check_platform),
                     ("problem report", check_report)):
        fn()
        print(f"ok  {name}")
    if sys.platform == "win32":
        check_windows()
        print("ok  windows integration")
    print("selftest passed")
    return 0
