"""Host-OS differences in one place.

Atelier is a Windows app: it shells out to a folder of Windows .exe tools, and its shell
integration (folder pickers, "show in Explorer", toasts) is PowerShell and Win32. On Linux we
keep the same .exe tools and run them under Wine, and swap the shell integration for the
freedesktop equivalents.

Two things Wine deliberately does NOT cover:
  * in-process DLL loads -- a Linux Python process cannot ctypes-load a Windows DLL. io_lib
    has its own Linux backends for Oodle and AES; see the module docstring there.
  * DXC's COM API (atelier.handlers.dxc_ir) and UAssetGUI (atelier.handlers.world), which are
    GUI/COM-bound rather than plain CLIs. Those raise unsupported() on Linux.
"""
import os
import shutil
import subprocess
import sys

IS_WINDOWS = os.name == "nt"

# CREATE_NO_WINDOW: suppresses the console flash when the packaged GUI app spawns a CLI tool.
# Meaningless off Windows, and passing it to subprocess there raises.
CNW = 0x08000000 if IS_WINDOWS else 0


class UnsupportedOnLinux(RuntimeError):
    """A feature that has no Linux path at all (COM, WinForms), as opposed to one Wine covers."""


def unsupported(feature):
    raise UnsupportedOnLinux(
        f"{feature} is Windows-only and has no Linux implementation yet. "
        f"Run Atelier on Windows for this feature.")


# ── running the bundled Windows tools ─────────────────────────────────────────

def _wine():
    return os.environ.get("ATELIER_WINE") or shutil.which("wine64") or shutil.which("wine")


def to_host_path(p):
    """POSIX path -> the path the Windows tool will see. Wine maps Z:\\ to /, so this is a
    pure string rewrite -- no `winepath` subprocess per argument."""
    if IS_WINDOWS or not isinstance(p, str) or not p.startswith("/"):
        return p
    return "Z:" + p.replace("/", "\\")


def from_host_path(p):
    """Inverse of to_host_path, for paths a tool echoes back in its output."""
    if IS_WINDOWS or not isinstance(p, str):
        return p
    q = p.replace("\\", "/")
    if len(q) > 1 and q[1] == ":" and q[0] in "Zz":
        return q[2:] or "/"
    return q


def native_tool(exe_path):
    """The native Linux build of a bundled tool, if one is installed beside the .exe.

    Convention: the same path without the extension -- Tools/UAssetTool.exe -> Tools/UAssetTool.
    Dropping the native binary in is the whole install step; nothing else has to be configured, and
    a tool that has no Linux build yet keeps going through Wine on its own.
    """
    if IS_WINDOWS:
        return None
    p = str(exe_path)
    if not p.lower().endswith(".exe"):
        return None
    cand = p[:-4]
    return cand if os.path.isfile(cand) and os.access(cand, os.X_OK) else None


def _resolve(args):
    r"""(argv, via_wine) for a bundled-tool command line.

    A native build is run directly and its arguments are left alone: to_host_path()'s Z:\ rewriting
    exists for Wine, and handing those paths to a Linux binary would point it at nothing.
    """
    if IS_WINDOWS:
        return list(args), False
    argv = list(args)
    nat  = native_tool(argv[0])
    if nat:
        return [nat] + argv[1:], False
    wine = _wine()
    if not wine:
        raise RuntimeError(
            "Wine is not installed and no native build of %s was found beside it. Install Wine "
            "(Arch: sudo pacman -S wine), set ATELIER_WINE, or drop a Linux build at %s."
            % (os.path.basename(argv[0]), argv[0][:-4] if argv[0].lower().endswith(".exe") else argv[0]))
    return [wine] + [to_host_path(a) for a in argv], True


def _wrap(args):
    """Prefix the Wine launcher and translate absolute paths in the argument list.

    Every tool argument that is a path is passed through os.path.abspath() by its caller, so
    "starts with /" is an exact test for 'this is a path' here -- subcommands ("to_json"),
    flags ("--usmap") and bare filenames used as filters never do."""
    return _resolve(args)[0]


def _env(extra=None):
    if IS_WINDOWS:
        return extra
    env = os.environ.copy()
    # Wine's own chatter goes to stderr and would otherwise be interleaved into the tool output
    # that uat_json() parses line by line.
    env.setdefault("WINEDEBUG", "-all")
    if extra:
        env.update(extra)
    return env


def _prep(kw, native_exe=None):
    if IS_WINDOWS:
        kw.setdefault("creationflags", CNW)
    else:
        kw.pop("creationflags", None)   # Popen rejects a non-zero value off Windows
    kw["env"] = _env(kw.get("env"))
    if native_exe:
        _prepare_dotnet_bundle(native_exe, kw["env"])
    return kw


# ── Wine needs a CONSOLE on stdin ───────────────────────────────────────────────────────────────
# UAssetTool sets Console.InputEncoding in Main(), before it looks at a single argument. Under Wine
# that setter throws
#     System.IO.IOException: Invalid access.
#        at System.ConsolePal.SetConsoleInputEncoding(Encoding enc)
# unless stdin is a real console: /dev/null and an ordinary pipe both fail, a pty succeeds. So every
# tool launch dies at startup with an unhandled .NET exception and an empty stdout, which surfaces
# as "the asset could not be extracted" for every asset in the app.
#
# A pty on stdin is the whole fix — stdout/stderr stay ordinary pipes, so capture_output and the
# worker's line pumps are unaffected. Raw mode matters for the persistent worker: canonical mode
# would echo each request back at the master (nobody reads that, so it eventually blocks) and caps a
# line at ~4KB, and the worker's JSON requests carry long absolute paths.
def _open_console_stdin():
    """(master_fd, slave_fd) for a raw pty. The child takes the slave as stdin."""
    import pty, tty
    master, slave = pty.openpty()
    try:
        tty.setraw(slave)
    except Exception:
        pass                       # raw mode is an optimisation; a working console is the point
    return master, slave


# ── native libraries for a single-file .NET tool ────────────────────────────────────────────────
# A .NET app published as a single file resolves its native dependencies against
# AppContext.BaseDirectory, which for that publish mode is the BUNDLE EXTRACTION directory
# ($DOTNET_BUNDLE_EXTRACT_BASE_DIR/<app>/<hash>/) rather than the directory holding the executable.
# UAssetTool looks for liboo2corelinux64.so.9 that way, so its own advice -- "place the Oodle
# library beside the executable" -- is something it cannot then find: beside the exe, on
# LD_LIBRARY_PATH and in the working directory were all verified NOT to work, the bundle dir does.
#
# Without Oodle the tool cannot decompress a single pak chunk, so on Linux this is the difference
# between the whole app working and nothing extracting at all.
#
# So: pin the extraction base somewhere we control and mirror the .so files that sit beside the
# executable into the extracted bundle. This is a workaround for a tool-side path lookup, not a
# design -- the fix belongs in the tool (resolve against Environment.ProcessPath, which is the real
# executable path under single-file publish). Once that lands this quietly does nothing: the copies
# are still made, and the tool no longer needs them.
_bundle_prepared = {}          # exe path -> True once its bundle has been seeded this process


def _bundle_base():
    from atelier.config import _CACHE          # lazy: config imports hostos at module scope
    return os.path.join(_CACHE, "netbundle")


def _prepare_dotnet_bundle(exe, env):
    """Mirror *.so beside `exe` into its .NET single-file extraction dir. Best effort, once per exe."""
    import glob as _glob
    libs = [p for p in _glob.glob(os.path.join(os.path.dirname(exe), "*.so*")) if os.path.isfile(p)]
    if not libs:
        return
    base = _bundle_base()
    env["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = base
    if _bundle_prepared.get(exe):
        return
    app = os.path.join(base, os.path.basename(exe))
    try:
        os.makedirs(base, exist_ok=True)
        if not _glob.glob(os.path.join(app, "*")):
            # Nothing extracted yet. A trivial invocation makes the runtime unpack the bundle; a
            # tool that is not a single-file .NET app (retoc) simply never creates the directory.
            subprocess.run([exe, "--help"], capture_output=True, timeout=120,
                           env={**os.environ, **env})
        for d in _glob.glob(os.path.join(app, "*")):
            if not os.path.isdir(d):
                continue
            for lib in libs:
                dst = os.path.join(d, os.path.basename(lib))
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(lib):
                    shutil.copy2(lib, dst)
    except Exception as e:
        print(f"  [warn] could not seed the .NET bundle for {os.path.basename(exe)}: {e}",
              file=sys.stderr, flush=True)
    _bundle_prepared[exe] = True


def run_exe(args, **kw):
    """subprocess.run for a bundled tool (native build if installed, else Wine)."""
    argv, via_wine = _resolve(args)
    native = None if via_wine or IS_WINDOWS else argv[0]
    if not via_wine or "stdin" in kw:
        return subprocess.run(argv, **_prep(kw, native))
    master, slave = _open_console_stdin()
    try:
        return subprocess.run(argv, stdin=slave, **_prep(kw, native))
    finally:
        for fd in (slave, master):
            try: os.close(fd)
            except OSError: pass


def popen_exe(args, **kw):
    """subprocess.Popen for a bundled tool (the persistent UAssetTool worker)."""
    argv, via_wine = _resolve(args)
    native = None if via_wine or IS_WINDOWS else argv[0]
    if not via_wine or kw.get("stdin") is not subprocess.PIPE:
        return subprocess.Popen(argv, **_prep(kw, native))
    # The worker is spoken to over stdin, so the pipe it asked for becomes the pty's master end.
    master, slave = _open_console_stdin()
    kw.pop("stdin")
    try:
        proc = subprocess.Popen(argv, stdin=slave, **_prep(kw, native))
    except BaseException:
        for fd in (slave, master):
            try: os.close(fd)
            except OSError: pass
        raise
    os.close(slave)                # the parent's copy; the child holds its own
    proc.stdin = os.fdopen(master, "w", encoding=kw.get("encoding") or "utf-8",
                           newline="") if kw.get("text") or kw.get("encoding") \
        else os.fdopen(master, "wb", 0)
    return proc


# Tools with no native build yet still need Wine; UAssetTool alone covers browsing, textures,
# materials, curves, VFX and the mod build, so its native binary is what decides "usable at all".
_CORE_TOOL = "UAssetTool.exe"


def tools_ready():
    """('ok', '') or ('error', why) for the prereq check.

    Wine stops being a hard requirement the moment a native build is installed for the core tool —
    see native_tool(). Anything still lacking one reports its own Wine error when it is reached,
    naming the tool, rather than blocking the whole app up front.
    """
    if IS_WINDOWS or _wine():
        return "ok", ""
    tools = os.environ.get("MR_TOOLS") or ""
    if tools and native_tool(os.path.join(tools, _CORE_TOOL)):
        return "ok", ""
    return "error", ("Wine not found — Atelier's asset tools are Windows binaries. "
                     "Install wine (Arch: sudo pacman -S wine), set ATELIER_WINE, or drop a native "
                     "Linux build at Tools/UAssetTool.")


# ── shell integration ─────────────────────────────────────────────────────────

def _zenity(args, timeout=300):
    z = shutil.which("zenity")
    if not z:
        raise RuntimeError("zenity is not installed — needed for file pickers on Linux "
                           "(Arch: sudo pacman -S zenity).")
    r = subprocess.run([z] + args, capture_output=True, encoding="utf-8", timeout=timeout)
    return (r.stdout or "").strip()


def pick_folder(initial="", title="Select a folder:"):
    if IS_WINDOWS:
        return _ps_pick_folder(initial, title)
    args = ["--file-selection", "--directory", "--title", title]
    if initial:
        args += ["--filename", initial.rstrip("/") + "/"]
    return _zenity(args).replace("\\", "/")


def pick_file(title="Select a file", patterns=(), initial=""):
    """patterns: shell globs, e.g. ("*.zip", "*.pak"). Empty means any file."""
    if IS_WINDOWS:
        return _ps_pick_file(title, patterns, initial)
    args = ["--file-selection", "--title", title]
    if initial:
        args += ["--filename", initial]
    if patterns:
        args += ["--file-filter", " ".join(patterns), "--file-filter", "All files | *"]
    return _zenity(args).replace("\\", "/")


def reveal(path, select=True):
    """Show a path in the desktop's file manager, selecting the file where possible."""
    path = os.path.abspath(path)
    if IS_WINDOWS:
        return _explorer_reveal(path, select)
    if select and shutil.which("dbus-send"):
        # The freedesktop equivalent of `explorer /select,` — honoured by Nautilus, Dolphin,
        # Nemo and Thunar. Falls through to opening the parent folder if the call fails.
        try:
            r = subprocess.run(
                ["dbus-send", "--session", "--print-reply",
                 "--dest=org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 "array:string:file://" + path, "string:"],
                capture_output=True, timeout=10)
            if r.returncode == 0:
                return
        except Exception:
            pass
        path = os.path.dirname(path)
    elif select:
        path = os.path.dirname(path)
    open_path(path)


def open_path(path):
    """Hand a file or folder to the desktop's default handler."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: F821  (Windows-only builtin)
        return
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if not opener:
        raise RuntimeError("no xdg-open available to open " + path)
    args = [opener, "open", path] if opener.endswith("gio") else [opener, path]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_with(path):
    """'Open with...' — Linux has no universal chooser dialog, so this is the default handler."""
    if IS_WINDOWS:
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.abspath(path)])
        return
    open_path(os.path.abspath(path))


def notify(title, body):
    """Best-effort desktop notification. Never raises — it is only ever a nicety."""
    try:
        if IS_WINDOWS:
            return _toast(title, body)
        ns = shutil.which("notify-send")
        if ns:
            subprocess.Popen([ns, "-a", "Atelier", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def focus_window(title):
    """Raise our own window after the webview comes up. Best-effort; never raises."""
    try:
        if IS_WINDOWS:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
        # Wayland compositors refuse programmatic focus stealing outright, and on X11 the
        # webview already maps focused, so there is nothing useful to do here.
    except Exception:
        pass


# ── Windows implementations (unchanged behaviour, moved here) ─────────────────

def _ps(ps, timeout, env=None):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, encoding="utf-8", timeout=timeout, env=env)
    return (r.stdout or "").strip()


def _ps_pick_folder(initial, title):
    env = os.environ.copy()
    env["PAKS_INITIAL"] = initial.replace("/", "\\")
    env["PICK_DESC"] = title
    ps = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
          "Add-Type -AssemblyName System.Windows.Forms; "
          "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
          "$f.Description = $env:PICK_DESC; "
          "$f.SelectedPath = $env:PAKS_INITIAL; "
          "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }")
    return _ps(ps, 120, env).replace("\\", "/")


def _ps_pick_file(title, patterns, initial):
    env = os.environ.copy()
    env["PICK_INITIAL"] = os.path.dirname(initial.replace("/", "\\")) if initial else ""
    env["PICK_TITLE"] = title
    if patterns:
        pats = ";".join(patterns)
        filt = f"Files ({pats})|{pats}|All files (*.*)|*.*"
    else:
        filt = "All files (*.*)|*.*"
    env["PICK_FILTER"] = filt
    ps = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
          "Add-Type -AssemblyName System.Windows.Forms; "
          "$f = New-Object System.Windows.Forms.OpenFileDialog; "
          "$f.Title = $env:PICK_TITLE; "
          "$f.Filter = $env:PICK_FILTER; "
          "$f.InitialDirectory = $env:PICK_INITIAL; "
          "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }")
    return _ps(ps, 180, env).replace("\\", "/")


def _toast(title, body):
    xml = (f'<toast duration="short"><visual><binding template="ToastText02">'
           f'<text id="1">{title}</text><text id="2">{body}</text>'
           f'</binding></visual></toast>')
    ps = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
          "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime]|Out-Null;"
          "$x=[Windows.Data.Xml.Dom.XmlDocument]::new();"
          f"$x.LoadXml('{xml}');"
          f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{title}').Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))")
    subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-NoProfile", "-Command", ps],
                     creationflags=CNW)


def _explorer_reveal(path, select):
    """Explorer, built as a QUOTED STRING command rather than an arg list: the list form mangles
    '/select,<path with spaces>' (the install path has spaces), which makes Explorer open the file
    itself or land on the wrong folder."""
    import ctypes
    import threading
    import time
    p = os.path.abspath(path).replace("/", "\\")
    cmd = ('explorer.exe /select,"%s"' % p) if select else ('explorer.exe "%s"' % p)

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_size_t)
    _CLS = ("CabinetWClass", "ExploreWClass")

    def _explorer_hwnds():
        found = []
        buf = ctypes.create_unicode_buffer(64)

        def cb(hwnd, _):
            user32.GetClassNameW(hwnd, buf, 64)
            if buf.value in _CLS and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        user32.EnumWindows(EnumProc(cb), 0)
        return found

    before = set(_explorer_hwnds())
    subprocess.Popen(cmd)

    def _focus():
        time.sleep(0.6)
        after = _explorer_hwnds()
        target = next((h for h in after if h not in before), None) or (after[0] if after else None)
        if target:
            fg_tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            our_tid = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(fg_tid, our_tid, True)
            user32.ShowWindow(target, 9)
            user32.BringWindowToTop(target)
            user32.SetForegroundWindow(target)
            user32.AttachThreadInput(fg_tid, our_tid, False)

    threading.Thread(target=_focus, daemon=True).start()
