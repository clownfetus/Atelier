"""Reproduce the pinned meshoptimizer WASM from its official, checked JS build.

Usage: python scripts/vendor_meshoptimizer.py [--source meshopt_simplifier.js]
The generated module and MIT license live in atelier/vendor/meshoptimizer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

COMMIT = 'f0a684f11ead064e176775c9b796f82a55910e92'
URL = f'https://raw.githubusercontent.com/zeux/meshoptimizer/{COMMIT}/js/meshopt_simplifier.js'
SOURCE_SHA256 = 'f5b8d8a7a9394d7fffac357f68bab8b92d52c18a7b2c17796ece047ec3a6b741'
WASM_SHA256 = 'a357a388a66eb7b039d888c8f44e3de1fd23c1e82f4ad19d89f48f080340e9b2'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.source:
        raw = args.source.read_bytes()
    else:
        with urlopen(URL, timeout=30) as response:
            raw = response.read(1_000_000)
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise SystemExit('Upstream source checksum mismatch')
    source = raw.decode('utf-8')
    packed = re.search(r"var wasm\s*=\s*'([^']+)';", source)[1]
    table_text = re.search(r'var wasmpack = new Uint8Array\((\[[^]]+\])\)', source)[1]
    table = json.loads(re.sub(r',\s*]', ']', table_text))
    encoded = [ord(ch)-97 if ord(ch)>96 else ord(ch)-39 if ord(ch)>64 else ord(ch)+4 for ch in packed]
    result = bytearray(); offset = 0
    while offset < len(encoded):
        value = encoded[offset]; offset += 1
        if value < 60:
            result.append(table[value])
        else:
            result.append((value-60)*64+encoded[offset]); offset += 1
    if hashlib.sha256(result).hexdigest() != WASM_SHA256:
        raise SystemExit('Extracted module checksum mismatch')
    target = Path(__file__).resolve().parents[1]/'atelier/vendor/meshoptimizer/simplifier.wasm'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result)
    print(f'Verified {len(result)} bytes: {WASM_SHA256}')


if __name__ == '__main__':
    main()
