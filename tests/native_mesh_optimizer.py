"""Opt-in real Blender and meshoptimizer round trip using generated geometry.

python tests/native_mesh_optimizer.py --blender <blender.exe> --report-dir <new-directory>
No game install is needed and no user projects are opened.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = args.report_dir.resolve()
    if report.exists() or not args.blender.is_file():
        parser.error('Choose an existing Blender executable and a new report directory')
    report.mkdir(parents=True)
    os.environ['ATELIER_DATA_DIR'] = str(report/'data')
    sys.path[:0] = [str(root), str(root/'tests')]
    import numpy as np
    from test_blender_import import FakeMesh
    from atelier.handlers import mesh
    from atelier.mesh_optimizer import simplify_section

    model = FakeMesh(side=24, sections=2)
    model.colors = lambda lod: np.column_stack((model.pos[:, :2]/1000,
        np.full(len(model.pos), .2), np.ones(len(model.pos)))).astype('f4')
    model.lods[0].update(col_off=1, num_tex_coords=2)
    model.uvs = lambda lod: np.stack((model.pos[:, :2]/100, model.pos[:, :2]/1000), axis=1).astype('f4')
    source, blend, exported = (report/name for name in ('source.glb', 'edit.blend', 'exported.glb'))
    mesh.export_glb(model, 0, str(source))
    for script, arguments in [('glb_to_blend.py', [source, blend]), ('blend_to_glb.py', [blend, exported, '1.000000'])]:
        command = [str(args.blender), '--background', '--factory-startup', '--disable-autoexec',
                   '--python', str(root/'atelier/blender'/script), '--', *map(str, arguments)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=120, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        (report/(script+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        if result.returncode or not (blend if script == 'glb_to_blend.py' else exported).is_file():
            raise RuntimeError(script+' failed; see the report log')
    records = []
    for section in mesh.glb_to_sections(model, 0, str(exported)):
        reduced, info = simplify_section(section, .4)
        assert len(reduced['triangles']) < len(section['triangles'])
        lookup = {int(value):i for i, value in enumerate(section['morph_ids'])}
        retained = [lookup[int(value)] for value in reduced['morph_ids']]
        for channel in ('uv', 'color', 'weight', 'global_idx', 'morph_rest', 'morph_lods'):
            np.testing.assert_array_equal(reduced[channel], section[channel][retained])
        blob, metadata, vertices, stride, indices = mesh.rebuild_lod_buffers([reduced])
        records.append(dict(material=section['mat'], before=len(section['triangles']),
            after=len(reduced['triangles']), vertices=vertices, bytes=len(blob), **info))
    (report/'results.json').write_text(json.dumps({'fixture':'Generated geometry; no game assets', 'sections':records}, indent=2))
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()
