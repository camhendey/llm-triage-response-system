"""Additional browser checks: creation, holds, cancellation, conflicting tabs, CSV and study."""

import os, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            "RW_PROVIDER": "offline",
            "RW_DEMO_DB": td + "/demo.sqlite",
            "RW_SESSION_DB": td + "/session.sqlite",
            "RW_STUDY_DB": td + "/study.sqlite",
            "RW_PORT": "8624",
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
                    opts = {"headless": True}
                    if os.getenv("RW_CHROMIUM"):
                        opts["executable_path"] = os.environ["RW_CHROMIUM"]
                    browser = p.chromium.launch(**opts)
                    page = browser.new_page(viewport={"width": 1440, "height": 1050})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    for _ in range(40):
                        try:
                            page.goto("http://127.0.0.1:8624/demo")
                            break
                        except Exception:
                            time.sleep(0.25)

                    def settle(pg=None):
                        pg = pg or page
                        pg.wait_for_timeout(450)
                        pg.locator(".busy-screen").wait_for(state="hidden")

                    def click(test, pg=None):
                        pg = pg or page
                        pg.get_by_test_id(test).click()
                        settle(pg)

                    page.get_by_test_id("ot-demo").click()
                    page.get_by_test_id("new-inquiry").wait_for()
                    click("new-inquiry")
                    page.get_by_label("Guest name / label", exact=True).fill("Riley")
                    page.get_by_label("Guest message", exact=True).fill(
                        "Hello, table for 6 people on November 16, 2026 at 6 pm. No accessibility needs, no minors and no allergies. One bill please. Email riley@example.com. Thanks, Riley"
                    )
                    click("create-inquiry")
                    click("select-arrangement")
                    click("create-hold")
                    click("record-hold")
                    assert page.get_by_text("Held", exact=True).count() > 0
                    click("stage-plan")
                    click("confirm-held")
                    assert page.get_by_text("Confirmed", exact=True).count()>0, page.locator("body").inner_text()
                    click("generate-reply")
                    text = page.get_by_label("Reply", exact=True).input_value()
                    page.get_by_label("Reply", exact=True).fill(
                        text + "\nThanks again."
                    )
                    settle()
                    # Independent browser page sees the saved text, not the first page's buffer.
                    second = browser.new_page(viewport={"width": 1440, "height": 1050})
                    second.goto("http://127.0.0.1:8624/demo")
                    second.get_by_test_id("ot-demo").click()
                    second.get_by_test_id("new-inquiry").wait_for()
                    settle(second)
                    second.locator(".inbox-row").filter(has_text="Riley").get_by_role(
                        "button", name="Open", exact=True
                    ).click()
                    settle(second)
                    click("stage-reply",second)
                    assert (
                        second.get_by_label("Reply", exact=True).input_value() == text
                    )
                    second.get_by_label("Reply", exact=True).fill(
                        text + "\nWe look forward to welcoming you."
                    )
                    settle(second)
                    click("save-reply", second)
                    click("save-reply")
                    assert (
                        page.get_by_text(
                            "This inquiry changed in another action or tab. Refresh and review the latest record before saving.",
                            exact=True,
                        ).count()
                        > 0
                    )
                    assert (
                        page.get_by_label("Reply", exact=True)
                        .input_value()
                        .endswith("Thanks again.")
                    )
                    second.close()
                    page.get_by_role("button", name="Refresh current record", exact=True).click()
                    settle()
                    click("save-reply")
                    click("review-reply")
                    # Adding a message without new extracted facts still makes the reviewed reply stale.
                    page.get_by_text("Add guest reply", exact=True).click()
                    settle()
                    page.get_by_label("New guest message", exact=True).fill(
                        "Thank you for checking."
                    )
                    click("add-message")
                    click("stage-reply")
                    assert page.get_by_test_id("update-draft").count() == 1
                    click("stage-plan")
                    page.get_by_text("Other booking actions", exact=True).click()
                    settle()
                    page.get_by_role(
                        "button", name="Cancel booking", exact=True
                    ).click()
                    settle()
                    page.get_by_label("Reason / reference", exact=True).fill(
                        "Guest requested cancellation by phone."
                    )
                    click("confirm-cancel")
                    assert page.get_by_text("Cancelled", exact=True).count() > 0
                    # CSV upload is parsed only after explicit Import; report rejected rows visibly.
                    page.get_by_role("button", name="Settings", exact=True).click()
                    settle()
                    page.locator("input[type=file]").set_input_files(
                        {
                            "name": "messages.csv",
                            "mimeType": "text/csv",
                            "buffer": b"guest_label,message\nCSV Guest,Table for six please\n",
                        }
                    )
                    page.get_by_text(
                        "messages.csv ready to import", exact=True
                    ).wait_for()
                    page.get_by_role("button", name="Import CSV", exact=True).click()
                    settle()
                    assert (
                        page.get_by_text("1 imported · 0 rejected", exact=True).count()
                        == 1
                    )
                    page.get_by_role("button", name="Project", exact=True).click()
                    settle()
                    page.get_by_role("tab", name="Operator study", exact=True).click()
                    settle()
                    page.get_by_role("button", name="Start", exact=True).click()
                    settle()
                    page.get_by_role("button", name="Finish", exact=True).click()
                    settle()
                    assert (
                        "1/36 sessions completed" in page.locator("body").inner_text()
                    )
                    assert not errors, errors
                    browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                logs = logpath.read_text()
                if "Traceback (most recent call last)" in logs:
                    print(logs)
                    raise AssertionError("Server exception")
    print(
        "PASS: new inquiry, hold, held confirmation, isolated draft buffers, stale-tab rejection, message invalidation, cancellation, CSV import, study timer"
    )


if __name__ == "__main__":
    main()
