"""Resolve cooked import identity through its package, never through a basename.

FModel's reference navigation keeps package and object identity separate. This
small resolver applies that rule to UAssetTool's import table, retaining the live
package record for callers that need to edit a reference.
"""
from atelier.config import validate_game_rel


def imported_package(document, index):
    imports = (document or {}).get('Imports', [])
    if not isinstance(imports, list):
        return None
    seen = set()
    for _ in range(64):
        if type(index) is not int or not -len(imports) <= index < 0 or index in seen:
            return None
        seen.add(index)
        record = imports[-index-1]
        if not isinstance(record, dict):
            return None
        name = record.get('ObjectName')
        if isinstance(name, str) and name.startswith('/Game/Marvel/'):
            relative = name[len('/Game/Marvel/'):]
            try:
                validate_game_rel(relative)
            except ValueError:
                return None
            return record, relative
        index = record.get('OuterIndex')
    return None
