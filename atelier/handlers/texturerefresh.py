"""Upgrade imports to newly available mips while retaining paint and a recoverable backup."""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import uuid

import numpy as np
from PIL import Image
from atelier import config, jobs
from atelier.handlers import texture
from atelier.handlers.meshreplace import digest
from atelier.storage import publish_project_files


def source_mip(base, size):
    """Decode the exact shipped smaller mip, rather than guessing it by resizing mip 0."""
    width, height, fmt = texture._tex_info(base)
    block = texture._BPB.get(fmt)
    if not block or width != height or size[0] != size[1]: return None
    for suffix in ('.uptnl', '.ubulk'):
        path = Path(base+suffix)
        if not path.is_file(): continue
        data = path.read_bytes()
        dimension = next((1 << power for power in range(14,1,-1)
                          if (1 << power) <= width and
                          (max(1,(1 << power)//4)**2*block == len(data) or
                           suffix == '.ubulk' and .6*len(data) < max(1,(1 << power)//4)**2*block <= len(data))), None)
        offset = 0
        while dimension and dimension >= 4:
            length = max(1,dimension//4)**2*block
            if dimension == size[0] and offset+length <= len(data):
                with Image.open(BytesIO(texture._dds_header(dimension,dimension,fmt,length)+data[offset:offset+length])) as image:
                    return image.convert('RGBA')
            offset += length; dimension //= 2
    return None


def merge_paint(edited, baseline, full):
    """Use full-size game pixels outside painted areas; preserve painted RGBA values inside."""
    edited = edited.convert('RGBA'); baseline = baseline.convert('RGBA'); full = full.convert('RGBA')
    if edited.size != baseline.size: raise ValueError('The original mip does not match the imported image')
    mask = np.any(np.asarray(edited) != np.asarray(baseline), axis=2).astype('uint8')*255
    changed = bool(mask.any())
    if changed:
        # Nearest preserves categorical masks, alpha values and normal-map channels too.
        mask = Image.fromarray(mask).resize(full.size, Image.Resampling.NEAREST)
        full.paste(edited.resize(full.size,Image.Resampling.NEAREST), (0,0), mask)
    return full, changed


def repair(items=None):
    root = config.get_import_root()
    candidates = texture.stale_mip_imports(root) if items is None else items
    repaired=[]; skipped=[]
    for index,item in enumerate(candidates):
        jobs.checkpoint(); gr=item['game_rel']; config.validate_game_rel(gr)
        jobs.progress('Refreshing '+os.path.basename(gr)+'…',current_count=index,total=len(candidates))
        target=next((p for p in (config.project_base(gr)+'.png',config.project_base_legacy(gr)+'.png') if os.path.isfile(p)),None)
        if not target: continue
        before=digest(target)
        try:
            with Image.open(target) as image: edited=image.convert('RGBA')
            # Capture the previous original before ensure_work_base refreshes its cache.
            from atelier import asset_cache
            cached=asset_cache.cache_base(gr)
            baseline=source_mip(cached,edited.size) if cached and Path(cached+'.uasset').is_file() else None
            with tempfile.TemporaryDirectory(prefix='atelier-texture-refresh-') as temporary:
                base=texture.ensure_work_base(gr)
                if not base: raise RuntimeError('The full-resolution source could not be extracted')
                decoded=texture.decode_to_png(str(Path(temporary)/'full'),base)
                if not decoded: raise RuntimeError('The full-resolution source could not be decoded')
                with Image.open(decoded) as image: full=image.convert('RGBA')
                if max(full.size) <= max(edited.size): raise RuntimeError('The extractor has not supplied a larger mip yet')
                if baseline is None: baseline=source_mip(base,edited.size)
                if baseline is None: raise RuntimeError('The original smaller mip could not be recovered safely')
                merged,painted=merge_paint(edited,baseline,full)
                output=Path(temporary)/'repaired.png';merged.save(output)
                backup='.atelier/texture-backups/'+uuid.uuid4().hex+'/'+os.path.relpath(target,root).replace('\\','/')
                jobs.checkpoint()
                # The edit can change externally while extraction runs; compare its hash before publication.
                publish_project_files(root,[{'path':backup,'before':None,'source':target},
                    {'path':os.path.relpath(target,root),'before':before,'source':str(output)}])
                repaired.append({'game_rel':gr,'paint_preserved':painted,'size':list(full.size),'backup':backup})
                # Existing viewport originals may still contain the smaller decoded mip.
                original=Path(config.project_base(gr,config.CACHE_3DVIEW)+'.png')
                if original.is_file(): original.unlink()
        except jobs.Cancelled: raise
        except Exception as error: skipped.append({'game_rel':gr,'reason':str(error)})
    return {'ok':True,'repaired':repaired,'skipped':skipped}
