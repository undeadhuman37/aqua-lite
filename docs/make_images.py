"""Regenerate the README pictures from the app's own drawing code.   python docs/make_images.py"""
import os
import random
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


from aqualite import aero, skin  # noqa: E402


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


def download_button():
    """The README's download button: the app's own glossy aqua button, drawn at 2x for sharp screens."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = 600, 120
    img = skin.button(w, h, "normal", primary=True)
    font = aero._font_px(40)
    text = "Download for Windows"
    tw = font.getlength(text)
    icon = 34
    x = (w - (icon + 22 + tw)) / 2
    cy = h / 2 - 4
    words = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(words)
    # a download arrow into a tray, in the same white as the words
    ax = x + icon / 2
    d.line((ax, cy - 16, ax, cy + 6), fill=(255, 255, 255, 255), width=5)
    d.line((ax - 11, cy - 4, ax, cy + 7, ax + 11, cy - 4), fill=(255, 255, 255, 255), width=5, joint="curve")
    d.line((x, cy + 8, x, cy + 15, x + icon, cy + 15, x + icon, cy + 8), fill=(255, 255, 255, 255), width=5,
           joint="curve")
    d.text((x + icon + 22, cy), text, font=font, fill=(255, 255, 255, 255), anchor="lm")
    shade = Image.new("RGBA", img.size, (0, 42, 92, 0))
    shade.putalpha(words.getchannel("A").point(lambda v: v * 150 // 255).filter(ImageFilter.GaussianBlur(1.5)))
    img.alpha_composite(shade, (0, 2))
    img.alpha_composite(words)
    img.save(os.path.join(HERE, "download.png"))


if __name__ == "__main__":
    banner()
    flow_bar()
    download_button()
    print("docs/banner.png, docs/flow-bar.png and docs/download.png updated")
