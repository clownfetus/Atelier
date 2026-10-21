"""Verify a real Blender file packs images without creating project texture edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fingerprints(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    os.environ['ATELIER_DATA_DIR'] = str(args.data_dir.resolve())
    report = args.report_dir.resolve(); report.mkdir(parents=True, exist_ok=False)
    from PIL import Image
    from atelier import config, index
    from atelier.handlers import meshstudio, meshedit
    project = report/'project'; project.mkdir()
    rows = meshstudio.skin_meshes('1047001')
    gr = next(row['game_rel'] for row in rows if row['kind'] != 'weapon')
    texture = next(path[:-7] for path, *_ in index.ensure_index() if path.startswith('Characters/1047/1047001/Textures/') and path.endswith('_D.uasset'))
    edited = Path(config.project_base(texture, str(project))+'.png'); edited.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (128,128), (37,89,131)).save(edited)
    before = fingerprints(project); start = time.perf_counter()
    with config.project_context(str(project)):
        result = meshedit.extract_blend(gr, force=True, project_textures=False)
    elapsed = round(time.perf_counter()-start, 2)
    after = fingerprints(project)
    assert all(after.get(path) == value for path,value in before.items()), 'Existing project artwork changed'
    new_files = set(after)-set(before)
    assert all(path.endswith(('.blend','.blend.mat.json','.mesh.json')) for path in new_files), sorted(new_files)
    assert not result['project_textures'] and result['textures'], 'The model did not retain its material images'
    manifest = json.loads(Path(result['blend']+'.mat.json').read_text())
    assert manifest['pack_images']
    assert result['material_manifest_complete'], result['material_issues']
    assert all(not Path(record['path']).is_relative_to(project) for record in manifest['textures'].values() if record.get('path'))
    assert Path(manifest['textures'][texture]['path']).read_bytes() == edited.read_bytes(), 'Cached images ignored existing paint'
    audit = report/'audit.py'
    audit.write_text("""import bpy,json,hashlib
images=[{'name':image.name,'path':image.filepath,'packed':bool(image.packed_file),
         'packed_sha256':hashlib.sha256(bytes(image.packed_file.data)).hexdigest() if image.packed_file else None}
        for image in bpy.data.images if image.source=='FILE']
meshes=[obj.name for obj in bpy.data.objects if obj.type=='MESH']
print('TEXTURE_CHOICE_AUDIT '+json.dumps({'images':images,'meshes':meshes}))
""", encoding='utf-8')
    process = subprocess.run([meshedit.find_blender(), '--background', '--factory-startup', '--disable-autoexec',
                              result['blend'], '--python', str(audit)], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=180, creationflags=config.CNW)
    (report/'audit.log').write_text(process.stdout+process.stderr, encoding='utf-8')
    assert process.returncode == 0
    data = json.loads(next(line[len('TEXTURE_CHOICE_AUDIT '):] for line in process.stdout.splitlines() if line.startswith('TEXTURE_CHOICE_AUDIT ')))
    assert data['meshes'] and data['images'] and all(image['packed'] for image in data['images'])
    assert before[str(edited.relative_to(project))] in {image['packed_sha256'] for image in data['images']}, 'The Blender file did not pack the existing paint'
    assert fingerprints(project) == after, 'Reading the Blender file changed the project'
    receipt = {'ok': True, 'mesh':gr,'seconds':elapsed,'project_texture_count_before':1,'project_texture_count_after':1,
               'existing_paint_unchanged':True, 'existing_paint_packed':True,
               'new_project_files':sorted(new_files), 'packed_images':len(data['images']),
               'material_manifest_complete':result['material_manifest_complete'], 'material_issues':result['material_issues'], 'audit':data}
    (report/'results.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in receipt.items() if key!='audit'},indent=2),flush=True)


if __name__ == '__main__': main()
