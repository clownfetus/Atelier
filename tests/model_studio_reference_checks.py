"""Read a supplied original PSK against the private cooked-mesh cache; no native calls."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from atelier.blender.psk_reader import read_psk,source_scale,unreal_points
from atelier.handlers.mesh import Mesh
from atelier.handlers.texture import find_extracted


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--target',required=True);parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    model=Mesh(find_extracted(args.target));data=read_psk(args.source)
    assert model.lods[0]['layout'].get('source_index',0)==0,'Complete every original LOD through the private app before this reference comparison'
    target={bone['name']:(model.bones[bone['parent']]['name'],float(np.linalg.norm(bone['translation']))/100) for bone in model.bones if bone['parent']>=0}
    scale=source_scale(data,target);points=np.array(unreal_points(data,scale['scale']))*100
    lod=model.lods[0];positions=model.positions(lod);distances,_=cKDTree(positions).query(points)
    count=lod['n_indices'];indices=np.frombuffer(model._blob(lod),'<u4' if lod['idx_stride']==4 else '<u2',count,lod['idx_off']).reshape(-1,3)
    def key(points):return tuple(sorted(tuple(point) for point in np.rint(np.asarray(points,dtype=np.float64)*10000).astype('int64')))
    fronts={}
    for triangle in positions[indices]:
        normal=-np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal)
        if length>1e-8:fronts[key(triangle)]=normal/length
    alignment=[]
    for face in data['faces']:
        triangle=points[[data['wedges'][index][0] for index in face[:3]]]
        original=fronts.get(key(triangle));normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal)
        if original is not None and length>1e-8:alignment.append(float(np.dot(original,normal/length)))
    report={'source':str(args.source),'target':args.target,'source_scale':scale,'source_vertices':len(points),
        'max_vertex_distance_cm':float(distances.max()),'mean_vertex_distance_cm':float(distances.mean()),
        'matched_faces':len(alignment),'front_face_alignment':float(np.mean(np.array(alignment)>.99)) if alignment else None}
    (args.report_dir/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    assert scale['units']=='centimetres' and scale['matching_bones']>=4,report
    assert distances.max()<.001 and len(alignment)>.95*len(data['faces']),report
    assert report['front_face_alignment']>.99,report
    print('PASS original gun PSK: centimetres, bone names, component-space coordinates and front-face winding match the game',flush=True)


if __name__=='__main__':main()
