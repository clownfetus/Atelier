"""Read real exported IoStore chunks and independently verify hidden LOD indices.

Pure readback: no native program, unpacking operation or game installation. Input
is a real-check results.json and the app's independent original mesh cache.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    assert os.environ.get('ATELIER_DATA_DIR'),'Set independent ATELIER_DATA_DIR'
    from atelier.handlers.mesh import Mesh
    from atelier.handlers.texture import find_extracted
    import io_lib
    reports=[]
    for result in json.loads(args.results.read_text(encoding='utf-8'))['results']:
        hidden=result.get('hidden_target');exported=result.get('export')
        if not hidden or not exported:continue
        gr=hidden['mesh_game_rel'];base=find_extracted(gr);assert base,gr
        original=Mesh(base)
        assert len(original.lods)==len(original._layout) and not any(l['blob']=='missing' for l in original._layout)
        assert original.materials[hidden['slot_index']]['slot_name']==hidden['slot_name']
        toc_path=next(p for p in exported['artifacts'] if p.endswith('.utoc'))
        toc=io_lib.parse_toc(toc_path);directory=io_lib.parse_dir_index(toc)
        entry=next(index for path,index in directory if path.lower().endswith('/'+gr.lower()+'.uasset'))
        main_chunk=io_lib.read_chunk(toc,toc_path[:-5]+'.ucas',entry)
        identity=toc.chunk_ids[entry][:8]+b'\x00\x00\x00\x02'
        expected={'ubulk':bytearray(original.ubulk),'uexp':bytearray(original.uexp),'uasset':bytearray(original.uasset)}
        changes=[]
        for index,lod in enumerate(original.lods):
            blob=original._layout[index]['blob'];data=expected[blob];count=0
            for section in lod['sections']:
                if section['mat']!=hidden['slot_index']:continue
                start=lod['idx_off']+section['base_index']*lod['idx_stride']
                # Do not call the production hide helper. Construct the expected
                # packed bytes independently from the original section bounds.
                fmt='<I' if lod['idx_stride']==4 else '<H'
                for triangle in range(section['num_tris']):
                    struct.pack_into('<3'+fmt[1],data,start+triangle*3*lod['idx_stride'],*([section['base_vertex']]*3))
                count+=1
            changes.append({'lod':index,'buffer':blob,'sections':count})
        if original.ubulk:
            bulk_index=toc.chunk_ids.index(identity)
            actual=io_lib.read_chunk(toc,toc_path[:-5]+'.ucas',bulk_index)
            assert actual==bytes(expected['ubulk']),'Exported streamed buffer differs from the exact expected edit'
        for index,lod in enumerate(original.lods):
            blob=original._layout[index]['blob']
            if blob=='ubulk':continue
            start=max(0,lod['idx_off']-11);end=lod['idx_off']+lod['n_indices']*lod['idx_stride']+32
            needle=bytes(expected[blob][start:end])
            assert needle and needle in main_chunk,('Inline index buffer missing',index,blob)
        reports.append({'skin':result['skin'],'mesh':gr,'slot':hidden['slot_name'],'lods':changes,
                        'streamed_bytes_verified':len(original.ubulk),'packed_main_bytes':len(main_chunk),
                        'bulk_sha256':hashlib.sha256(expected['ubulk']).hexdigest(),
                        'all_other_streamed_bytes_unchanged':True,'in_game_verified':False})
        print('Verified packed indices and unchanged streamed geometry: '+gr+' · '+str(len(changes))+' LODs',flush=True)
    assert reports,'No exported visibility cases were supplied'
    args.report_dir.mkdir(parents=True,exist_ok=True)
    (args.report_dir/'results.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')


if __name__=='__main__':main()
