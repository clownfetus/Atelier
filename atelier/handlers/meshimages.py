"""Preserve inline HDR texture inputs that the native PNG decoder cannot read.

BC6H is floating point. Keep its dynamic range in Radiance HDR through the
bundled DirectXTex converter, rather than clamping it into a painted PNG. A cube
input retains all six faces in a vertical strip, in the source face order. It is
an explicitly named auxiliary shader input, not a recreated game reflection
shader, and is read-only for the game's 2D texture painting workflow.
"""
import json
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
    """Read a native texture as HDR using only private staging destinations."""
    from atelier.handlers.texture import _dds_header
    destination=Path(destination).with_suffix('.hdr')
    destination.parent.mkdir(parents=True,exist_ok=True)
    converter=Path(config.TOOLS)/'texconv.exe'
    if not converter.is_file():return None
    with tempfile.TemporaryDirectory(prefix='.hdr-',dir=destination.parent) as temporary:
        scratch=Path(temporary)
        read=uat(['to_json',os.path.abspath(str(source)+'.uasset'),config.USMAP,str(scratch)])
        path=scratch/(Path(source).name+'.json')
        if read.returncode or not path.is_file():return None
        blocks=inline_hdr_blocks(json.loads(path.read_text(encoding='utf-8-sig')),source)
        if blocks is None:return None
        data,width,height,faces=blocks
        # A strip preserves the exact BC6H blocks of every source cube face. No
        # mip generation, exposure change or LDR conversion is involved.
        encoded=scratch/'input.dds'
        encoded.write_bytes(_dds_header(width,height*faces,'BC6H',len(data))+data)
        result=hostos.run_exe([str(converter),'-nologo','-y','-m','1','-ft','hdr','-o',str(scratch),str(encoded)],
                             capture_output=True,text=True,timeout=120)
        output=scratch/'input.hdr'
        if result.returncode or not output.is_file():
            raise ValueError('The HDR texture could not be converted: '+((result.stderr or '')+(result.stdout or ''))[-300:])
        jobs.checkpoint();os.replace(output,destination)
    return {'path':str(destination),'status':'extracted','readonly':True,
            'layout':'cubemap_strip' if faces==6 else '2d',
            'note':('HDR cubemap: all six faces are retained in a vertical strip as a named auxiliary input.'
                    if faces==6 else 'HDR texture retained as a named floating-point input.')+
                   ' Game texture painting is unavailable for this input.'}
