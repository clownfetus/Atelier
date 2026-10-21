# meshoptimizer simplifier

Official meshoptimizer 1.3 WebAssembly build, extracted without executing the
JavaScript wrapper from commit `f0a684f11ead064e176775c9b796f82a55910e92`:

https://github.com/zeux/meshoptimizer/blob/f0a684f11ead064e176775c9b796f82a55910e92/js/meshopt_simplifier.js

- JavaScript SHA-256: `f5b8d8a7a9394d7fffac357f68bab8b92d52c18a7b2c17796ece047ec3a6b741`
- WASM SHA-256: `a357a388a66eb7b039d888c8f44e3de1fd23c1e82f4ad19d89f48f080340e9b2`
- License: MIT; the full upstream notice is in `LICENSE.md`.
- Reproduce: `python scripts/vendor_meshoptimizer.py`.

`atelier.mesh_optimizer` uses Wasmtime with a 512 MiB guest memory limit and a
fuel limit, checks this digest before compilation and rejects host imports.
Fuel scales with index and attribute counts from a one-billion floor up to a
50-billion ceiling; this admits ordinary dense character sections while keeping
execution bounded. A limit failure reports an actionable error and leaves the
authored mesh unchanged.
The module has no filesystem, network or WASI access. Only this pinned module
can be loaded; uploaded WASM is never accepted. GC, exceptions, shared-memory
threads, memory64 and multiple memories are disabled. The Python API's current
49.0.0 wheel predates Rust patch releases; GC/exception advisory workarounds are
applied, and WASI/component functionality is not instantiated. Relevant review:

- https://github.com/bytecodealliance/wasmtime/security/advisories/GHSA-hw8m-q44c-ggrf
- https://github.com/bytecodealliance/wasmtime/security/advisories/GHSA-cfhf-m2cr-62wj
- https://github.com/bytecodealliance/wasmtime/security/advisories/GHSA-c9gc-w9vx-w86p

Simplification changes indices only. Vertex streams stay aligned, section
borders and bone-support boundaries are locked, and untouched imported parts
keep the original geometry of each target LOD. A 1% geometric/attribute error
budget can retain more triangles than the requested ratio. Morph data is still
remapped and verified by Atelier's existing cooker.
