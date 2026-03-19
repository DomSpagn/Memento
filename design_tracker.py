"""
design_tracker.py
Builds and returns the Design Tracker view for the Memento main window.
"""

import os
import re
import shutil
import flet as ft
from datetime import datetime, timedelta
from pathlib import Path
from design_db import (
    STATUSES, CATEGORIES, FUNCTIONS,
    init_db, fetch_all_designs, fetch_distinct_projects,
    create_design, update_design, delete_design,
    fetch_design_attachments, add_attachment, remove_attachment,
    fetch_history, fetch_all_history, add_history_entry, update_history_entry,
    delete_history_entry, fetch_history_attachments,
    add_history_attachment, remove_history_attachment,
    fetch_related_designs, add_related_design, remove_related_design,
    fetch_design_task_links, add_design_task_link, remove_design_task_link,
    fetch_all_design_attachments, fetch_all_history_attachments_bulk,
    fetch_all_related_design_links, fetch_all_design_task_links_raw,
)
from task_db import fetch_all_tasks


def build_design_tracker(page: ft.Page, config: dict,
                          add_btn, edit_btn, del_btn, chart_btn=None,
                          filter_btn=None, search_btn=None,
                          on_open_design=None, on_close_design=None) -> ft.Column:
    """Return the Design Tracker UI and wire add_btn / edit_btn / del_btn / chart_btn / filter_btn / search_btn."""

    output_path: str = config.get("OutputPath", "")
    init_db(output_path)

    _sel: dict = {"design": None}
    _sort: dict = {"col": None, "asc": True}
    _SORT_KEYS = {
        2: "board",
        3: "revision",
        4: "project",
        5: "category",
        6: "function",
        7: "opened_at",
        8: "modified_at",
        9: "closed_at",
        10: "status",
    }

    edit_btn.disabled   = True
    del_btn.disabled    = True
    edit_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400)
    del_btn.icon_color  = ft.Colors.with_opacity(0.3, ft.Colors.RED_400)
    if chart_btn:
        chart_btn.disabled   = True
        chart_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400)

    # ── Filter state ──────────────────────────────────────────────────────────
    _active_filters: dict = {
        "project": "", "board": "", "category": "", "function": "",
        "opened": "", "modified": "", "closed": "", "status": "",
        "tags": []
    }

    # ── Search state ──────────────────────────────────────────────────────────
    _search_query: dict = {"q": ""}

    def _apply_filter(designs: list[dict]) -> list[dict]:
        result = designs
        if _active_filters["project"]:
            result = [d for d in result if d.get("project") == _active_filters["project"]]
        if _active_filters["board"]:
            result = [d for d in result if d.get("board") == _active_filters["board"]]
        if _active_filters["category"]:
            result = [d for d in result if d.get("category") == _active_filters["category"]]
        if _active_filters["function"]:
            result = [d for d in result if d.get("function") == _active_filters["function"]]
        if _active_filters["status"]:
            result = [d for d in result if d.get("status") == _active_filters["status"]]
        if _active_filters["opened"]:
            result = [d for d in result if (d.get("opened_at") or "")[:10] == _active_filters["opened"]]
        if _active_filters["modified"]:
            result = [d for d in result if (d.get("modified_at") or "")[:10] == _active_filters["modified"]]
        if _active_filters["closed"]:
            result = [d for d in result if (d.get("closed_at") or "")[:10] == _active_filters["closed"]]
        if _active_filters["tags"]:
            all_hist = fetch_all_history(output_path)
            required = set(_active_filters["tags"])
            tagged_ids: set = set()
            for h in all_hist:
                found = {m.lstrip("#").lower() for m in re.findall(r"#\w+", h.get("body") or "")}
                if found & required:
                    tagged_ids.add(h["design_id"])
            result = [d for d in result if d["id"] in tagged_ids]
        return result

    def _apply_search(designs: list[dict]) -> list[dict]:
        q = _search_query["q"]
        if not q:
            return designs
        all_hist     = fetch_all_history(output_path)
        all_h_atts   = fetch_all_history_attachments_bulk(output_path)
        all_d_atts   = fetch_all_design_attachments(output_path)
        all_rel_d    = fetch_all_related_design_links(output_path)
        all_dtlinks  = fetch_all_design_task_links_raw(output_path)
        tasks_map    = {t["id"]: (t.get("title") or "").lower()
                        for t in fetch_all_tasks(output_path)}

        hist_map: dict = {}
        for h in all_hist:
            hist_map.setdefault(h["design_id"], []).append((h.get("body") or "").lower())

        h_att_map: dict = {}
        for ha in all_h_atts:
            h_att_map.setdefault(ha["design_id"], []).append((ha.get("orig_name") or "").lower())

        d_att_map: dict = {}
        for da in all_d_atts:
            d_att_map.setdefault(da["design_id"], []).append((da.get("orig_name") or "").lower())

        rel_d_map: dict = {}
        for rd in all_rel_d:
            rel_d_map.setdefault(rd["design_id"], []).append((rd.get("related_title") or "").lower())

        rel_t_map: dict = {}
        for dtl in all_dtlinks:
            title = tasks_map.get(dtl["task_id"], "")
            if title:
                rel_t_map.setdefault(dtl["design_id"], []).append(title)

        def _matches(design: dict) -> bool:
            did = design["id"]
            haystack = " ".join(filter(None, [
                (design.get("title")       or "").lower(),
                (design.get("board")       or "").lower(),
                (design.get("revision")    or "").lower(),
                (design.get("project")     or "").lower(),
                (design.get("category")    or "").lower(),
                (design.get("function")    or "").lower(),
                (design.get("status")      or "").lower(),
                (design.get("description") or "").lower(),
                " ".join(rel_d_map.get(did, [])),
                " ".join(rel_t_map.get(did, [])),
                " ".join(d_att_map.get(did, [])),
                " ".join(hist_map.get(did, [])),
                " ".join(h_att_map.get(did, [])),
            ]))
            return q in haystack

        return [d for d in designs if _matches(d)]

    def _update_filter_btn_color() -> None:
        if filter_btn:
            active = any(v for v in _active_filters.values())
            filter_btn.icon_color = ft.Colors.ORANGE_400 if active else ft.Colors.GREY_500
            filter_btn.update()

    def _update_search_btn_color() -> None:
        if search_btn:
            search_btn.icon_color = ft.Colors.BLUE_400 if _search_query["q"] else ft.Colors.GREY_500
            search_btn.update()

    def _clear_selection() -> None:
        _sel["design"] = None
        edit_btn.disabled   = True
        del_btn.disabled    = True
        edit_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400)
        del_btn.icon_color  = ft.Colors.with_opacity(0.3, ft.Colors.RED_400)

    def _select_design(e, design: dict) -> None:
        if _sel["design"] and _sel["design"]["id"] == design["id"]:
            _clear_selection()
        else:
            _sel["design"] = design
            edit_btn.disabled   = False
            del_btn.disabled    = False
            edit_btn.icon_color = ft.Colors.BLUE_400
            del_btn.icon_color  = ft.Colors.RED_400
        data_table.rows = _build_rows(_apply_sort(fetch_all_designs(output_path)))
        page.update()

    def _apply_sort(designs: list[dict]) -> list[dict]:
        col = _sort["col"]
        if col is None or col not in _SORT_KEYS:
            return designs
        key = _SORT_KEYS[col]
        return sorted(designs, key=lambda d: (d[key] or ""), reverse=not _sort["asc"])

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

    # ── Category / Function display helpers ───────────────────────────────────

    def _display_category(design: dict) -> str:
        cat = design.get("category") or "Schematic"
        if cat == "Other":
            custom = (design.get("category_custom") or "").strip()
            return custom if custom else "Other"
        return cat

    def _display_function(design: dict) -> str:
        fn = design.get("function") or "Connectivity"
        if fn == "Other":
            custom = (design.get("function_custom") or "").strip()
            return custom if custom else "Other"
        return fn

    # ── Detail / Edit dialog ──────────────────────────────────────────────────

    def open_design_dialog(design: dict | None = None) -> None:  # noqa: C901
        is_new = design is None

        # ── NEW DESIGN ────────────────────────────────────────────────────────
        if is_new:
            title_field    = ft.TextField(label="Name",     value="", expand=True, autofocus=True, dense=True)
            board_field    = ft.TextField(label="Board",    value="", expand=True, dense=True)
            revision_field = ft.TextField(label="Revision", value="", expand=True, dense=True)
            _projects = fetch_distinct_projects(output_path)
            _proj_suggestions = ft.Column([], spacing=0, visible=False)
            project_text = ft.TextField(label="Project", value="", expand=True, dense=True)

            def _check_new_save() -> None:
                _eff_cat = cat_custom_field.value.strip() if cat_dd.value == "Other" else (cat_dd.value or "")
                _eff_fn  = fn_custom_field.value.strip()  if fn_dd.value  == "Other" else (fn_dd.value  or "")
                new_save_btn.disabled = not (
                    bool(title_field.value.strip())
                    and bool(project_text.value.strip())
                    and bool(_eff_cat)
                    and bool(_eff_fn)
                    and bool(status_dd.value)
                )
                page.update()

            def _on_project_change(e) -> None:
                typed = e.control.value.strip()
                matches = [p for p in _projects if typed.lower() and typed.lower() in p.lower()][:6]
                _proj_suggestions.controls = [
                    ft.Container(
                        content=ft.Text(p, size=13, color=ft.Colors.BLUE_400),
                        padding=ft.padding.symmetric(horizontal=12, vertical=4),
                        border_radius=4,
                        ink=True,
                        on_click=lambda _, p=p: _pick_project(p),
                    )
                    for p in matches
                ]
                _proj_suggestions.visible = bool(matches)
                _check_new_save()

            def _pick_project(name: str) -> None:
                project_text.value = name
                _proj_suggestions.visible = False
                _check_new_save()

            project_text.on_change = _on_project_change
            title_field.on_change  = lambda _e: _check_new_save()

            cat_dd = ft.Dropdown(
                label="Category",
                value="Schematic",
                options=[ft.dropdown.Option(c, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for c in CATEGORIES],
                width=200,
                dense=True,
            )
            cat_custom_field = ft.TextField(label="Specify category", value="", expand=True, visible=False, dense=True)

            def _on_cat_change(_e) -> None:
                cat_custom_field.visible = (cat_dd.value == "Other")
                _check_new_save()

            cat_dd.on_select = _on_cat_change
            cat_custom_field.on_change = lambda _e: _check_new_save()

            fn_dd = ft.Dropdown(
                label="Function",
                value="Connectivity",
                options=[ft.dropdown.Option(f, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for f in FUNCTIONS],
                width=200,
                dense=True,
            )
            fn_custom_field = ft.TextField(label="Specify function", value="", expand=True, visible=False, dense=True)

            def _on_fn_change(_e) -> None:
                fn_custom_field.visible = (fn_dd.value == "Other")
                _check_new_save()

            fn_dd.on_select = _on_fn_change
            fn_custom_field.on_change = lambda _e: _check_new_save()

            status_dd = ft.Dropdown(
                label="Status",
                value="Open",
                options=[ft.dropdown.Option(s, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for s in STATUSES],
                width=160,
                dense=True,
                on_select=lambda _e: _check_new_save(),
            )

            # ── Description ────────────────────────────────────────────────────
            new_desc_field = ft.TextField(
                label="Description",
                value="",
                multiline=True,
                min_lines=3,
                max_lines=5,
                expand=True,
            )

            # ── Related Designs ────────────────────────────────────────────────
            _staged_rel_designs: list = []
            staged_rel_designs_col = ft.Column([], spacing=4)

            def _new_refresh_rel_designs() -> None:
                staged_rel_designs_col.controls = [
                    ft.Row(
                        [
                            ft.Text(f"#{rd['id']}", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_500, width=36),
                            ft.Text(rd["title"], size=13, expand=True, no_wrap=False),
                            ft.IconButton(
                                icon=ft.Icons.LINK_OFF,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove",
                                on_click=lambda _, did=rd["id"]: _new_remove_rel_design(did),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    for rd in _staged_rel_designs
                ]
                page.update()

            def _new_remove_rel_design(did: int) -> None:
                _staged_rel_designs[:] = [d for d in _staged_rel_designs if d["id"] != did]
                _new_refresh_rel_designs()

            new_rel_design_input = ft.TextField(
                hint_text="Design #",
                width=100,
                keyboard_type=ft.KeyboardType.NUMBER,
                input_filter=ft.NumbersOnlyInputFilter(),
                content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                border_radius=6,
                dense=True,
            )
            new_rel_design_error = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

            def _new_add_rel_design(_e) -> None:
                raw = (new_rel_design_input.value or "").strip()
                if not raw:
                    return
                try:
                    did = int(raw)
                except ValueError:
                    new_rel_design_error.value   = "Enter a valid number"
                    new_rel_design_error.visible = True
                    page.update()
                    return
                if any(d["id"] == did for d in _staged_rel_designs):
                    new_rel_design_error.value   = "Already added"
                    new_rel_design_error.visible = True
                    page.update()
                    return
                all_d = fetch_all_designs(output_path)
                target = next((d for d in all_d if d["id"] == did), None)
                if not target:
                    new_rel_design_error.value   = "Design not found"
                    new_rel_design_error.visible = True
                    page.update()
                    return
                _staged_rel_designs.append({"id": did, "title": target["title"]})
                new_rel_design_input.value   = ""
                new_rel_design_error.visible = False
                _new_refresh_rel_designs()

            new_rel_design_add_btn = ft.IconButton(
                icon=ft.Icons.CHECK,
                icon_size=17,
                icon_color=ft.Colors.GREEN_400,
                tooltip="Add design relation",
                on_click=_new_add_rel_design,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_design_cancel_btn = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=17,
                icon_color=ft.Colors.GREY_500,
                tooltip="Cancel",
                on_click=lambda _: (
                    setattr(new_rel_design_input, 'value', ''),
                    setattr(new_rel_design_error, 'visible', False),
                    page.update(),
                ),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_designs_section = ft.Column(
                [
                    ft.Text("Related Designs", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    staged_rel_designs_col,
                    ft.Row(
                        [new_rel_design_input, new_rel_design_add_btn, new_rel_design_cancel_btn, new_rel_design_error],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )

            # ── Related Tasks ──────────────────────────────────────────────────
            _staged_rel_tasks: list = []
            staged_rel_tasks_col = ft.Column([], spacing=4)

            def _new_refresh_rel_tasks() -> None:
                staged_rel_tasks_col.controls = [
                    ft.Row(
                        [
                            ft.Text(f"#{rt['id']}", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_500, width=36),
                            ft.Text(rt["title"], size=13, expand=True, no_wrap=False),
                            ft.IconButton(
                                icon=ft.Icons.LINK_OFF,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove",
                                on_click=lambda _, tid=rt["id"]: _new_remove_rel_task(tid),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    for rt in _staged_rel_tasks
                ]
                page.update()

            def _new_remove_rel_task(tid: int) -> None:
                _staged_rel_tasks[:] = [t for t in _staged_rel_tasks if t["id"] != tid]
                _new_refresh_rel_tasks()

            new_rel_task_input = ft.TextField(
                hint_text="Task #",
                width=90,
                keyboard_type=ft.KeyboardType.NUMBER,
                input_filter=ft.NumbersOnlyInputFilter(),
                content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                border_radius=6,
                dense=True,
            )
            new_rel_task_error = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

            def _new_add_rel_task(_e) -> None:
                raw = (new_rel_task_input.value or "").strip()
                if not raw:
                    return
                try:
                    tid = int(raw)
                except ValueError:
                    new_rel_task_error.value   = "Enter a valid number"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                if any(t["id"] == tid for t in _staged_rel_tasks):
                    new_rel_task_error.value   = "Already added"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                all_t = fetch_all_tasks(output_path)
                target = next((t for t in all_t if t["id"] == tid), None)
                if not target:
                    new_rel_task_error.value   = "Task not found"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                _staged_rel_tasks.append({"id": tid, "title": target["title"]})
                new_rel_task_input.value   = ""
                new_rel_task_error.visible = False
                _new_refresh_rel_tasks()

            new_rel_task_add_btn = ft.IconButton(
                icon=ft.Icons.CHECK,
                icon_size=17,
                icon_color=ft.Colors.GREEN_400,
                tooltip="Add task relation",
                on_click=_new_add_rel_task,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_task_cancel_btn = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=17,
                icon_color=ft.Colors.GREY_500,
                tooltip="Cancel",
                on_click=lambda _: (
                    setattr(new_rel_task_input, 'value', ''),
                    setattr(new_rel_task_error, 'visible', False),
                    page.update(),
                ),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_tasks_section = ft.Column(
                [
                    ft.Text("Related Tasks", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    staged_rel_tasks_col,
                    ft.Row(
                        [new_rel_task_input, new_rel_task_add_btn, new_rel_task_cancel_btn, new_rel_task_error],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )

            # ── Files ──────────────────────────────────────────────────────────
            _staged_files: list = []
            staged_files_col = ft.Column([], spacing=4)

            def _new_refresh_staged_files() -> None:
                staged_files_col.controls = [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ATTACH_FILE, size=14, color=ft.Colors.GREY_500),
                            ft.Text(sf["name"], size=13, expand=True, no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove",
                                on_click=lambda _, n=sf["name"]: _new_remove_file(n),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    for sf in _staged_files
                ]
                page.update()

            def _new_remove_file(name: str) -> None:
                _staged_files[:] = [f for f in _staged_files if f["name"] != name]
                _new_refresh_staged_files()

            async def _new_attach_files(_e) -> None:
                fp = ft.FilePicker()
                files = await fp.pick_files(allow_multiple=True)
                if not files:
                    return
                for f in files:
                    src = Path(f.path)
                    if not any(sf["name"] == src.name for sf in _staged_files):
                        _staged_files.append({"path": src, "name": src.name})
                _new_refresh_staged_files()

            new_attach_btn = ft.ElevatedButton(
                "Attach File",
                icon=ft.Icons.ATTACH_FILE,
                on_click=_new_attach_files,
                style=ft.ButtonStyle(elevation=0),
            )
            new_files_section = ft.Column(
                [
                    ft.Text("Files", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    new_attach_btn,
                    staged_files_col,
                ],
                spacing=4,
            )

            # ── Save / Cancel ──────────────────────────────────────────────────
            def _new_save(_) -> None:
                title   = title_field.value.strip()
                project = project_text.value.strip()
                if not title or not project:
                    return
                design_id = create_design(
                    output_path,
                    title,
                    project,
                    board_field.value.strip(),
                    revision_field.value.strip(),
                    cat_dd.value,
                    cat_custom_field.value.strip() if cat_dd.value == "Other" else "",
                    fn_dd.value,
                    fn_custom_field.value.strip() if fn_dd.value == "Other" else "",
                    status_dd.value,
                )
                # description
                desc = new_desc_field.value.strip()
                if desc:
                    update_design(output_path, design_id, description=desc)
                # related designs
                for rd in _staged_rel_designs:
                    add_related_design(output_path, design_id, rd["id"])
                # related tasks
                for rt in _staged_rel_tasks:
                    add_design_task_link(output_path, design_id, rt["id"])
                # files
                if _staged_files:
                    _att_dir = Path(output_path) / "Memento" / "DesignTracker" / "attachments"
                    _att_dir.mkdir(parents=True, exist_ok=True)
                    for sf in _staged_files:
                        dest_name = f"{design_id}_{sf['name']}"
                        dest = _att_dir / dest_name
                        try:
                            shutil.copy2(str(sf["path"]), str(dest))
                            add_attachment(output_path, design_id, dest_name, sf["name"])
                        except OSError:
                            pass
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
                title=ft.Text("New Design", weight=ft.FontWeight.BOLD),
                content=ft.Column(
                    [
                        # ── Required ──────────────────────────────────────────
                        title_field,
                        board_field,
                        revision_field,
                        ft.Column([project_text, _proj_suggestions], spacing=0, tight=True),
                        ft.Row([cat_dd, cat_custom_field], spacing=8),
                        ft.Row([fn_dd,  fn_custom_field],  spacing=8),
                        status_dd,
                        ft.Divider(height=6),
                        # ── Optional ─────────────────────────────────────────
                        new_desc_field,
                        ft.Divider(height=4),
                        new_rel_designs_section,
                        ft.Divider(height=4),
                        new_rel_tasks_section,
                        ft.Divider(height=4),
                        new_files_section,
                    ],
                    tight=True,
                    spacing=8,
                    width=520,
                    scroll=ft.ScrollMode.AUTO,
                ),
                actions=[new_cancel_btn, new_save_btn],
                actions_alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            )
            page.overlay.append(new_dlg)
            new_dlg.open = True
            page.update()
            return

        # ── EXISTING DESIGN ───────────────────────────────────────────────────

        def _label_row(label: str, value_ctrl) -> ft.Row:
            return ft.Row(
                [
                    ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600, width=68),
                    value_ctrl,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        header_title = ft.TextField(
            value=design["title"],
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        header_board = ft.TextField(
            value=design.get("board") or "",
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        header_revision = ft.TextField(
            value=design.get("revision") or "",
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        _hdr_projects = fetch_distinct_projects(output_path)
        _hdr_suggestions = ft.Column([], spacing=0, visible=False)
        header_project = ft.TextField(
            value=design["project"] or "",
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )

        _orig_cat     = design.get("category") or "Schematic"
        _orig_cat_cus = design.get("category_custom") or ""
        _orig_fn      = design.get("function") or "Connectivity"
        _orig_fn_cus  = design.get("function_custom") or ""

        header_cat = ft.Dropdown(
            value=_orig_cat,
            options=[ft.dropdown.Option(c, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for c in CATEGORIES],
            width=200,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        header_cat_custom = ft.TextField(
            value=_orig_cat_cus,
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            hint_text="Specify…",
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
            visible=(_orig_cat == "Other"),
        )

        header_fn = ft.Dropdown(
            value=_orig_fn,
            options=[ft.dropdown.Option(f, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for f in FUNCTIONS],
            width=200,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        header_fn_custom = ft.TextField(
            value=_orig_fn_cus,
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            hint_text="Specify…",
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
            visible=(_orig_fn == "Other"),
        )

        header_status = ft.Dropdown(
            value=design["status"],
            options=[ft.dropdown.Option(s, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.BLUE_400, ft.ControlState.FOCUSED: ft.Colors.BLUE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for s in STATUSES],
            width=160,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )

        _current_desc   = design.get("description", "") or ""
        _desc_has_content = bool(_current_desc.strip())
        _main_btns: dict = {"delete": None, "save": None}
        _orig = {
            "title":           design["title"],
            "board":           design.get("board") or "",
            "revision":        design.get("revision") or "",
            "project":         design.get("project", "") or "",
            "category":        _orig_cat,
            "category_custom": _orig_cat_cus,
            "function":        _orig_fn,
            "function_custom": _orig_fn_cus,
            "status":          design["status"],
            "description":     _current_desc,
        }
        _edit_state = {"dirty": False, "editing": not _desc_has_content}

        def _update_save_btn() -> None:
            if _main_btns["save"]:
                # Required fields: Name, Project, Category, Function, Status
                _eff_cat = header_cat_custom.value.strip() if header_cat.value == "Other" else (header_cat.value or "")
                _eff_fn  = header_fn_custom.value.strip()  if header_fn.value  == "Other" else (header_fn.value  or "")
                fields_ok = (
                    bool(header_title.value.strip())
                    and bool(header_project.value.strip())
                    and bool(_eff_cat)
                    and bool(_eff_fn)
                    and bool(header_status.value)
                )
                header_changed = (
                    header_title.value.strip() != _orig["title"]
                    or header_board.value.strip() != _orig["board"]
                    or header_revision.value.strip() != _orig["revision"]
                    or header_project.value.strip() != _orig["project"]
                    or header_cat.value != _orig["category"]
                    or header_cat_custom.value.strip() != _orig["category_custom"]
                    or header_fn.value != _orig["function"]
                    or header_fn_custom.value.strip() != _orig["function_custom"]
                    or (header_status.value or "") != _orig["status"]
                )
                can_save = fields_ok and (
                    header_changed or (
                        _edit_state["dirty"] and not _edit_state["editing"]
                    )
                )
                _main_btns["save"].disabled = not can_save
            page.update()

        def _mark_dirty() -> None:
            _edit_state["dirty"] = True
            _update_save_btn()

        def _on_hdr_project_change(e) -> None:
            typed = header_project.value.strip()
            matches = [p for p in _hdr_projects if typed.lower() and typed.lower() in p.lower()][:6]
            _hdr_suggestions.controls = [
                ft.Container(
                    content=ft.Text(p, size=13, color=ft.Colors.BLUE_400),
                    padding=ft.padding.symmetric(horizontal=12, vertical=8),
                    border_radius=4,
                    ink=True,
                    on_click=lambda _, p=p: _pick_hdr_project(p),
                )
                for p in matches
            ]
            _hdr_suggestions.visible = bool(matches)
            _update_save_btn()

        def _pick_hdr_project(name: str) -> None:
            header_project.value = name
            _hdr_suggestions.visible = False
            _update_save_btn()

        header_project.on_change = _on_hdr_project_change

        def _on_hdr_title_change(_e) -> None:
            _update_save_btn()

        def _on_hdr_board_change(_e) -> None:
            _update_save_btn()

        def _on_hdr_revision_change(_e) -> None:
            _update_save_btn()

        def _on_hdr_status_change(_e) -> None:
            _update_save_btn()

        def _on_hdr_cat_change(_e) -> None:
            header_cat_custom.visible = (header_cat.value == "Other")
            _update_save_btn()

        def _on_hdr_cat_custom_change(_e) -> None:
            _update_save_btn()

        def _on_hdr_fn_change(_e) -> None:
            header_fn_custom.visible = (header_fn.value == "Other")
            _update_save_btn()

        def _on_hdr_fn_custom_change(_e) -> None:
            _update_save_btn()

        header_title.on_change        = _on_hdr_title_change
        header_board.on_change        = _on_hdr_board_change
        header_revision.on_change     = _on_hdr_revision_change
        header_status.on_select       = _on_hdr_status_change
        header_cat.on_select          = _on_hdr_cat_change
        header_cat_custom.on_change   = _on_hdr_cat_custom_change
        header_fn.on_select           = _on_hdr_fn_change
        header_fn_custom.on_change    = _on_hdr_fn_custom_change

        header_col = ft.Column(
            [
                _label_row("Name:",     header_title),
                _label_row("Board:",    header_board),
                _label_row("Revision:", header_revision),
                _label_row("Project:",  ft.Column([header_project, _hdr_suggestions], spacing=0)),
                _label_row("Category:", ft.Row([header_cat, header_cat_custom], spacing=8)),
                _label_row("Function:", ft.Row([header_fn,  header_fn_custom],  spacing=8)),
                _label_row("Status:",   header_status),
            ],
            spacing=6,
        )

        # ── Description ───────────────────────────────────────────────────────

        def _build_rich_spans(raw: str) -> list:
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
                    spans.append(ft.TextSpan(text='    ', style=ft.TextStyle(color=ft.Colors.GREY_500)))
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
            hint_text="Design description…",
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            expand=True,
            read_only=False,
            visible=not _desc_has_content,
            on_selection_change=_on_selection_change,
            on_change=lambda _e: _desc_field_on_change(),
        )

        def _desc_field_on_change() -> None:
            _edit_state["editing"] = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = True
            if _main_btns["save"]:
                _main_btns["save"].disabled = True
            page.update()

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
        desc_cancel_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            tooltip="Cancel editing",
            visible=False,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
        )

        def _on_desc_save(_e) -> None:
            new_desc = desc_field.value or ""
            update_design(output_path, design["id"], description=new_desc)
            has_content = bool(new_desc.strip())
            desc_display.spans = _build_rich_spans(new_desc)
            desc_display.visible = has_content
            desc_field.visible   = not has_content
            desc_edit_btn.visible    = has_content
            desc_save_btn.visible    = not has_content
            desc_cancel_btn.visible  = False
            desc_toolbar.visible     = not has_content
            _edit_state["editing"]   = False
            if new_desc != _orig["description"]:
                _edit_state["dirty"] = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()

        desc_save_btn.on_click = _on_desc_save

        def _on_desc_cancel(_e) -> None:
            desc_field.value = _current_desc
            has_content = bool(_current_desc.strip())
            desc_display.visible    = has_content
            desc_field.visible      = not has_content
            desc_edit_btn.visible   = has_content
            desc_save_btn.visible   = not has_content
            desc_cancel_btn.visible = False
            desc_toolbar.visible    = not has_content
            _edit_state["editing"]  = False
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()

        desc_cancel_btn.on_click = _on_desc_cancel

        async def _on_desc_edit(_e) -> None:
            desc_display.visible    = False
            desc_field.visible      = True
            desc_edit_btn.visible   = False
            desc_save_btn.visible   = True
            desc_cancel_btn.visible = True
            desc_toolbar.visible    = True
            _edit_state["editing"]  = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = True
            if _main_btns["save"]:
                _main_btns["save"].disabled = True
            page.update()
            await desc_field.focus()

        desc_edit_btn.on_click = _on_desc_edit

        async def _insert_at_cursor(text: str) -> None:
            cur = desc_field.value or ""
            pos = min(_cursor["pos"], len(cur))
            new_val = cur[:pos] + text + cur[pos:]
            new_pos = pos + len(text)
            desc_field.value = new_val
            desc_field.selection = ft.TextSelection(base_offset=new_pos, extent_offset=new_pos)
            _cursor["pos"] = new_pos
            page.update()

        async def _apply_format(prefix: str, suffix: str, placeholder: str) -> None:
            await _insert_at_cursor(f"{prefix}{placeholder}{suffix}")

        async def _apply_line_prefix(prefix: str) -> None:
            cur = desc_field.value or ""
            pos = min(_cursor["pos"], len(cur))
            line_start = cur.rfind('\n', 0, pos) + 1
            before = cur[:line_start]
            after  = cur[line_start:]
            new_val = before + prefix + after
            new_pos = line_start + len(prefix)
            desc_field.value = new_val
            desc_field.selection = ft.TextSelection(base_offset=new_pos, extent_offset=new_pos)
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
            ("#D32F2F", "Red"), ("#E65100", "Orange"), ("#F57F17", "Yellow"),
            ("#2E7D32", "Green"), ("#1565C0", "Blue"), ("#6A1B9A", "Purple"),
            ("#AD1457", "Pink"), ("#212121", "Black"), ("#757575", "Gray"),
        ]

        async def _on_bold(_e):      await _apply_format("**",  "**",   "bold text")
        async def _on_italic(_e):    await _apply_format("*",   "*",    "italic text")
        async def _on_underline(_e): await _apply_format("<u>", "</u>", "underlined text")
        async def _on_bullet(_e):    await _apply_line_prefix("• ")
        async def _on_quote(_e):     await _apply_line_prefix("    ")

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
                        [ft.Container(width=14, height=14, bgcolor=hx, border_radius=2),
                         ft.Text(nm, size=12)],
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
                    _tb_btn(ft.Icons.FORMAT_BOLD,          "Bold",          _on_bold),
                    _tb_btn(ft.Icons.FORMAT_ITALIC,        "Italic",        _on_italic),
                    _tb_btn(ft.Icons.FORMAT_UNDERLINED,    "Underline",     _on_underline),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _tb_btn(ft.Icons.FORMAT_LIST_BULLETED, "Bullet list",   _on_bullet),
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
                        desc_edit_btn, desc_save_btn, desc_cancel_btn,
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
                    bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.YELLOW),
                    expand=True,
                ),
            ],
            spacing=4,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        # ── Related Designs ───────────────────────────────────────────────────
        _related_editing = {"active": False}
        related_list_col = ft.Column([], spacing=4)

        def _refresh_related() -> None:
            rels = fetch_related_designs(output_path, design["id"])
            rows = []
            for r in rels:
                rid    = r["id"]
                rtitle = r["title"]
                rows.append(
                    ft.Row(
                        [
                            ft.Text(f"#{rid}", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_500, width=36),
                            ft.TextButton(
                                content=ft.Text(
                                    rtitle,
                                    size=13,
                                    no_wrap=False,
                                    text_align=ft.TextAlign.LEFT,
                                ),
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                    text_style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                                ),
                                on_click=lambda _, rid=rid: _navigate_to_related(rid),
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.LINK_OFF,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove relation",
                                on_click=lambda _, rid=rid: _remove_related(rid),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                )
            related_list_col.controls = rows
            page.update()

        def _navigate_to_related(rid: int) -> None:
            all_d = fetch_all_designs(output_path)
            target = next((d for d in all_d if d["id"] == rid), None)
            if target:
                open_design_dialog(target)

        def _remove_related(rid: int) -> None:
            remove_related_design(output_path, design["id"], rid)
            _edit_state["dirty"]   = True
            _edit_state["editing"] = False
            _update_save_btn()
            _refresh_related()

        related_input = ft.TextField(
            hint_text="Design #",
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=6,
        )
        related_error = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

        rel_save_btn = ft.IconButton(
            icon=ft.Icons.CHECK,
            icon_size=17,
            tooltip="Add relation",
            icon_color=ft.Colors.GREEN_400,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        rel_cancel_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=17,
            tooltip="Cancel",
            icon_color=ft.Colors.GREY_500,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _set_related_editing(active: bool) -> None:
            _related_editing["active"] = active
            _edit_state["editing"]     = active
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = active
            if _main_btns["save"]:
                _main_btns["save"].disabled = active or not _edit_state["dirty"]

        def _on_rel_input_change(_e) -> None:
            related_error.visible = False
            has_text = bool((related_input.value or "").strip())
            _set_related_editing(has_text)
            _update_save_btn()
            page.update()

        related_input.on_change = _on_rel_input_change

        def _on_rel_save(_e) -> None:
            raw = (related_input.value or "").strip()
            if not raw:
                return
            try:
                rid = int(raw)
            except ValueError:
                related_error.value   = "Enter a valid number"
                related_error.visible = True
                page.update()
                return
            if rid == design["id"]:
                related_error.value   = "Cannot relate to self"
                related_error.visible = True
                page.update()
                return
            existing = fetch_related_designs(output_path, design["id"])
            if any(r["id"] == rid for r in existing):
                related_error.value   = "Already linked"
                related_error.visible = True
                page.update()
                return
            ok = add_related_design(output_path, design["id"], rid)
            if not ok:
                related_error.value   = "Design not found"
                related_error.visible = True
                page.update()
                return
            related_input.value   = ""
            related_error.visible = False
            _edit_state["dirty"]  = True
            _set_related_editing(False)
            _update_save_btn()
            _refresh_related()

        def _on_rel_cancel(_e) -> None:
            related_input.value   = ""
            related_error.visible = False
            _set_related_editing(False)
            _update_save_btn()
            page.update()

        rel_save_btn.on_click   = _on_rel_save
        rel_cancel_btn.on_click = _on_rel_cancel

        related_section = ft.Column(
            [
                ft.Text("Related Designs", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                related_list_col,
                ft.Row([related_input, rel_save_btn, rel_cancel_btn, related_error],
                       spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_related()

        # ── Related Tasks ─────────────────────────────────────────────────────
        _rel_tasks_editing = {"active": False}
        rel_tasks_list_col = ft.Column([], spacing=4)

        def _refresh_related_tasks() -> None:
            links    = fetch_design_task_links(output_path, design["id"])
            all_t    = fetch_all_tasks(output_path)
            task_map = {t["id"]: t for t in all_t}
            rows_t   = []
            for lnk in links:
                tid    = lnk["task_id"]
                ttitle = task_map[tid]["title"] if tid in task_map else f"(task #{tid} not found)"
                rows_t.append(
                    ft.Row(
                        [
                            ft.Text(f"#{tid}", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_500, width=36),
                            ft.Text(ttitle, size=13, expand=True, no_wrap=False),
                            ft.IconButton(
                                icon=ft.Icons.LINK_OFF,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove relation",
                                on_click=lambda _, tid=tid: _remove_related_task(tid),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                )
            rel_tasks_list_col.controls = rows_t
            page.update()

        def _remove_related_task(tid: int) -> None:
            remove_design_task_link(output_path, design["id"], tid)
            _edit_state["dirty"]   = True
            _edit_state["editing"] = False
            _update_save_btn()
            _refresh_related_tasks()

        rel_task_input = ft.TextField(
            hint_text="Task #",
            width=90,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=6,
        )
        rel_task_error = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

        rel_task_save_btn = ft.IconButton(
            icon=ft.Icons.CHECK,
            icon_size=17,
            tooltip="Add task relation",
            icon_color=ft.Colors.GREEN_400,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        rel_task_cancel_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=17,
            tooltip="Cancel",
            icon_color=ft.Colors.GREY_500,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _set_rel_tasks_editing(active: bool) -> None:
            _rel_tasks_editing["active"] = active
            _edit_state["editing"]       = active
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = active
            if _main_btns["save"]:
                _main_btns["save"].disabled = active or not _edit_state["dirty"]

        def _on_rel_task_input_change(_e) -> None:
            rel_task_error.visible = False
            has_text = bool((rel_task_input.value or "").strip())
            _set_rel_tasks_editing(has_text)
            _update_save_btn()
            page.update()

        rel_task_input.on_change = _on_rel_task_input_change

        def _on_rel_task_save(_e) -> None:
            raw = (rel_task_input.value or "").strip()
            if not raw:
                return
            try:
                tid = int(raw)
            except ValueError:
                rel_task_error.value   = "Enter a valid number"
                rel_task_error.visible = True
                page.update()
                return
            all_t  = fetch_all_tasks(output_path)
            exists = any(t["id"] == tid for t in all_t)
            if not exists:
                rel_task_error.value   = "Task not found"
                rel_task_error.visible = True
                page.update()
                return
            ok = add_design_task_link(output_path, design["id"], tid)
            if not ok:
                rel_task_error.value   = "Already linked"
                rel_task_error.visible = True
                page.update()
                return
            rel_task_input.value   = ""
            rel_task_error.visible = False
            _edit_state["dirty"]   = True
            _set_rel_tasks_editing(False)
            _update_save_btn()
            _refresh_related_tasks()

        def _on_rel_task_cancel(_e) -> None:
            rel_task_input.value   = ""
            rel_task_error.visible = False
            _set_rel_tasks_editing(False)
            _update_save_btn()
            page.update()

        rel_task_save_btn.on_click   = _on_rel_task_save
        rel_task_cancel_btn.on_click = _on_rel_task_cancel

        related_tasks_section = ft.Column(
            [
                ft.Text("Related Tasks", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                rel_tasks_list_col,
                ft.Row([rel_task_input, rel_task_save_btn, rel_task_cancel_btn, rel_task_error],
                       spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_related_tasks()

        # ── Attachments ───────────────────────────────────────────────────────
        attach_dir = Path(output_path) / "Memento" / "DesignTracker" / "attachments"
        attach_list_col = ft.Column([], spacing=4)

        def _open_file(path) -> None:
            try:
                os.startfile(str(path))
            except Exception:
                pass

        def _refresh_attach() -> None:
            atts = fetch_design_attachments(output_path, design["id"])
            attach_list_col.controls = [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.ATTACH_FILE, size=14, color=ft.Colors.GREY_500),
                        ft.TextButton(
                            a["orig_name"],
                            style=ft.ButtonStyle(
                                padding=ft.padding.all(0),
                                overlay_color=ft.Colors.TRANSPARENT,
                                text_style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                            ),
                            on_click=lambda _e, fn=a["filename"]: _open_file(attach_dir / fn),
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
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
                dest_name = f"{design['id']}_{src.name}"
                dest = attach_dir / dest_name
                shutil.copy2(str(src), str(dest))
                add_attachment(output_path, design["id"], dest_name, src.name)
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

        # ── History ───────────────────────────────────────────────────────────
        history_attach_dir = attach_dir
        history_entries_col = ft.Column([], spacing=8)

        def _rel_date(iso: str) -> str:
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
            h_atts = fetch_history_attachments(output_path, entry["id"])
            h_att_col = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.ATTACH_FILE, size=13, color=ft.Colors.GREY_500),
                            ft.TextButton(
                                a["orig_name"],
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                    text_style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                                ),
                                on_click=lambda _e, fn=a["filename"]: _open_file(history_attach_dir / fn),
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

            edit_body_btn   = ft.IconButton(icon=ft.Icons.EDIT_NOTE,      icon_size=15, tooltip="Edit",   style=ft.ButtonStyle(padding=ft.padding.all(2)))
            save_body_btn   = ft.IconButton(icon=ft.Icons.SAVE_OUTLINED,  icon_size=15, tooltip="Save",   visible=False, style=ft.ButtonStyle(padding=ft.padding.all(2)))
            cancel_body_btn = ft.IconButton(icon=ft.Icons.CLOSE,          icon_size=15, tooltip="Cancel", visible=False, style=ft.ButtonStyle(padding=ft.padding.all(2)))
            del_entry_btn   = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=15, icon_color=ft.Colors.RED_400, tooltip="Delete entry", style=ft.ButtonStyle(padding=ft.padding.all(2)))

            def _on_edit_body(_e, bt=body_txt, eb=edit_body_btn, sb=save_body_btn, cb=cancel_body_btn):
                bt.read_only = False
                eb.visible = False
                sb.visible = True
                cb.visible = True
                _edit_state["editing"] = True
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = True
                if _main_btns["save"]:
                    _main_btns["save"].disabled = True
                page.update()

            def _on_save_body(_e, eid=entry["id"], bt=body_txt,
                              eb=edit_body_btn, sb=save_body_btn, cb=cancel_body_btn):
                update_history_entry(output_path, eid, bt.value or "")
                bt.read_only = True
                eb.visible = True
                sb.visible = False
                cb.visible = False
                _edit_state["editing"] = False
                _edit_state["dirty"]   = True
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = False
                _update_save_btn()

            def _on_cancel_body(_e, orig=entry["body"], bt=body_txt,
                                eb=edit_body_btn, sb=save_body_btn, cb=cancel_body_btn):
                bt.value = orig
                bt.read_only = True
                eb.visible = True
                sb.visible = False
                cb.visible = False
                _edit_state["editing"] = False
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = False
                _update_save_btn()

            def _on_del_entry(_e, eid=entry["id"]):
                delete_history_entry(output_path, eid)
                _refresh_history()

            edit_body_btn.on_click   = _on_edit_body
            save_body_btn.on_click   = _on_save_body
            cancel_body_btn.on_click = _on_cancel_body
            del_entry_btn.on_click   = _on_del_entry

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
                                ft.Text(_rel_date(entry["created_at"]), size=11,
                                        color=ft.Colors.GREY_500, expand=True),
                                ft.Text(f"#{index}", size=11, color=ft.Colors.GREY_500,
                                        weight=ft.FontWeight.W_600),
                                edit_body_btn, save_body_btn, cancel_body_btn, del_entry_btn,
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
                bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
                padding=ft.padding.all(8),
            )

        def _refresh_history() -> None:
            entries = fetch_history(output_path, design["id"])
            history_entries_col.controls = [
                _build_history_entry_widget(e, i + 1) for i, e in enumerate(entries)
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
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE),
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )
        save_entry_btn = ft.FilledButton(
            "Save update",
            icon=ft.Icons.SAVE_OUTLINED,
            disabled=True,
            style=ft.ButtonStyle(
                bgcolor={
                    ft.ControlState.DEFAULT:  ft.Colors.BLUE_600,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.35, ft.Colors.BLUE_600),
                },
                color={
                    ft.ControlState.DEFAULT:  ft.Colors.WHITE,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.4, ft.Colors.WHITE),
                },
            ),
        )

        # ── Tag input row ──────────────────────────────────────────────────────
        _staged_tags: list[str] = []
        _tags_chips_row = ft.Row([], spacing=6, wrap=True)

        def _refresh_tag_chips() -> None:
            _tags_chips_row.controls = [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(f"#{t}", size=12, color=ft.Colors.BLUE_300,
                                    weight=ft.FontWeight.W_500,
                                    no_wrap=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=12,
                                icon_color=ft.Colors.GREY_500,
                                tooltip="Remove tag",
                                on_click=lambda _, tag=t: _remove_tag(tag),
                                style=ft.ButtonStyle(padding=ft.padding.all(0)),
                            ),
                        ],
                        spacing=2,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.BLUE_400),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.BLUE_400)),
                    border_radius=12,
                    padding=ft.padding.only(left=8, right=2, top=2, bottom=2),
                    # no fixed width — let the container shrink-wrap to content
                )
                for t in _staged_tags
            ]
            page.update()

        def _remove_tag(tag: str) -> None:
            if tag in _staged_tags:
                _staged_tags.remove(tag)
            _refresh_tag_chips()

        def _on_tag_input_change(e) -> None:
            if " " in (e.control.value or ""):
                e.control.value = (e.control.value or "").replace(" ", "")
                e.control.update()

        tag_input = ft.TextField(
            hint_text="#tag",
            width=120,
            dense=True,
            border_radius=6,
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            disabled=True,
            on_change=_on_tag_input_change,
        )
        add_tag_btn = ft.IconButton(
            icon=ft.Icons.ADD,
            icon_size=16,
            tooltip="Add tag",
            disabled=True,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _do_add_tag(_e=None) -> None:
            raw = (tag_input.value or "").strip().lstrip("#")
            if not raw:
                return
            # Sanitise: no spaces, lowercase
            tag = raw.split()[0].lower()
            if tag and tag not in _staged_tags:
                _staged_tags.append(tag)
                _refresh_tag_chips()
            tag_input.value = ""
            page.update()

        def _on_tag_submit(e) -> None:
            _do_add_tag()

        tag_input.on_submit = _on_tag_submit
        add_tag_btn.on_click = _do_add_tag

        tags_section = ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.TAG, size=15, color=ft.Colors.GREY_500),
                        tag_input,
                        add_tag_btn,
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                _tags_chips_row,
            ],
            spacing=4,
        )

        def _on_new_entry_change(_e) -> None:
            has_text = bool((new_entry_field.value or "").strip())
            save_entry_btn.disabled = not has_text
            tag_input.disabled  = not has_text
            add_tag_btn.disabled = not has_text
            if not has_text and _staged_tags:
                _staged_tags.clear()
                _refresh_tag_chips()
            _edit_state["editing"] = has_text
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = has_text
            _update_save_btn()

        new_entry_field.on_change = _on_new_entry_change

        def _add_history_entry_cb(_e) -> None:
            text = new_entry_field.value or ""
            if not text.strip():
                return
            # Append tags if any
            if _staged_tags:
                text = text.rstrip() + "\n" + " ".join(f"#{t}" for t in _staged_tags)
            add_history_entry(output_path, design["id"], text)
            new_entry_field.value  = ""
            _staged_tags.clear()
            _refresh_tag_chips()
            save_entry_btn.disabled = True
            tag_input.disabled     = True
            add_tag_btn.disabled   = True
            _edit_state["editing"] = False
            _edit_state["dirty"]   = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()
            _refresh_history()

        save_entry_btn.on_click = _add_history_entry_cb

        history_section = ft.Column(
            [
                ft.Text("History", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                history_entries_col,
                new_entry_field,
                tags_section,
                ft.Row([save_entry_btn], alignment=ft.MainAxisAlignment.END),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_history()

        # ── Actions ───────────────────────────────────────────────────────────
        _dlg_ref: dict = {"dlg": None}

        def _go_back() -> None:
            if on_close_design:
                on_close_design()
            elif _dlg_ref["dlg"]:
                _dlg_ref["dlg"].open = False
                _clear_selection()
                _refresh()

        def _save(_) -> None:
            update_design(
                output_path, design["id"],
                title=header_title.value.strip() or design["title"],
                board=header_board.value.strip(),
                revision=header_revision.value.strip(),
                project=header_project.value.strip(),
                category=header_cat.value,
                category_custom=header_cat_custom.value.strip() if header_cat.value == "Other" else "",
                function=header_fn.value,
                function_custom=header_fn_custom.value.strip() if header_fn.value == "Other" else "",
                status=header_status.value,
                description=desc_field.value or "",
            )
            _go_back()

        def _delete(_) -> None:
            for att in fetch_design_attachments(output_path, design["id"]):
                try:
                    (attach_dir / att["filename"]).unlink(missing_ok=True)
                except OSError:
                    pass
            for entry in fetch_history(output_path, design["id"]):
                for hatt in fetch_history_attachments(output_path, entry["id"]):
                    try:
                        (history_attach_dir / hatt["filename"]).unlink(missing_ok=True)
                    except OSError:
                        pass
            delete_design(output_path, design["id"])
            _go_back()

        def _cancel(_) -> None:
            _go_back()

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
            disabled=True,
        )
        _main_btns["delete"] = delete_btn
        _main_btns["save"]   = save_btn

        if on_open_design:
            detail_view = ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    header_col,
                                    ft.Divider(height=4),
                                    desc_section,
                                    ft.Divider(height=4),
                                    related_section,
                                    ft.Divider(height=4),
                                    related_tasks_section,
                                    ft.Divider(height=4),
                                    files_section,
                                    ft.Divider(height=4),
                                    history_section,
                                ],
                                spacing=6,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                            ),
                            expand=True,
                            padding=ft.padding.symmetric(horizontal=32, vertical=16),
                        ),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    expand=True,
                ),
                expand=True,
            )
            _refresh_attach()
            _action_bar = ft.Container(
                content=ft.Row(
                    [delete_btn, cancel_btn, save_btn],
                    alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                ),
                padding=ft.padding.symmetric(horizontal=32, vertical=10),
                bgcolor=ft.Colors.SURFACE_CONTAINER,
            )
            detail_outer = ft.Column(
                [detail_view, _action_bar],
                spacing=0,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            on_open_design(detail_outer, f"Design  #{design['id']}")
        else:
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Design  #{design['id']}", weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            header_col,
                            ft.Divider(height=4),
                            desc_section,
                            ft.Divider(height=4),
                            related_section,
                            ft.Divider(height=4),
                            related_tasks_section,
                            ft.Divider(height=4),
                            files_section,
                            ft.Divider(height=4),
                            history_section,
                        ],
                        spacing=6,
                        expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                    width=560,
                    height=700,
                    expand=True,
                ),
                actions=[delete_btn, cancel_btn, save_btn],
                actions_alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            )
            _dlg_ref["dlg"] = dlg
            page.overlay.append(dlg)
            dlg.open = True
            _refresh_attach()
            page.update()

    # ── Table ─────────────────────────────────────────────────────────────────

    _COL_HEADER = ft.FontWeight.BOLD

    data_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#",         size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Text("Name",      size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Board",    size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Revision", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Project",  size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Category", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Function", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Opened",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Modified", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Closed",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Status",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
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

    def _build_rows(designs: list[dict]) -> list[ft.DataRow]:
        def _c(ctrl): return ft.Container(content=ctrl, alignment=ft.alignment.Alignment(0, 0))
        sel_id = _sel["design"]["id"] if _sel["design"] else None
        rows = []
        for d in designs:
            design = dict(d)
            is_sel = design["id"] == sel_id
            rows.append(
                ft.DataRow(
                    selected=is_sel,
                    color=ft.Colors.with_opacity(0.12, ft.Colors.BLUE) if is_sel else None,
                    on_select_change=lambda e, d=design: _select_design(e, d),
                    cells=[
                        ft.DataCell(_c(ft.Text(str(design["id"]), size=13))),
                        ft.DataCell(
                            _c(ft.TextButton(
                                design["title"],
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                ),
                                on_click=lambda _, d=design: open_design_dialog(d),
                            ))
                        ),
                        ft.DataCell(_c(ft.Text(_fmt(design.get("board") or ""),      size=13))),
                        ft.DataCell(_c(ft.Text(_fmt(design.get("revision") or ""),   size=13))),
                        ft.DataCell(_c(ft.Text(_fmt(design["project"]),           size=13))),
                        ft.DataCell(_c(ft.Text(_display_category(design),         size=13))),
                        ft.DataCell(_c(ft.Text(_display_function(design),         size=13))),
                        ft.DataCell(_c(ft.Text(_fmt(design["opened_at"]),         size=12, color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(ft.Text(_fmt(design["modified_at"]),       size=12, color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(ft.Text(_fmt(design["closed_at"]),         size=12, color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(_status_chip(design["status"]))),
                    ]
                )
            )
        return rows

    empty_state = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.SCHEMA_OUTLINED, size=64, color=ft.Colors.GREY_400),
                ft.Text(
                    "No designs yet — use the  +  button in the toolbar to create one.",
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

    _filter_banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.FILTER_LIST, size=16, color=ft.Colors.WHITE),
                ft.Text("Filter active", size=13, color=ft.Colors.WHITE,
                        weight=ft.FontWeight.W_500),
                ft.Container(expand=True),
                ft.TextButton(
                    "Clear",
                    style=ft.ButtonStyle(
                        color={
                            ft.ControlState.DEFAULT:  ft.Colors.WHITE,
                            ft.ControlState.HOVERED:  ft.Colors.WHITE,
                            ft.ControlState.PRESSED:  ft.Colors.WHITE,
                        },
                        overlay_color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                    ),
                    on_click=lambda _: _clear_filters(),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.ORANGE_700,
        padding=ft.padding.symmetric(horizontal=16, vertical=6),
        visible=False,
    )

    _search_field = ft.TextField(
        hint_text="Search…",
        expand=True,
        dense=True,
        border_radius=6,
        content_padding=ft.padding.symmetric(horizontal=8, vertical=4),
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
        color=ft.Colors.WHITE,
        hint_style=ft.TextStyle(color=ft.Colors.with_opacity(0.6, ft.Colors.WHITE)),
        cursor_color=ft.Colors.WHITE,
        border_color=ft.Colors.with_opacity(0.3, ft.Colors.WHITE),
        focused_border_color=ft.Colors.WHITE,
    )

    def _on_search_change(e) -> None:
        _search_query["q"] = (e.control.value or "").strip().lower()
        _update_search_btn_color()
        _refresh()

    _search_field.on_change = _on_search_change

    def _close_search(_=None) -> None:
        _search_query["q"] = ""
        _search_field.value = ""
        _search_banner.visible = False
        _update_search_btn_color()
        _refresh()

    _search_banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.SEARCH, size=16, color=ft.Colors.WHITE),
                _search_field,
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=16,
                    icon_color=ft.Colors.WHITE,
                    tooltip="Close search",
                    on_click=_close_search,
                    style=ft.ButtonStyle(padding=ft.padding.all(4)),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.BLUE_700,
        padding=ft.padding.symmetric(horizontal=16, vertical=6),
        visible=False,
    )

    def _clear_filters() -> None:
        for k in _active_filters:
            _active_filters[k] = [] if k == "tags" else ""
        _update_filter_btn_color()
        _refresh()

    def _refresh() -> None:
        all_designs = _apply_sort(fetch_all_designs(output_path))
        designs     = _apply_filter(all_designs)
        designs     = _apply_search(designs)
        _filter_banner.visible = any(v for v in _active_filters.values())
        if designs:
            data_table.rows = _build_rows(designs)
            list_area.content = ft.ListView(
                [
                    ft.Container(
                        content=data_table,
                        padding=ft.padding.symmetric(horizontal=24, vertical=12),
                    )
                ],
                expand=True,
            )
            if chart_btn:
                chart_btn.disabled   = False
                chart_btn.icon_color = ft.Colors.PURPLE_400
        else:
            list_area.content = empty_state
            if chart_btn:
                chart_btn.disabled   = True
                chart_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400)
        page.update()

    # ── Chart dialog ──────────────────────────────────────────────────────────

    def _open_chart_dialog(_=None) -> None:  # noqa: C901
        import math
        import flet.canvas as cv

        _STATUS_COLORS = {
            "Open":        "#1E88E5",
            "In Progress": "#FB8C00",
            "On Hold":     "#8E24AA",
            "Closed":      "#43A047",
        }

        _SIZE   = 240
        _CX     = _SIZE / 2
        _CY     = _SIZE / 2
        _R      = _SIZE / 2 - 6
        _HOLE_R = _R * 0.32

        _filter        = {"period": "day", "project": ""}
        all_designs_snap = fetch_all_designs(output_path)
        pie_canvas     = cv.Canvas([], width=_SIZE, height=_SIZE)
        pie_area       = ft.Container(content=pie_canvas, width=_SIZE, height=_SIZE)
        legend_col     = ft.Column([], spacing=10, tight=True)

        def _parse_dt(val) -> datetime:
            try:
                return datetime.fromisoformat(val)
            except (TypeError, ValueError):
                return datetime.min

        def _compute(period: str, project: str):
            days_map = {"day": 1, "week": 7, "month": 30, "year": 365}
            cutoff   = datetime.now() - timedelta(days=days_map[period])
            filtered = [
                d for d in all_designs_snap
                if (not project or d["project"] == project)
                and _parse_dt(d["opened_at"]) >= cutoff
            ]
            counts = {s: 0 for s in STATUSES}
            for d in filtered:
                if d["status"] in counts:
                    counts[d["status"]] += 1
            return counts, sum(counts.values())

        def _make_slice(cx, cy, r, hole_r, start_rad, sweep_rad, color):
            import math as _math
            end_rad   = start_rad + sweep_rad
            large_arc = sweep_rad > _math.pi
            ox1 = cx + r * _math.cos(start_rad)
            oy1 = cy + r * _math.sin(start_rad)
            ox2 = cx + r * _math.cos(end_rad)
            oy2 = cy + r * _math.sin(end_rad)
            ix1 = cx + hole_r * _math.cos(end_rad)
            iy1 = cy + hole_r * _math.sin(end_rad)
            ix2 = cx + hole_r * _math.cos(start_rad)
            iy2 = cy + hole_r * _math.sin(start_rad)
            return cv.Path(
                elements=[
                    cv.Path.MoveTo(ox1, oy1),
                    cv.Path.ArcTo(ox2, oy2, radius=r, large_arc=large_arc, clockwise=True),
                    cv.Path.LineTo(ix1, iy1),
                    cv.Path.ArcTo(ix2, iy2, radius=hole_r, large_arc=large_arc, clockwise=False),
                    cv.Path.Close(),
                ],
                paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL),
            )

        def _update() -> None:
            import math as _math
            counts, total = _compute(_filter["period"], _filter["project"])
            if total == 0:
                pie_canvas.shapes = [
                    cv.Circle(_CX, _CY, _R,
                               paint=ft.Paint(color=ft.Colors.OUTLINE_VARIANT,
                                              style=ft.PaintingStyle.FILL)),
                ]
                legend_col.controls = [
                    ft.Text("No data for the selected filters.", size=13,
                            color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER)
                ]
            else:
                shapes       = []
                legend_items = []
                angle = -_math.pi / 2
                non_zero = [(s, counts[s]) for s in STATUSES if counts[s] > 0]
                for status, n in non_zero:
                    pct   = n / total * 100
                    color = _STATUS_COLORS[status]
                    sweep = 2 * _math.pi * (n / total)
                    if len(non_zero) == 1:
                        shapes.append(cv.Circle(_CX, _CY, _R, paint=ft.Paint(color=color, style=ft.PaintingStyle.FILL)))
                        shapes.append(cv.Circle(_CX, _CY, _HOLE_R, paint=ft.Paint(color=ft.Colors.SURFACE, style=ft.PaintingStyle.FILL)))
                    else:
                        shapes.append(_make_slice(_CX, _CY, _R, _HOLE_R, angle, sweep, color))
                    if pct >= 7:
                        mid = angle + sweep / 2 if len(non_zero) > 1 else -_math.pi / 2
                        lr  = (_R + _HOLE_R) / 2
                        lx  = _CX + lr * _math.cos(mid)
                        ly  = _CY + lr * _math.sin(mid)
                        shapes.append(cv.Text(x=lx, y=ly, value=f"{pct:.1f}%",
                                              alignment=ft.Alignment(0, 0),
                                              style=ft.TextStyle(size=10, color="#FFFFFF",
                                                                 weight=ft.FontWeight.BOLD)))
                    angle += sweep
                    legend_items.append(
                        ft.Row(
                            [
                                ft.Container(width=14, height=14, bgcolor=color, border_radius=3),
                                ft.Text(f"{status}  ·  {n}  ({pct:.1f}%)", size=13),
                            ],
                            spacing=8, tight=True,
                        )
                    )
                pie_canvas.shapes = shapes
                legend_col.controls = legend_items
            page.update()

        def _on_period_change(e) -> None:
            _filter["period"] = e.data
            _update()

        def _on_project_change(e) -> None:
            _filter["project"] = e.data or ""
            _update()

        period_dd = ft.Dropdown(
            label="Period",
            value="day",
            width=165,
            options=[
                ft.DropdownOption(key="day",   text="Last Day"),
                ft.DropdownOption(key="week",  text="Last Week"),
                ft.DropdownOption(key="month", text="Last Month"),
                ft.DropdownOption(key="year",  text="Last Year"),
            ],
            on_select=_on_period_change,
        )
        project_dd = ft.Dropdown(
            label="Project",
            value="",
            width=185,
            options=(
                [ft.DropdownOption(key="", text="All Projects")]
                + [ft.DropdownOption(key=p, text=p) for p in fetch_distinct_projects(output_path)]
            ),
            on_select=_on_project_change,
        )

        def _close_chart(_) -> None:
            chart_dlg.open = False
            page.update()

        chart_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.PIE_CHART, color=ft.Colors.PURPLE_400),
                 ft.Text("Status Distribution", weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Row([period_dd, project_dd], spacing=12),
                    ft.Divider(height=6),
                    ft.Row(
                        [
                            pie_area,
                            ft.Container(content=legend_col, expand=True,
                                         padding=ft.padding.only(left=20),
                                         alignment=ft.Alignment(-1, 0)),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                tight=True,
                spacing=8,
                width=540,
            ),
            actions=[ft.TextButton("Close", on_click=_close_chart)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(chart_dlg)
        chart_dlg.open = True
        _update()

    _refresh()

    # ── Wire AppBar button handlers ───────────────────────────────────────────

    def _open_confirm(_) -> None:
        _confirm_dlg.open = True
        page.update()

    def _confirm_delete(_) -> None:
        _confirm_dlg.open = False
        delete_design(output_path, _sel["design"]["id"])
        _clear_selection()
        _refresh()

    def _cancel_confirm(_) -> None:
        _confirm_dlg.open = False
        page.update()

    _confirm_dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Delete Design", weight=ft.FontWeight.BOLD),
        content=ft.Text("Are you sure you want to permanently delete this design?"),
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

    add_btn.on_click  = lambda _: open_design_dialog(None)
    edit_btn.on_click = lambda _: open_design_dialog(_sel["design"]) if _sel["design"] else None
    del_btn.on_click  = _open_confirm
    if chart_btn:
        chart_btn.on_click = _open_chart_dialog

    # ── Filter popup ──────────────────────────────────────────────────────────────────

    def _open_filter_popup(_=None) -> None:
        all_designs  = fetch_all_designs(output_path)
        projects     = sorted({d["project"] for d in all_designs if d.get("project")})
        boards       = sorted({d["board"]   for d in all_designs if d.get("board")})
        opened_dates = sorted({(d.get("opened_at") or "")[:10] for d in all_designs if d.get("opened_at")}, reverse=True)
        mod_dates    = sorted({(d.get("modified_at") or "")[:10] for d in all_designs if d.get("modified_at")}, reverse=True)
        closed_dates = sorted({(d.get("closed_at") or "")[:10] for d in all_designs if d.get("closed_at")}, reverse=True)

        all_hist = fetch_all_history(output_path)
        all_tags = sorted(set(
            m.lstrip("#").lower()
            for h in all_hist
            for m in re.findall(r"#\w+", h.get("body") or "")
        ))
        _tag_checks = {
            tag: ft.Checkbox(
                label=f"#{tag}",
                value=tag in _active_filters["tags"],
                active_color=ft.Colors.ORANGE_400,
            )
            for tag in all_tags
        }
        tags_body = ft.Column(
            list(_tag_checks.values()),
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            height=min(140, len(all_tags) * 34),
        ) if all_tags else ft.Text("No tags found", size=12, color=ft.Colors.GREY_500, italic=True)
        _tags_panel_open = {"open": bool(_active_filters["tags"])}
        tags_body_container = ft.Container(content=tags_body, visible=_tags_panel_open["open"])
        tags_chevron = ft.Icon(
            ft.Icons.EXPAND_LESS if _tags_panel_open["open"] else ft.Icons.EXPAND_MORE,
            size=16, color=ft.Colors.GREY_500,
        )
        def _toggle_tags_panel(_e=None):
            _tags_panel_open["open"] = not _tags_panel_open["open"]
            tags_body_container.visible = _tags_panel_open["open"]
            tags_chevron.name = ft.Icons.EXPAND_LESS if _tags_panel_open["open"] else ft.Icons.EXPAND_MORE
            page.update()
        tags_section = ft.Column(
            [
                ft.TextButton(
                    content=ft.Row(
                        [
                            ft.Text("Tags", size=12, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_600),
                            tags_chevron,
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_click=_toggle_tags_panel,
                    style=ft.ButtonStyle(
                        padding=ft.padding.symmetric(vertical=2, horizontal=0),
                        overlay_color=ft.Colors.TRANSPARENT,
                    ),
                ),
                tags_body_container,
            ],
            spacing=2,
        )

        _OPT_STYLE = ft.ButtonStyle(color={
            ft.ControlState.HOVERED:  ft.Colors.ORANGE_400,
            ft.ControlState.FOCUSED:  ft.Colors.ORANGE_400,
            ft.ControlState.DEFAULT:  ft.Colors.ON_SURFACE,
        })
        _STATUS_STYLE = {
            "Open":        ft.ButtonStyle(color={ft.ControlState.DEFAULT: ft.Colors.BLUE_700,   ft.ControlState.HOVERED: ft.Colors.BLUE_400}),
            "In Progress": ft.ButtonStyle(color={ft.ControlState.DEFAULT: ft.Colors.ORANGE_700, ft.ControlState.HOVERED: ft.Colors.ORANGE_400}),
            "On Hold":     ft.ButtonStyle(color={ft.ControlState.DEFAULT: ft.Colors.PURPLE_700, ft.ControlState.HOVERED: ft.Colors.PURPLE_400}),
            "Closed":      ft.ButtonStyle(color={ft.ControlState.DEFAULT: ft.Colors.GREEN_700,  ft.ControlState.HOVERED: ft.Colors.GREEN_400}),
        }

        def _dd(label, key, options, extra_style=None):
            opts = [ft.dropdown.Option("", text="— All —", style=_OPT_STYLE)] + [
                ft.dropdown.Option(o, text=o, style=extra_style.get(o, _OPT_STYLE) if extra_style else _OPT_STYLE)
                for o in options
            ]
            return ft.Dropdown(
                label=label,
                value=_active_filters[key] or "",
                options=opts,
                width=200,
                dense=True,
                data=key,
            )

        dd_project  = _dd("Project",  "project",  projects)
        dd_board    = _dd("Board",    "board",    boards)
        dd_category = _dd("Category", "category", CATEGORIES)
        dd_function = _dd("Function", "function", FUNCTIONS)
        dd_opened   = _dd("Opened",   "opened",   opened_dates)
        dd_modified = _dd("Modified", "modified", mod_dates)
        dd_closed   = _dd("Closed",   "closed",   closed_dates)
        dd_status   = _dd("Status",   "status",   STATUSES, _STATUS_STYLE)

        def _apply(_) -> None:
            _active_filters["project"]  = dd_project.value  or ""
            _active_filters["board"]    = dd_board.value    or ""
            _active_filters["category"] = dd_category.value or ""
            _active_filters["function"] = dd_function.value or ""
            _active_filters["opened"]   = dd_opened.value   or ""
            _active_filters["modified"] = dd_modified.value or ""
            _active_filters["closed"]   = dd_closed.value   or ""
            _active_filters["status"]   = dd_status.value   or ""
            _active_filters["tags"]     = [tag for tag, cb in _tag_checks.items() if cb.value]
            filter_dlg.open = False
            _update_filter_btn_color()
            _refresh()

        def _reset(_) -> None:
            for k in _active_filters:
                _active_filters[k] = [] if k == "tags" else ""
            filter_dlg.open = False
            _update_filter_btn_color()
            _refresh()

        filter_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [ft.Icon(ft.Icons.FILTER_LIST, color=ft.Colors.ORANGE_400),
                 ft.Text("Filter Designs", weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [dd_project, dd_board, dd_category, dd_function,
                 dd_opened, dd_modified, dd_closed, dd_status, tags_section],
                tight=True, spacing=12, width=240,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("Reset", on_click=_reset,
                              style=ft.ButtonStyle(color=ft.Colors.RED_400)),
                ft.TextButton("Cancel", on_click=lambda _: (setattr(filter_dlg, "open", False), page.update())),
                ft.FilledButton("Apply", on_click=_apply),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(filter_dlg)
        filter_dlg.open = True
        page.update()

    if filter_btn:
        filter_btn.on_click = _open_filter_popup

    if search_btn:
        def _toggle_search(_=None) -> None:
            _search_banner.visible = not _search_banner.visible
            if _search_banner.visible:
                _search_field.focus()
            else:
                _close_search()
            page.update()
        search_btn.on_click = _toggle_search

    return ft.Column(
        [_search_banner, _filter_banner, list_area],
        spacing=0,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
