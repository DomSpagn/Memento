"""
task_tracker.py
Builds and returns the Task Tracker view for the Memento main window.
"""

import re
import shutil
import flet as ft
from pathlib import Path
from task_db import (
    STATUSES, init_db, fetch_all_tasks, fetch_distinct_projects,
    create_task, update_task, delete_task,
    fetch_task_attachments, add_attachment, remove_attachment,
)


def build_task_tracker(page: ft.Page, config: dict,
                       add_btn, edit_btn, del_btn) -> ft.Column:
    """Return the Task Tracker UI and wire add_btn / edit_btn / del_btn."""

    output_path: str = config.get("OutputPath", "")
    init_db(output_path)

    # ── Selection state ───────────────────────────────────────────────────────
    _sel: dict = {"task": None}

    # ── Sort state ───────────────────────────────────────────────────────────
    _sort: dict = {"col": None, "asc": True}
    # Maps DataTable column index → task dict key
    _SORT_KEYS = {
        2: "project",
        3: "opened_at",
        4: "modified_at",
        5: "closed_at",
        6: "status",
    }
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
        data_table.rows = _build_rows(_apply_sort(fetch_all_tasks(output_path)))
        page.update()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _apply_sort(tasks: list[dict]) -> list[dict]:
        col = _sort["col"]
        if col is None or col not in _SORT_KEYS:
            return tasks
        key = _SORT_KEYS[col]
        return sorted(tasks, key=lambda t: (t[key] or ""), reverse=not _sort["asc"])

    def _on_sort(e) -> None:
        _sort["col"] = e.column_index
        _sort["asc"] = e.ascending
        data_table.sort_column_index = e.column_index
        data_table.sort_ascending    = e.ascending
        _refresh()

    def _fmt(val) -> str:
        return val if val else "—"

    def _status_chip(status: str) -> ft.Container:
        palette = {
            "Open":        (ft.Colors.BLUE_100,   ft.Colors.BLUE_900),
            "In Progress": (ft.Colors.ORANGE_100, ft.Colors.ORANGE_900),
            "On Hold":     (ft.Colors.PURPLE_100, ft.Colors.PURPLE_900),
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

    def open_task_dialog(task: dict | None = None) -> None:  # noqa: C901
        is_new = task is None

        # ── NEW TASK: editable title / project / status ──────────────────────
        if is_new:
            title_field = ft.TextField(
                label="Title",
                value="",
                expand=True,
                autofocus=True,
            )
            _projects = fetch_distinct_projects(output_path)
            _proj_suggestions = ft.Column([], spacing=0, visible=False)
            project_text = ft.TextField(label="Project", value="", expand=True)

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
                new_save_btn.disabled = not bool(typed)
                page.update()

            def _pick_project(name: str) -> None:
                project_text.value = name
                _proj_suggestions.visible = False
                new_save_btn.disabled = False
                page.update()

            project_text.on_change = _on_project_change

            status_dd = ft.Dropdown(
                label="Status",
                value="Open",
                options=[ft.dropdown.Option(s) for s in STATUSES],
                width=160,
            )

            def _new_save(_) -> None:
                if not title_field.value.strip():
                    title_field.error_text = "Required"
                    page.update()
                    return
                create_task(
                    output_path,
                    title_field.value.strip(),
                    project_text.value.strip(),
                    status_dd.value,
                )
                new_dlg.open = False
                _clear_selection()
                _refresh()

            def _new_cancel(_) -> None:
                new_dlg.open = False
                page.update()

            new_save_btn = ft.FilledButton(
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
                on_click=_new_save,
                disabled=True,
            )
            new_cancel_btn = ft.FilledButton(
                "Cancel",
                icon=ft.Icons.CLOSE,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_600, color=ft.Colors.WHITE),
                on_click=_new_cancel,
            )
            new_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("New Task", weight=ft.FontWeight.BOLD),
                content=ft.Column(
                    [
                        title_field,
                        ft.Column([project_text, _proj_suggestions], spacing=0),
                        status_dd,
                        ft.Divider(height=16),
                        ft.Row(
                            [new_cancel_btn, new_save_btn],
                            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                        ),
                    ],
                    tight=True,
                    spacing=12,
                    width=480,
                ),
                actions=[],
            )
            page.overlay.append(new_dlg)
            new_dlg.open = True
            page.update()
            return

        # ── EXISTING TASK: read-only title/project/status + description + files ─

        # ── Read-only header ──────────────────────────────────────────────────
        def _label_row(label: str, value_ctrl) -> ft.Row:
            return ft.Row(
                [
                    ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600, width=58),
                    value_ctrl,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        header_col = ft.Column(
            [
                _label_row("Title:",   ft.Text(task["title"],          size=13)),
                _label_row("Project:", ft.Text(task["project"] or "—", size=13)),
                _label_row("Status:",  _status_chip(task["status"])),
            ],
            spacing=6,
        )

        # ── Description field with toolbar ────────────────────────────────────
        desc_field = ft.TextField(
            value=task.get("description", "") or "",
            multiline=True,
            min_lines=9,
            max_lines=9,
            border=ft.InputBorder.NONE,
            hint_text="Task description…",
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            expand=True,
        )

        async def _append(text: str) -> None:
            desc_field.value = (desc_field.value or "") + text
            await desc_field.focus()
            page.update()

        async def _apply_format(prefix: str, suffix: str, placeholder: str) -> None:
            await _append(f"{prefix}{placeholder}{suffix}")

        async def _apply_line_prefix(prefix: str) -> None:
            cur = desc_field.value or ""
            if cur and not cur.endswith("\n"):
                cur += "\n"
            desc_field.value = cur + prefix
            await desc_field.focus()
            page.update()

        async def _apply_numbered(_e) -> None:
            cur = desc_field.value or ""
            count = len(re.findall(r"^\d+\.\s", cur, re.MULTILINE))
            await _apply_line_prefix(f"{count + 1}. ")

        async def _remove_quotes(_e) -> None:
            cur = desc_field.value or ""
            lines = [ln[2:] if ln.startswith("> ") else ln for ln in cur.splitlines()]
            desc_field.value = "\n".join(lines)
            await desc_field.focus()
            page.update()

        def _tb_btn(icon, tooltip, on_click):
            return ft.IconButton(
                icon=icon,
                icon_size=18,
                tooltip=tooltip,
                on_click=on_click,
                style=ft.ButtonStyle(
                    padding=ft.padding.symmetric(horizontal=4, vertical=4),
                    shape=ft.RoundedRectangleBorder(radius=4),
                ),
            )

        _COLOR_OPTS = [
            ("#D32F2F", "Red"),
            ("#E65100", "Orange"),
            ("#F57F17", "Yellow"),
            ("#2E7D32", "Green"),
            ("#1565C0", "Blue"),
            ("#6A1B9A", "Purple"),
            ("#AD1457", "Pink"),
            ("#212121", "Black"),
            ("#757575", "Gray"),
        ]
        # ── Async handlers for toolbar buttons ────────────────────────────────
        async def _on_bold(_e):        await _apply_format("**",   "**",    "bold text")
        async def _on_italic(_e):      await _apply_format("*",    "*",     "italic text")
        async def _on_underline(_e):   await _apply_format("<u>",  "</u>",  "underlined text")
        async def _on_bullet(_e):      await _apply_line_prefix("• ")
        async def _on_quote(_e):       await _apply_line_prefix("> ")

        def _make_color_handler(hex_color):
            async def _handler(_e):
                await _apply_format(f"[color={hex_color}]", "[/color]", "text")
            return _handler

        color_popup = ft.PopupMenuButton(
            icon=ft.Icons.FORMAT_COLOR_TEXT,
            icon_size=18,
            tooltip="Text color",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Container(width=14, height=14, bgcolor=hx, border_radius=2),
                            ft.Text(nm, size=12),
                        ],
                        spacing=6,
                    ),
                    on_click=_make_color_handler(hx),
                )
                for hx, nm in _COLOR_OPTS
            ],
        )

        desc_toolbar = ft.Container(
            content=ft.Row(
                [
                    _tb_btn(ft.Icons.FORMAT_BOLD,          "Bold",         _on_bold),
                    _tb_btn(ft.Icons.FORMAT_ITALIC,        "Italic",       _on_italic),
                    _tb_btn(ft.Icons.FORMAT_UNDERLINED,    "Underline",    _on_underline),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _tb_btn(ft.Icons.FORMAT_LIST_BULLETED, "Bullet list",  _on_bullet),
                    _tb_btn(ft.Icons.FORMAT_LIST_NUMBERED, "Numbered list", _apply_numbered),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    color_popup,
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _tb_btn(ft.Icons.FORMAT_INDENT_INCREASE, "Quote",        _on_quote),
                    _tb_btn(ft.Icons.FORMAT_INDENT_DECREASE, "Remove quote", _remove_quotes),
                ],
                spacing=0,
                tight=True,
            ),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
        )

        desc_section = ft.Column(
            [
                ft.Text("Description", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                ft.Container(
                    content=ft.Column([desc_toolbar, desc_field], spacing=0),
                    border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                    expand=True,
                ),
            ],
            spacing=4,
            expand=True,
        )

        # ── Attachments ───────────────────────────────────────────────────────
        attach_dir = (
            Path(output_path) / "Memento" / "TaskTracker" / "attachments" / str(task["id"])
        )
        attach_list_col = ft.Column([], spacing=4)

        def _refresh_attach() -> None:
            atts = fetch_task_attachments(output_path, task["id"])
            attach_list_col.controls = [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ATTACH_FILE, size=14, color=ft.Colors.GREY_500),
                            ft.Text(a["orig_name"], size=12, expand=True),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove attachment",
                                on_click=lambda _e, att=a: _remove_att(att),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=4,
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                )
                for a in atts
            ]
            page.update()

        def _remove_att(att: dict) -> None:
            fname = remove_attachment(output_path, att["id"])
            if fname:
                try:
                    (attach_dir / fname).unlink(missing_ok=True)
                except OSError:
                    pass
            _refresh_attach()

        async def _attach_files(_e) -> None:
            file_picker = ft.FilePicker()
            files = await file_picker.pick_files(allow_multiple=True)
            if not files:
                return
            attach_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                src = Path(f.path)
                dest_name = f"{task['id']}_{src.name}"
                dest = attach_dir / dest_name
                shutil.copy2(str(src), str(dest))
                add_attachment(output_path, task["id"], dest_name, src.name)
            _refresh_attach()

        _refresh_attach()

        files_section = ft.Column(
            [
                ft.Text("Files", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                ft.ElevatedButton(
                    "Attach File",
                    icon=ft.Icons.ATTACH_FILE,
                    on_click=_attach_files,
                    style=ft.ButtonStyle(elevation=0),
                ),
                attach_list_col,
            ],
            spacing=6,
        )

        # ── Dialog actions ────────────────────────────────────────────────────
        def _save(_) -> None:
            update_task(output_path, task["id"], description=desc_field.value or "")
            dlg.open = False
            _clear_selection()
            _refresh()

        def _delete(_) -> None:
            for att in fetch_task_attachments(output_path, task["id"]):
                try:
                    (attach_dir / att["filename"]).unlink(missing_ok=True)
                except OSError:
                    pass
            delete_task(output_path, task["id"])
            dlg.open = False
            _clear_selection()
            _refresh()

        def _cancel(_) -> None:
            dlg.open = False
            page.update()

        delete_btn = ft.FilledButton(
            "Delete",
            icon=ft.Icons.DELETE_OUTLINE,
            style=ft.ButtonStyle(bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
            on_click=_delete,
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
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE),
            on_click=_save,
        )

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Task  #{task['id']}", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [
                        header_col,
                        ft.Divider(height=4),
                        desc_section,
                        ft.Divider(height=4),
                        files_section,
                        ft.Divider(height=4),
                        ft.Row(
                            [delete_btn, cancel_btn, save_btn],
                            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                        ),
                    ],
                    spacing=6,
                    expand=True,
                ),
                width=560,
                height=600,
                expand=True,
            ),
            actions=[],
        )
        page.overlay.append(dlg)
        dlg.open = True
        _refresh_attach()
        page.update()

    # ── Table ────────────────────────────────────────────────────────────────

    _COL_HEADER = ft.FontWeight.BOLD

    data_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#",        size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Text("Title",    size=13, weight=_COL_HEADER)),
            ft.DataColumn(ft.Row([ft.Text("Project",  size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2, tight=True), on_sort=_on_sort),
            ft.DataColumn(ft.Row([ft.Text("Opened",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2, tight=True), on_sort=_on_sort),
            ft.DataColumn(ft.Row([ft.Text("Modified", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2, tight=True), on_sort=_on_sort),
            ft.DataColumn(ft.Row([ft.Text("Closed",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2, tight=True), on_sort=_on_sort),
            ft.DataColumn(ft.Row([ft.Text("Status",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2, tight=True), on_sort=_on_sort),
        ],
        rows=[],
        sort_column_index=None,
        sort_ascending=True,
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
                                    mouse_cursor=ft.MouseCursor.CLICK,
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
        tasks = _apply_sort(fetch_all_tasks(output_path))
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
