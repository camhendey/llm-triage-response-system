"""Capture the 1.1 UI using a disposable database. No mutation of user workspaces.
Install Playwright Chromium or set RW_CHROMIUM to its executable; run from repo root.
"""

from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screenshots/refined"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rw-capture-") as td:
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "RW_PROVIDER": "offline",
            "RW_DEMO_DB": td + "/demo.sqlite",
            "RW_SESSION_DB": td + "/session.sqlite",
            "RW_STUDY_DB": td + "/study.sqlite",
        }
        with open(td + "/server.log", "w") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "app.py"),
                    "--server.port",
                    "8613",
                    "--server.address",
                    "127.0.0.1",
                    "--server.headless",
                    "true",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            atexit.register(proc.terminate)
            try:
                with sync_playwright() as p:
                    opts = {"headless": True}
                    if os.getenv("RW_CHROMIUM"):
                        opts["executable_path"] = os.environ["RW_CHROMIUM"]
                    b = p.chromium.launch(**opts)
                    page = b.new_page(
                        viewport={"width": 1440, "height": 1700}, device_scale_factor=1
                    )
                    for attempt in range(30):
                        try:
                            page.goto("http://127.0.0.1:8613")
                            break
                        except Exception:
                            if attempt == 29:
                                raise
                            time.sleep(0.5)
                    page.locator(".st-key-scenario_INQ-0101 button").wait_for()

                    def settle():
                        page.wait_for_timeout(300)
                        page.wait_for_function(
                            "() => !document.querySelector('[data-testid=stStatusWidget]')"
                        )
                        page.wait_for_timeout(300)
                        assert not page.locator("[data-testid=stException]").count()

                    def click(key):
                        page.locator(".st-key-" + key + " button").click()
                        settle()

                    def shot(name):
                        page.evaluate(
                            "() => { document.querySelector('[data-testid=stMain]').scrollTop=0; document.querySelector('[data-testid=stSidebarContent]').scrollTop=0; }"
                        )
                        page.screenshot(path=str(OUT / (name + ".png")))

                    settle()
                    shot("01-overview")
                    click("scenario_INQ-0101")
                    click("suggest_INQ-0101")
                    page.get_by_text("Compare seating and times", exact=True).click()
                    settle()
                    shot("02-seating")
                    page.get_by_text("Compare seating and times", exact=True).click()
                    click("confirm_INQ-0101")
                    click("gen_INQ-0101")
                    shot("03-reply")
                    page.get_by_role("button", name="Mark reviewed", exact=True).click()
                    settle()
                    page.get_by_role(
                        "button", name="I sent this reply elsewhere", exact=True
                    ).click()
                    settle()
                    assert (
                        "Team reply · reported sent"
                        in page.locator("body").inner_text()
                    )
                    shot("04-conversation")
                    page.get_by_text("Service view", exact=True).click()
                    settle()
                    assert page.get_by_role(
                        "button", name="Export service handoff", exact=True
                    ).count()
                    shot("05-service")
                    page.get_by_text("Workbench", exact=True).click()
                    settle()
                    click("back_overview")
                    click("scenario_INQ-0103")
                    page.set_viewport_size({"width": 820, "height": 1400})
                    settle()
                    toggle = page.locator(
                        "[data-testid=stSidebarCollapseButton] button"
                    )
                    if toggle.count() and toggle.is_visible():
                        toggle.click()
                        settle()
                    shot("06-narrow")
                    (OUT / "manifest.json").write_text(
                        json.dumps(
                            {
                                "source": "Unedited Chromium captures; disposable synthetic database",
                                "viewports": [
                                    {"width": 1440, "height": 1700},
                                    {"width": 820, "height": 1400},
                                ],
                                "journey": "Select arrangement → confirm → prepare/review reply → report sent → inspect conversation and service handoff",
                                "images": sorted(x.name for x in OUT.glob("*.png")),
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    b.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
    print("Saved", OUT)


if __name__ == "__main__":
    main()
