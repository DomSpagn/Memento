"""
main.py
Entry point for the Memento application.

Start-up logic:
  - If mem_conf.json does not exist → show the first-run wizard.
  - Otherwise             → load the saved configuration and open the
                            main window directly.
"""

import flet as ft
from config_manager import config_exists, load_config, save_config
from wizard import show_wizard
from main_app import show_main_app


def main(page: ft.Page) -> None:
    page.title          = "Memento"
    page.window.width   = 1024
    page.window.height  = 768
    page.window.min_width  = 800
    page.window.min_height = 600

    def on_wizard_complete(config: dict) -> None:
        """Called by the wizard when the user clicks Finish."""
        save_config(config)
        show_main_app(page, config)

    if not config_exists():
        # First run: start with dark theme so the wizard looks consistent
        page.theme_mode = ft.ThemeMode.DARK
        show_wizard(page, on_complete=on_wizard_complete)
    else:
        config = load_config()
        show_main_app(page, config)


if __name__ == "__main__":
    ft.run(main)
