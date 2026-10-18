"""Windows prerequisites without importing pywebview/.NET first."""
import os
import re

WEBVIEW_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_WEBVIEW_KEY = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_version():
    if os.name != "nt":
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, _WEBVIEW_KEY, 0, winreg.KEY_READ | view) as key:
                    version = winreg.QueryValueEx(key, "pv")[0]
                    if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version) and any(int(p) for p in version.split('.')):
                        return version
            except OSError:
                pass
    return None


def launch_issue():
    if os.name != "nt":
        return None
    if not webview2_version():
        return "Microsoft Edge WebView2 Runtime is required. Install the Evergreen Runtime from " + WEBVIEW_URL + " and restart Atelier."
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            if winreg.QueryValueEx(key, "Release")[0] >= 528040:
                return None
    except OSError:
        pass
    return ".NET Framework 4.8 or newer is required for Atelier's Windows shell. Install it from https://dotnet.microsoft.com/download/dotnet-framework and restart Atelier."


def native_tool_warnings(tools):
    if os.name != "nt":
        return []
    required = [
        ("UAssetTool.exe", "Asset extraction and mod builds"),
        ("UAssetGUI.exe", "World editing"),
        ("AtelierMesh/AtelierMesh.exe", "3D mesh previews"),
        ("AtelierMesh/CUE4Parse-Natives.dll", "Mesh native decoding"),
        ("AtelierMesh/oo2core_9_win64.dll", "Mesh Oodle decompression; obtain a licensed compatible DLL"),
        ("shaders/retoc-rivals-cli.exe", "World, text and shader tools (Atelier's custom retoc is required)"),
        ("shaders/oo2core_9_win64.dll", "Oodle decompression; obtain a licensed compatible DLL"),
        ("shaders/dxc.exe", "Shader compilation"),
        ("shaders/dxcompiler.dll", "Shader disassembly"),
        ("shaders/dxil.dll", "Shader validation"),
    ]
    return [("warning", f"{feature}: missing {os.path.join(tools, relative)}. See PACKAGING.md in the matching source archive for tool setup.")
            for relative, feature in required if not os.path.isfile(os.path.join(tools, relative))]
