"""
main.py
Entry point for the Memento application.
"""

import os
import sys
import flet as ft
from config_manager import config_exists, load_config, save_config
from wizard import show_wizard
from main_app import show_main_app
from taskbar_utils import setup_taskbar_relaunch

# Resolve the base directory (works both frozen and from source)
_BASE = (os.path.dirname(sys.executable)
         if getattr(sys, 'frozen', False)
         else os.path.dirname(os.path.abspath(__file__)))
_ICON_PATH = os.path.join(_BASE, "_internal", "Images", "memento.ico") \
             if getattr(sys, 'frozen', False) \
             else os.path.join(_BASE, "Images", "memento.ico")

# Set Windows AppUserModelID so the taskbar shows memento.ico and not flet.exe
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Memento.App")
    except Exception:
        pass


def main(page: ft.Page) -> None:
    page.title             = "Memento"
    page.window.width      = 1024
    page.window.height     = 768
    page.window.min_width  = 800
    page.window.min_height = 600
    if os.path.isfile(_ICON_PATH):
        page.window.icon = _ICON_PATH

    # Tell Windows taskbar to relaunch Memento.exe (not flet.exe) when pinned
    if getattr(sys, "frozen", False):
        setup_taskbar_relaunch(
            window_title="Memento",
            relaunch_cmd=sys.executable,
            app_id="Memento.App",
        )

    def on_wizard_complete(config: dict) -> None:
        save_config(config)
        show_main_app(page, config)

    if not config_exists():
        page.theme_mode = ft.ThemeMode.DARK
        show_wizard(page, on_complete=on_wizard_complete)
    else:
        config = load_config()
        show_main_app(page, config)


if __name__ == "__main__":
    ft.run(main, assets_dir="Images")
