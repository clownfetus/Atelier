"""Read ActorX mesh data independently of a Blender add-on.

Layout reference: https://github.com/gildor2/UEViewer/blob/master/Exporters/Psk.h
The result is plain data; the target character supplies the skeleton.
"""
import math
from pathlib import Path
import re
import struct
import statistics


def normalized_weights(weights):
    """Accumulate repeated vertex/bone entries before Blender assigns groups.

    UEFormat's mesh importer accumulates influences. ActorX files can carry the
    same pair more than once too; replacing each entry silently drops weight.
    """
    pairs = {}
    for weight, point, bone in weights:
        if weight:
            pairs.setdefault((point, bone), []).append(weight)
    values = {key: math.fsum(parts) for key, parts in pairs.items()}
    totals = {}
    for (point, bone), weight in values.items():
        totals.setdefault(point, []).append(weight)
    totals = {point: math.fsum(parts) for point, parts in totals.items()}
    return [(weight/totals[point], point, bone) for (point, bone), weight in values.items()]


def read_psk(path):
    raw=Path(path).read_bytes()
    if len(raw)>512*1024*1024:raise ValueError('PSK exceeds 512 MB')
    chunks={};offset=0
    while offset<len(raw):
        if len(raw)-offset<32:raise ValueError('Truncated PSK chunk header')
        label,version,size,count=struct.unpack_from('<20s3i',raw,offset);offset+=32
        label=label.split(b'\0',1)[0].decode('ascii')
        if size<0 or count<0 or count>20_000_000 or size*count>len(raw)-offset:
            raise ValueError('Invalid PSK chunk length')
        if label in chunks:raise ValueError('Duplicate PSK chunk: '+label)
        chunks[label]=(size,count,memoryview(raw)[offset:offset+size*count]);offset+=size*count
    if 'ACTRHEAD' not in chunks:raise ValueError('Not an ActorX PSK mesh')
    def records(label,fmt,optional=False):
        if optional and label not in chunks:return []
        if label not in chunks:raise ValueError('Missing PSK chunk: '+label)
        size,count,body=chunks[label];expected=struct.calcsize(fmt)
        if size!=expected:raise ValueError('Unsupported PSK record size: '+label)
        return [struct.unpack_from(fmt,body,i*size) for i in range(count)]
    points=records('PNTS0000','<3f')
    if not points or len(points)>3_000_000 or any(not all(map(math.isfinite,p)) for p in points):
        raise ValueError('Invalid PSK vertices')
    wedges=records('VTXW0000','<IffBBH')
    wedges=[((p if p<len(points) else p&65535),u,v) for p,u,v,*_ in wedges]
    if any(p>=len(points) or not math.isfinite(u) or not math.isfinite(v) for p,u,v in wedges):
        raise ValueError('Invalid PSK wedge')
    face_chunk='FACE3200' if 'FACE3200' in chunks else 'FACE0000'
    faces=records(face_chunk,'<IIIBBI' if face_chunk=='FACE3200' else '<HHHBBI')
    materials=[r[0].split(b'\0',1)[0].decode('utf-8',errors='replace') for r in records('MATT0000','<64s6i')]
    if not faces or any(max(f[:3])>=len(wedges) or f[3]>=len(materials) for f in faces):
        raise ValueError('Invalid PSK face or material index')
    skeleton=records('REFSKELT','<64sIii4f3ff3f',True)
    bones=[r[0].split(b'\0',1)[0].decode('utf-8',errors='replace') for r in skeleton]
    parents=[r[3] for r in skeleton];positions=[r[8:11] for r in skeleton]
    if any(not -1<=parent<len(bones) for parent in parents) or any(not all(map(math.isfinite,p)) for p in positions):
        raise ValueError('Invalid PSK reference skeleton')
    weights=records('RAWWEIGHTS','<fii',True)
    if any(not math.isfinite(w) or w<0 or not 0<=p<len(points) or not 0<=b<len(bones) for w,p,b in weights):
        raise ValueError('Invalid PSK bone weight')
    weights=normalized_weights(weights)
    normals=records('VTXNORMS','<3f',True);colors=records('VERTEXCOLOR','<4B',True)
    if normals and (len(normals)!=len(points) or any(not all(map(math.isfinite,n)) for n in normals)):
        raise ValueError('Invalid PSK custom normals')
    if colors and len(colors)!=len(wedges):raise ValueError('Invalid PSK vertex colours')
    extra_uvs=[]
    for label in sorted(name for name in chunks if re.fullmatch(r'EXTRAUVS[0-7]',name)):
        values=records(label,'<2f')
        if len(values)!=len(wedges) or any(not all(map(math.isfinite,uv)) for uv in values):raise ValueError('Invalid PSK secondary UVs')
        extra_uvs.append(values)
    return {'points':points,'wedges':wedges,'faces':faces,'materials':materials,'bones':bones,'weights':weights,
            'bone_parents':parents,'bone_positions':positions,'normals':normals,'colors':colors,'extra_uvs':extra_uvs}


def source_scale(data, target_bones, units='auto'):
    """Select metres or centimetres from matching reference-bone lengths.

    ActorX does not declare a unit. Blender-exported PSKs can already be metres;
    blindly dividing them by 100 produces a two-centimetre character. Bone-length
    ratios work for partial meshes too, without resizing the intended proportions.
    target_bones maps names to (parent name, parent-to-head distance in metres).
    """
    if units not in ('auto','metres','centimetres'):raise ValueError('Choose automatic, metres or centimetres for PSK units')
    ratios=[]
    for index,(name,parent,position) in enumerate(zip(data['bones'],data['bone_parents'],data['bone_positions'])):
        if parent<0 or parent==index or name not in target_bones:continue
        expected,length=target_bones[name];raw=math.sqrt(sum(v*v for v in position))
        if data['bones'][parent]==expected and length>1e-5 and raw>1e-5:ratios.append(length/raw)
    selected=units
    if selected=='auto':
        selected='metres' if len(ratios)>=4 and .5<=statistics.median(ratios)<=2 else 'centimetres'
    return {'scale':1.0 if selected=='metres' else .01,'units':selected,'matching_bones':len(ratios),
            'detected':units=='auto'}


def unreal_points(data,scale):
    """Undo ActorX's Y mirror before editing the game's component-space mesh.

    UEViewer ExportPsk.cpp mirrors Y and swaps triangle indices on export. The
    Blender fronts retain PSK face order when this reflection is applied; the
    winding conversion and reflection cancel. Matching bone names alone cannot
    correct mirrored positions.
    """
    return [(x*scale,-y*scale,z*scale) for x,y,z in data['points']]
