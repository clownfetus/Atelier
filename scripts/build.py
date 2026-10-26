"""Build Atelier for release: one entry point for Windows and Linux.

    python scripts/build.py [--platform windows|linux] [--version N.N.N] [--skip-tools] [--no-package]

Steps (each fails the build on error, nothing is skipped silently):
  1. check the interpreter is the pinned Python (see PYTHON_VERSION) running from a venv;
  2. fetch and build every native tool from toolchain/tools.lock.json into Tools/
     (scripts/toolchain.py install; --skip-tools reuses an existing, verified Tools/);
  3. freeze the app with PyInstaller (packaging/Atelier.spec);
  4. stage the tools into dist/Atelier/Tools and audit the dist (scripts/stage_tools.py);
  5. collect licences (scripts/release_manifest.py);
  6. package: Inno Setup installer on Windows, AppImage on Linux (--no-package stops before).

Run it from the repository's .venv (BUILD.bat does this on Windows).
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = (3, 15)
HOST = "windows" if os.name == "nt" else "linux"


def step(title):
    print(f"\n== {title}", flush=True)


def run(*cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kw)


def find_iscc():
    candidates = [os.environ.get("ISCC"),
                  Path(os.environ.get("LOCALAPPDATA", "")) / "AtelierBuildTools" / "Inno Setup 6" / "ISCC.exe",
                  Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"), Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
                  shutil.which("ISCC")]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    raise SystemExit("Inno Setup 6 (ISCC.exe) not found: run scripts/bootstrap_windows.ps1 or set ISCC")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", choices=("windows", "linux"), default=HOST)
    parser.add_argument("--version", help="N.N.N; written to ./version (default: keep ./version)")
    parser.add_argument("--skip-tools", action="store_true", help="reuse Tools/ (still verified)")
    parser.add_argument("--no-package", action="store_true", help="stop after staging dist/Atelier")
    args = parser.parse_args()
    if args.platform != HOST:
        parser.error(f"Build {args.platform} on {args.platform}: PyInstaller does not cross-compile")

    step("Interpreter")
    if sys.version_info[:2] != PYTHON_VERSION or sys.maxsize <= 2**32 or sys.prefix == sys.base_prefix:
        raise SystemExit(f"Run from a 64-bit Python {'.'.join(map(str, PYTHON_VERSION))} venv "
                         f"(this is {sys.version.split()[0]} at {sys.executable})")
    print(f"  Python {sys.version.split()[0]} ({sys.executable})")

    version = args.version or (ROOT / "version").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{1,2}", version):
        raise SystemExit(f'Invalid version "{version}": expected N.N.N with 1-2 digit numbers')
    if (ROOT / "version").read_text(encoding="utf-8").strip() != version:
        (ROOT / "version").write_text(version + "\n", encoding="utf-8", newline="\n")
    print(f"  Atelier {version} for {args.platform}")

    step("Native tools (toolchain/tools.lock.json)")
    tools = ROOT / "Tools"
    run(sys.executable, "scripts/toolchain.py", "verify" if args.skip_tools else "install",
        "--platform", args.platform, "--dest", tools)

    step("Freeze the application (PyInstaller)")
    for folder in (ROOT / "dist" / "Atelier", ROOT / "build" / "pyinstaller"):
        shutil.rmtree(folder, ignore_errors=True)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", ROOT / "build" / "pyinstaller", "--distpath", ROOT / "dist",
        ROOT / "packaging" / "Atelier.spec")
    if args.platform == "linux":
        (ROOT / "dist" / "Atelier" / "Atelier").chmod(0o755)

    step("Stage tools and audit the dist")
    run(sys.executable, "scripts/stage_tools.py", "--platform", args.platform)
    run(sys.executable, "scripts/release_manifest.py")
    if args.platform == "windows":
        run(sys.executable, "scripts/package_updates.py", "--inventory-only")
    if args.no_package:
        print(f"\nStaged dist/Atelier for {args.platform}.")
        return

    step("Package")
    if args.platform == "windows":
        run(find_iscc(), ROOT / "packaging" / "Atelier.iss", f"/DAppVersion={version}")
        print(f"\nBuilt dist/AtelierSetup.exe ({version})")
    else:
        run("bash", ROOT / "packaging" / "linux" / "build_appimage.sh", version,
            env={**os.environ, "PYTHON": sys.executable})
        print(f"\nBuilt dist/Atelier-{version}-x86_64.AppImage")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"build failed at: {' '.join(map(str, error.cmd))}") from None
