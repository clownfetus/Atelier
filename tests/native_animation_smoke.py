"""Compare a source-built idle decoder with the installed decoder on a real clip.

Use an isolated application data directory with its own empty test-mods folder.
Neither decoder writes to game files or projects. The report holds extracted data.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--mesh-rel', default='Characters/1033/1033504/Meshes/SK_1033_1033504_Lobby')
    args = parser.parse_args()
    data, report = args.data_root.resolve(strict=True), args.report_dir.resolve()
    cfg = json.loads((data / 'mr_config.json').read_text(encoding='utf-8'))
    if (not (data / 'test-mods').is_dir() or Path(cfg.get('mods_folder', '')).resolve() != data / 'test-mods'
            or report.is_relative_to(ROOT) or report.is_relative_to(Path(cfg['paks']).resolve())):
        raise SystemExit('Use isolated application data and a fresh report directory outside source/game folders.')
    report.mkdir(parents=True, exist_ok=False)
    os.environ['ATELIER_DATA_DIR'] = str(data)
    from atelier import config
    from atelier.handlers.animation import idle_candidates
    from atelier.paths import pak_game_path
    from atelier.tools import vanilla_paks, _aes_hex
    paks, problem = vanilla_paks()
    if problem:
        raise SystemExit('A vanilla-only game mirror is required for decoder parity checks.')
    candidates = idle_candidates(args.mesh_rel)
    if not candidates:
        raise SystemExit('No standing idle found for the requested mesh.')
    animation = candidates[0]['game_rel']
    rebuilt = Path(config.TOOLS) / 'AtelierAnimation/AtelierAnimation.exe'
    baseline = args.baseline.resolve(strict=True)
    with rebuilt.open('rb') as stream:
        rebuilt_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = dict(mesh=args.mesh_rel, animation=animation, rebuilt_sha256=rebuilt_sha, checks=[], runs=[])
    key = _aes_hex()
    try:
        decoded = []
        for name, executable in [('baseline', baseline), ('rebuilt', rebuilt)]:
            target = report / (name + '.json')
            command = [str(executable), '--paks', str(Path(paks).resolve()), '--aes', key,
                '--usmap', config.USMAP, '--mesh', pak_game_path(args.mesh_rel),
                '--animation', pak_game_path(animation), '--out', str(target)]
            started = time.monotonic()
            try:
                proc = subprocess.run(command, cwd=executable.parent, capture_output=True, text=True,
                    errors='replace', timeout=240, creationflags=subprocess.CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired:
                # TimeoutExpired.__str__ includes arguments, including the private key.
                raise RuntimeError('Native animation decoder exceeded 240 seconds') from None
            result['runs'].append(dict(name=name, seconds=round(time.monotonic() - started, 3),
                                       returncode=proc.returncode))
            if proc.returncode:
                message = (proc.stderr or 'Native animation decoder failed').replace(key, '<redacted>')
                message = re.sub(r'(?i)(?:0x)?[a-f0-9]{64}', '<redacted>', message)
                raise RuntimeError(name + ': ' + message[-1500:])
            decoded.append(json.loads(target.read_text(encoding='utf-8')))
        assert decoded[0] == decoded[1], 'Rebuilt animation tracks differ from the installed decoder'
        result['checks'].append('Rebuilt decoder matches every baseline animation track and metadata field exactly')
        clip = decoded[1]
        assert clip['version'] == 2 and clip['space'] == 'atelier-gltf-local'
        assert 0 < clip['duration'] <= 120
        tracks = clip['tracks']
        assert len(tracks) > 8 and len({track['bone'] for track in tracks}) == len(tracks)
        frames = len(tracks[0]['times'])
        assert frames >= 2
        animated = 0
        for track in tracks:
            times = track['times']
            assert len(times) == frames and all(a < b for a, b in zip(times, times[1:]))
            assert times[0] == 0 and times[-1] < clip['duration']
            for field, width in [('positions', 3), ('rotations', 4), ('scales', 3)]:
                values = track[field]
                assert len(values) == frames * width and all(math.isfinite(value) for value in values)
            rotations = track['rotations']
            assert all(abs(sum(value * value for value in rotations[i:i + 4]) - 1) < .002
                       for i in range(0, len(rotations), 4))
            if any(abs(value - track['rotations'][i % 4]) > .00001
                   for i, value in enumerate(track['rotations'])):
                animated += 1
        assert animated > 8, 'Standing idle contains no meaningful bone motion'
        result.update(tracks=len(tracks), frames=frames, animated_bones=animated, duration=clip['duration'])
        result['checks'].append('All bone tracks have finite, aligned samples and normalized rotations with real motion')
        result['checks'].append('Decoder output uses the expected glTF local coordinate schema')
        result['ok'] = True
    except Exception as error:
        result.update(ok=False, error=str(error))
        raise
    finally:
        (report / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for check in result['checks']:
        print('PASS ' + check)


if __name__ == '__main__':
    main()
