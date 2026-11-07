"""Build dist/AquaLite-Setup-<version>.exe.   python installer/build.py

Needs NSIS (makensis): `apt install nsis` on Linux, or https://nsis.sourceforge.io on Windows.
"""
import os
import random
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "build")
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from aqualite import aero  # noqa: E402

APP_FILES = ["AquaLite.pyw", "VERSION", "CHANGELOG.md", "README.md", "LICENSE", "requirements.txt",
             "install.bat", "uninstall.bat"]


def stage():
    src = os.path.join(BUILD, "src")
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(src)
    for f in APP_FILES:
        shutil.copy2(os.path.join(ROOT, f), src)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(ROOT, "aqualite"), os.path.join(src, "aqualite"), ignore=ignore)
    shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(src, "assets"), ignore=ignore)


def _bubbles(img, n, seed, area):
    rnd = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))  # drawn on its own layer so the glass blends, not paints
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = area
    for _ in range(n):
        r = rnd.uniform(3, 13)
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 150), width=1, fill=(255, 255, 255, 30))
        d.ellipse((x - r * 0.55, y - r * 0.65, x - r * 0.1, y - r * 0.25), fill=(255, 255, 255, 170))
    img.alpha_composite(layer)


def welcome_bitmap(path):
    """164x314 side picture on the welcome/finish pages: sky to water, sun glow, bubbles, the app icon."""
    w, h = 164, 314
    img = aero.vgradient(w, h, (130, 210, 255), (0, 120, 200))
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((-40, -90, w + 40, 150), fill=170)
    sun = Image.new("RGBA", (w, h), (255, 255, 235, 0))
    sun.putalpha(glow.filter(ImageFilter.GaussianBlur(40)))
    img.alpha_composite(sun)
    sw = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(sw)
    for i, a in enumerate((80, 50, 30)):
        d.arc((-160, 170 + i * 26, w + 160, 520 + i * 26), 200, 340, fill=(255, 255, 255, a), width=5)
    img.alpha_composite(sw.filter(ImageFilter.GaussianBlur(1.2)))
    _bubbles(img, 18, 3, (0, 205, w, h))
    icon = aero.app_icon(96)
    img.alpha_composite(icon, ((w - 96) // 2, 52))
    d = ImageDraw.Draw(img)
    f = aero._font(19)
    d.text((w // 2 + 1, 175 + 1), "Aqua Lite", font=f, fill=(0, 60, 110, 130), anchor="mm")
    d.text((w // 2, 175), "Aqua Lite", font=f, fill=(255, 255, 255, 255), anchor="mm")
    img.convert("RGB").save(path, "BMP")


def header_bitmap(path):
    """150x57 picture in the top-right corner of the progress page."""
    w, h = 150, 57
    img = aero.vgradient(w, h, (215, 243, 255), (120, 200, 245))
    _bubbles(img, 6, 9, (0, 0, w - 60, h))
    img.alpha_composite(aero.app_icon(44), (w - 52, 6))
    img.convert("RGB").save(path, "BMP")


def main():
    version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    stage()
    welcome_bitmap(os.path.join(BUILD, "welcome.bmp"))
    header_bitmap(os.path.join(BUILD, "header.bmp"))
    makensis = shutil.which("makensis") or r"C:\Program Files (x86)\NSIS\makensis.exe"
    subprocess.run([makensis, "-V2", f"-DVERSION={version}", os.path.join(HERE, "AquaLite.nsi")], check=True)
    out = os.path.join(ROOT, "dist", f"AquaLite-Setup-{version}.exe")
    print(f"built {out} ({os.path.getsize(out) // 1024} KB)")
    return out


if __name__ == "__main__":
    main()
