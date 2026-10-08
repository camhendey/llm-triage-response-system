"""Disposable end-to-end coordinator journey. No real guests or external actions."""

import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screenshots/coordinator"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            "RW_COORDINATOR_DB": td + "/coordinator.sqlite",
            "RW_DEMO_DB": td + "/demo.sqlite",
            "RW_SESSION_DB": td + "/session.sqlite",
            "RW_STUDY_DB": td + "/study.sqlite",
            "RW_PORT": "8626",
            "RW_PROVIDER": "offline",
        }
        path = Path(td) / "server.log"
        with path.open("w") as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "app.py")],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with sync_playwright() as playwright:
                    opts = {"headless": True}
                    if os.getenv("RW_CHROMIUM"):
                        opts["executable_path"] = os.environ["RW_CHROMIUM"]
                    browser = playwright.chromium.launch(**opts)
                    ctx = browser.new_context(
                        viewport={"width": 1440, "height": 1100},
                        permissions=["clipboard-read", "clipboard-write"],
                    )
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    for _ in range(60):
                        try:
                            page.goto("http://127.0.0.1:8626")
                            break
                        except Exception:
                            time.sleep(0.25)

                    def settle():
                        page.wait_for_timeout(350)

                    def click(name):
                        page.get_by_role("button", name=name, exact=True).click()
                        settle()

                    def fill(label, value):
                        page.get_by_label(label, exact=True).fill(value)

                    def expand(name):
                        page.get_by_text(name, exact=True).click()
                        settle()

                    def pick(label, value):
                        page.get_by_label(label, exact=True).click()
                        page.get_by_role("option", name=value, exact=True).click()
                        settle()

                    def shot(name):
                        page.evaluate("window.scrollTo(0,0)")
                        page.wait_for_timeout(1500)
                        page.screenshot(path=str(OUT / name), full_page=True)

                    fill("Coordinator name", "Test coordinator")
                    fill("Restaurant name", "Illustrative venue")
                    fill("Restaurant time zone (IANA)", "UTC")
                    page.get_by_text(
                        "I am authorized to store guest records locally on this computer.",
                        exact=True,
                    ).click()
                    click("Start shift")
                    click("Settings")
                    for tid, capacity, stepfree in [
                        ("A", "8", True),
                        ("B", "10", False),
                    ]:
                        expand("Add or update a table")
                        fill("Table ID", tid)
                        fill("Table capacity", capacity)
                        fill("Area", "Main")
                        if stepfree:
                            page.get_by_text(
                                "Verified step-free access", exact=True
                            ).click()
                        click("Save table")
                    fill("Estimated occupancy minutes", "120")
                    fill("Current policy reviewed by", "Test manager")
                    click("Save current policy")
                    click("Shift & reports")
                    future = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
                    csv = f"Reservation ID,Restaurant ID,Guest name,Visit date,Visit time,Party size,Status,Tables\nOTHER,V1,Synthetic Guest,{future},18:00,4,Confirmed,B\n"
                    page.locator("input[type=file]").set_input_files(
                        {
                            "name": "synthetic-reservations.csv",
                            "mimeType": "text/csv",
                            "buffer": csv.encode(),
                        }
                    )
                    settle()
                    fill(
                        "Export created at (ISO with offset)",
                        (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                    )
                    fill("Report coverage start", future)
                    fill("Report coverage end", future)
                    page.get_by_text(
                        "I checked the mappings, restaurant, export time and report date range. I reviewed report filters; missing rows do not prove availability.",
                        exact=True,
                    ).click()
                    click("Validate report")
                    page.get_by_text(
                        "I checked filters and confirm complete reservation coverage for the declared dates.",
                        exact=True,
                    ).click()
                    click("Use this report")
                    page.reload()
                    settle()
                    assert (
                        page.get_by_text(
                            "Reservations: synthetic-reservations.csv · 1 rows",
                            exact=True,
                        ).count()
                        == 1
                    )
                    click("Open work queue")
                    click("New inquiry")
                    fill("Guest name / label", "Morgan")
                    fill("Email", "morgan@example.com")
                    fill(
                        "Original inquiry",
                        f"Table for 6 people on {future} at 6 pm. No allergies, no accessibility needs, no minors, one bill and no special occasion.",
                    )
                    click("Create inquiry")
                    for key in (
                        "accessibility",
                        "minors",
                        "allergies",
                        "billing",
                        "occasion",
                    ):
                        expand(key.title() + " · Not asked")
                        fill(
                            key.title() + " value",
                            "One bill" if key == "billing" else "None",
                        )
                        pick(key.title() + " state", "Confirmed for this visit")
                        fill(
                            key.title() + " evidence",
                            "Guest confirmed in the original inquiry",
                        )
                    click("Save visit details")
                    shot("01-request.png")
                    click("Plan")
                    fill("Visit date", future)
                    fill("Visit time", "18:00")
                    fill("Party size", "6")
                    page.get_by_label("Tables", exact=True).click()
                    page.get_by_role("option", name="A", exact=True).click()
                    page.keyboard.press("Escape")
                    fill(
                        "Guest-facing seating explanation",
                        "One booth for six guests, for two hours.",
                    )
                    fill(
                        "Photo exception and reason",
                        "Guest inspected the seating in person.",
                    )
                    click("Save arrangement")
                    assert (
                        page.get_by_text(
                            "Snapshot check · Potentially feasible", exact=True
                        ).count()
                        == 1
                    )
                    fill(
                        "Availability evidence / flow considerations",
                        "Checked current availability and restaurant flow externally.",
                    )
                    click("Record external availability check")
                    expand("Verify saved OpenTable booking")
                    fill("External reservation reference", "SYNTHETIC-REF-1")
                    for label in (
                        "Date and time",
                        "Tables and party size",
                        "Guest details and requirements",
                        "Large-party classification",
                        "Made by and saved notes",
                    ):
                        page.get_by_text(label, exact=True).click()
                    fill(
                        "External verification evidence",
                        "Saved and double-checked in simulated external workflow.",
                    )
                    click("Record external verification")
                    click("Communicate")
                    pick("Response purpose", "Final confirmation")
                    click("Generate response")
                    assert (
                        "Before final confirmation:"
                        in page.locator("body").inner_text()
                    )
                    notifications = page.locator(".q-notification").filter(
                        has_text="Before final confirmation:"
                    )
                    if notifications.count():
                        notifications.get_by_role("button").click()
                    click("Request")
                    expand("Record a call")
                    fill(
                        "Call summary / exact guest words",
                        "Guest said: I accept the booth, time and two-hour duration.",
                    )
                    click("Save call")
                    click("Plan")
                    expand("Record guest acceptance")
                    page.get_by_label("Acceptance source", exact=True).click()
                    page.get_by_role("option").filter(
                        has_text="Call · Guest said:"
                    ).click()
                    fill(
                        "Exact acceptance quote",
                        "I accept the booth, time and two-hour duration.",
                    )
                    page.get_by_text(
                        "This evidence accepts the current date, tables, duration and terms.",
                        exact=True,
                    ).click()
                    click("Record acceptance")
                    shot("02-plan.png")
                    click("Communicate")
                    pick("Response purpose", "Final confirmation")
                    click("Generate response")
                    text = page.get_by_label("Response text", exact=True).input_value()
                    assert "Your reservation is confirmed" in text
                    fill("Response text", text + "\nThank you.")
                    settle()
                    page.reload()
                    settle()
                    assert (
                        page.get_by_label("Response text", exact=True)
                        .input_value()
                        .endswith("Thank you.")
                    )
                    pick("Response purpose", "Final confirmation")
                    click("Save response")
                    click("Mark saved response reviewed")
                    click("Copy reviewed response")
                    assert page.evaluate("navigator.clipboard.readText()").endswith(
                        "Thank you."
                    )
                    click("Report sent externally")
                    assert page.get_by_text("Complete", exact=True).count() > 0
                    shot("03-communicate.png")
                    click("Service")
                    fill("Service date", future)
                    settle()
                    fill("Handoff reviewed by", "Front door lead")
                    click("Record staff review")
                    fill("Service date", future)
                    settle()
                    assert (
                        page.get_by_text("Staff review is current.", exact=True).count()
                        == 1
                    )
                    shot("04-service.png")
                    click("Work queue")
                    pick("Show", "All inquiries")
                    click("Open")
                    for width in (820, 390):
                        page.set_viewport_size({"width": width, "height": 900})
                        for view in ("Request", "Plan", "Communicate"):
                            click(view)
                            assert (
                                page.evaluate("document.documentElement.scrollWidth")
                                <= width
                            ), (width, view)
                        shot(f"05-communicate-{width}.png")
                    page.set_viewport_size({"width": 1440, "height": 1100})
                    click("Shift & reports")
                    click("End shift and clear exports")
                    assert (
                        page.get_by_role(
                            "button", name="Start shift", exact=True
                        ).count()
                        == 1
                    )
                    assert not errors, errors
                    browser.close()
                    print(
                        "PASS: start shift, settings, report mapping/apply/reload, inquiry, visit facts, snapshot check, external verification, premature-final guard, call acceptance, draft recovery/review/copy/sent, service review, 820/390px layout, end shift."
                    )
            except Exception:
                if "page" in locals():
                    print(page.locator("body").inner_text()[-6000:])
                raise
            finally:
                process.terminate()
                process.wait(timeout=10)
                server = path.read_text()
                if "Traceback" in server:
                    print(server[-8000:])
                    raise AssertionError(
                        "Server traceback during coordinator browser verification"
                    )


if __name__ == "__main__":
    main()
