"""
task_tracker.py
Builds and returns the Task Tracker view for the Memento main window.
"""

import flet as ft
from task_db import (
    STATUSES, init_db, fetch_all_tasks, fetch_distinct_projects,
    create_task, update_task, delete_task,
)


def build_task_tracker(page: ft.Page, config: dict,
                       add_btn, edit_btn, del_btn) -> ft.Column:
    """Return the Task Tracker UI and wire add_btn / edit_btn / del_btn."""

    output_path: str = config.get("OutputPath", "")
    init_db(output_path)

    # ── Selection state ───────────────────────────────────────────────────────
    _sel: dict = {"task": None}
    edit_btn.disabled   = True
    del_btn.disabled    = True
    edit_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400)
    del_btn.icon_color  = ft.Colors.with_opacity(0.3, ft.Colors.RED_400)

    def _clear_selection() -> None:
        _sel["task"] = None
        edit_btn.disabled   = True
        del_btn.disabled    = True
        edit_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400)
        del_btn.icon_color  = ft.Colors.with_opacity(0.3, ft.Colors.RED_400)

    def _select_task(e, task: dict) -> None:
        if _sel["task"] and _sel["task"]["id"] == task["id"]:
            _clear_selection()
        else:
            _sel["task"] = task
            edit_btn.disabled   = False
            del_btn.disabled    = False
            edit_btn.icon_color = ft.Colors.BLUE_400
            del_btn.icon_color  = ft.Colors.RED_400
        data_table.rows = _build_rows(fetch_all_tasks(output_path))
        page.update()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _fmt(val) -> str:
        return val if val else "—"

    def _status_chip(status: str) -> ft.Container:
        palette = {
            "Open":        (ft.Colors.BLUE_100,   ft.Colors.BLUE_900),
            "In Progress": (ft.Colors.ORANGE_100, ft.Colors.ORANGE_900),
            "Closed":      (ft.Colors.GREEN_100,  ft.Colors.GREEN_900),
        }
        bg, fg = palette.get(status, (ft.Colors.GREY_200, ft.Colors.GREY_800))
        return ft.Container(
            content=ft.Text(status, size=11, color=fg, weight=ft.FontWeight.W_500),
            bgcolor=bg,
            border_radius=10,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
        )

    # ── Detail / Edit dialog ─────────────────────────────────────────────────

    def open_task_dialog(task: dict | None = None) -> None:
        is_new = task is None

        title_field = ft.TextField(
            label="Title",
            value=task["title"] if task else "",
            expand=True,
            autofocus=True,
        )

        _projects = fetch_distinct_projects(output_path)
        _proj_suggestions = ft.Column([], spacing=0, visible=False)

        project_text = ft.TextField(
            label="Project",
            value=task["project"] if task else "",
            expand=True,
        )

        def _on_project_change(e) -> None:
            typed = e.control.value.strip()
            matches = [p for p in _projects if typed.lower() and typed.lower() in p.lower()][:6]
            _proj_suggestions.controls = [
                ft.Container(
                    content=ft.Text(p, size=13),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=4,
                    ink=True,
                    on_click=lambda _, p=p: _pick_project(p),
                )
                for p in matches
            ]
            _proj_suggestions.visible = bool(matches)
            save_btn.disabled = not bool(typed)
            page.update()

        def _pick_project(name: str) -> None:
            project_text.value = name
            _proj_suggestions.visible = False
            save_btn.disabled = False
            page.update()

        project_text.on_change = _on_project_change

        status_dd = ft.Dropdown(
            label="Status",
            value=task["status"] if task else "Open",
            options=[ft.dropdown.Option(s) for s in STATUSES],
            width=160,
        )

        def _save(_) -> None:
            if not title_field.value.strip():
                title_field.error_text = "Required"
                page.update()
                return
            proj = project_text.value.strip()
            if is_new:
                create_task(
                    output_path,
                    title_field.value.strip(),
                    proj,
                    status_dd.value,
                )
            else:
                update_task(
                    output_path,
                    task["id"],
                    title=title_field.value.strip(),
                    project=proj,
                    status=status_dd.value,
                )
            dlg.open = False
            _clear_selection()
            _refresh()

        def _delete(_) -> None:
            delete_task(output_path, task["id"])
            dlg.open = False
            _clear_selection()
            _refresh()

        def _cancel(_) -> None:
            dlg.open = False
            page.update()

        date_rows = []

        delete_btn = ft.FilledButton(
            "Delete",
            icon=ft.Icons.DELETE_OUTLINE,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
            on_click=_delete,
            visible=not is_new,
        )
        cancel_btn = ft.FilledButton(
            "Cancel",
            icon=ft.Icons.CLOSE,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_600, color=ft.Colors.WHITE),
            on_click=_cancel,
        )
        save_btn = ft.FilledButton(
            "Save",
            icon=ft.Icons.CHECK,
            style=ft.ButtonStyle(
                bgcolor={
                    ft.ControlState.DEFAULT:  ft.Colors.GREEN_600,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.35, ft.Colors.GREEN_600),
                },
                color={
                    ft.ControlState.DEFAULT:  ft.Colors.WHITE,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.4, ft.Colors.WHITE),
                },
            ),
            on_click=_save,
            disabled=not bool((task["project"] if task else "").strip()),
        )

        btn_row = ft.Row(
            [delete_btn, cancel_btn, save_btn] if not is_new else [cancel_btn, save_btn],
            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
        )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "New Task" if is_new else f"Task  #{task['id']}",
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Column(
                [
                    title_field,
                    ft.Column([project_text, _proj_suggestions], spacing=0),
                    status_dd,
                    ft.Divider(height=16),
                    btn_row,
                ],
                tight=True,
                spacing=12,
                width=480,
            ),
            actions=[],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # ── Table ────────────────────────────────────────────────────────────────

    _COL_HEADER = ft.FontWeight.BOLD

    data_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#",        size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Title",    size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Project",  size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Opened",   size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Modified", size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Closed",   size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Status",   size=13, weight=_COL_HEADER)),
        ],
        rows=[],
        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        vertical_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
        heading_row_color=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        expand=True,
    )

    def _build_rows(tasks: list[dict]) -> list[ft.DataRow]:
        sel_id = _sel["task"]["id"] if _sel["task"] else None
        rows = []
        for t in tasks:
            task = dict(t)
            is_sel = task["id"] == sel_id
            rows.append(
                ft.DataRow(
                    selected=is_sel,
                    color=ft.Colors.with_opacity(0.12, ft.Colors.BLUE) if is_sel else None,
                    on_select_change=lambda e, t=task: _select_task(e, t),
                    cells=[
                        ft.DataCell(ft.Text(str(task["id"]), size=13)),
                        ft.DataCell(
                            ft.TextButton(
                                task["title"],
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                ),
                                on_click=lambda _, t=task: open_task_dialog(t),
                            )
                        ),
                        ft.DataCell(ft.Text(_fmt(task["project"]),    size=13)),
                        ft.DataCell(ft.Text(_fmt(task["opened_at"]),   size=12,
                                            color=ft.Colors.GREY_500)),
                        ft.DataCell(ft.Text(_fmt(task["modified_at"]), size=12,
                                            color=ft.Colors.GREY_500)),
                        ft.DataCell(ft.Text(_fmt(task["closed_at"]),   size=12,
                                            color=ft.Colors.GREY_500)),
                        ft.DataCell(_status_chip(task["status"])),
                    ]
                )
            )
        return rows

    empty_state = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.CHECKLIST, size=64, color=ft.Colors.GREY_400),
                ft.Text(
                    "No tasks yet — use the  +  button in the toolbar to create one.",
                    size=15,
                    color=ft.Colors.GREY_500,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=14,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
    )

    list_area = ft.Container(content=empty_state, expand=True)

    def _refresh() -> None:
        tasks = fetch_all_tasks(output_path)
        if tasks:
            data_table.rows = _build_rows(tasks)
            list_area.content = ft.ListView(
                [
                    ft.Container(
                        content=data_table,
                        padding=ft.padding.symmetric(horizontal=24, vertical=12),
                    )
                ],
                expand=True,
            )
        else:
            list_area.content = empty_state
        page.update()

    _refresh()

    # ── Wire AppBar button handlers ───────────────────────────────────────────

    def _open_confirm(_) -> None:
        _confirm_dlg.open = True
        page.update()

    def _confirm_delete(_) -> None:
        _confirm_dlg.open = False
        delete_task(output_path, _sel["task"]["id"])
        _clear_selection()
        _refresh()

    def _cancel_confirm(_) -> None:
        _confirm_dlg.open = False
        page.update()

    _confirm_dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Delete Task", weight=ft.FontWeight.BOLD),
        content=ft.Text("Are you sure you want to permanently delete this task?"),
        actions=[
            ft.TextButton("Cancel", on_click=_cancel_confirm),
            ft.FilledButton(
                "Delete",
                style=ft.ButtonStyle(bgcolor=ft.Colors.ERROR, color=ft.Colors.WHITE),
                on_click=_confirm_delete,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(_confirm_dlg)

    add_btn.on_click  = lambda _: open_task_dialog(None)
    edit_btn.on_click = lambda _: open_task_dialog(_sel["task"]) if _sel["task"] else None
    del_btn.on_click  = _open_confirm

    # ── Root ─────────────────────────────────────────────────────────────────

    return list_area
