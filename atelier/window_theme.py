"""Mirror appearance into native chrome and a small validated launch-color cache."""
import json
import os
from pathlib import Path
import re
import sys
import threading


def _color(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None


def _system_dark():
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return not winreg.QueryValueEx(key, 'AppsUseLightTheme')[0]
        except OSError:
            pass
    return True


class WindowTheme:
    def __init__(self, data_root):
        self._path = Path(data_root) / '_webview' / 'window-theme.json'
        self._window = None
        self._lock = threading.Lock()
        self._state = {'preference': 'system', 'light': '#f5f6f8', 'dark': '#17191d'}
        try:
            saved = json.loads(self._path.read_text(encoding='utf-8'))
            if (saved.get('preference') in ('light', 'dark', 'system')
                    and all(_color(saved.get(mode)) for mode in ('light', 'dark'))):
                self._state = {key: saved[key] for key in self._state}
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _mode(self):
        pref = self._state['preference']
        return ('dark' if _system_dark() else 'light') if pref == 'system' else pref

    def _background(self):
        return self._state[self._mode()]

    def _attach(self, window):
        self._window = window
        window.events.before_show += self._apply
        window.events.closing += self._detach

    def _detach(self):
        self._window = None

    def _apply(self, mode=None, background=None):
        if sys.platform != 'win32' or self._window is None or self._window.native is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            native = self._window.native
            hwnd = int(native.Handle.ToInt64())
            set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
            set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            mode, background = mode or self._mode(), background or self._background()
            def set_value(attribute, value):
                number = ctypes.c_int(value)
                return set_attribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
            if set_value(20, int(mode == 'dark')):
                set_value(19, int(mode == 'dark'))  # Older Windows 10.
            red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
            set_value(35, red | green << 8 | blue << 16)  # Windows 11 caption color.
            set_value(36, 0xFFFFFF if .2126*red + .7152*green + .0722*blue < 145 else 0x000000)
        except Exception:
            # Other backends and older Windows retain their native title bar.
            pass

    def set_window_theme(self, mode, background, preference='system', light='#f5f6f8', dark='#17191d'):
        if (mode not in ('light', 'dark') or preference not in ('light', 'dark', 'system')
                or not all(_color(value) for value in (background, light, dark))):
            return {'ok': False}
        with self._lock:
            state = {'preference': preference, 'light': light.lower(), 'dark': dark.lower()}
            if state != self._state or not self._path.exists():
                self._state = state
                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self._path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state), encoding='utf-8')
                    os.replace(temporary, self._path)
                except OSError:
                    pass
            self._apply(mode, background)
        return {'ok': True}
