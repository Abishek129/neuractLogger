import os
import sys
from pathlib import Path

try:
    import winreg
except Exception:  # pragma: no cover
    winreg = None


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "NeuractLoggerAgentTray"


def _exe_path() -> str:
    # When packaged by PyInstaller, sys.executable is the EXE.
    return os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])


def is_enabled() -> bool:
    try:
        if winreg is None:
            return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            try:
                val, _ = winreg.QueryValueEx(k, VALUE_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception:
        return False


def enable() -> bool:
    exe = _exe_path()
    quoted = f'"{exe}"'
    try:
        if winreg is None:
            return _enable_startup_shortcut()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, quoted)
        return True
    except Exception:
        # Fallback: Startup folder shortcut
        return _enable_startup_shortcut()


def disable() -> bool:
    ok = False
    try:
        if winreg is not None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, VALUE_NAME)
                    ok = True
                except FileNotFoundError:
                    pass
    except Exception:
        pass
    try:
        link = _startup_link_path()
        if link.exists():
            link.unlink()
            ok = True
    except Exception:
        pass
    return ok


def _startup_link_path() -> Path:
    appdata = os.environ.get("APPDATA")
    folder = Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    return folder / "Neuract Agent Tray.lnk"


def _enable_startup_shortcut() -> bool:
    # Create a Startup folder shortcut via WScript.Shell
    try:
        from win32com.client import Dispatch  # type: ignore
    except Exception:
        return False
    try:
        link_path = _startup_link_path()
        link_path.parent.mkdir(parents=True, exist_ok=True)
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortcut(str(link_path))
        shortcut.TargetPath = _exe_path()
        shortcut.WorkingDirectory = str(Path(_exe_path()).parent)
        shortcut.IconLocation = _exe_path()
        shortcut.Save()
        return True
    except Exception:
        return False


