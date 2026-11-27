"""Zero-dependency frontend asset bundler for packaged Atelier releases.

Concatenates static stylesheets and classic scripts referenced by gui/index.html
into three ordered bundles (bundle.css, bundle-head.js, bundle-body.js) to cut
cold-start HTTP fan-out in WebView2 while keeping dev checkouts unbundled.

Usage:
  python scripts/bundle_frontend.py --check
  python scripts/bundle_frontend.py --src gui --out build/gui-bundled
"""
import argparse
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CSS_RE = re.compile(r'<link\s+rel="stylesheet"\s+href="/static/([^"]+)">')
JS_RE = re.compile(r'<script\s+src="/static/([^"]+)"></script>')
BUNDLE_MARKER = ".atelier-frontend-bundle"
BUNDLE_SIGNATURE = "Atelier frontend bundle\n"


def _check_paths(src_dir: Path, html: str):
    missing = []
    for regex in (CSS_RE, JS_RE):
        for match in regex.finditer(html):
            rel = match.group(1)
            if not (src_dir / rel).is_file():
                missing.append(rel)
    return missing


def _check_output(out_dir: Path):
    if not out_dir.exists():
        return
    if out_dir.is_dir():
        if not any(out_dir.iterdir()):
            return
        marker = out_dir / BUNDLE_MARKER
        if marker.is_file() and marker.read_text(encoding="utf-8") == BUNDLE_SIGNATURE:
            return
    raise ValueError(f"Output must be empty or a previously generated Atelier bundle: {out_dir}")


def bundle(src_dir: Path, out_dir: Path):
    src_dir, out_dir = src_dir.resolve(), out_dir.resolve()
    if out_dir.is_relative_to(src_dir) or src_dir.is_relative_to(out_dir):
        raise ValueError("The source and output directories must be separate.")
    _check_output(out_dir)
    index_path = src_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    missing = _check_paths(src_dir, html)
    if missing:
        raise FileNotFoundError(f"Missing static assets referenced in index.html: {missing}")

    head_end = html.index("</head>")
    head_html, body_html = html[:head_end], html[head_end:]

    css_files = CSS_RE.findall(html)
    head_js_files = JS_RE.findall(head_html)
    body_js_files = JS_RE.findall(body_html)

    css_parts = []
    for rel in css_files:
        text = (src_dir / rel).read_text(encoding="utf-8")
        css_parts.append(f"/* === {rel} === */\n{text}\n")

    def concat_js(files):
        parts = []
        for rel in files:
            text = (src_dir / rel).read_text(encoding="utf-8").rstrip()
            parts.append(f"/* === {rel} === */\n{text}\n;\n")
        return "\n".join(parts)

    # Replace matched tags with single bundle references at first occurrence.
    css_inserted = False
    def replace_css(_match):
        nonlocal css_inserted
        if not css_inserted:
            css_inserted = True
            return '<link rel="stylesheet" href="/static/bundle.css">'
        return ""

    head_js_inserted = False
    def replace_head_js(_match):
        nonlocal head_js_inserted
        if not head_js_inserted:
            head_js_inserted = True
            return '<script src="/static/bundle-head.js"></script>'
        return ""

    body_js_inserted = False
    def replace_body_js(_match):
        nonlocal body_js_inserted
        if not body_js_inserted:
            body_js_inserted = True
            return '<script src="/static/bundle-body.js"></script>'
        return ""

    new_head = JS_RE.sub(replace_head_js, CSS_RE.sub(replace_css, head_html))
    new_body = JS_RE.sub(replace_body_js, CSS_RE.sub(replace_css, body_html))
    bundled_html = re.sub(r"\n{3,}", "\n\n", new_head + new_body)

    files = {
        "bundle.css": "\n".join(css_parts),
        "bundle-head.js": concat_js(head_js_files),
        "bundle-body.js": concat_js(body_js_files),
        "index.html": bundled_html,
        BUNDLE_MARKER: BUNDLE_SIGNATURE,
    }
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".atelier-bundle-", dir=out_dir.parent) as scratch:
        staged = Path(scratch) / "gui"
        previous = Path(scratch) / "previous"
        shutil.copytree(src_dir, staged)
        for filename, content in files.items():
            (staged / filename).write_text(content, encoding="utf-8", newline="\n")
        _check_output(out_dir)
        if out_dir.exists():
            out_dir.rename(previous)
        try:
            staged.rename(out_dir)
        except OSError:
            if previous.exists() and not out_dir.exists():
                previous.rename(out_dir)
            raise

    return {
        "css_count": len(css_files),
        "head_js_count": len(head_js_files),
        "body_js_count": len(body_js_files),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ROOT / "gui")
    parser.add_argument("--out", type=Path, help="New, empty, or previously generated output directory")
    parser.add_argument("--check", action="store_true", help="Verify all referenced static assets exist")
    args = parser.parse_args()

    html = (args.src / "index.html").read_text(encoding="utf-8")
    missing = _check_paths(args.src, html)
    if missing:
        print(f"Missing static assets: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    if args.check and not args.out:
        print(f"OK: {len(CSS_RE.findall(html))} CSS + {len(JS_RE.findall(html))} classic JS assets verified.")
        return
    if not args.out:
        parser.error("Provide --out <dir> or --check")
    try:
        stats = bundle(args.src, args.out)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Bundled {stats['css_count']} CSS and {stats['head_js_count'] + stats['body_js_count']} JS files into {args.out}")


if __name__ == "__main__":
    main()
