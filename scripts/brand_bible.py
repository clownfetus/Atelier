"""Print the brand bible: docs/brand/bible.html to docs/brand/Atelier_Brand_Bible_v1.3.pdf.

The page draws its own artwork from gui/brand/ and the glyph engine, so run this after the mark,
the colours or the poses change. It uses Playwright's Chromium, or the installed Edge with --edge.
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'docs' / 'brand' / 'bible.html'
OUTPUT = ROOT / 'docs' / 'brand' / 'Atelier_Brand_Bible_v1.3.pdf'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--edge', action='store_true', help="print with the installed Edge instead of Playwright's Chromium")
    parser.add_argument('--out', type=Path, default=OUTPUT)
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch(**({'channel': 'msedge'} if args.edge else {}))
        page = browser.new_page(viewport={'width': 1600, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(SOURCE.as_uri())
        page.wait_for_selector('body[data-ready="true"]', timeout=20000)
        if errors:
            print('The page failed:', *errors, sep='\n  ')
            return 1
        pdf = page.pdf(width='1600px', height='900px', print_background=True, prefer_css_page_size=True)
        browser.close()
    args.out.write_bytes(pdf)
    print(f'Wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out} ({len(pdf) // 1024} KB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
