"""Verify material reads across fresh native processes using real game data.

Reads the supplied installation's configuration and tools, but writes only into
--report-dir. No project edits, game files or installed caches are changed.
The default material reproduced the equal-priority Rivals patch regression.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--exe', type=Path, help='Override the installed native helper')
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=6)
    parser.add_argument('--material', action='append', help='Game-relative MI path; repeatable')
    args = parser.parse_args()
    if not 2 <= args.iterations <= 30:
        parser.error('Use 2–30 fresh processes')
    root = args.data_root.resolve(strict=True)
    config = json.loads((root/'mr_config.json').read_text(encoding='utf-8'))
    tools = Path(config.get('tools') or root/'Tools')
    exe = (args.exe or tools/'AtelierNative/AtelierNative.exe').resolve(strict=True)
    report = args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=False)
    key = (config.get('aes_key') or (tools/'AES_KEY.txt').read_text()).strip()
    key = '0x' + key.removeprefix('0x').removeprefix('0X')
    materials = args.material or [
        'Characters/1060/1060302/Materials/Lobby/MI_10600_1060302_Equip_01',
        'Characters/1060/1060302/Materials/Lobby/MI_10600_1060302_Head',
    ]
    expected = {}
    results = []
    for trial in range(args.iterations):
        requests = [dict(id='initialize', action='initialize', paks=config['paks'],
                         usmap=config['usmap'], aes=key, cache_root=str(report/f'cache-{trial}'))]
        requests.extend(dict(id=str(i), action='material', asset='Marvel/Content/Marvel/'+path)
                        for i, path in enumerate(materials))
        process = subprocess.run([str(exe), 'serve'],
            input=''.join(json.dumps(request)+'\n' for request in requests),
            capture_output=True, text=True, encoding='utf-8', timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        stderr = process.stderr.replace(key, '[runtime key]').replace(key[2:], '[runtime key]')
        (report/f'process-{trial}.log').write_text(stderr, encoding='utf-8')
        assert process.returncode == 0, f'Native process {trial} failed; see its log'
        replies = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        assert len(replies) == len(requests), 'Native protocol lost a response'
        for request, reply in zip(requests, replies):
            assert reply.get('id') == request['id'] and reply.get('ok'), reply
        for path, reply in zip(materials, replies[1:]):
            data = reply['data']
            assert data.get('textures') and data.get('colors'), f'{path}: empty material on process {trial}'
            digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            assert digest == expected.setdefault(path, digest), f'{path}: changed between fresh processes'
            results.append(dict(trial=trial, material=path, colors=len(data['colors']),
                                textures=len(data['textures']), sha256=digest))
        print(f'Process {trial+1}/{args.iterations}: {len(materials)} complete, consistent materials', flush=True)
    (report/'results.json').write_text(json.dumps(dict(ok=True, results=results), indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
