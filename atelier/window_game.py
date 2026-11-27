"""Marvel Rivals controls for the desktop window."""
import threading
import time
from pathlib import Path

from atelier import hostos


_STEAM_URL = 'steam://rungameid/2767030'
_GAME_EXE = 'marvel-win64-shipping.exe'
_START_TIMEOUT = 45


if hostos.IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', wintypes.WCHAR * 260),
        ]

    # The process snapshot includes image names even when the game runs elevated.
    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for _function in (_kernel.Process32FirstW, _kernel.Process32NextW):
        _function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
        _function.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel.CloseHandle.restype = wintypes.BOOL


def _windows_game_running():
    snapshot = _kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = _kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() == _GAME_EXE:
                return True
            found = _kernel.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(error)
        return False
    finally:
        _kernel.CloseHandle(snapshot)


def _proton_game_running(proc=Path('/proc')):
    # Linux process names in /proc/.../comm can truncate the executable name.
    # Wine sets the first command-line entry to the Windows executable.
    expected = _GAME_EXE.encode('ascii')
    for process in proc.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            executable = (process / 'cmdline').read_bytes().partition(b'\0')[0]
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        name = executable.replace(b'\\', b'/').rsplit(b'/', 1)[-1]
        if name.lower() == expected:
            return True
    return False


def _game_running():
    if hostos.IS_WINDOWS:
        return _windows_game_running()
    return _proton_game_running()


class GameControls:
    def __init__(self):
        self._lock = threading.Lock()
        self._launch_deadline = 0

    def _state(self):
        try:
            if _game_running():
                self._launch_deadline = 0
                return 'running'
        except OSError:
            return 'unknown'
        return 'starting' if time.monotonic() < self._launch_deadline else 'ready'

    def game_status(self):
        with self._lock:
            return {'state': self._state()}

    def launch_game(self):
        with self._lock:
            state = self._state()
            if state != 'ready':
                return {'state': state}
            try:
                hostos.open_path(_STEAM_URL)
            except (OSError, RuntimeError):
                return {
                    'state': 'ready',
                    'error': 'Could not open Steam. Start Marvel Rivals from your Steam library.',
                }
            self._launch_deadline = time.monotonic() + _START_TIMEOUT
            return {'state': 'starting'}
