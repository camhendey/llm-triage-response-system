"""Browser integration check using labelled illustrative reports and temporary databases."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/screenshots/opentable'
OUT.mkdir(parents=True, exist_ok=True)


def main():
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, 'RW_PROVIDER':'offline', 'RW_DEMO_DB':td+'/demo.sqlite',
               'RW_SESSION_DB':td+'/session.sqlite', 'RW_STUDY_DB':td+'/study.sqlite', 'RW_PORT':'8625'}
        with open(td+'/server.log', 'w') as log:
            proc = subprocess.Popen([sys.executable, str(ROOT/'app.py')], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with sync_playwright() as p:
                    options = {'headless':True}
                    if os.getenv('RW_CHROMIUM'):
                        options['executable_path'] = os.environ['RW_CHROMIUM']
                    browser = p.chromium.launch(**options)
                    page = browser.new_page(viewport={'width':1440,'height':1050})
                    errors=[]
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    for _ in range(60):
                        try:
                            page.goto('http://127.0.0.1:8625/demo')
                            break
                        except Exception:
                            time.sleep(.25)
                    expect(page.get_by_text('Prepare your session', exact=True)).to_be_visible()
                    page.screenshot(path=str(OUT/'01-session-setup.png'))
                    with page.expect_file_chooser() as chooser:
                        page.get_by_test_id('ot-choose').click()
                    chooser.value.set_files({'name':'invalid.csv','mimeType':'text/csv','buffer':b'A,B\n'})
                    expect(page.get_by_text('The report has headers but no data. An empty report cannot establish availability.',exact=True)).to_be_visible()
                    def upload(filename, kind='reservations'):
                        page.locator('input[type=file]').set_input_files(str(ROOT/'data/synthetic/opentable'/filename))
                        expect(page.get_by_text('Report settings', exact=True)).to_be_visible()
                        if kind=='guests':
                            page.get_by_label('Report type',exact=True).click()
                            page.get_by_role('option',name='Optional guestbook',exact=True).click()
                        page.get_by_label('Restaurant name',exact=True).fill('Illustrative restaurant')
                        page.get_by_label('Export created at (ISO with offset)',exact=True).fill('2026-10-07T09:00:00-04:00')
                        page.get_by_label('Report coverage start',exact=True).fill('2026-11-13')
                        page.get_by_label('Report coverage end',exact=True).fill('2026-11-14')
                        page.get_by_role('checkbox').click()
                        expect(page.get_by_role('checkbox')).to_have_attribute('aria-checked', 'true')
                        page.get_by_test_id('ot-validate').click()
                        expect(page.get_by_text('Review import',exact=True)).to_be_visible()
                        page.get_by_test_id('ot-apply').click()
                        expect(page.get_by_text('Report settings',exact=True)).not_to_be_visible()
                        expect(page.get_by_text('2 · Ready for review',exact=True)).to_be_visible()
                    upload('reservations_ILLUSTRATIVE.csv')
                    upload('guests_ILLUSTRATIVE.csv','guests')
                    # Same report replaces the snapshot rather than appending rows.
                    upload('reservations_ILLUSTRATIVE.csv')
                    expect(page.get_by_text('Reservations: reservations_ILLUSTRATIVE.csv · 3 rows',exact=True)).to_be_visible()
                    page.evaluate('window.scrollTo(0,0)')
                    page.wait_for_timeout(3000)
                    page.screenshot(path=str(OUT/'02-reviewed-reports.png'),full_page=True)
                    page.get_by_test_id('ot-continue').click()
                    page.get_by_test_id('new-inquiry').click()
                    page.get_by_label('Guest name / label',exact=True).fill('Morgan')
                    page.get_by_label('Guest message',exact=True).fill('Hello, table for 6 people on November 13, 2026 at 6 pm. Email morgan@example.invalid. No allergies, no minors, no accessibility needs. One bill please.')
                    page.get_by_test_id('create-inquiry').click()
                    expect(page.get_by_text('2026-11-13: 1 potentially active reservations · 6 covers in this export',exact=True)).to_be_visible()
                    expect(page.get_by_text('Guestbook contact matches: 2 candidate records',exact=True)).to_be_visible()
                    page.get_by_text('Morgan · source record 2',exact=True).last.click()
                    expect(page.get_by_text('Guestbook notes: Prefers a quiet table',exact=True)).to_be_visible()
                    page.evaluate('window.scrollTo(0,0)')
                    page.wait_for_timeout(3000)
                    page.screenshot(path=str(OUT/'03-inquiry-context.png'),full_page=True)
                    # New browser page cannot see the first page's import.
                    second=browser.new_page()
                    second.goto('http://127.0.0.1:8625/demo')
                    expect(second.get_by_text('Prepare your session',exact=True)).to_be_visible()
                    assert not second.get_by_text('2 · Ready for review',exact=True).count()
                    second.close()
                    page.reload()
                    expect(page.get_by_text('Prepare your session',exact=True)).to_be_visible()
                    assert not page.get_by_text('2 · Ready for review',exact=True).count()
                    page.set_viewport_size({'width':390,'height':844})
                    page.wait_for_timeout(500)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                    page.screenshot(path=str(OUT/'04-mobile-setup.png'),full_page=True)
                    page.locator('input[type=file]').set_input_files(str(ROOT/'data/synthetic/opentable/reservations_ILLUSTRATIVE.csv'))
                    expect(page.get_by_text('Report settings',exact=True)).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                    page.screenshot(path=str(OUT/'05-mobile-mapping.png'),full_page=True)
                    page.get_by_test_id('ot-demo').click()
                    expect(page.get_by_test_id('new-inquiry')).to_be_visible()
                    assert not errors, errors
                    browser.close()
                log.flush()
                assert 'Traceback' not in Path(td+'/server.log').read_text(), Path(td+'/server.log').read_text()
                print('PASS: setup gate, CSV mapping/preview/apply, optional guestbook, replacement, date totals, shared-contact candidates, tab isolation, reload, mobile setup, demo path. No browser errors or server tracebacks.')
            finally:
                proc.terminate()
                proc.wait(timeout=15)

if __name__=='__main__':
    main()
