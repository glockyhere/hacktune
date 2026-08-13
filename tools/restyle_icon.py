#!/usr/bin/env python3
"""
Restyle an APK's launcher icon to match the Dongfeng MAGE launcher's tile spec.

WHY THIS EXISTS
---------------
The MAGE launcher does not mask app icons. Apps that ship a legacy (non-adaptive)
`ic_launcher.png` therefore render as a full-bleed hard-edged square that towers
over the OEM tiles beside it. The OEM icons aren't styled by code — the rounding
and the inset are baked into the artwork.

Spec measured off the launcher's own mipmaps (mdpi, which is 1:1 with the unit's
160-dpi display):

    canvas 200x200 · visible tile 120x120 centred (40px inset) · corner radius 25
    plus a soft drop shadow that bleeds to the canvas edge

Radius 25 is a least-squares fit to the OEM corner profile — PIL's rounded
rectangle measures its radius differently from the OEM curve, so the nominal 22
comes out too tight. The shadow is lifted from a real OEM asset rather than
re-invented, so it matches exactly.

USAGE
-----
    python tools/restyle_icon.py --apk in.apk --out out.apk \\
        --icon-path res/mipmap-{d}-v4/ic_launcher.png \\
        --shadow icon_allapp_media.webp --launcher DFLauncher_release.apk

`--icon-path` takes `{d}` where the density bucket goes; find the real path with

    aapt2 dump badging in.apk | grep "^application:"

The APK is repackaged and MUST be re-signed afterwards (apksigner). See
docs/DONGFENG_MAGE.md for which apps tolerate re-signing — Yandex Navi does NOT.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required:  python -m pip install pillow")

CANVAS = 200
TILE = 120
RADIUS = 25
INSET = (CANVAS - TILE) // 2
DENSITIES = [("mdpi", 1.0), ("hdpi", 1.5), ("xhdpi", 2.0),
             ("xxhdpi", 3.0), ("xxxhdpi", 4.0)]


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=radius, fill=255)
    return m


def oem_shadow(oem_icon: Image.Image, scale: float) -> Image.Image:
    """Take a real OEM tile and keep only what lies outside the tile *shape*.

    The hole punched here is rounded, not square: the tile's corners are
    transparent, so the shadow must still show through them exactly as it does
    on the OEM icons. Punching a square hole leaves visibly bare corners.
    """
    side = int(CANVAS * scale)
    oem = oem_icon.convert("RGBA").resize((side, side), Image.LANCZOS)
    tile, inset = int(TILE * scale), int(INSET * scale)
    keep = Image.new("L", (side, side), 255)
    hole = rounded_mask(tile, int(RADIUS * scale)).point(lambda v: 255 - v)
    keep.paste(hole, (inset, inset))
    # Binarise: any partially-covered edge pixel keeps its shadow. This matches
    # the artwork already verified on the unit; blending here instead would
    # shift every corner pixel and silently change the shipped icons.
    keep = keep.point(lambda v: 255 if v else 0)
    a = oem.split()[3]
    oem.putalpha(Image.composite(a, Image.new("L", (side, side), 0), keep))
    return oem


def bg_colour(art: Image.Image) -> tuple[int, int, int, int]:
    w, h = art.size
    pts = [(w // 2, 2), (w // 2, h - 3), (2, h // 2), (w - 3, h // 2)]
    px = [art.getpixel(p) for p in pts if art.getpixel(p)[3] > 200]
    if not px:
        return (255, 255, 255, 255)
    n = len(px)
    return (sum(p[0] for p in px) // n, sum(p[1] for p in px) // n,
            sum(p[2] for p in px) // n, 255)


def restyle(art_src: Image.Image, oem_icon: Image.Image, scale: float) -> Image.Image:
    art0 = art_src.convert("RGBA")
    bbox = art0.split()[3].getbbox()
    if bbox:
        art0 = art0.crop(bbox)
    t, r, i = int(TILE * scale), int(RADIUS * scale), int(INSET * scale)
    art = art0.resize((t, t), Image.LANCZOS)
    tile = Image.new("RGBA", (t, t), bg_colour(art))
    tile.alpha_composite(art)
    tile.putalpha(rounded_mask(t, r))
    canvas = oem_shadow(oem_icon, scale)
    canvas.alpha_composite(tile, (i, i))
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apk", required=True, help="input APK")
    ap.add_argument("--out", required=True, help="output APK (unsigned)")
    ap.add_argument("--icon-path", required=True,
                    help="in-APK icon path with {d} for the density bucket")
    ap.add_argument("--launcher", required=True,
                    help="DFLauncher_release.apk, pulled from /system/app on the unit")
    ap.add_argument("--shadow", default="icon_allapp_media.webp",
                    help="OEM mipmap inside the launcher APK to lift the shadow from")
    a = ap.parse_args()

    with zipfile.ZipFile(a.launcher) as z:
        name = next((n for n in z.namelist()
                     if n.endswith(a.shadow) and "mipmap-mdpi" in n), None)
        if not name:
            sys.exit(f"{a.shadow} not found in {a.launcher}")
        with z.open(name) as f:
            oem = Image.open(f).copy()

    work = Path(tempfile.mkdtemp())
    src_zip = zipfile.ZipFile(a.apk)

    # Build EVERY density from the highest-resolution artwork in the APK.
    # Using each bucket's own source would upscale e.g. a 48x48 mdpi icon into a
    # 120px tile and ship something visibly soft.
    present = [(d, s, a.icon_path.format(d=d)) for d, s in DENSITIES
               if a.icon_path.format(d=d) in src_zip.namelist()]
    if not present:
        src_zip.close()
        sys.exit(f"no icon entries matched {a.icon_path!r} — check `aapt2 dump badging`")

    best, best_px = None, -1
    for _, _, entry in present:
        with src_zip.open(entry) as f:
            im = Image.open(f).copy()
        if im.size[0] * im.size[1] > best_px:
            best, best_px = im, im.size[0] * im.size[1]
    print(f"source artwork: {best.size[0]}x{best.size[1]}")

    made = []
    for dens, scale, entry in present:
        out = work / entry
        out.parent.mkdir(parents=True, exist_ok=True)
        restyle(best, oem, scale).save(out)
        made.append(entry)
    src_zip.close()

    if not made:
        sys.exit(f"no icon entries matched {a.icon_path!r} — check `aapt2 dump badging`")

    shutil.copy(a.apk, a.out)
    # `zip` updates entries in place, leaving resources.arsc stored/aligned.
    subprocess.run(["zip", "-X", "-q", os.path.abspath(a.out), *made],
                   cwd=work, check=True)
    for pat in ("META-INF/*.RSA", "META-INF/*.SF", "META-INF/*.MF"):
        subprocess.run(["zip", "-q", "-d", a.out, pat],
                       capture_output=True)

    print(f"restyled {len(made)} density variant(s): {', '.join(made)}")
    print(f"wrote {a.out}")
    print("NOW: zipalign -f -p 4, then apksigner sign — the APK is unsigned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
