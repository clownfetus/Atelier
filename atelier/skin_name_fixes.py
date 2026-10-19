"""Verified skin display-name corrections shared by every Atelier catalogue.

The donor table used by Atelier AND Repak-X currently lists Cyclops 1063100
as SHADOWED NEMESIS. Only IDs that have independent cross-reference evidence
belong here. This affects presentation, never cooked paths or asset identities.
"""

# 2026-10-19, Cyclops: Marvel Rivals Wiki and rivals.gs agree on this name/ID.
# https://marvelrivals.fandom.com/wiki/Shadowed_Gaze
# https://rivals.gs/heroes/cyclops/
VERIFIED_SKIN_NAMES = {'1063100': 'Shadowed Gaze'}


def correct_skin_name(skin_id, upstream_name):
    return VERIFIED_SKIN_NAMES.get(str(skin_id), upstream_name)


def merge_reference(existing, incoming):
    """Merge parsed character tables without losing missing/offline entries.

    Name updates are real updates, not just additions; return (merged, number
    changed). Reject an empty response so a broken download cannot wipe names.
    Caller controls when persistence is atomic and whether the source is trusted.
    """
    if not isinstance(incoming, dict) or not incoming:
        raise ValueError('The refreshed character table was empty or invalid')
    result = {cid: {'name': row['name'], 'skins': dict(row.get('skins', {}))}
              for cid, row in existing.items()}
    changes = 0
    for cid, row in incoming.items():
        if not (isinstance(cid, str) and len(cid) == 4 and cid.isdigit()
                and isinstance(row, dict)):
            continue
        name = row.get('name', '')
        if not isinstance(name, str) or not name.strip():
            continue
        current = result.setdefault(cid, {'name': name.strip(), 'skins': {}})
        if current['name'] != name.strip():
            current['name'] = name.strip()
            changes += 1
        for sid, label in row.get('skins', {}).items():
            if not (isinstance(sid, str) and len(sid) == 7 and sid.isdigit()
                    and sid.startswith(cid) and isinstance(label, str) and label.strip()):
                continue
            corrected = correct_skin_name(sid, label.strip())
            if current['skins'].get(sid) != corrected:
                current['skins'][sid] = corrected
                changes += 1
    return result, changes
