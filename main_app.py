"""
main_app.py
Builds and displays the main application window once configuration is available.

Responsibilities:
- Apply saved theme and window position (multi-monitor support)
- Persist window position on every move and on close
- Render the menu bar  (File | Settings | Help)
- Show About / User Manual dialogs
- Provide the empty work area (task list — to be implemented)
"""

import flet as ft
from config_manager import save_config

APP_VERSION = "v1.0"
BUILD_DATE  = "13/03/2026"
APP_AUTHOR  = "Domenico Spagnuolo"


# ── Small helper ─────────────────────────────────────────────────────────────

def _info_row(icon: str, label: str, value: str) -> ft.Row:
    """One key-value row used inside the About dialog."""
    return ft.Row(
        [
            ft.Icon(icon, size=18, color=ft.Colors.BLUE_400),
            ft.Text(f"{label}:", weight=ft.FontWeight.BOLD, size=13, width=90),
            ft.Text(value, size=13),
        ],
        spacing=8,
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def show_main_app(page: ft.Page, config: dict) -> None:
    """Build and display the main application window."""

    # ── Theme ────────────────────────────────────────────────────
    page.theme_mode = (
        ft.ThemeMode.LIGHT if config.get("Theme") == "Light"
        else ft.ThemeMode.DARK
    )

    # ── Restore window position (multi-monitor support) ──────────
    # The saved coordinates ensure the window reopens on the same
    # monitor the user was last working on.
    if "window_x" in config and "window_y" in config:
        try:
            page.window.left = float(config["window_x"])
            page.window.top  = float(config["window_y"])
        except (TypeError, ValueError):
            pass

    # ── Track window position ────────────────────────────────────
    # prevent_close lets us intercept the close event, save state,
    # then destroy the window cleanly.
    page.window.prevent_close = True

    def on_window_event(e) -> None:
        event_type = e.type if hasattr(e, "type") else str(e)
        if event_type == "move":
            # Keep config in sync with the current monitor position
            config["window_x"] = page.window.left
            config["window_y"] = page.window.top
        elif event_type == "close":
            config["window_x"] = page.window.left
            config["window_y"] = page.window.top
            save_config(config)
            page.window.destroy()

    page.window.on_event = on_window_event

    # ── Dialog helpers ───────────────────────────────────────────

    def close_dlg(dlg: ft.AlertDialog) -> None:
        dlg.open = False
        page.update()

    def show_about(_) -> None:
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.BLUE_400),
                    ft.Text("About Memento", weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Divider(height=6),
                    _info_row(ft.Icons.NEW_RELEASES,   "Version",    APP_VERSION),
                    _info_row(ft.Icons.CALENDAR_TODAY, "Build date", BUILD_DATE),
                    _info_row(ft.Icons.PERSON,         "Author",     APP_AUTHOR),
                    ft.Divider(height=6),
                ],
                tight=True,
                spacing=6,
                width=360,
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: close_dlg(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def show_manual(_) -> None:
        dlg = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.MENU_BOOK, color=ft.Colors.BLUE_400),
                    ft.Text("User Manual", weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Text(
                "The user manual will be available in a future release.",
                width=360,
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: close_dlg(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # ── Menu bar ─────────────────────────────────────────────────
    menu_bar = ft.MenuBar(
        controls=[
            # ── File ─────────────────────────────────────────────
            ft.SubmenuButton(
                content=ft.Text("File"),
                controls=[
                    ft.MenuItemButton(
                        content=ft.Text("Exit"),
                        leading=ft.Icon(ft.Icons.EXIT_TO_APP),
                        # Triggers the "close" window event which saves config
                        on_click=lambda _: page.window.close(),
                    ),
                ],
            ),

            # ── Settings ─────────────────────────────────────────
            ft.SubmenuButton(
                content=ft.Text("Settings"),
                controls=[
                    ft.MenuItemButton(
                        content=ft.Text("Preferences…"),
                        leading=ft.Icon(ft.Icons.SETTINGS),
                        on_click=lambda _: None,   # TODO: implement preferences dialog
                    ),
                ],
            ),

            # ── Help ─────────────────────────────────────────────
            ft.SubmenuButton(
                content=ft.Text("Help"),
                controls=[
                    ft.MenuItemButton(
                        content=ft.Text("About"),
                        leading=ft.Icon(ft.Icons.INFO),
                        on_click=show_about,
                    ),
                    ft.MenuItemButton(
                        content=ft.Text("User Manual"),
                        leading=ft.Icon(ft.Icons.MENU_BOOK),
                        on_click=show_manual,
                    ),
                ],
            ),
        ],
    )

    # ── Work area placeholder ────────────────────────────────────
    work_area = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.LIST_ALT, size=72, color=ft.Colors.GREY_400),
                ft.Text(
                    "Work area — coming soon",
                    size=18,
                    color=ft.Colors.GREY_500,
                    weight=ft.FontWeight.W_300,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
        ),
        expand=True,
    )

    # ── Assemble final layout ────────────────────────────────────
    page.controls.clear()
    page.add(
        ft.Column(
            [
                menu_bar,
                ft.Divider(height=1, thickness=1),
                work_area,
            ],
            spacing=0,
            expand=True,
        )
    )
    page.update()
