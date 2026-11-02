"""Average colours of a skin's original diffuse textures, for the export review's ink-well.

The palette is decoration: a few of the cooked skin's colours swirl through the loader's bubbles.
It reads only images that are already cached (library thumbnails and decoded viewport textures of
the original game assets); it never extracts or decodes a texture, so asking costs a few small PNG
reads and a skin nobody has browsed yet simply returns no colours.
"""
import re

_DIFFUSE = re.compile(r"_(?:D|BC|BaseColor|Diffuse|Albedo)$", re.I)
# Small or special-purpose maps that say little about the costume's colours.
_MINOR = re.compile(r"eye|lash|brow|teeth|tongue|mouth|hair_?line|mask|decal|fx", re.I)
# Larger costume parts first.
_RANK = ("body", "head", "hair", "equip", "weapon", "cloth")


def diffuse_candidates(paths, limit=8):
    """game_rels (no extension) of the diffuse maps among a skin folder's index paths."""
    found = []
    for path in paths:
        if not path.lower().endswith(".uasset"):
            continue
        game_rel = path[:-7]
        name = game_rel.rsplit("/", 1)[-1]
        if _DIFFUSE.search(name) and not _MINOR.search(name):
            found.append(game_rel)

    def rank(game_rel):
        name = game_rel.rsplit("/", 1)[-1].lower()
        return (next((i for i, part in enumerate(_RANK) if part in name), len(_RANK)), name)

    return sorted(dict.fromkeys(found), key=rank)[:limit]


def _linear(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _encoded(value):
    c = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(c * 255)))


def average_colour(path, floor=0.1):
    """Chroma-weighted mean colour of the painted texels as '#rrggbb', or None.

    Transparent texels and near-black UV padding are left out. The mean is taken in linear light,
    and coloured texels count up to five times as much as grey ones, so a costume's actual colours
    outweigh its neutral cloth and shading instead of averaging to mud. A result darker than
    `floor` (relative luminance) is lifted along its own hue, so it never reads as an ink hole."""
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert("RGBA")
        image.thumbnail((64, 64))
        data = image.tobytes()
    total, weight = [0.0, 0.0, 0.0], 0.0
    for i in range(0, len(data), 4):
        r, g, b, a = data[i:i + 4]
        if a < 128 or max(r, g, b) < 12:
            continue
        w = 0.25 + (max(r, g, b) - min(r, g, b)) / 255
        total[0] += _linear(r) * w
        total[1] += _linear(g) * w
        total[2] += _linear(b) * w
        weight += w
    if not weight:
        return None
    mean = [t / weight for t in total]
    luminance = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
    if 0 < luminance < floor:
        mean = [min(1.0, c * floor / luminance) for c in mean]
    return "#" + "".join(f"{_encoded(c):02x}" for c in mean)


def _distinct(colour, chosen, minimum=24):
    rgb = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    for other in chosen:
        o = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
        if sum((a - b) ** 2 for a, b in zip(rgb, o)) ** 0.5 < minimum:
            return False
    return True


def skin_palette(skin_ids, folder_paths, cached_png, limit=4):
    """{'colors': [...], 'sources': [...]} for up to `limit` distinct diffuse averages.

    `folder_paths(skin_id)` lists the skin folder's index paths; `cached_png(game_rel)` returns an
    already-cached PNG of the original texture, or None. Skins are visited in order and each
    contributes its best-ranked maps before the next skin is read."""
    colours, sources = [], []
    for skin_id in skin_ids:
        for game_rel in diffuse_candidates(folder_paths(skin_id)):
            path = cached_png(game_rel)
            if not path:
                continue
            try:
                colour = average_colour(path)
            except OSError:
                continue
            if colour and _distinct(colour, colours):
                colours.append(colour)
                sources.append(game_rel)
                if len(colours) >= limit:
                    return {"colors": colours, "sources": sources}
    return {"colors": colours, "sources": sources}
