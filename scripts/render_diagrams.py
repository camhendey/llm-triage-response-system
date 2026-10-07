"""Render docs/diagrams/*.mmd to SVG and PNG with a local Mermaid build and Chromium.

    npm install --prefix /tmp/mm mermaid@11
    python scripts/render_diagrams.py --mermaid-js /tmp/mm/node_modules/mermaid/dist/mermaid.min.js

The .mmd files are the editable sources; the SVG/PNG files are derived exports.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

DIAGRAMS = Path(__file__).resolve().parents[1] / "docs" / "diagrams"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mermaid-js", required=True)
    a = ap.parse_args()
    js = Path(a.mermaid_js).read_text(encoding="utf-8")
    exe = os.getenv("RW_CHROMIUM", "/opt/pw-browsers/chromium")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe if Path(exe).exists() else None)
        page = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        page.set_content("<html><body style='margin:0;background:#fff'><div id=o></div></body></html>")
        page.add_script_tag(content=js)
        page.evaluate("""() => mermaid.initialize({startOnLoad:false, theme:'base', securityLevel:'strict',
          themeVariables:{primaryColor:'#F1EDE6', primaryBorderColor:'#8F887C', lineColor:'#6B655C',
          primaryTextColor:'#1E1C19', fontFamily:'Helvetica, Arial, sans-serif', fontSize:'15px'}})""")
        for src in sorted(DIAGRAMS.glob("*.mmd")):
            code = src.read_text(encoding="utf-8")
            svg = page.evaluate(f"async () => (await mermaid.render('d', {json.dumps(code)})).svg")
            src.with_suffix(".svg").write_text(svg, encoding="utf-8")
            page.evaluate("s => { document.getElementById('o').innerHTML = s; }", svg)
            page.locator("#o svg").screenshot(path=str(src.with_suffix(".png")))
            print("rendered", src.name)
        b.close()


if __name__ == "__main__":
    main()
