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
import os
from datetime import datetime
import flet as ft
from config_manager import save_config
from task_tracker import build_task_tracker
from design_tracker import build_design_tracker
import translations
from translations import t

APP_VERSION = "v0.3"
BUILD_DATE  = datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%d/%m/%Y")
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

    # ── Language ─────────────────────────────────────────────────
    translations.set_lang(config.get("Language", "en"))

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
                    ft.Text(t("About Memento"), weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Divider(height=6),
                    _info_row(ft.Icons.NEW_RELEASES,   t("Version"),    APP_VERSION),
                    _info_row(ft.Icons.CALENDAR_TODAY, t("Build date"), BUILD_DATE),
                    _info_row(ft.Icons.PERSON,         t("Author"),     APP_AUTHOR),
                    ft.Divider(height=6),
                ],
                tight=True,
                spacing=6,
                width=360,
            ),
            actions=[
                ft.TextButton(t("Close"), on_click=lambda _: close_dlg(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def show_manual(_) -> None:
        lang = translations.get_lang()
        manual_file = "manual_it.html" if lang == "it" else "manual_en.html"
        manual_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), manual_file)
        if os.path.exists(manual_path):
            os.startfile(manual_path)
        else:
            dlg = ft.AlertDialog(
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.MENU_BOOK, color=ft.Colors.BLUE_400),
                        ft.Text(t("User Manual"), weight=ft.FontWeight.BOLD),
                    ],
                    spacing=10,
                ),
                content=ft.Text(t("The user manual will be available in a future release."), width=360),
                actions=[ft.TextButton(t("Close"), on_click=lambda _: close_dlg(dlg))],
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
                content=ft.Icon(icon, size=20),
                padding=ft.Padding(left=10, right=10, top=6, bottom=6),
                border_radius=6,
            ),
            items=items,
            tooltip=label,
        )

    # ── Output path dialog ───────────────────────────────────────────────────
    def show_output_path(_) -> None:
        from pathlib import Path as _Path

        path_field = ft.TextField(
            label=t("Installation Path"),
            value=config.get("OutputPath", ""),
            expand=True,
        )
        dir_picker = ft.FilePicker()

        async def browse(_) -> None:
            path = await dir_picker.get_directory_path(dialog_title=t("Select Installation Folder"))
            if path:
                path_field.value = path
                page.update()

        def save_path(_) -> None:
            config["OutputPath"] = path_field.value
            root = _Path(path_field.value) / "Memento"
            for tracker in ("TaskTracker", "DesignTracker"):
                for sub in ("db", "attachments"):
                    (root / tracker / sub).mkdir(parents=True, exist_ok=True)
            save_config(config)
            close_dlg(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.FOLDER_OPEN, color=ft.Colors.BLUE_400),
                 ft.Text(t("Installation Path"), weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Row(
                [path_field,
                 ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip=t("Browse…"), on_click=browse)],
                width=460,
            ),
            actions=[
                ft.TextButton(t("Cancel"), on_click=lambda _: close_dlg(dlg)),
                ft.FilledButton(t("Save"), on_click=save_path),
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

    # ── Task Tracker toolbar buttons (centred in AppBar) ──────────
    _cmd_pos = {"v": config.get("CmdBarPosition", "Top")}

    _task_add_btn    = ft.IconButton(icon=ft.Icons.ADD_TASK,       tooltip=t("New Task"),     icon_size=22, icon_color=ft.Colors.GREEN_400)
    _task_edit_btn   = ft.IconButton(icon=ft.Icons.EDIT_NOTE,      tooltip=t("Edit Task"),    icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400),   disabled=True)
    _task_del_btn    = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip=t("Delete Task"),  icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.RED_400),    disabled=True)
    _task_chart_btn  = ft.IconButton(icon=ft.Icons.PIE_CHART,      tooltip=t("Status Chart"), icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400), disabled=True)
    _task_cal_btn    = ft.IconButton(icon=ft.Icons.CALENDAR_MONTH, tooltip=t("Calendar"),     icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.GREEN_500),   disabled=True)
    _task_filter_btn = ft.IconButton(icon=ft.Icons.FILTER_LIST,    tooltip=t("Filter"),       icon_size=22, icon_color=ft.Colors.GREY_500)
    _task_search_btn = ft.IconButton(icon=ft.Icons.SEARCH,          tooltip=t("Search"),       icon_size=22, icon_color=ft.Colors.GREY_500)
    _task_actions    = ft.Row(
        [_task_add_btn, _task_edit_btn, _task_del_btn, _task_chart_btn, _task_cal_btn, _task_filter_btn, _task_search_btn],
        spacing=0,
        tight=True,
    )

    # ── Design Tracker toolbar buttons ───────────────────────────
    _design_add_btn    = ft.IconButton(icon=ft.Icons.ADD_TASK,          tooltip=t("New Design"),    icon_size=22, icon_color=ft.Colors.GREEN_400)
    _design_edit_btn   = ft.IconButton(icon=ft.Icons.EDIT_NOTE,        tooltip=t("Edit Design"),   icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400),   disabled=True)
    _design_del_btn    = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,   tooltip=t("Delete Design"), icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.RED_400),    disabled=True)
    _design_chart_btn  = ft.IconButton(icon=ft.Icons.PIE_CHART,        tooltip=t("Status Chart"),  icon_size=22, icon_color=ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400), disabled=True)
    _design_filter_btn = ft.IconButton(icon=ft.Icons.FILTER_LIST,      tooltip=t("Filter"),        icon_size=22, icon_color=ft.Colors.GREY_500)
    _design_search_btn = ft.IconButton(icon=ft.Icons.SEARCH,            tooltip=t("Search"),        icon_size=22, icon_color=ft.Colors.GREY_500)
    _design_actions    = ft.Row(
        [_design_add_btn, _design_edit_btn, _design_del_btn, _design_chart_btn, _design_filter_btn, _design_search_btn],
        spacing=0,
        tight=True,
    )

    # ── Tracker state ────────────────────────────────────────────
    _state = {"tracker": config.get("StartWith", "TaskTracker")}
    _task_actions.visible   = _state["tracker"] == "TaskTracker"
    _design_actions.visible = _state["tracker"] == "DesignTracker"

    # ── Body layout (changes with CmdBarPosition) ────────────────
    # work_area is defined later; _body wraps work_area + optional cmd panel
    _body = ft.Container(expand=True)  # content set by _apply_layout
    _cmd_panel = ft.Container(visible=False, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)

    def _active_actions():
        return _task_actions if _state["tracker"] == "TaskTracker" else _design_actions

    def _apply_layout(pos: str, navigating: bool = False) -> None:
        """Rebuild body and AppBar according to pos ('Top','Bottom','Left','Right')."""
        active = _active_actions()
        _task_actions.visible   = (not navigating) and _state["tracker"] == "TaskTracker"
        _design_actions.visible = (not navigating) and _state["tracker"] == "DesignTracker"
        if pos == "Top":
            # buttons inside AppBar – existing behaviour
            _cmd_panel.visible = False
            _actions_row.controls = [] if navigating else [active]
            _body.content = work_area
        else:
            # buttons outside AppBar
            _actions_row.controls = []
            if navigating:
                _cmd_panel.visible = False
                _body.content = work_area
            else:
                is_vert = pos in ("Left", "Right")
                btn_ctrl = (ft.Column([_task_add_btn, _task_edit_btn, _task_del_btn, _task_chart_btn, _task_cal_btn, _task_filter_btn, _task_search_btn]
                                      if _state["tracker"] == "TaskTracker" else
                                      [_design_add_btn, _design_edit_btn, _design_del_btn, _design_chart_btn, _design_filter_btn, _design_search_btn],
                                      spacing=4, tight=True)
                            if is_vert else
                            ft.Row([_task_add_btn, _task_edit_btn, _task_del_btn, _task_chart_btn, _task_cal_btn, _task_filter_btn, _task_search_btn]
                                   if _state["tracker"] == "TaskTracker" else
                                   [_design_add_btn, _design_edit_btn, _design_del_btn, _design_chart_btn, _design_filter_btn, _design_search_btn],
                                   spacing=0, tight=True))
                _cmd_panel.content = ft.Container(
                    content=btn_ctrl,
                    padding=ft.padding.symmetric(horizontal=4, vertical=8) if is_vert
                            else ft.padding.symmetric(horizontal=8, vertical=4),
                    alignment=ft.Alignment(0, 0) if not is_vert else None,
                    expand=not is_vert,
                )
                _cmd_panel.visible = True
                if pos == "Bottom":
                    _body.content = ft.Column([work_area, _cmd_panel], expand=True, spacing=0)
                elif pos == "Left":
                    _body.content = ft.Row([_cmd_panel, work_area], expand=True, spacing=0)
                else:  # Right
                    _body.content = ft.Row([work_area, _cmd_panel], expand=True, spacing=0)

    # ── Page-level navigation ────────────────────────────────────────
    def _restore_appbar() -> None:
        """Reset AppBar to the tracker-list state."""
        app_bar.leading = ft.Container(
            content=_tracker_seg,
            padding=ft.padding.only(left=8),
            alignment=ft.Alignment(-1, 0),
        )
        app_bar.leading_width = 260
        app_bar.title = _actions_row
        app_bar.center_title = True
        _apply_layout(_cmd_pos["v"])

    def _navigate_to_detail(view, task_label: str) -> None:
        """Replace the work area with a task/design detail full page."""
        _apply_layout(_cmd_pos["v"], navigating=True)
        app_bar.leading = ft.Container(
            content=ft.IconButton(
                icon=ft.Icons.ARROW_BACK,
                icon_size=20,
                tooltip=t("Back to list"),
                on_click=_navigate_back,
            ),
            padding=ft.padding.only(left=4),
            alignment=ft.Alignment(0, 0),
        )
        app_bar.leading_width = 56
        app_bar.title = ft.Text(task_label, weight=ft.FontWeight.W_500, size=15)
        app_bar.center_title = True
        work_area.content = view
        page.update()

    def _navigate_back(_=None) -> None:
        """Return from task detail to the task list."""
        _restore_appbar()
        work_area.content = _build_tracker_view(_state["tracker"])
        page.update()

    def _build_tracker_view(tracker: str):
        _task_actions.visible   = tracker == "TaskTracker"
        _design_actions.visible = tracker == "DesignTracker"
        if tracker == "TaskTracker":
            return build_task_tracker(page, config, _task_add_btn, _task_edit_btn, _task_del_btn, _task_chart_btn,
                                      calendar_btn=_task_cal_btn,
                                      filter_btn=_task_filter_btn,
                                      search_btn=_task_search_btn,
                                      on_open_task=_navigate_to_detail,
                                      on_close_task=_navigate_back)
        return build_design_tracker(page, config, _design_add_btn, _design_edit_btn, _design_del_btn, _design_chart_btn,
                                    filter_btn=_design_filter_btn,
                                    search_btn=_design_search_btn,
                                    on_open_design=_navigate_to_detail,
                                    on_close_design=_navigate_back)

    work_area = ft.Container(
        content=_build_tracker_view(_state["tracker"]),
        expand=True,
    )

    # ── Tracker segmented button (placed in AppBar) ──────────────
    def _on_segment_change(e) -> None:
        key = "DesignTracker" if e.control.selected_index == 1 else "TaskTracker"
        _state["tracker"] = key
        config["StartWith"] = key
        save_config(config)
        _tracker_seg.thumb_color = ft.Colors.BLUE_400 if key == "DesignTracker" else ft.Colors.DEEP_ORANGE_400
        work_area.content = _build_tracker_view(key)
        _restore_appbar()
        _apply_layout(_cmd_pos["v"])
        page.update()

    _tracker_seg = ft.CupertinoSlidingSegmentedButton(
        selected_index=0 if _state["tracker"] == "TaskTracker" else 1,
        on_change=_on_segment_change,
        thumb_color=ft.Colors.DEEP_ORANGE_400 if _state["tracker"] == "TaskTracker" else ft.Colors.BLUE_400,
        controls=[
            ft.Text("Task Tracker",   size=12),
            ft.Text("Design Tracker", size=12),
        ],
    )

    _actions_row = ft.Row(
        [_task_actions if _state["tracker"] == "TaskTracker" else _design_actions],
        spacing=0,
        tight=True,
    )

    app_bar = ft.AppBar(
        leading=ft.Container(
            content=_tracker_seg,
            padding=ft.padding.only(left=8),
            alignment=ft.Alignment(-1, 0),
        ),
        leading_width=260,
        title=_actions_row,
        center_title=True,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        elevation=0,
        actions=[
            # ── Settings menu ────────────────────────────────────
            _popup(ft.Icons.SETTINGS_OUTLINED, t("Settings"), [
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=16), ft.Text(t("Installation Path…"))], spacing=8),
                    on_click=show_output_path,
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.SPACE_DASHBOARD_OUTLINED, size=16), ft.Text(t("Command Bar…"))], spacing=8),
                    on_click=lambda _: _show_cmdbar_dialog(),
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.LANGUAGE, size=16), ft.Text(t("Language…"))], spacing=8),
                    on_click=lambda _: _show_language_dialog(),
                ),
            ]),
            # ── Theme toggle ─────────────────────────────────────
            ft.IconButton(
                icon=ft.Icons.DARK_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE,
                tooltip=t("Toggle theme"),
                on_click=toggle_theme,
            ),
            # ── Help menu ────────────────────────────────────────
            _popup(ft.Icons.HELP_OUTLINE, t("Help"), [
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=16), ft.Text(t("About"))], spacing=8),
                    on_click=show_about,
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.MENU_BOOK, size=16), ft.Text(t("User Manual"))], spacing=8),
                    on_click=show_manual,
                ),
            ]),
            ft.Container(width=4),
        ],
    )
    page.appbar = app_bar

    # Initialise body layout (all widgets now exist)
    _apply_layout(_cmd_pos["v"])

    # ── Command Bar position dialog ──────────────────────────────
    _POS_OPTIONS = ["Top", "Bottom", "Left", "Right"]
    _OPT_STYLE = ft.ButtonStyle(color={
        ft.ControlState.HOVERED:  ft.Colors.ORANGE_400,
        ft.ControlState.FOCUSED:  ft.Colors.ORANGE_400,
        ft.ControlState.DEFAULT:  ft.Colors.ON_SURFACE,
    })

    def _show_cmdbar_dialog() -> None:
        pos_dd = ft.Dropdown(
            label=t("Position"),
            value=_cmd_pos["v"],
            options=[ft.dropdown.Option(key=p, text=t(p), style=_OPT_STYLE) for p in _POS_OPTIONS],
            width=200,
        )

        def _save_cmdbar(_) -> None:
            new_pos = pos_dd.value or "Top"
            _cmd_pos["v"] = new_pos
            config["CmdBarPosition"] = new_pos
            save_config(config)
            cmdbar_dlg.open = False
            _apply_layout(new_pos)
            page.update()

        cmdbar_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.SPACE_DASHBOARD_OUTLINED, color=ft.Colors.ORANGE_400),
                 ft.Text(t("Command Bar Position"), weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [ft.Text(t("Choose where the action buttons appear:"), size=13), pos_dd],
                tight=True, spacing=12, width=320,
            ),
            actions=[
                ft.TextButton(t("Cancel"), on_click=lambda _: close_dlg(cmdbar_dlg)),
                ft.FilledButton(t("Apply"), on_click=_save_cmdbar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(cmdbar_dlg)
        cmdbar_dlg.open = True
        page.update()

    def _show_language_dialog() -> None:
        _LANG_OPTIONS = [("en", "English"), ("it", "Italian")]
        lang_dd = ft.Dropdown(
            label=t("Language"),
            value=config.get("Language", "en"),
            options=[
                ft.dropdown.Option(key=code, text=t(label), style=_OPT_STYLE)
                for code, label in _LANG_OPTIONS
            ],
            width=200,
        )

        def _save_lang(_) -> None:
            new_lang = lang_dd.value or "en"
            config["Language"] = new_lang
            save_config(config)
            lang_dlg.open = False
            page.update()
            translations.set_lang(new_lang)
            # Rebuild the entire UI with the new language
            page.controls.clear()
            page.appbar = None
            show_main_app(page, config)

        lang_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.LANGUAGE, color=ft.Colors.BLUE_400),
                 ft.Text(t("Language"), weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [ft.Text(t("Select language:"), size=13), lang_dd],
                tight=True, spacing=12, width=260,
            ),
            actions=[
                ft.TextButton(t("Cancel"), on_click=lambda _: close_dlg(lang_dlg)),
                ft.FilledButton(t("Apply"), on_click=_save_lang),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(lang_dlg)
        lang_dlg.open = True
        page.update()

    # ── Assemble final layout ────────────────────────────────────
    page.controls.clear()
    page.add(_body)
    page.update()
