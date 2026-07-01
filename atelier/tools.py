import os, json, subprocess, threading, atexit
from atelier.config import TOOLS, CNW, ROOT, PAKS, USMAP

UAT = os.path.join(TOOLS, "UAssetTool.exe")

# AtelierMesh: CUE4Parse-based mesh -> glTF (.glb) decoder for the 3D viewport.
ATELIER_MESH = os.path.join(TOOLS, "AtelierMesh", "AtelierMesh.exe")

def _aes_hex():
    try:
        k = open(os.path.join(TOOLS, "AES_KEY.txt"), encoding="utf-8").read().strip()
    except Exception:
        return ""
    return k if k.lower().startswith("0x") else "0x" + k

def atelier_mesh(asset, out_dir):
    """Decode an MR mesh (content-mount path, no ext) to glTF (.glb) under out_dir."""
    return subprocess.run(
        [ATELIER_MESH, "--paks", PAKS, "--aes", _aes_hex(), "--usmap", USMAP,
         "--asset", asset, "--out", os.path.abspath(out_dir)],
        capture_output=True, text=True, cwd=ROOT, creationflags=CNW)

def uat(args):
    """Run UAssetTool (one-shot). Pass ABSOLUTE paths — it requires them for output."""
    return subprocess.run([UAT] + args, capture_output=True, text=True, cwd=ROOT,
                          creationflags=CNW)

_proc = None
_lock = threading.Lock()

def uat_json(req):
    """Send one line-delimited JSON request to the persistent UAssetTool worker.
    Reusing one process keeps batch decode fast (startup paid once, parallel across all cores)."""
    global _proc
    with _lock:
        if _proc is None or _proc.poll() is not None:
            _proc = subprocess.Popen([UAT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=ROOT, creationflags=CNW,
                                     text=True, encoding="utf-8")
        _proc.stdin.write(json.dumps(req) + "\n"); _proc.stdin.flush()
        # Drain lines until the JSON reply (UAssetTool also writes human-readable status to stdout).
        while True:
            line = _proc.stdout.readline()
            if line == "":
                return {"success": False, "message": "UAssetTool worker closed unexpectedly"}
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    d = json.loads(s)
                    if isinstance(d, dict) and ("success" in d or "data" in d): return d
                except Exception: pass

@atexit.register
def _shutdown():
    if _proc and _proc.poll() is None:
        try: _proc.terminate()
        except Exception: pass
