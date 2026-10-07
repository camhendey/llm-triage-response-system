"""ARCHIVED: release 1.0 layout only. For current captures use capture_refined.py.

Compose explanatory figures from real screenshots in docs/screenshots.

    python scripts/compose_figures.py

- docs/figures/annotated_overview.png: 02_conflict_workspace_desktop.png with numbered outlines at the element
  boxes Playwright recorded during capture (02_conflict_workspace_desktop.boxes.json) and a numbered key below.
- docs/figures/correction_sequence.png: the three real crops 10a/10b/10c side by side with captions.

Only outlines, numbers and captions are added; the screenshot pixels are not edited.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "docs" / "figures"
ACCENT, INK, MUTED, BG = "#eb6834", "#1E1C19", "#5b5750", "#FFFFFF"


def font(size: int, bold: bool = False):
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),):
        for base in ("/usr/share/fonts/truetype/dejavu", str(Path(ImageFont.__file__).parent / "fonts")):
            p = Path(base) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    try:
        import matplotlib

        return ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name), size)
    except Exception:  # pragma: no cover
        return ImageFont.load_default()


def annotated_overview() -> Path:
    img = Image.open(SHOTS / "02_conflict_workspace_desktop.png").convert("RGB")
    boxes = json.loads((SHOTS / "02_conflict_workspace_desktop.boxes.json").read_text(encoding="utf-8"))
    key_h = 40 + 30 * len(boxes)
    canvas = Image.new("RGB", (img.width, img.height + key_h), BG)
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    f_num, f_key = font(20, True), font(18)
    for i, (label, b) in enumerate(boxes.items(), start=1):
        x0, y0 = max(b["x"] - 4, 2), max(b["y"] - 4, 2)
        x1, y1 = b["x"] + b["width"] + 4, min(b["y"] + b["height"] + 4, img.height - 2)
        d.rectangle([x0, y0, x1, y1], outline=ACCENT, width=3)
        cx, cy = max(x0 - 12, 16), max(y0 - 12, 16)  # badge sits on the corner, outside the content
        d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill=ACCENT, outline="white", width=2)
        d.text((cx, cy), str(i), fill="white", font=f_num, anchor="mm")
        d.text((30, img.height + 24 + (i - 1) * 30), f"{i}. {label}", fill=INK, font=f_key)
    p = OUT / "annotated_overview.png"
    canvas.save(p)
    return p


def correction_sequence() -> Path:
    names = [("10a_correction_approved.png", "1. Proposal P-0001 approved for record v2 (party 14)"),
             ("10b_correction_stale.png", "2. Operator sets party size to 9: P-0001 is stale, commit blocked"),
             ("10c_correction_reapproved.png", "3. Rechecked: P-0002 approved for record v3 (party 9)")]
    imgs = [Image.open(SHOTS / n).convert("RGB") for n, _ in names]
    gap, top = 24, 60
    w = sum(i.width for i in imgs) + gap * (len(imgs) + 1)
    h = max(i.height for i in imgs) + top + 50
    canvas = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(canvas)
    x = gap
    for im, (_n, cap) in zip(imgs, names):
        d.text((x, 20), cap, fill=INK, font=font(19, True))
        canvas.paste(im, (x, top))
        d.rectangle([x - 1, top - 1, x + im.width, top + im.height], outline="#d8d2c8", width=1)
        x += im.width + gap
    d.text((gap, h - 34), "Real crops of the running app (scripts/capture_screenshots.py, INQ-0104 on a fresh demo "
           "database). Approvals are bound to a record version; an operator edit makes earlier proposals stale.",
           fill=MUTED, font=font(16))
    p = OUT / "correction_sequence.png"
    canvas.save(p)
    return p


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for f in (annotated_overview(), correction_sequence()):
        print("wrote", f.relative_to(ROOT))
