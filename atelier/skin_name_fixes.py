"""Verified skin display-name corrections shared by every Atelier catalogue.

The legacy reference table lists Cyclops 1063100 as SHADOWED NEMESIS.
Only IDs that have independent cross-reference evidence belong here.
This affects display names.
"""

# 2026-10-19, Cyclops: Marvel Rivals Wiki and rivals.gs agree on this name/ID.
# https://marvelrivals.fandom.com/wiki/Shadowed_Gaze
# https://rivals.gs/heroes/cyclops/
VERIFIED_SKIN_NAMES = {'1063100': 'Shadowed Gaze'}


def correct_skin_name(skin_id, upstream_name):
    return VERIFIED_SKIN_NAMES.get(str(skin_id), upstream_name)
