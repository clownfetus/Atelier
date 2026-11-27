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

ROOT = Path(__file__).resolve().parents[1]
CSS_RE = re.compile(r'<link\s+rel="stylesheet"\s+href="/static/([^"]+)">')
JS_RE = re.compile(r'<script\s+src="/static/([^"]+)"></script>')


def _check_paths(src_dir: Path, html: str):
    missing = []
    for regex in (CSS_RE, JS_RE):
        for match in regex.finditer(html):
            rel = match.group(1)
            if not (src_dir / rel).is_file():
                missing.append(rel)
    return missing


def bundle(src_dir: Path, out_dir: Path):
    index_path = src_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    missing = _check_paths(src_dir, html)
    if missing:
        raise FileNotFoundError(f"Missing static assets referenced in index.html: {missing}")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(src_dir, out_dir)

    head_end = html.index("</head>")
    head_html, body_html = html[:head_end], html[head_end:]

    css_files = CSS_RE.findall(html)
    head_js_files = JS_RE.findall(head_html)
    body_js_files = JS_RE.findall(body_html)

    css_parts = []
    for rel in css_files:
        text = (src_dir / rel).read_text(encoding="utf-8")
        css_parts.append(f"/* === {rel} === */\n{text}\n")
    (out_dir / "bundle.css").write_text("\n".join(css_parts), encoding="utf-8", newline="\n")

    def concat_js(files):
        parts = []
        for rel in files:
            text = (src_dir / rel).read_text(encoding="utf-8").rstrip()
            parts.append(f"/* === {rel} === */\n{text};\n")
        return "\n".join(parts)

    (out_dir / "bundle-head.js").write_text(concat_js(head_js_files), encoding="utf-8", newline="\n")
    (out_dir / "bundle-body.js").write_text(concat_js(body_js_files), encoding="utf-8", newline="\n")

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
    (out_dir / "index.html").write_text(bundled_html, encoding="utf-8", newline="\n")

    return {
        "css_count": len(css_files),
        "head_js_count": len(head_js_files),
        "body_js_count": len(body_js_files),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ROOT / "gui")
    parser.add_argument("--out", type=Path, help="Output directory for bundled GUI")
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
    stats = bundle(args.src, args.out)
    print(f"Bundled {stats['css_count']} CSS and {stats['head_js_count'] + stats['body_js_count']} JS files into {args.out}")


if __name__ == "__main__":
    main()
