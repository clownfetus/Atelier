"""Preserve HDR textures and complete cube inputs the native PNG decoder cannot read.

BC6H is floating point. Keep its dynamic range in Radiance HDR through the
bundled DirectXTex converter, rather than clamping it into a painted PNG. A cube
input retains all six faces in a vertical strip, in the source face order. LDR
cubes use RGBA TGA so their alpha survives too. It is
an explicitly named auxiliary shader input, not a recreated game reflection
shader, and is read-only for the game's 2D texture painting workflow.
"""
import json
import io
import os
from pathlib import Path
import tempfile

from atelier import config, hostos, jobs
from atelier.tools import uat


def inline_hdr_blocks(document, source):
    """Return validated BC6H top-mip bytes, width, height and face count."""
    platforms=[record['PlatformData'] for record in document.get('Exports',[])
               if isinstance(record.get('PlatformData'),dict)]
    if len(platforms)!=1:return None
    platform=platforms[0]
    if platform.get('PixelFormat')!='PF_BC6H':return None
    mip=next(iter(platform.get('Mips') or []),{})
    width,height=mip.get('SizeX'),mip.get('SizeY')
    if any(type(value) is not int or not 1<=value<=16384 for value in (width,height)):
        raise ValueError('Invalid HDR texture dimensions')
    cube=any(row.get('ObjectName')=='TextureCube' and row.get('ClassName')=='Class'
             for row in document.get('Imports',[]))
    faces=6 if cube else 1
    if faces==6 and height%4:
        raise ValueError('This HDR cube needs per-face padding support before it can be ported')
    header=(mip.get('BulkData') or {}).get('Header') or {}
    offset,size=header.get('OffsetInFile'),header.get('SizeOnDisk')
    expected=((width+3)//4)*((height+3)//4)*16*faces
    if not header.get('IsInline') or header.get('IsInSeparateFile'):
        return None
    payload=Path(str(source)+'.uexp').read_bytes()
    if type(offset) is not int or type(size) is not int or size!=expected or not 0<=offset<=len(payload)-size:
        raise ValueError('The inline HDR texture range could not be verified')
    return payload[offset:offset+size],width,height,faces


def recover_inline_hdr(source, destination):
    """Retain a floating-point input or every LDR cube face in a read-only image."""
    from atelier.handlers.texture import _dds_header
    from atelier.handlers.cooked_texture import read_cooked
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    converter=Path(config.TOOLS)/'texconv.exe'
    with tempfile.TemporaryDirectory(prefix='.hdr-',dir=destination.parent) as temporary:
        scratch=Path(temporary)
        read=uat(['to_json',os.path.abspath(str(source)+'.uasset'),config.USMAP,str(scratch)])
        path=scratch/(Path(source).name+'.json')
        if read.returncode or not path.is_file():return None
        document=json.loads(path.read_text(encoding='utf-8-sig'))
        cooked=read_cooked(document,source)
        fmt='BC6H'
        if cooked:
            if cooked['faces']!=6 and cooked['format']!='BC6H':return None
            mip=next((mip for mip in cooked['mips'] if mip['data'] is not None),None)
            if mip is None:return None
            blocks=mip['data'],mip['width'],mip['height'],cooked['faces']
            fmt=cooked['format']
        else:
            blocks=inline_hdr_blocks(document,source)
        if blocks is None:return None
        data,width,height,faces=blocks
        if faces==6 and height%4:
            raise ValueError('This cube needs per-face padding support before it can be ported')
        # A strip preserves the exact BC6H blocks of every source cube face. No
        # mip generation, exposure change or LDR conversion is involved.
        encoded=scratch/'input.dds'
        encoded.write_bytes(_dds_header(width,height*faces,fmt,len(data))+data)
        if fmt=='BC6H':
            if not converter.is_file():return None
            result=hostos.run_exe([str(converter),'-nologo','-y','-m','1','-f','R32G32B32A32_FLOAT','-ft','hdr','-o',str(scratch),str(encoded)],
                                 capture_output=True,text=True,timeout=120)
            output=scratch/'input.hdr'
            if result.returncode or not output.is_file():
                raise ValueError('The HDR texture could not be converted: '+((result.stderr or '')+(result.stdout or ''))[-300:])
        else:
            # An LDR cube can contain alpha. TGA keeps all four decoded channels
            # and stays outside the game's PNG/DDS texture-injection workflow.
            from PIL import Image
            output=scratch/'input.tga'
            with Image.open(io.BytesIO(encoded.read_bytes())) as image:
                image.convert('RGBA').save(output)
        destination=destination.with_suffix(output.suffix)
        jobs.checkpoint();os.replace(output,destination)
    return {'path':str(destination),'status':'extracted','readonly':True,
            'layout':'cubemap_strip' if faces==6 else '2d',
            'note':('Cubemap: all six faces are retained in a vertical strip as a named auxiliary input.'
                    if faces==6 else 'HDR texture retained as a named floating-point input.')+
                   ' Game texture painting is unavailable for this input.'}
