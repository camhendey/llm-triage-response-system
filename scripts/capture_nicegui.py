"""Real-browser migration verification against disposable databases. No live calls."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screenshots/nicegui"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            "RW_PROVIDER": "offline",
            "RW_DEMO_DB": td + "/demo.sqlite",
            "RW_SESSION_DB": td + "/session.sqlite",
            "RW_STUDY_DB": td + "/study.sqlite",
            "RW_PORT": "8623",
        }
        logpath = Path(td) / "server.log"
        with logpath.open("w") as log:
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "app.py")],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with sync_playwright() as p:
                    options = {"headless": True}
                    if os.getenv("RW_CHROMIUM"):
                        options["executable_path"] = os.environ["RW_CHROMIUM"]
                    browser = p.chromium.launch(**options)
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 1050},
                        permissions=["clipboard-read", "clipboard-write"],
                    )
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    for _ in range(40):
                        try:
                            page.goto("http://127.0.0.1:8623")
                            break
                        except Exception:
                            time.sleep(0.25)

                    def settle():
                        page.wait_for_timeout(350)
                        page.locator(".busy-screen").wait_for(state="hidden")
                        assert not page.get_by_text(
                            "500 Internal Server Error", exact=True
                        ).count()

                    def click(test):
                        page.get_by_test_id(test).click()
                        settle()

                    def shot(name):
                        page.mouse.move(0,0)
                        page.wait_for_timeout(3500)
                        page.evaluate("window.scrollTo(0,0)")
                        page.screenshot(path=str(OUT / (name + ".png")))

                    page.get_by_test_id("new-inquiry").wait_for()
                    settle()
                    shot("01-inbox")
                    click("open-INQ-0101")
                    shot("02-workspace")
                    click("select-arrangement")
                    click("edit-reservation")
                    shot("03-edit")
                    page.get_by_label("Party size", exact=True).fill("10")
                    click("save-details")
                    assert (
                        "earlier arrangement is out of date"
                        in page.locator("body").inner_text()
                    )
                    assert "10 guests" in page.locator("body").inner_text()
                    click("select-arrangement")
                    shot("04-plan")
                    click("confirm-booking")
                    click("generate-reply")
                    shot("05-reply")
                    editor = page.get_by_label("Reply", exact=True)
                    draft = editor.input_value()
                    editor.fill(draft + "\nThank you.")
                    settle()
                    click("stage-plan")
                    click("stage-reply")
                    assert (
                        page.get_by_label("Reply", exact=True)
                        .input_value()
                        .endswith("Thank you.")
                    )
                    click("save-reply")
                    click("review-reply")
                    shot("06-reviewed")
                    click("copy-reply")
                    assert page.evaluate("navigator.clipboard.readText()").endswith(
                        "Thank you."
                    )
                    click("sent-reply")
                    shot("07-completed")
                    assert (
                        page.get_by_text(
                            "Reply recorded as sent externally", exact=True
                        ).count()
                        >= 1
                    )
                    assert page.get_by_test_id("sent-reply").count() == 0
                    page.get_by_role("button", name="Service", exact=True).click()
                    settle()
                    shot("08-service")
                    page.get_by_role("button", name="Timeline", exact=True).click()
                    settle()
                    shot("09-timeline")
                    page.get_by_role("button", name="Project", exact=True).click()
                    settle()
                    shot("10-project")
                    page.get_by_role("button", name="Settings", exact=True).click()
                    settle()
                    shot("11-settings")
                    for width, height in [(820, 1100), (390, 844)]:
                        page = browser.new_page(
                            viewport={"width": width, "height": height}
                        )
                        page.goto("http://127.0.0.1:8623")
                        page.get_by_test_id("new-inquiry").wait_for()
                        settle()
                        shot(f"12-inbox-{width}")
                        click("open-INQ-0103")
                        shot(f"13-workspace-{width}")
                        dims = page.evaluate(
                            "({viewport:innerWidth,width:document.documentElement.scrollWidth})"
                        )
                        assert dims["width"] <= width, dims
                        print(json.dumps(dims))
                    assert not errors, errors
                    browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                logs = logpath.read_text()
                if "Traceback (most recent call last)" in logs:
                    print(logs)
                    raise AssertionError("Server exception during browser journey")
    print("NiceGUI browser journey passed")


if __name__ == "__main__":
    main()
