#!/usr/bin/env bash
# Builds Tools/libooz.so — the Linux stand-in for oo2core_9_win64.dll that io_lib loads.
#
# io_lib decodes pak chunks in-process via ctypes, so Wine cannot help there the way it does
# for the .exe tools: a Linux Python process cannot load a Windows DLL. Oodle has no
# redistributable Linux build we can ship, so we use powzix/ooz, an open-source decoder for
# the Kraken/Mermaid/Selkie/Leviathan codecs that UE5 IoStore containers actually use.
# Decode-only, which is all io_lib needs — container_merge writes uncompressed blocks.
#
# Usage: linux/build_ooz.sh   (from the repo root; needs git + g++)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/linux/_ooz"
OUT="$ROOT/Tools/libooz.so"

[ -d "$SRC" ] || git clone --depth 1 https://github.com/powzix/ooz.git "$SRC"
cd "$SRC"

# ooz is an MSVC project: these headers pull in the Windows SDK and the sources use MSVC-only
# intrinsics. Replace the two platform headers with portable equivalents.
cat > targetver.h <<'EOF'
#pragma once
#ifdef _WIN32
#include <SDKDDKVer.h>
#endif
EOF

cat > stdafx.h <<'EOF'
#pragma once
#include "targetver.h"
#define _CRT_SECURE_NO_WARNINGS 1
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#ifdef _WIN32
  #include <tchar.h>
  #include <intrin.h>
  #include <Windows.h>
  typedef unsigned __int64 uint64;
  typedef signed __int64 int64;
#else
  #include <x86intrin.h>
  #include <stdint.h>
  typedef uint64_t uint64;
  typedef int64_t  int64;
  // MSVC intrinsics GCC/Clang do not provide. _rotl/_rotr already come from x86intrin.h.
  static inline unsigned char _BitScanReverse(unsigned long *idx, unsigned int m) {
    if (!m) return 0; *idx = 31 - __builtin_clz(m); return 1; }
  static inline unsigned char _BitScanForward(unsigned long *idx, unsigned int m) {
    if (!m) return 0; *idx = __builtin_ctz(m); return 1; }
  static inline unsigned short _byteswap_ushort(unsigned short v) { return __builtin_bswap16(v); }
  static inline unsigned int _byteswap_ulong(unsigned int v) { return __builtin_bswap32(v); }
  static inline unsigned long long _byteswap_uint64(unsigned long long v) { return __builtin_bswap64(v); }
  #define __forceinline inline __attribute__((always_inline))
  #define __debugbreak() __builtin_trap()
#endif
typedef unsigned char byte;
typedef unsigned char uint8;
typedef unsigned int uint32;
typedef signed int int32;
typedef unsigned short uint16;
typedef signed short int16;
typedef unsigned int uint;
EOF

# LZNA and BitKnit are legacy Oodle codecs that UE5 IoStore never selects, and their sources
# lean hardest on MSVC. Stub them so the build needs only kraken.cpp.
cat > stubs.cpp <<'EOF'
#include "stdafx.h"
struct LznaState; struct BitknitState;
int LZNA_DecodeQuantum(byte *, byte *, byte *, const byte *, const byte *, struct LznaState *) { return -1; }
void LZNA_InitLookup(struct LznaState *) {}
void BitknitState_Init(struct BitknitState *) {}
size_t Bitknit_Decode(const byte *, const byte *, byte *, byte *, byte *, struct BitknitState *) { return 0; }
EOF

# Expose an OodleLZ_Decompress-shaped entry point for io_lib's ctypes binding.
cat > shim.cpp <<'EOF'
#include <cstddef>
typedef unsigned char byte;
int Kraken_Decompress(const byte *src, size_t src_len, byte *dst, size_t dst_len);
extern "C" long long OozDecompress(const byte *src, long long src_len, byte *dst, long long dst_len) {
    return (long long)Kraken_Decompress(src, (size_t)src_len, dst, (size_t)dst_len);
}
EOF

# kraken.cpp ends with a Windows-only CLI (LoadLibraryA of the real oo2core) — cut it off.
CUT="$(grep -n 'typedef int WINAPI OodLZ_CompressFunc' kraken.cpp | cut -d: -f1)"
head -n "$((CUT - 2))" kraken.cpp > kraken_lib.cpp

mkdir -p "$ROOT/Tools"
g++ -O2 -fPIC -shared -w -msse4.1 -o "$OUT" kraken_lib.cpp stdafx.cpp stubs.cpp shim.cpp
echo "built $OUT"
