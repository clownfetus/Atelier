"""Quick-lookup "Sets": user-authored markdown files that name a bundle of assets by PATH LOOKUP, so
a whole related set (a skin's textures + materials + meshes, a themed collection, …) can be
unpacked / loaded / staged in one action instead of hunting each asset.

Drop `*.md` files in the `Sets/` folder next to the exe. Format is deliberately loose:
  - The first `# Heading` (or the filename) is the set's display name.
  - Any line that looks like an asset PATH or GLOB is a lookup pattern. Everything else (prose,
    `## Section` headings, blank lines, `- ` bullets' prose) is ignored, so you can annotate freely.
  - Globs: `*` matches within a path segment, `**` matches across segments. Patterns are matched
    (case-insensitive) against every asset's game_rel. A bare folder like `Characters/1060/1060501`
    is treated as `Characters/1060/1060501/**` (everything under it).

Example `Coastal Kumiho.md`:
    # Coastal Kumiho
    ## the skin + its shared material bucket
    Characters/1060/1060501/**
    Characters/1060/1060CommonMaterial/**
    ## just the recolour inputs
    Characters/1060/1060501/**/*_ColorID
    Characters/1060/1060501/**/*_D

Resolving a set returns game_rels, which flow straight into the existing extract / import / build_mod
paths — this module only turns markdown → game_rels + a bit of grouping for the UI.
"""
import os, re, glob as _glob
from atelier.config import ROOT
from atelier.index import ensure_index

SETS_DIR = os.path.join(ROOT, "Sets")


def _to_regex(pattern):
    """Glob → regex fragment. `**` spans '/', `*` and `?` don't. Anchored, case-insensitive, and a
    trailing bare folder gets an implicit `/**` so 'Characters/1060/1060501' means everything under."""
    p = pattern.strip().strip("/").replace("\\", "/")
    if not p:
        return None
    # a pattern with no wildcard and no file extension = a folder prefix → match everything under it
    if "*" not in p and "?" not in p and not re.search(r"\.\w+$", p) and "/" in p:
        p = p + "/**"
    out, i = [], 0
    while i < len(p):
        c = p[i]
        if c == "*":
            if p[i:i + 2] == "**":
                out.append(".*"); i += 2
                if i < len(p) and p[i] == "/":
                    i += 1                        # `**/` also matches zero segments
            else:
                out.append("[^/]*"); i += 1
        elif c == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(c)); i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE)


def _is_lookup_line(ln):
    """A markdown line that is an asset path/glob rather than prose."""
    s = ln.strip().lstrip("-*").strip().strip("`")     # allow `- path` bullets and `code` spans
    if not s or s.startswith("#") or s.startswith("|"):
        return None
    # must look like a content path: has a '/' and only path-safe chars (letters, digits, _ . / * ? -)
    if "/" not in s or not re.match(r"^[\w./*?\-]+$", s):
        return None
    return s


def parse_set(path):
    """{name, file, patterns:[...], note} from one markdown file."""
    name, patterns, note = None, [], []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return None
    for ln in lines:
        if name is None:
            h = re.match(r"^#\s+(.*\S)", ln)
            if h:
                name = h.group(1).strip(); continue
        lk = _is_lookup_line(ln)
        if lk:
            patterns.append(lk)
        elif ln.strip() and not ln.strip().startswith("#") and len(note) < 3:
            note.append(ln.strip().lstrip("-").strip())
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]
    return {"name": name, "file": os.path.basename(path), "patterns": patterns,
            "note": " ".join(note)[:160]}


def list_sets():
    """All parsed sets in SETS_DIR (with a resolved match count each)."""
    os.makedirs(SETS_DIR, exist_ok=True)
    out = []
    for f in sorted(_glob.glob(os.path.join(SETS_DIR, "*.md"))):
        s = parse_set(f)
        if not s:
            continue
        s["count"] = len(resolve_patterns(s["patterns"]))
        out.append(s)
    return out


def resolve_patterns(patterns):
    """game_rels (no .uasset) for every indexed asset matching ANY pattern. De-duplicated, sorted."""
    regs = [r for r in (_to_regex(p) for p in patterns) if r is not None]
    if not regs:
        return []
    hits = set()
    for virt, _cont, _pfx in ensure_index():
        gr = virt[:-7] if virt.lower().endswith(".uasset") else virt     # strip .uasset → game_rel
        if any(r.match(gr) for r in regs):
            hits.add(gr)
    return sorted(hits)


def _bucket(gr):
    """Coarse type for grouping in the UI, from the basename."""
    b = os.path.basename(gr).lower()
    if b.startswith("t_"):
        return "textures"
    if b.startswith(("mi_", "m_")):
        return "materials"
    if b.startswith(("sk_", "sm_")):
        return "meshes"
    if b.startswith(("ns_", "nsm_", "fx_")):
        return "vfx"
    if b.startswith("c_"):
        return "curves"
    if gr.lower().endswith(".umap") or "/maps/" in gr.lower():
        return "worlds"
    return "other"


def resolve_set(name_or_file):
    """{name, patterns, game_rels, groups:{bucket:[game_rel,...]}} for one set (matched by name or
    filename, case-insensitive)."""
    key = str(name_or_file).lower()
    for s in list_sets():
        if key in (s["name"].lower(), s["file"].lower(), os.path.splitext(s["file"])[0].lower()):
            grs = resolve_patterns(s["patterns"])
            groups = {}
            for gr in grs:
                groups.setdefault(_bucket(gr), []).append(gr)
            return {"name": s["name"], "file": s["file"], "patterns": s["patterns"],
                    "game_rels": grs, "groups": groups}
    return None
