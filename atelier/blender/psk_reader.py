"""Read ActorX mesh data independently of a Blender add-on.

Layout reference: https://github.com/gildor2/UEViewer/blob/master/Exporters/Psk.h
The result is plain data; the target character supplies the skeleton.
"""
import math
from pathlib import Path
import struct


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
    bones=[r[0].split(b'\0',1)[0].decode('utf-8',errors='replace') for r in records('REFSKELT','<64sIii4f3ff3f',True)]
    weights=records('RAWWEIGHTS','<fii',True)
    if any(not math.isfinite(w) or w<0 or not 0<=p<len(points) or not 0<=b<len(bones) for w,p,b in weights):
        raise ValueError('Invalid PSK bone weight')
    return {'points':points,'wedges':wedges,'faces':faces,'materials':materials,'bones':bones,'weights':weights}
