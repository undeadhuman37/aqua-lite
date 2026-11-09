"""Regenerate the README pictures from the app's own drawing code.   python docs/make_images.py"""
import os
import random
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


from aqualite import aero  # noqa: E402


def banner():
    aero.sky_banner(900, 120, subtitle="Free, open-source voice dictation for Windows").save(os.path.join(HERE, "banner.png"))


def flow_bar():
    r = aero.FlowBarRenderer(1.0)
    w, h = r.size
    rnd = random.Random(4)
    lv = [abs(rnd.gauss(0.45, 0.25)) % 1 for _ in range(14)]
    frames = [
        r.render("recording", "", lv, 3, "info", "hey, the photos came out great, sending them tonight"),
        r.render("locked", "", lv, 7, "info", "send the invoice to Kaitlyn before Friday"),
        r.render("command", "", lv, 5, "info", "make this more formal"),
        r.render("processing", "", [], 4),
        r.render("toast", 'Learned "Kaitlyn" - added to your dictionary', [], 0, "ok"),
    ]
    trim = 26  # empty space above the shorter states
    rows = [frames[0], frames[1], frames[2], frames[3].crop((0, trim * 2, w, h)), frames[4].crop((0, trim * 2, w, h))]
    total = sum(f.size[1] for f in rows) + 20
    bg = aero.vgradient(w, total, (24, 70, 120), (8, 28, 56))
    y = 10
    for f in rows:
        bg.alpha_composite(f, (0, y))
        y += f.size[1]
    bg.save(os.path.join(HERE, "flow-bar.png"))


if __name__ == "__main__":
    banner()
    flow_bar()
    print("docs/banner.png and docs/flow-bar.png updated")
