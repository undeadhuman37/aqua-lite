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
    assert lw("Tell Patrisio hi.", "Tell Patricio hi.") == ["Patricio"] and lw("the api is down", "the API is down") == ["API"]
    assert lw("have a meeting", "have a call") == [] and lw("hello there", "Hello there") == []
    from . import learn, live
    t = [0.0]
    d, states = "Tell Patrisio hi. ", [(0, "Hey! Tell Patrisio hi. "), (3, "Hey! Tell Patricio hi. "), (8, "")]
    read = lambda: [x for at, x in states if t[0] >= at][-1]
    w = learn.CorrectionWatcher(d, read, lambda: 1, lambda _w: None, clock=lambda: t[0],
                                sleep=lambda secs: t.__setitem__(0, t[0] + secs))
    assert w.run() == ["Patricio"]
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
    assert se("Send it to Patrisio.", "Send it to Patricio.") is None                    # a name: dictionary's job
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
    assert context.assemble(["Patricio", "Patricio: are the samples in?", "  ", "Patricio: are the samples in?",
                             "Yes, Huilin sent them"]) == "Patricio: are the samples in?\nYes, Huilin sent them"
    names = context.hint_names("Patricio: did Huilin ship? Yes. Ask Patricio about the DHL tracking")
    assert names[:3] == ["DHL", "Patricio", "Huilin"] and "Yes" not in names and "Ask" not in names, names
    cfg = {"context_blocked_apps": ["bitwarden"]}
    assert context.allowed("whatsapp", "Chat", cfg) and not context.allowed("Bitwarden", "", cfg)
    assert not context.allowed("chrome", "New Tab - InPrivate", cfg) and not context.allowed("pythonw", "", cfg)
    ctx = {"app": "WhatsApp", "examples": [("Okay, see you.", "ok see u")], "screen": "Sara: lunch?", "draft": "so "}
    x = llm._extras(ctx)
    assert "ok see u" in x and "Sara: lunch?" in x and "so " in x and "never reply" in x
    xc = llm._extras(ctx, command=True)
    assert "ok see u" not in xc and "Sara: lunch?" in xc and llm._extras({"app": "x"}) == ""
    assert stt.vocab_prompt({"dictionary": ["Patricio"]}, ["patricio", "Huilin"]) == "Patricio, Huilin."


def check_instant():
    from . import instant
    a = instant.Agreement()
    w = lambda t, s: (" " + t, s, s + 0.3)
    assert a.insert([w("Hey", 0.1), w("Patrisio", 0.5)]) == []                     # first pass: nothing is sure yet
    assert [x[0] for x in a.insert([w("hey", 0.1), w("Patricio", 0.5), w("the", 0.9)])] == [" hey"]
    assert [x[0] for x in a.insert([w("Hey", 0.1), w("Patricio,", 0.5), w("the", 0.9)])] == [" Patricio,", " the"]
    assert a.insert([w("the", 0.92), w("samples", 1.3)]) == []                     # re-heard 'the' isn't doubled
    assert [x[0] for x in a.insert([w("samples", 1.31), w("arrived", 1.7)])] == [" samples"]
    assert a.text() == "hey Patricio, the samples"
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


def check_report():
    from . import report
    r = report.redact
    assert r("dictation 2.1s audio, 0.9s, groq [personal] -> ctrl+v | text='call mom at 6 '").endswith("| text=[removed]")
    assert r("INFO dictation 1.0s audio, 0.5s, local [other] -> ctrl+v: 'secret words'").endswith(": [removed]")
    assert r("learned from a correction | text=['Patricio']").endswith("text=[removed]")
    assert r("learned from a correction: ['Patricio']").endswith(": [removed]")
    assert "gsk_" not in r("auth failed for gsk_abcdefghijklmnop1234")
    assert r("update: installed 1.3.1, GitHub 1.3.1 (abc1234)") == "update: installed 1.3.1, GitHub 1.3.1 (abc1234)"
    text = report.build({"groq_api_key": "gsk_secretsecret", "dictionary": ["Patricio"], "language": "auto"}, {"x": 1})
    assert "gsk_secret" not in text and "Patricio" not in text and "language: auto" in text and "API keys set: groq" in text


def check_updater():
    from . import updater
    pv, new = updater.parse_version, updater.is_newer
    assert pv("1.2.3") == (1, 2, 3) and pv("1.10") == (1, 10, 0) and pv("v2.0.1\n") == (2, 0, 1) and pv("x") == (0, 0, 0)
    assert new("1.10.0", "1.9.9") and new("1.1.0", "1.0.0") and not new("1.0.0", "1.0.0") and not new("0.9", "1.0")
    assert updater.parse_version(updater.local_version()) > (0, 0, 0), "VERSION file missing"


def main():
    for name, fn in (("paste rules & app styles", check_rules), ("text cleanup & snippets", check_text),
                     ("shortcuts", check_hotkeys), ("AI prompts & engines", check_prompts),
                     ("music shuffle", check_music), ("updater", check_updater), ("new features", check_new_features),
                     ("learning & screen context", check_learning), ("instant text", check_instant), ("edit by voice", check_voice_edit),
                     ("problem report", check_report)):
        fn()
        print(f"ok  {name}")
    if sys.platform == "win32":
        check_windows()
        print("ok  windows integration")
    print("selftest passed")
    return 0
