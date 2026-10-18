"""Build-side access to the stdlib-only Windows runtime check."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_atelier_windows_runtime", Path(__file__).resolve().parents[1] / "atelier" / "windows_runtime.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
webview2_version = _module.webview2_version
launch_issue = _module.launch_issue
