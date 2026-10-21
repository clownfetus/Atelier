"""Check the exact mesh/shader release inputs. No game files or keys are needed."""
import argparse
import json
from pathlib import Path

from native_inputs import LOCK_PATH, digest, load_lock, verify_mesh, verify_shaders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--tool', choices=('all', 'animation', 'shader'), default='all')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--require-shader-source', action='store_true',
                        help='Fail if the original shader fork cannot be rebuilt from verified source')
    args = parser.parse_args()
    lock = load_lock()
    result = dict(lock_sha256=digest(LOCK_PATH))
    if args.tool in ('all', 'animation'):
        result['mesh'] = verify_mesh(args.tools, lock)
        print('Animation dependencies: exact pinned mesh bundle and native libraries verified.')
    if args.tool in ('all', 'shader'):
        result['shader'] = verify_shaders(args.tools, lock)
        print('Shader tool: exact legacy binary and custom commands verified; original source unavailable.'
              if not result['shader']['rebuildable'] else 'Shader tool: verified source build.')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    if args.require_shader_source and not result.get('shader', {}).get('rebuildable'):
        raise SystemExit('Original custom shader-fork source, Cargo.lock and build recipe are still missing.')


if __name__ == '__main__':
    main()
