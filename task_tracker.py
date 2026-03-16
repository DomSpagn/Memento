"""
task_tracker.py
Builds and returns the Task Tracker view for the Memento main window.
"""

import os
import re
import shutil
import flet as ft
from datetime import datetime, timezone
from pathlib import Path
from task_db import (
    STATUSES, init_db, fetch_all_tasks, fetch_distinct_projects,
    create_task, update_task, delete_task,
    fetch_task_attachments, add_attachment, remove_attachment,
    fetch_history, add_history_entry, update_history_entry,
    delete_history_entry, fetch_history_attachments,
    add_history_attachment, remove_history_attachment,
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
        _current_desc = task.get("description", "") or ""
        _desc_has_content = bool(_current_desc.strip())
        # Shared refs to main action buttons (populated after they are created)
        _main_btns: dict = {"delete": None, "save": None}

        def _build_rich_spans(raw: str) -> list:
            """Parse stored markup → list[ft.TextSpan]. Supports nested combos."""

            def _merge_style(base, extra):
                if base is None:
                    return extra
                deco = base.decoration
                if extra.decoration is not None:
                    deco = (
                        ft.TextDecoration.UNDERLINE
                        if deco == ft.TextDecoration.UNDERLINE
                        else extra.decoration
                    )
                return ft.TextStyle(
                    weight=extra.weight or base.weight,
                    italic=(True if (extra.italic or base.italic) else None),
                    decoration=deco,
                    color=extra.color if extra.color is not None else base.color,
                )

            def parse_inline(text, inherited=None):
                pat = re.compile(
                    r'\*\*(?P<b>(?:(?!\*\*).)+?)\*\*'
                    r'|\*(?P<i>(?:(?!\*).)+?)\*'
                    r'|<u>(?P<u>(?:(?!</u>).)+?)</u>'
                    r'|\[color=(?P<chex>[^\]]+)\](?P<cv>(?:(?!\[/color\]).)+?)\[/color\]',
                    re.DOTALL,
                )
                result = []
                last = 0
                for m in pat.finditer(text):
                    if m.start() > last:
                        result.append(ft.TextSpan(text=text[last:m.start()], style=inherited))
                    if m.group('b') is not None:
                        s = _merge_style(inherited, ft.TextStyle(weight=ft.FontWeight.BOLD))
                        result.extend(parse_inline(m.group('b'), s))
                    elif m.group('i') is not None:
                        s = _merge_style(inherited, ft.TextStyle(italic=True))
                        result.extend(parse_inline(m.group('i'), s))
                    elif m.group('u') is not None:
                        s = _merge_style(inherited, ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE))
                        result.extend(parse_inline(m.group('u'), s))
                    elif m.group('chex') is not None:
                        s = _merge_style(inherited, ft.TextStyle(color=m.group('chex')))
                        result.extend(parse_inline(m.group('cv'), s))
                    last = m.end()
                if last < len(text):
                    result.append(ft.TextSpan(text=text[last:], style=inherited))
                return result

            spans = []
            for i, line in enumerate(raw.split('\n')):
                if i > 0:
                    spans.append(ft.TextSpan(text='\n'))
                if line.startswith('    '):
                    spans.append(ft.TextSpan(
                        text='    ',
                        style=ft.TextStyle(color=ft.Colors.GREY_500),
                    ))
                    line = line[4:]
                if line.startswith('• '):
                    spans.append(ft.TextSpan(text='• '))
                    line = line[2:]
                else:
                    nm = re.match(r'^(\d+\.\s)(.*)', line)
                    if nm:
                        spans.append(ft.TextSpan(text=nm.group(1)))
                        line = nm.group(2)
                spans.extend(parse_inline(line))
            return spans

        desc_display = ft.Text(
            spans=_build_rich_spans(_current_desc),
            selectable=True,
            visible=_desc_has_content,
        )

        # Tracks cursor position updated via on_selection_change
        _cursor: dict = {"pos": len(_current_desc)}

        def _on_selection_change(e) -> None:
            sel = desc_field.selection
            if sel is not None:
                _cursor["pos"] = sel.extent_offset

        desc_field = ft.TextField(
            value=_current_desc,
            multiline=True,
            min_lines=9,
            max_lines=9,
            border=ft.InputBorder.NONE,
            hint_text="Task description…",
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            expand=True,
            read_only=False,
            visible=not _desc_has_content,
            on_selection_change=_on_selection_change,
        )

        desc_edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT_NOTE,
            icon_size=18,
            tooltip="Edit description",
            visible=_desc_has_content,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
        )

        desc_save_btn = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED,
            icon_size=18,
            tooltip="Save description",
            visible=not _desc_has_content,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
        )

        def _on_desc_save(_e) -> None:
            new_desc = desc_field.value or ""
            update_task(output_path, task["id"], description=new_desc)
            has_content = bool(new_desc.strip())
            desc_display.spans = _build_rich_spans(new_desc)
            desc_display.visible = has_content
            desc_field.visible = not has_content
            desc_edit_btn.visible = has_content
            desc_save_btn.visible = not has_content
            desc_toolbar.visible = not has_content
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            if _main_btns["save"]:
                _main_btns["save"].disabled = False
            page.update()

        desc_save_btn.on_click = _on_desc_save

        async def _on_desc_edit(_e) -> None:
            desc_display.visible = False
            desc_field.visible = True
            desc_edit_btn.visible = False
            desc_save_btn.visible = True
            desc_toolbar.visible = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = True
            if _main_btns["save"]:
                _main_btns["save"].disabled = True
            page.update()
            await desc_field.focus()

        desc_edit_btn.on_click = _on_desc_edit

        async def _insert_at_cursor(text: str) -> None:
            """Insert text at the current cursor position, restore cursor after."""
            cur = desc_field.value or ""
            pos = min(_cursor["pos"], len(cur))
            new_val = cur[:pos] + text + cur[pos:]
            new_pos = pos + len(text)
            desc_field.value = new_val
            desc_field.selection = ft.TextSelection(
                base_offset=new_pos, extent_offset=new_pos
            )
            _cursor["pos"] = new_pos
            page.update()

        async def _append(text: str) -> None:
            await _insert_at_cursor(text)

        async def _apply_format(prefix: str, suffix: str, placeholder: str) -> None:
            await _insert_at_cursor(f"{prefix}{placeholder}{suffix}")

        async def _apply_line_prefix(prefix: str) -> None:
            cur = desc_field.value or ""
            pos = min(_cursor["pos"], len(cur))
            # Go to start of current line
            line_start = cur.rfind('\n', 0, pos) + 1
            before = cur[:line_start]
            after  = cur[line_start:]
            if after.endswith('\n') or not after:
                new_val = before + prefix + after
            else:
                new_val = before + prefix + after
            new_pos = line_start + len(prefix)
            desc_field.value = new_val
            desc_field.selection = ft.TextSelection(
                base_offset=new_pos, extent_offset=new_pos
            )
            _cursor["pos"] = new_pos
            page.update()

        async def _apply_numbered(_e) -> None:
            cur = desc_field.value or ""
            count = len(re.findall(r"^\d+\.\s", cur, re.MULTILINE))
            await _apply_line_prefix(f"{count + 1}. ")

        async def _remove_quotes(_e) -> None:
            cur = desc_field.value or ""
            lines = [ln[4:] if ln.startswith("    ") else ln for ln in cur.splitlines()]
            desc_field.value = "\n".join(lines)
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
        async def _on_quote(_e):       await _apply_line_prefix("    ")

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
            visible=not _desc_has_content,
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
                ft.Row(
                    [
                        ft.Text("Description", size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.GREY_600, expand=True),
                        desc_edit_btn,
                        desc_save_btn,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=ft.Column(
                        [desc_toolbar, desc_display, desc_field],
                        spacing=0,
                        expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                    border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                    expand=True,
                ),
            ],
            spacing=4,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        # ── Attachments ───────────────────────────────────────────────────────
        attach_dir = (
            Path(output_path) / "Memento" / "TaskTracker" / "attachments"
        )
        attach_list_col = ft.Column([], spacing=4)

        def _open_file(path) -> None:
            try:
                os.startfile(str(path))
            except Exception:
                pass

        def _refresh_attach() -> None:
            atts = fetch_task_attachments(output_path, task["id"])
            attach_list_col.controls = [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ATTACH_FILE, size=14, color=ft.Colors.GREY_500),
                            ft.TextButton(
                                a["orig_name"],
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                ),
                                on_click=lambda _e, fn=a["filename"]: _open_file(attach_dir / fn),
                                expand=True,
                            ),
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

        # ── History section ───────────────────────────────────────────────────
        history_attach_dir = attach_dir  # same attachments folder
        history_entries_col = ft.Column([], spacing=8)

        def _rel_date(iso: str) -> str:
            """Return a human-readable relative date string."""
            try:
                dt = datetime.fromisoformat(iso)
                delta = datetime.now() - dt
                days = delta.days
                if days == 0:
                    return "Today"
                if days == 1:
                    return "Yesterday"
                return f"{days} days ago"
            except Exception:
                return iso

        def _build_history_entry_widget(entry: dict, index: int) -> ft.Container:
            """Build a single history entry card."""
            h_atts = fetch_history_attachments(output_path, entry["id"])
            h_att_col = ft.Column(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.ATTACH_FILE, size=13, color=ft.Colors.GREY_500),
                                ft.TextButton(
                                    a["orig_name"],
                                    style=ft.ButtonStyle(
                                        padding=ft.padding.all(0),
                                        overlay_color=ft.Colors.TRANSPARENT,
                                    ),
                                    on_click=lambda _e, fn=a["filename"]: _open_file(history_attach_dir / fn),
                                    expand=True,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_size=13,
                                    icon_color=ft.Colors.RED_400,
                                    tooltip="Remove",
                                    on_click=lambda _e, a=a, eid=entry["id"]: _del_h_att(a, eid),
                                    style=ft.ButtonStyle(padding=ft.padding.all(2)),
                                ),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=4,
                        padding=ft.padding.symmetric(horizontal=6, vertical=3),
                    )
                    for a in h_atts
                ],
                spacing=3,
            )

            body_txt = ft.TextField(
                value=entry["body"],
                multiline=True,
                min_lines=2,
                max_lines=6,
                read_only=True,
                border=ft.InputBorder.NONE,
                content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                expand=True,
            )

            edit_body_btn = ft.IconButton(
                icon=ft.Icons.EDIT_NOTE, icon_size=15,
                tooltip="Edit",
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            save_body_btn = ft.IconButton(
                icon=ft.Icons.SAVE_OUTLINED, icon_size=15,
                tooltip="Save",
                visible=False,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            del_entry_btn = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=15,
                icon_color=ft.Colors.RED_400,
                tooltip="Delete entry",
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

            def _on_edit_body(_e, bt=body_txt, eb=edit_body_btn, sb=save_body_btn):
                bt.read_only = False
                eb.visible = False
                sb.visible = True
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = True
                if _main_btns["save"]:
                    _main_btns["save"].disabled = True
                page.update()

            def _on_save_body(_e, eid=entry["id"], bt=body_txt,
                              eb=edit_body_btn, sb=save_body_btn):
                update_history_entry(output_path, eid, bt.value or "")
                bt.read_only = True
                eb.visible = True
                sb.visible = False
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = False
                if _main_btns["save"]:
                    _main_btns["save"].disabled = False
                page.update()

            def _on_del_entry(_e, eid=entry["id"]):
                delete_history_entry(output_path, eid)
                _refresh_history()

            edit_body_btn.on_click = _on_edit_body
            save_body_btn.on_click = _on_save_body
            del_entry_btn.on_click = _on_del_entry

            async def _attach_to_history(_e, eid=entry["id"], hac=h_att_col):
                fp = ft.FilePicker()
                files = await fp.pick_files(allow_multiple=True)
                if not files:
                    return
                history_attach_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    src = Path(f.path)
                    dest_name = f"h{eid}_{src.name}"
                    shutil.copy2(str(src), str(history_attach_dir / dest_name))
                    add_history_attachment(output_path, eid, dest_name, src.name)
                _refresh_history()

            return ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(_rel_date(entry["created_at"]),
                                        size=11, color=ft.Colors.GREY_500,
                                        expand=True),
                                ft.Text(f"#{index}", size=11,
                                        color=ft.Colors.GREY_500,
                                        weight=ft.FontWeight.W_600),
                                edit_body_btn,
                                save_body_btn,
                                del_entry_btn,
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=2,
                        ),
                        body_txt,
                        h_att_col,
                        ft.IconButton(
                            icon=ft.Icons.ATTACH_FILE,
                            icon_size=15,
                            tooltip="Attach file to this entry",
                            on_click=_attach_to_history,
                            style=ft.ButtonStyle(padding=ft.padding.all(2)),
                        ),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=6,
                padding=ft.padding.all(8),
            )

        def _refresh_history() -> None:
            entries = fetch_history(output_path, task["id"])
            history_entries_col.controls = [
                _build_history_entry_widget(e, i + 1)
                for i, e in enumerate(entries)
            ]
            page.update()

        def _del_h_att(att: dict, _history_id: int) -> None:
            fname = remove_history_attachment(output_path, att["id"])
            if fname:
                try:
                    (history_attach_dir / fname).unlink(missing_ok=True)
                except OSError:
                    pass
            _refresh_history()

        new_entry_field = ft.TextField(
            hint_text="Write an update…",
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
            border_radius=6,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )

        add_entry_btn = ft.IconButton(
            icon=ft.Icons.ADD_COMMENT_OUTLINED,
            tooltip="Add update",
        )

        def _on_new_entry_change(_e) -> None:
            has_text = bool((new_entry_field.value or "").strip())
            add_entry_btn.icon = ft.Icons.SAVE_OUTLINED if has_text else ft.Icons.ADD_COMMENT_OUTLINED
            add_entry_btn.tooltip = "Save update" if has_text else "Add update"
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = has_text
            if _main_btns["save"]:
                _main_btns["save"].disabled = has_text
            page.update()

        new_entry_field.on_change = _on_new_entry_change

        def _add_history_entry(_e) -> None:
            text = new_entry_field.value or ""
            if not text.strip():
                return
            add_history_entry(output_path, task["id"], text)
            new_entry_field.value = ""
            add_entry_btn.icon = ft.Icons.ADD_COMMENT_OUTLINED
            add_entry_btn.tooltip = "Add update"
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            if _main_btns["save"]:
                _main_btns["save"].disabled = False
            _refresh_history()

        add_entry_btn.on_click = _add_history_entry

        history_section = ft.Column(
            [
                ft.Text("History", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                history_entries_col,
                ft.Row(
                    [
                        new_entry_field,
                        add_entry_btn,
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_history()

        # ── Dialog actions ────────────────────────────────────────────────────
        def _save(_) -> None:
            # If description editor is open, persist it too
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
            for entry in fetch_history(output_path, task["id"]):
                for hatt in fetch_history_attachments(output_path, entry["id"]):
                    try:
                        (history_attach_dir / hatt["filename"]).unlink(missing_ok=True)
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
            style=ft.ButtonStyle(
                bgcolor={
                    ft.ControlState.DEFAULT:  ft.Colors.RED_600,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.35, ft.Colors.RED_600),
                },
                color={
                    ft.ControlState.DEFAULT:  ft.Colors.WHITE,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.4, ft.Colors.WHITE),
                },
            ),
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
        )
        _main_btns["delete"] = delete_btn
        _main_btns["save"]   = save_btn

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
                        history_section,
                        ft.Divider(height=4),
                        ft.Row(
                            [delete_btn, cancel_btn, save_btn],
                            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                        ),
                    ],
                    spacing=6,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                width=560,
                height=700,
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
