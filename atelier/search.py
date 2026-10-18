"""Grouped, accent-insensitive search over one immutable index generation."""
import os
import threading
import unicodedata

from atelier import index

_lock = threading.Lock()
_generation = None
_table = None
_catalogue_for = None


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value))
                   if not unicodedata.combining(c)).lower().replace('\\', '/')


def _table_for(entries, catalogue_data):
    global _generation, _table, _catalogue_for
    if _generation is entries and _catalogue_for is catalogue_data and _table is not None:
        return _table
    with _lock:
        if _generation is entries and _catalogue_for is catalogue_data and _table is not None:
            return _table
        from atelier.web.browse import _classify_file, LISTED_FILE_TYPES
        assets, haystacks, folders = [], [], {}
        names = {key:normalize(entry.get('name') or '') for key,entry in catalogue_data.get('entries',{}).items()}
        def text(path):
            parts = path.split('/')
            context = [names.get(part, '') for part in parts[1:3]] if parts[0].lower()=='characters' else []
            return normalize(path)+' '+' '.join(context)
        for path, *_ in entries:
            kind = _classify_file(os.path.basename(path), path)
            if kind not in LISTED_FILE_TYPES:
                continue
            gr = path[:-7] if path.lower().endswith('.uasset') else path
            parent = gr.rpartition('/')[0]
            cursor = parent
            while cursor and cursor not in folders:
                folders[cursor] = cursor; cursor = cursor.rpartition('/')[0]
            # Hundreds of assets share a folder; retain one parent string rather than one per row.
            assets.append((gr, kind, folders.get(parent, ''))); haystacks.append(text(gr))
        folder_rows = sorted(folders)
        table = (assets, haystacks, folder_rows, [text(path) for path in folder_rows])
        _generation, _table, _catalogue_for = entries, table, catalogue_data
        return table


def _matches(haystacks, terms):
    if not terms:
        return []
    matches = [i for i, text in enumerate(haystacks) if terms[0] in text]
    for term in terms[1:]:
        matches = [i for i in matches if term in haystacks[i]]
    return matches


def search(query, limit=50):
    from atelier.catalogue import catalogue
    try:
        limit = min(50, max(1, int(limit)))
    except (ValueError, TypeError):
        limit = 50
    terms = list(dict.fromkeys(normalize(query[:200]).split()))
    groups = {'heroes':[], 'skins':[], 'folders':[], 'assets':[]}
    totals = dict.fromkeys(groups, 0)
    if not terms:
        return {**groups, 'totals':totals, 'building':False}
    # Never wait behind the index builder or hold its lock to construct the search table.
    if index._INDEX is None and index.index_progress()['stage'] == 'indexing':
        return {**groups, 'totals':totals, 'building':True}
    with catalogue.lock:
        catalogue_data = catalogue.data
        entries = dict(catalogue_data.get('entries', {}))
    assets, haystacks, folders, folder_text = _table_for(index.ensure_index(), catalogue_data)
    for key, entry in entries.items():
        if entry.get('kind') not in ('hero','skin'):
            continue
        kind = 'heroes' if entry['kind']=='hero' else 'skins'
        path = 'Characters/'+(key if kind=='heroes' else key[:4]+'/'+key)
        hero_name = (entries.get(entry.get('hero')) or {}).get('name') or ''
        text = normalize(' '.join((str(entry.get('name') or ''), hero_name, key, path)))
        if all(term in text for term in terms):
            totals[kind] += 1
            if len(groups[kind]) < min(limit,8):
                groups[kind].append({'name':entry.get('name') or key, 'id':key, 'path':path})
    found = _matches(folder_text, terms)
    totals['folders'] = len(found)
    groups['folders'] = [{'name':os.path.basename(folders[i]),'path':folders[i]} for i in found[:min(limit,8)]]
    found = _matches(haystacks, terms)
    totals['assets'] = len(found)
    groups['assets'] = [{'name':os.path.basename(assets[i][0]), 'game_rel':assets[i][0],
                         'type':assets[i][1], 'parent':assets[i][2]} for i in found[:limit]]
    return {**groups,'totals':totals,'building':False}
