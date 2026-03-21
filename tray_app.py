"""
tray_app.py
Lightweight Memento tray process.

- Starts automatically at Windows login (optional; see install_startup() below).
- Sits in the notification area with the Memento icon.
- Checks task alarms every 30 seconds and fires native Windows toast notifications.
- Right-click menu: Open Memento | Exit.

Usage:
    python tray_app.py            # run normally
    python tray_app.py --install  # add to Windows startup (current user)
    python tray_app.py --remove   # remove from Windows startup
"""

import os
import sys
import time
import subprocess
import threading
import argparse

# ── resolve paths ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ICON_PATH = os.path.join(_HERE, "Images", "memento.ico")
_MAIN_SCRIPT = os.path.join(_HERE, "main.py")
_PYTHON = sys.executable

# ── startup registry helpers ──────────────────────────────────────────────────
_STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_NAME = "MementoTray"


def _startup_command() -> str:
    """Command stored in the registry to launch this script at login.

    Uses pythonw.exe instead of python.exe so no console window appears
    when Windows runs this entry at login.
    """
    pythonw = os.path.join(os.path.dirname(_PYTHON), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = _PYTHON  # fallback if pythonw.exe is not present
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def install_startup() -> None:
    """Add tray_app.py to Windows user startup via the registry."""
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0,
                         winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, _STARTUP_NAME, 0, winreg.REG_SZ, _startup_command())
    winreg.CloseKey(key)
    print(f"[Memento Tray] Installed in startup: {_startup_command()}")


def remove_startup() -> None:
    """Remove tray_app.py from Windows user startup."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _STARTUP_NAME)
        winreg.CloseKey(key)
        print("[Memento Tray] Removed from startup.")
    except FileNotFoundError:
        print("[Memento Tray] Not found in startup.")


# ── config / DB helpers ───────────────────────────────────────────────────────

def _load_output_path() -> str | None:
    """Read OutputPath from mem_conf.json; return None if missing."""
    import json
    cfg_file = os.path.join(_HERE, "mem_conf.json")
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            return json.load(f).get("OutputPath")
    except Exception:
        return None


def _get_pending_alarms(output_path: str) -> list[dict]:
    """Return tasks whose alarm is due and not yet fired."""
    # Import lazily to keep startup fast; task_db lives in the same directory.
    sys.path.insert(0, _HERE)
    from task_db import get_pending_alarms
    return get_pending_alarms(output_path)


def _mark_alarm_fired(output_path: str, task_id: int) -> None:
    sys.path.insert(0, _HERE)
    from task_db import mark_alarm_fired
    mark_alarm_fired(output_path, task_id)


# ── Windows toast notification ────────────────────────────────────────────────

def _ps_esc(s: str) -> str:
    return s.replace("'", "''")


def _fire_notification(title: str, project: str = "") -> None:
    """Fire a native Windows toast and play the system notification sound."""
    # Sound
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass

    t0 = _ps_esc(title)
    t1 = _ps_esc(project)
    icon_uri = "file:///" + _ICON_PATH.replace("\\", "/")

    ps_lines = [
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime]>$null",
        "$xml=[Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastImageAndText02)",
        f"$xml.GetElementsByTagName('text').Item(0).InnerText='{t0}'",
        f"$xml.GetElementsByTagName('text').Item(1).InnerText='{t1}'",
        f"$xml.GetElementsByTagName('image').Item(0).SetAttribute('src','{icon_uri}')",
        "$t=[Windows.UI.Notifications.ToastNotification]::new($xml)",
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('Memento').Show($t)",
    ]
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", "; ".join(ps_lines)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ── alarm checker thread ──────────────────────────────────────────────────────

def _alarm_checker_loop(stop_event: threading.Event) -> None:
    """Background thread: check alarms every 30 seconds."""
    while not stop_event.wait(30):
        output_path = _load_output_path()
        if not output_path:
            continue
        try:
            tasks = _get_pending_alarms(output_path)
            for t in tasks:
                _fire_notification(t.get("title", ""), t.get("project", ""))
                _mark_alarm_fired(output_path, t["id"])
        except Exception:
            pass


# ── tray icon ─────────────────────────────────────────────────────────────────

def _open_memento(_icon, _item) -> None:
    """Launch the main Memento application."""
    subprocess.Popen(
        [_PYTHON, _MAIN_SCRIPT],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _quit_tray(icon, _item) -> None:
    icon.stop()


def run_tray() -> None:
    # Windows 11 requires DPI awareness to be set before creating the tray icon
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    try:
        import pystray
        from PIL import Image
    except ImportError:
        print("[Memento Tray] pystray and/or Pillow not installed.\n"
              "Run: pip install pystray Pillow")
        sys.exit(1)

    # Load icon image; convert to RGBA for correct transparency on Windows 11
    try:
        img = Image.open(_ICON_PATH).convert("RGBA")
    except Exception:
        # Fallback: plain coloured square
        img = Image.new("RGBA", (64, 64), color=(255, 109, 0, 255))

    menu = pystray.Menu(
        pystray.MenuItem("Open Memento", _open_memento, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", _quit_tray),
    )

    icon = pystray.Icon("Memento", img, "Memento", menu)

    # Start alarm checker daemon
    stop_event = threading.Event()
    checker = threading.Thread(target=_alarm_checker_loop, args=(stop_event,),
                               daemon=True, name="AlarmChecker")
    checker.start()

    # Also fire a first check immediately (before the 30 s wait)
    threading.Thread(target=_alarm_checker_loop.__wrapped__
                     if hasattr(_alarm_checker_loop, "__wrapped__")
                     else lambda: None,
                     daemon=True).start()
    # Immediate first check
    def _first_check():
        time.sleep(2)  # let the icon settle
        output_path = _load_output_path()
        if not output_path:
            return
        try:
            tasks = _get_pending_alarms(output_path)
            for t in tasks:
                _fire_notification(t.get("title", ""), t.get("project", ""))
                _mark_alarm_fired(output_path, t["id"])
        except Exception:
            pass
    threading.Thread(target=_first_check, daemon=True).start()

    try:
        icon.run()
    finally:
        stop_event.set()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Memento system-tray alarm daemon")
    parser.add_argument("--install", action="store_true",
                        help="Add to Windows startup (current user)")
    parser.add_argument("--remove", action="store_true",
                        help="Remove from Windows startup")
    args = parser.parse_args()

    if args.install:
        install_startup()
    elif args.remove:
        remove_startup()
    else:
        run_tray()
