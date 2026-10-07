"""Real-browser workflow checks and screenshots using disposable synthetic databases."""

import os, subprocess, tempfile, time, json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screenshots/clean"
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as td:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "RW_PROVIDER": "offline",
        "RW_DEMO_DB": td + "/demo.sqlite",
        "RW_SESSION_DB": td + "/session.sqlite",
        "RW_STUDY_DB": td + "/study.sqlite",
    }
    with open(Path(td) / "server.log", "w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "app.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8622",
                "--server.headless",
                "true",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    executable_path=os.getenv("RW_CHROMIUM"),
                    args=["--no-sandbox"],
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                for n in range(30):
                    try:
                        page.goto("http://127.0.0.1:8622")
                        break
                    except:
                        time.sleep(0.4)

                def settle():
                    page.wait_for_timeout(300)
                    page.wait_for_function(
                        "() => !document.querySelector('[data-testid=stStatusWidget]')"
                    )
                    page.wait_for_timeout(300)
                    assert not page.locator("[data-testid=stException]").count(), (
                        page.locator("body").inner_text()
                    )
                    assert "RangeError:" not in page.locator("body").inner_text()

                def click(k):
                    page.locator(".st-key-" + k + " button").click()
                    settle()

                def shot(name):
                    page.evaluate(
                        "() => {document.querySelector('[data-testid=stMain]').scrollTop=0;document.querySelector('[data-testid=stSidebarContent]').scrollTop=0;}"
                    )
                    page.screenshot(path=str(OUT / (name + ".png")))

                page.locator(".st-key-open_INQ-0101 button").wait_for()
                settle()
                shot("01-inbox")
                click("open_INQ-0101")
                shot("02-plan")
                click("suggest_INQ-0101")
                page.get_by_role("button", name="Edit reservation", exact=True).click()
                settle()
                shot("03-edit")
                page.get_by_role("spinbutton", name="Party size", exact=True).fill("10")
                page.get_by_role("button", name="Save details", exact=True).click()
                settle()
                assert "10 guests" in page.locator("body").inner_text()
                assert (
                    "earlier arrangement is stale" in page.locator("body").inner_text()
                )
                click("suggest_INQ-0101")
                shot("04-selected")
                click("confirm_INQ-0101")
                click("gen_INQ-0101")
                shot("05-reply")
                assert page.locator(".st-key-open_INQ-0101 button").count() == 1
                page.get_by_role("button", name="Mark reviewed", exact=True).click()
                settle()
                shot("06-reviewed")
                page.get_by_role(
                    "button", name="Record sent elsewhere", exact=True
                ).click()
                settle()
                shot("07-complete")
                assert (
                    page.get_by_text(
                        "Reply recorded as sent elsewhere", exact=True
                    ).count()
                    == 1
                )
                assert (
                    page.get_by_role(
                        "button", name="Record sent elsewhere", exact=True
                    ).count()
                    == 0
                )
                page.get_by_text("Service", exact=True).click()
                settle()
                shot("08-service")
                page.get_by_text("Timeline", exact=True).click()
                settle()
                shot("09-timeline")
                for width, height in [(820, 1100), (390, 844)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto("http://127.0.0.1:8622")
                    page.get_by_role(
                        "button", name="Open inquiry", exact=True
                    ).first.wait_for()
                    settle()
                    page.get_by_role(
                        "button", name="Open inquiry", exact=True
                    ).first.click()
                    settle()
                    shot(f"10-workspace-{width}")
                    print(
                        json.dumps(
                            {
                                "width": width,
                                "overflow": page.evaluate(
                                    "() => ({viewport:innerWidth,docWidth:document.documentElement.scrollWidth, mainWidth:document.querySelector('[data-testid=stMain]').scrollWidth})"
                                ),
                            }
                        )
                    )
                browser.close()
        finally:
            proc.terminate()
            proc.wait(timeout=10)
print("Captured clean UI")
