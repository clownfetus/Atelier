"""Labelled native-tool fixtures; packages use JSON bytes instead of Unreal serialization."""
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from PIL import Image


def image_bytes(color=(120, 40, 90, 255), size=(16, 16)):
    output = io.BytesIO(); Image.new('RGBA', size, color).save(output, 'PNG'); return output.getvalue()


def document(name, kind, folder='Fixtures'):
    cls = {'texture': 'Texture2D', 'material': 'MaterialInstanceConstant', 'mesh': 'SkeletalMesh'}[kind]
    package = '/Game/Marvel/' + folder + '/' + name
    data = []
    if kind == 'material':
        data = [{'Name': 'VectorParameterValues', 'Value': [{'Value': [
            {'Name': 'ParameterInfo', 'Value': [{'Name': 'Name', 'Value': 'Tint'}]},
            {'Name': 'ParameterValue', 'Value': [{'Value': {'R': .2, 'G': .3, 'B': .4, 'A': 1}}]}]}]}]
    return {'FolderName': package, 'NameMap': [name, package],
            'SoftObjectPathList': [package + '.' + name],
            'Imports': [{'ObjectName': cls, 'OuterIndex': 0},
                        {'ObjectName': '/Game/Marvel/Shared/T_External', 'ClassName': 'Package', 'OuterIndex': 0}],
            'Exports': [{'ObjectName': name, 'OuterIndex': 0, 'ClassIndex': -1, 'Data': data,
                         'Extras': 'opaque payload with stable FName indices'}]}


def package(path, kind, color=(120, 40, 90, 255)):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document(path.stem, kind)), encoding='utf-8')
    path.with_suffix('.uexp').write_bytes(b'opaque payload')
    if kind == 'texture': path.with_suffix('.ubulk').write_bytes(image_bytes(color))
    return path


class AssetTool:
    def __init__(self):
        self.fail = None
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == self.fail:
            return SimpleNamespace(returncode=1, stdout='', stderr='Fixture conversion failure')
        if cmd == 'to_json':
            source = Path(args[1]); output = Path(args[3], source.stem + '.json')
            output.write_bytes(source.read_bytes())
        elif cmd == 'from_json':
            source, output = Path(args[1]), Path(args[2])
            output.write_bytes(source.read_bytes()); output.with_suffix('.uexp').write_bytes(b'opaque payload')
        elif cmd == 'inject_texture':
            source, image, output = map(Path, args[1:4])
            output.write_bytes(source.read_bytes()); output.with_suffix('.uexp').write_bytes(b'opaque payload')
            output.with_suffix('.ubulk').write_bytes(image.read_bytes())
        elif cmd == 'extract_texture':
            source, output = Path(args[1]), Path(args[2])
            shutil.copyfile(source.with_suffix('.ubulk'), output)
        else:
            raise AssertionError('Unexpected native fixture command: ' + cmd)
        return SimpleNamespace(returncode=0, stdout='', stderr='')


def decode_png(base, source):
    Path(base).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source + '.ubulk', base + '.png')
    return base + '.png'
