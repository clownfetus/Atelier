"""Read, remap and write UE5 GPU morph buffers without changing target identities.

Format references (Apache-2.0 CUE4Parse): FMorphTargetVertexInfoBuffers.cs and
Animation/FMorphTargetLODModel.cs in https://github.com/FabianFG/CUE4Parse.
The codec and nearest-surface projection here are independent implementations.
"""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile

import numpy as np
from atelier import config, jobs
from atelier.storage import atomic_json


def decode(raw, vertex_count=None):
    view=memoryview(raw);offset=0
    def take(fmt):
        nonlocal offset
        size=struct.calcsize(fmt)
        if offset+size>len(view):raise ValueError('Truncated morph buffer')
        values=struct.unpack_from(fmt,view,offset);offset+=size
        return values
    def array(dtype,width=1):
        nonlocal offset
        count=take('<i')[0];length=count*width*np.dtype(dtype).itemsize
        if count<0 or offset+length>len(view):raise ValueError('Invalid morph array length')
        result=np.frombuffer(view,dtype,count*width,offset).reshape(count,width).copy()
        offset+=length;return result
    words=array('<u4').reshape(-1);packed=words.tobytes()
    minimum=array('<f4',4);maximum=array('<f4',4)
    starts=array('<u4').reshape(-1);counts=array('<u4').reshape(-1)
    batches,position_precision,tangent_precision=take('<iff')
    if offset!=len(view) or batches<0 or batches*40>len(packed):raise ValueError('Invalid morph batch table')
    if batches and not (position_precision>0 and tangent_precision>0 and math.isfinite(position_precision+tangent_precision)):
        raise ValueError('Invalid morph quantization precision')
    if not (len(minimum)==len(maximum)==len(starts)==len(counts)):raise ValueError('Morph target tables disagree')
    targets=[]
    for start,count in zip(starts,counts):
        if int(start)+int(count)>batches:raise ValueError('Morph batch range is invalid')
        indices=[];values=[]
        for batch_index in range(int(start),int(start)+int(count)):
            data_offset,bits,index_min,*rest=struct.unpack_from('<III3iI3i',packed,batch_index*40)
            position_min=np.array(rest[:3],dtype='i8');tangent_bits=rest[3];tangent_min=np.array(rest[4:],dtype='i8')
            widths=[bits&31,(bits>>5)&31,(bits>>10)&31,(bits>>15)&31]
            tangents=bool(bits&(1<<20));elements=bits>>21
            widths+=[(tangent_bits>>shift)&31 for shift in (0,5,10)] if tangents else []
            total_bits=sum(widths)*elements;length=(total_bits+31)//32*4
            if data_offset<batches*40 or data_offset+length>len(packed):raise ValueError('Invalid packed morph batch')
            payload=int.from_bytes(packed[data_offset:data_offset+length],'little');cursor=0
            for i in range(elements):
                decoded=[]
                for width in widths:
                    decoded.append((payload>>cursor)&((1<<width)-1));cursor+=width
                index=index_min+i+decoded[0]
                if vertex_count is not None and index>=vertex_count:raise ValueError('Morph vertex lies outside its LOD')
                p=(position_min+decoded[1:4])*position_precision
                t=(tangent_min+decoded[4:7])*tangent_precision if tangents else np.zeros(3)
                indices.append(index);values.append(np.concatenate((p,t)))
        ids=np.array(indices,dtype='<u4');deltas=np.array(values,dtype='<f4').reshape(-1,6)
        if len(ids)>1 and np.any(ids[1:]<=ids[:-1]):raise ValueError('Morph vertex indices are not ordered and unique')
        targets.append({'indices':ids,'deltas':deltas})
    return {'targets':targets,'minimum':minimum,'maximum':maximum,'position_precision':position_precision,
            'tangent_precision':tangent_precision,'raw':bytes(raw),'batches':batches}


def encode(targets,position_precision,tangent_precision):
    precisions=np.array([position_precision]*3+[tangent_precision]*3,dtype='f8')
    if not np.isfinite(precisions).all() or np.any(precisions<=0):raise ValueError('Invalid morph precision')
    headers=[];payloads=[];starts=[];counts=[];minimum=[];maximum=[]
    for target in targets:
        jobs.checkpoint();ids=np.asarray(target['indices'],dtype='i8');values=np.asarray(target['deltas'],dtype='f8')
        if values.shape!=(len(ids),6) or not np.isfinite(values).all():raise ValueError('Invalid morph deltas')
        if len(ids) and (ids.min()<0 or ids.max()>0xffffffff or np.any(ids[1:]<=ids[:-1])):raise ValueError('Invalid morph indices')
        quantized=np.rint(values/precisions).astype('i8')
        if np.any(abs(quantized)>0x3fffffff):raise ValueError('Morph deltas exceed supported quantization range')
        keep=np.any(quantized!=0,axis=1);ids=ids[keep];quantized=quantized[keep]
        starts.append(len(headers));counts.append((len(ids)+63)//64)
        decoded=quantized*precisions
        minimum.append([*(np.minimum(decoded[:,:3].min(0),0) if len(ids) else np.zeros(3)),min(0,float(decoded[:,3:].min())) if len(ids) else 0])
        maximum.append([*(np.maximum(decoded[:,:3].max(0),0) if len(ids) else np.zeros(3)),max(0,float(decoded[:,3:].max())) if len(ids) else 0])
        for offset in range(0,len(ids),64):
            indices=ids[offset:offset+64];q=quantized[offset:offset+64]
            lo=q.min(0);hi=q.max(0);widths=[int(int(x).bit_length()) for x in hi-lo]
            index_min=int(indices[0]);residuals=indices-index_min-np.arange(len(indices))
            index_bits=int(int(residuals.max()).bit_length());has_tangent=bool(np.any(q[:,3:]))
            bits=index_bits|(widths[0]<<5)|(widths[1]<<10)|(widths[2]<<15)|(int(has_tangent)<<20)|(len(indices)<<21)
            tangent_bits=widths[3]|(widths[4]<<5)|(widths[5]<<10)
            fields=np.column_stack((residuals,q-lo));field_widths=[index_bits]+widths
            packed=cursor=0
            for row in fields:
                for value,width in zip(row[:7 if has_tangent else 4],field_widths):
                    packed|=int(value)<<cursor;cursor+=width
            payload=packed.to_bytes((cursor+31)//32*4,'little')
            headers.append((bits,index_min,*lo[:3],tangent_bits,*lo[3:]));payloads.append(payload)
    data=bytearray();pointer=len(headers)*40
    for header,payload in zip(headers,payloads):
        data.extend(struct.pack('<III3iI3i',pointer,*header));pointer+=len(payload)
    for payload in payloads:data.extend(payload)
    def array(values,dtype,width=1):
        value=np.asarray(values,dtype=dtype).reshape(-1,width)
        return struct.pack('<i',len(value))+value.tobytes()
    return (struct.pack('<i',len(data)//4)+data+array(minimum,'<f4',4)+array(maximum,'<f4',4)+
        array(starts,'<u4')+array(counts,'<u4')+struct.pack('<iff',len(headers),position_precision,tangent_precision))


def closest_triangles(points,triangles):
    """Closest points and barycentric weights, including triangle edges and degeneracies."""
    a,b,c=np.moveaxis(triangles,-2,0);ab=b-a;ac=c-a;ap=points-a
    aa=np.sum(ab*ab,-1);bb=np.sum(ab*ac,-1);cc=np.sum(ac*ac,-1)
    ad=np.sum(ap*ab,-1);cd=np.sum(ap*ac,-1);den=aa*cc-bb*bb
    den=np.where(abs(den)>1e-20,den,np.inf)
    v=(cc*ad-bb*cd)/den;w=(aa*cd-bb*ad)/den;u=1-v-w
    bary=np.stack((u,v,w),-1);projected=np.sum(triangles*bary[...,None],-2)
    distances=np.sum((points-projected)**2,-1)
    distances=np.where((bary>=0).all(-1)&np.isfinite(den),distances,np.inf)
    for start,end in ((0,1),(1,2),(2,0)):
        edge=triangles[...,end,:]-triangles[...,start,:]
        t=np.clip(np.sum((points-triangles[...,start,:])*edge,-1)/np.maximum(np.sum(edge*edge,-1),1e-30),0,1)
        point=triangles[...,start,:]+t[...,None]*edge;distance=np.sum((points-point)**2,-1)
        use=distance<distances;weights=np.zeros_like(bary);weights[...,start]=1-t;weights[...,end]=t
        bary=np.where(use[...,None],weights,bary);distances=np.minimum(distances,distance)
    return bary,distances


def correspondence(mesh,lod,sections):
    from scipy.spatial import cKDTree
    original=mesh.positions(lod).astype('f8');vertices=[];weights=[];identity=True
    uv=mesh.uvs(lod)[:,0] if hasattr(mesh,'uvs') else None
    normals=mesh.normals_tangents(lod)[0] if hasattr(mesh,'normals_tangents') else None
    for source,replacement in zip(lod['sections'],sections):
        jobs.checkpoint();lo=source['base_vertex'];hi=lo+source['num_verts']
        points=np.asarray(replacement.get('morph_rest',replacement['positions']),dtype='f8')
        count=source['num_tris']*3
        tris=np.frombuffer(bytes(mesh._blob(lod)),'<u4' if lod['idx_stride']==4 else '<u2',count,
            lod['idx_off']+source['base_index']*lod['idx_stride']).reshape(-1,3).astype('i8')
        geometry=original[tris];centers=geometry.mean(1);tree=cKDTree(centers)
        direct_tree=cKDTree(original[lo:hi]);k_direct=min(16,hi-lo)
        direct_distance,candidates=direct_tree.query(points,k=k_direct)
        direct_distance=direct_distance.reshape(len(points),k_direct);candidates=candidates.reshape(len(points),k_direct)
        score=direct_distance*1e-8
        if uv is not None and 'uv' in replacement:
            score+=np.sum((uv[lo:hi][candidates]-np.asarray(replacement['uv'])[:,0,None,:])**2,axis=2)
        if normals is not None and 'normal' in replacement:
            score+=np.sum((normals[lo:hi][candidates]-np.asarray(replacement['normal'])[:,None,:])**2,axis=2)*.01
        score=np.where(direct_distance<1e-4,score,np.inf)
        chosen=np.argmin(score,axis=1);rows=np.arange(len(points))
        direct=candidates[rows,chosen];direct_distance=direct_distance[rows,chosen]
        exact=direct_distance<1e-4
        if 'morph_ids' in replacement and 'morph_lods' in replacement:
            ids=np.asarray(replacement['morph_ids']);source_lods=np.asarray(replacement['morph_lods'])
            valid=np.isfinite(ids)&np.isfinite(source_lods)&(abs(ids-np.rint(ids))<1e-6)&(ids>=lo)&(ids<hi)
            valid&=source_lods==lod.get('layout',{}).get('source_index',-1)
            indices=np.rint(np.where(valid,ids,lo)).astype('i8')
            valid&=np.linalg.norm(original[indices]-points,axis=1)<1e-3
            direct[valid]=indices[valid]-lo;exact[valid]=True
        mapped=np.zeros((len(points),3),dtype='i8');factors=np.zeros((len(points),3),dtype='f4')
        mapped[exact,:]=direct[exact,None]+lo;factors[exact,0]=1
        for begin in range(0,len(points),2048):
            take=np.arange(begin,min(begin+2048,len(points)));take=take[~exact[take]]
            if not len(take):continue
            k=min(16,len(tris));candidate=tree.query(points[take],k=k)[1].reshape(len(take),k)
            bary,distance=closest_triangles(points[take,None,:],geometry[candidate])
            best=np.argmin(distance,axis=1);rows=np.arange(len(take))
            mapped[take]=tris[candidate[rows,best]];factors[take]=bary[rows,best]
        identity=identity and len(points)==source['num_verts'] and np.all(exact) and np.array_equal(direct,np.arange(len(points)))
        vertices.append(mapped);weights.append(factors)
    return np.concatenate(vertices),np.concatenate(weights),identity


def remap(mesh,lod,sections,buffer):
    indices,factors,identity=correspondence(mesh,lod,sections)
    if identity:return buffer['raw'],buffer['targets'],True
    targets=[]
    for target in buffer['targets']:
        jobs.checkpoint();dense=np.zeros((lod['num_verts'],6),dtype='f4');dense[target['indices']]=target['deltas']
        values=np.einsum('nkj,nk->nj',dense[indices],factors)
        threshold=np.array([buffer['position_precision']]*3+[buffer['tangent_precision']]*3)*.5
        keep=np.any(abs(values)>=threshold,axis=1)
        targets.append({'indices':np.flatnonzero(keep).astype('<u4'),'deltas':values[keep]})
    packed=encode(targets,buffer['position_precision'],buffer['tangent_precision'])
    return packed,decode(packed,len(indices))['targets'],False


def metadata(base):
    """Target names/order and fixed-size cooked CPU metadata fields from UAssetTool's parser."""
    from atelier.tools import uat
    stamp=[(str(Path(base+suffix).resolve()),os.stat(base+suffix).st_mtime_ns,os.path.getsize(base+suffix)) for suffix in ('.uasset','.uexp')]
    key=hashlib.sha256(json.dumps(stamp).encode()).hexdigest()
    cache=Path(config._CACHE)/'morph-metadata'/(key+'.json')
    if cache.is_file():return json.loads(cache.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='atelier-morph-metadata-') as folder:
        result=uat(['to_json',os.path.abspath(base+'.uasset'),config.USMAP,folder])
        files=list(Path(folder).glob('*.json'))
        if result.returncode or len(files)!=1:raise ValueError('Could not read original morph identities')
        data=json.loads(files[0].read_text(encoding='utf-8-sig'))
    skeletal=next(e for e in data['Exports'] if e.get('ObjectName')==Path(base).name)
    properties=skeletal.get('Data',[])
    refs=next((p['Value'] for p in properties if isinstance(p,dict) and p.get('Name')=='MorphTargets'),None) if isinstance(properties,list) else None
    if refs is None:
        # Some Rivals meshes reach UAssetTool as RawExport. Resolve the property
        # array structurally using its exact set of MorphTarget export links.
        exports={i+1:e for i,e in enumerate(data['Exports']) if e.get('ClassIndex',0)<0 and
            data['Imports'][-e['ClassIndex']-1].get('ObjectName')=='MorphTarget'}
        if not exports:raise ValueError('No original morph target identities were found')
        start=int(skeletal['SerialOffset'])-os.path.getsize(base+'.uasset')
        payload=Path(base+'.uexp').read_bytes()[start:start+min(int(skeletal['SerialSize']),1024*1024)]
        needle=struct.pack('<i',len(exports));cursor=0;candidates=[]
        while (cursor:=payload.find(needle,cursor))>=0:
            begin=cursor+4;cursor+=1
            if begin+len(exports)*4>len(payload):continue
            values=struct.unpack_from('<'+str(len(exports))+'i',payload,begin)
            if len(set(values))==len(exports) and set(values)==set(exports):candidates.append(values)
        if len(candidates)!=1:raise ValueError('Could not resolve the original morph target order unambiguously')
        refs=[{'Value':value} for value in candidates[0]]
    entries=[]
    for ref in refs:
        export=data['Exports'][int(ref['Value'])-1];raw=base64.b64decode(export.get('Extras') or '')
        if len(raw)<6:raise ValueError('Morph target metadata is missing')
        count=struct.unpack_from('<i',raw,2)[0];cursor=6;lods=[]
        if not 0<=count<=16:raise ValueError('Unsupported morph CPU metadata layout')
        for i in range(count):
            stripped,n_vertices,n_base,n_sections=struct.unpack_from('<4i',raw,cursor)
            if stripped!=1 or not 0<=n_sections<=256:raise ValueError('Unsupported unstripped morph CPU metadata')
            lods.append({'offset':cursor,'vertices':n_vertices,'base_vertices':n_base,'sections':list(struct.unpack_from('<'+str(n_sections)+'i',raw,cursor+16))})
            cursor+=16+4*n_sections+4
        if cursor!=len(raw):raise ValueError('Unsupported trailing morph CPU metadata')
        offset=int(export['SerialOffset'])-os.path.getsize(base+'.uasset')+int(export['SerialSize'])-len(raw)
        entries.append({'name':export['ObjectName'],'offset':offset,'lods':lods})
    result={'names':[e['name'] for e in entries],'entries':entries}
    cache.parent.mkdir(parents=True,exist_ok=True);atomic_json(str(cache),result)
    return result


def patch_metadata(mesh,lod,targets,new_vertices):
    info=metadata(mesh.base)
    if targets and len(targets)!=len(info['entries']):raise ValueError('GPU morph target order/count does not match the original asset')
    index=lod.get('layout',{}).get('source_index',mesh.lods.index(lod))
    for i,entry in enumerate(info['entries']):
        if index>=len(entry['lods']):
            if targets and len(targets[i]['indices']):raise ValueError('Morph LOD has no matching original metadata')
            continue
        cpu=entry['lods'][index];offset=entry['offset']+cpu['offset']
        count=len(targets[i]['indices']) if targets else 0
        struct.pack_into('<II',mesh.uexp,offset+4,count,new_vertices)
    return len(info['entries'])
