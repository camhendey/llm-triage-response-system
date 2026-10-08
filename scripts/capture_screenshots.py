"""ARCHIVED: release 1.0 layout only. For current captures use capture_refined.py.

Capture real screenshots of the running app with Playwright (Chromium).

Usage: streamlit run streamlit_app.py --server.port 8599   (against a freshly reset demo DB)
       python scripts/capture_screenshots.py --url http://localhost:8599 --out docs/screenshots

Every image is a capture of the live application; nothing is drawn or edited.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

CHROMIUM = os.getenv("RW_CHROMIUM", "/opt/pw-browsers/chromium")


def settle(page: Page, ms: int = 600) -> None:
    page.wait_for_timeout(300)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=30000)
    page.wait_for_timeout(ms)


def click_key(page: Page, key: str) -> None:
    page.locator(f".st-key-{key} button").first.click()
    settle(page)


def tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    settle(page, 300)


ANNOTATE = {  # label -> JS returning the element whose box is recorded (for the annotated overview)
    "Queue sorted by urgency": "document.querySelector('.rw-q').closest('[data-testid=\"stColumn\"]')",
    "Next action, blockers and rule IDs": "document.querySelector('.rw-next')",
    "Guest text with cited evidence highlighted": "[...document.querySelectorAll('h3')].find(h => h.innerText.trim() === 'Conversation').closest('[data-testid=\"stColumn\"]')",
    "Facts with status and provenance": "document.querySelector('table.rw-facts')",
    "Demo clock, provider mode, policy hash": "document.querySelector('[data-testid=\"stSidebarContent\"]')",
}


def boxes(page: Page) -> dict:
    out = {}
    for label, js in ANNOTATE.items():
        b = page.evaluate(f"() => {{ const e = {js}; if (!e) return null; const r = e.getBoundingClientRect(); "
                          "return {x: r.x, y: r.y, width: r.width, height: r.height}; }")
        if b:
            out[label] = b
    return out


def shot(page: Page, out: Path, name: str, full: bool = True, record_boxes: bool = False) -> None:
    """Streamlit scrolls inside its own container, so grow the viewport to the content height."""
    vp = page.viewport_size
    if full:
        h = page.evaluate("() => Math.max(...[...document.querySelectorAll('[data-testid=\"stMain\"], "
                          "[data-testid=\"stSidebarContent\"]')].map(e => e.scrollHeight))")
        page.set_viewport_size({"width": vp["width"], "height": min(max(int(h) + 40, vp["height"]), 6000)})
        page.wait_for_timeout(1200)
    if record_boxes:
        (out / f"{name}.boxes.json").write_text(json.dumps(boxes(page), indent=2), encoding="utf-8")
    page.screenshot(path=str(out / f"{name}.png"))
    page.set_viewport_size(vp)
    page.wait_for_timeout(300)
    print("saved", out / f"{name}.png")


def seating_clip(page: Page, out: Path, name: str) -> None:
    """Capture the next-action panel down to the end of the proposal column (a crop of the live page)."""
    page.set_viewport_size({"width": 1440, "height": 1800})
    page.wait_for_timeout(1000)
    top = page.locator(".rw-next").bounding_box()
    col = page.evaluate("() => { const h = [...document.querySelectorAll('h3')].find(h => h.innerText.trim() === "
                        "'Proposal'); const r = h.closest('[data-testid=\"stColumn\"]').getBoundingClientRect(); "
                        "return {x: r.x, y: r.y, width: r.width, height: r.height}; }")
    y0 = top["y"] - 2
    clip = {"x": top["x"] - 8, "y": y0, "width": top["width"] + 16, "height": col["y"] + col["height"] - y0 + 8}
    page.screenshot(path=str(out / f"{name}.png"), clip=clip)
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.wait_for_timeout(300)
    print("saved", out / f"{name}.png")


def correction_sequence(page: Page, out: Path) -> None:
    """Approve a proposal, correct the party size as the operator, show the stale proposal, re-approve."""
    click_key(page, "open_INQ-0104")
    tab(page, "Seating & actions")
    click_key(page, "prop_INQ-0104")
    tab(page, "Seating & actions")
    page.locator("[class*='st-key-appr_'] button").first.click()
    settle(page)
    tab(page, "Seating & actions")
    seating_clip(page, out, "10a_correction_approved")
    tab(page, "Conversation & facts")
    page.get_by_text("Edit a fact (operator)").click()
    settle(page, 300)
    form = page.locator("[data-testid='stForm']").filter(has_text="Save operator value")
    form.locator("[data-testid='stSelectbox']").click()
    page.keyboard.type("Party size")
    page.keyboard.press("Enter")
    form.get_by_role("textbox", name="Value", exact=True).fill("9")
    form.get_by_role("textbox", name="Reason / source (e.g. 'guest phoned')").fill("guest phoned: two more guests")
    form.get_by_role("button", name="Save operator value").click()
    settle(page)
    tab(page, "Seating & actions")
    seating_clip(page, out, "10b_correction_stale")
    click_key(page, "prop_INQ-0104")
    tab(page, "Seating & actions")
    page.locator("[class*='st-key-appr_'] button").first.click()
    settle(page)
    tab(page, "Seating & actions")
    seating_clip(page, out, "10c_correction_reapproved")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8599")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        exe = CHROMIUM if Path(CHROMIUM).exists() else None
        browser = p.chromium.launch(executable_path=exe)
        for width, suffix in ((1440, "desktop"), (820, "narrow")):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.goto(a.url)
            settle(page, 1500)
            shot(page, out, f"01_queue_{suffix}", full=False)
            click_key(page, "open_INQ-0103")
            shot(page, out, f"02_conflict_workspace_{suffix}", record_boxes=suffix == "desktop")
            tab(page, "Seating & actions")
            shot(page, out, f"03_seating_{suffix}")
            if suffix == "narrow":
                page.close()
                continue
            click_key(page, "open_INQ-0101")
            tab(page, "Conversation & facts")
            shot(page, out, f"04_facts_provenance_{suffix}")
            tab(page, "Draft & notes")
            click_key(page, "gen_INQ-0101")
            tab(page, "Draft & notes")
            shot(page, out, f"05_draft_{suffix}")
            tab(page, "History")
            shot(page, out, f"06_history_{suffix}")
            page.get_by_text("Service view", exact=True).click()
            settle(page)
            shot(page, out, f"07_service_view_{suffix}")
            page.get_by_text("Policies & about", exact=True).click()
            settle(page)
            shot(page, out, f"08_policies_{suffix}")
            page.get_by_text("Operator study", exact=True).click()
            settle(page)
            shot(page, out, f"09_operator_study_{suffix}")
            page.get_by_text("Workbench", exact=True).click()
            settle(page)
            correction_sequence(page, out)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
