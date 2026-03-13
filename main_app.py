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

import asyncio
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
    # Save position to disk as soon as the user stops dragging the window
    # (MOVED fires once at end of drag). No prevent_close needed: the
    # window closes instantly via the OS mechanism.
    async def on_window_event(e) -> None:
        event_type = e.type
        if event_type == ft.WindowEventType.MOVE:
            # Keep config in sync while dragging (in-memory only)
            config["window_x"] = page.window.left
            config["window_y"] = page.window.top
        elif event_type == ft.WindowEventType.MOVED:
            # Drag ended — persist position to disk
            config["window_x"] = page.window.left
            config["window_y"] = page.window.top
            await asyncio.to_thread(save_config, config)

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

    # ── Popup menu helpers ───────────────────────────────────────
    def _menu_btn(icon, label, on_click) -> ft.TextButton:
        return ft.TextButton(
            content=ft.Row(
                [ft.Icon(icon, size=16), ft.Text(label, size=13)],
                spacing=6,
                tight=True,
            ),
            style=ft.ButtonStyle(
                padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                overlay_color=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
            on_click=on_click,
        )

    def _popup(icon, label, items) -> ft.PopupMenuButton:
        return ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row(
                    [ft.Icon(icon, size=16), ft.Text(label, size=13)],
                    spacing=6,
                    tight=True,
                ),
                padding=ft.Padding(left=14, right=10, top=6, bottom=6),
                border_radius=6,
            ),
            items=items,
            tooltip="",
        )

    # ── Output path dialog ───────────────────────────────────────
    def show_output_path(_) -> None:
        from pathlib import Path as _Path

        task_field = ft.TextField(
            label="Task Tracker Output Path",
            value=config.get("TaskTrackerPath", ""),
            expand=True,
        )
        design_field = ft.TextField(
            label="Design Tracker Output Path",
            value=config.get("DesignTrackerPath", ""),
            expand=True,
        )
        dir_picker = ft.FilePicker()

        async def browse_task(_) -> None:
            path = await dir_picker.get_directory_path(dialog_title="Select Task Tracker Output Folder")
            if path:
                task_field.value = path
                page.update()

        async def browse_design(_) -> None:
            path = await dir_picker.get_directory_path(dialog_title="Select Design Tracker Output Folder")
            if path:
                design_field.value = path
                page.update()

        def save_paths(_) -> None:
            for key, field in (("TaskTrackerPath", task_field), ("DesignTrackerPath", design_field)):
                config[key] = field.value
                p = _Path(field.value)
                (p / "db").mkdir(parents=True, exist_ok=True)
                (p / "attachments").mkdir(parents=True, exist_ok=True)
            save_config(config)
            close_dlg(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.FOLDER_OPEN, color=ft.Colors.BLUE_400),
                 ft.Text("Output Paths", weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Row([task_field,   ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip="Browse…", on_click=browse_task)]),
                    ft.Row([design_field, ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip="Browse…", on_click=browse_design)]),
                ],
                spacing=10,
                width=460,
                tight=True,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: close_dlg(dlg)),
                ft.FilledButton("Save", on_click=save_paths),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # ── Top app bar (modern title bar + toolbar) ─────────────────
    def toggle_theme(_) -> None:
        is_light = page.theme_mode == ft.ThemeMode.LIGHT
        page.theme_mode = ft.ThemeMode.DARK if is_light else ft.ThemeMode.LIGHT
        config["Theme"] = "Dark" if page.theme_mode == ft.ThemeMode.DARK else "Light"
        save_config(config)
        page.update()

    async def exit_app(_) -> None:
        config["window_x"] = page.window.left
        config["window_y"] = page.window.top
        save_config(config)
        await page.window.close()

    app_bar = ft.AppBar(
        leading=ft.Icon(ft.Icons.HISTORY_EDU, color=ft.Colors.BLUE_400),
        leading_width=48,
        title=ft.Text("Memento", weight=ft.FontWeight.BOLD, size=18),
        center_title=False,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        elevation=0,
        actions=[
            # ── File menu ────────────────────────────────────────
            _popup(ft.Icons.FOLDER_OUTLINED, "File", [
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.EXIT_TO_APP, size=16), ft.Text("Exit")], spacing=8),
                    on_click=exit_app,
                ),
            ]),
            # ── Settings menu ────────────────────────────────────
            _popup(ft.Icons.SETTINGS_OUTLINED, "Settings", [
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text("Output Path…")], spacing=8),
                    on_click=show_output_path,
                ),
                ft.PopupMenuItem(),  # divider
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.TUNE, size=16), ft.Text("Preferences…")], spacing=8),
                    on_click=lambda _: None,  # TODO
                ),
            ]),
            # ── Help menu ────────────────────────────────────────
            _popup(ft.Icons.HELP_OUTLINE, "Help", [
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=16), ft.Text("About")], spacing=8),
                    on_click=show_about,
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.MENU_BOOK, size=16), ft.Text("User Manual")], spacing=8),
                    on_click=show_manual,
                ),
            ]),
            ft.Container(width=4),
            # ── Theme toggle ─────────────────────────────────────
            ft.IconButton(
                icon=ft.Icons.DARK_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE,
                tooltip="Toggle theme",
                on_click=toggle_theme,
            ),
            ft.Container(width=4),
        ],
    )
    page.appbar = app_bar

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
    page.add(work_area)
    page.update()
