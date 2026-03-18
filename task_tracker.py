"""
task_tracker.py
Builds and returns the Task Tracker view for the Memento main window.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import flet as ft
from datetime import datetime, timedelta, timezone
from pathlib import Path
from task_db import (
    STATUSES, init_db, fetch_all_tasks, fetch_distinct_projects,
    create_task, update_task, delete_task,
    fetch_task_attachments, add_attachment, remove_attachment,
    fetch_history, add_history_entry, update_history_entry,
    delete_history_entry, fetch_history_attachments,
    add_history_attachment, remove_history_attachment,
    fetch_related_tasks, add_related_task, remove_related_task,
    get_pending_alarms, mark_alarm_fired,
)
from design_db import (
    fetch_all_designs, fetch_task_design_links,
    add_task_design_link, remove_task_design_link,
    init_db as _design_init_db,
)


# ── Module-level alarm checker ───────────────────────────────────────────────────────

_alarm_checker_started: dict = {}
_ICON_PATH = str(Path(__file__).parent / "Images" / "memento.ico")


def _fire_notification(task_title: str, project: str = "") -> None:
    """Fire a native Windows toast notification for a task alarm."""
    # Play Windows notification sound first (always works, no deps)
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
    if sys.platform == "win32":
        # Use PowerShell WinRT directly on Windows for full layout control
        def _ps_esc(s: str) -> str:
            return s.replace("'", "''")

        t0 = _ps_esc(task_title)
        t1 = _ps_esc(project) if project else ""
        icon_uri = "file:///" + _ICON_PATH.replace("\\", "/")
        lines = [
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
        ps = "; ".join(lines)
        try:
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        return
    # Fallback for non-Windows: try plyer
    try:
        from plyer import notification as _plyer
        _plyer.notify(
            title=task_title,
            message=project or "",
            app_name="Memento",
            timeout=10,
        )
    except Exception:
        pass


def _start_alarm_checker(output_path: str, on_fired=None) -> None:
    """Start the background alarm checker daemon thread (once per output_path).
    If already running, just update the on_fired callback."""
    if output_path in _alarm_checker_started:
        _alarm_checker_started[output_path]["on_fired"] = on_fired
        return
    _alarm_checker_started[output_path] = {"on_fired": on_fired}

    def _run() -> None:
        while True:
            try:
                fired_any = False
                for t in get_pending_alarms(output_path):
                    mark_alarm_fired(output_path, t["id"])
                    _fire_notification(t["title"], t.get("project") or "")
                    fired_any = True
                if fired_any:
                    cb = _alarm_checker_started[output_path].get("on_fired")
                    if cb:
                        try:
                            cb()
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(30)

    threading.Thread(target=_run, daemon=True, name="memento_alarm").start()


def build_task_tracker(page: ft.Page, config: dict,
                       add_btn, edit_btn, del_btn, chart_btn=None,
                       on_open_task=None, on_close_task=None) -> ft.Column:
    """Return the Task Tracker UI and wire add_btn / edit_btn / del_btn / chart_btn."""

    output_path: str = config.get("OutputPath", "")
    init_db(output_path)
    _design_init_db(output_path)

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
    if chart_btn:
        chart_btn.disabled   = True
        chart_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400)

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

    def _alarm_icon(task: dict) -> ft.Control:
        alarm_at    = task.get("alarm_at") or ""
        alarm_fired = int(task.get("alarm_fired") or 0)
        if not alarm_at:
            return ft.Icon(ft.Icons.NOTIFICATIONS_OFF, size=16,
                           color=ft.Colors.RED_400, tooltip="No alarm")
        if alarm_fired:
            return ft.Icon(ft.Icons.NOTIFICATIONS_OFF, size=16,
                           color=ft.Colors.RED_400, tooltip=f"Alarm fired: {alarm_at}")
        return ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, size=16,
                       color=ft.Colors.GREEN_500, tooltip=f"Alarm: {alarm_at}")

    # ── Detail / Edit dialog ─────────────────────────────────────────────────

    def open_task_dialog(task: dict | None = None) -> None:  # noqa: C901
        is_new = task is None

        # ── NEW TASK dialog ───────────────────────────────────────────────────
        if is_new:
            # ── Required fields ───────────────────────────────────────────────
            title_field = ft.TextField(
                label="Title",
                value="",
                expand=True,
                autofocus=True,
                dense=True,
            )
            _new_projects = fetch_distinct_projects(output_path)
            _proj_suggestions = ft.Column([], spacing=0, visible=False)
            project_text = ft.TextField(label="Project", value="", expand=True, dense=True)

            def _check_required() -> None:
                ok = (
                    bool(title_field.value.strip())
                    and bool(project_text.value.strip())
                    and bool(status_dd.value)
                )
                new_save_btn.disabled = not ok
                page.update()

            def _on_project_change(e) -> None:
                typed = e.control.value.strip()
                matches = [p for p in _new_projects if typed.lower() and typed.lower() in p.lower()][:6]
                _proj_suggestions.controls = [
                    ft.Container(
                        content=ft.Text(p, size=13, color=ft.Colors.ORANGE_400),
                        padding=ft.padding.symmetric(horizontal=12, vertical=4),
                        border_radius=4,
                        ink=True,
                        on_click=lambda _, p=p: _pick_project(p),
                    )
                    for p in matches
                ]
                _proj_suggestions.visible = bool(matches)
                _check_required()

            def _pick_project(name: str) -> None:
                project_text.value = name
                _proj_suggestions.visible = False
                new_save_btn.disabled = False
                page.update()

            project_text.on_change = _on_project_change
            title_field.on_change  = lambda _: _check_required()

            status_dd = ft.Dropdown(
                label="Status",
                value="Open",
                options=[ft.dropdown.Option(s, style=ft.ButtonStyle(color={
                    ft.ControlState.HOVERED:  ft.Colors.ORANGE_400,
                    ft.ControlState.FOCUSED:  ft.Colors.ORANGE_400,
                    ft.ControlState.DEFAULT:  ft.Colors.ON_SURFACE,
                })) for s in STATUSES],
                width=160,
                dense=True,
                on_select=lambda _: _check_required(),
            )

            # ── Alarm ──────────────────────────────────────────────────────────
            _NEW_ALARM_BEFORE_OPTS = [
                ("0",   "At alarm time"),
                ("5",   "5 min before"),
                ("15",  "15 min before"),
                ("30",  "30 min before"),
                ("60",  "1 hour before"),
                ("120", "2 hours before"),
            ]
            new_alarm_date = ft.TextField(
                hint_text="YYYY-MM-DD",
                width=115,
                border=ft.InputBorder.UNDERLINE,
                content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
                text_size=13,
                dense=True,
            )
            def _new_cap2(e) -> None:
                if len(e.control.value) > 2:
                    e.control.value = e.control.value[:2]
                    e.control.update()
            new_alarm_hh = ft.TextField(
                hint_text="HH",
                width=36,
                input_filter=ft.NumbersOnlyInputFilter(),
                on_change=_new_cap2,
                border=ft.InputBorder.UNDERLINE,
                content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
                text_size=13,
                text_align=ft.TextAlign.CENTER,
                dense=True,
            )
            new_alarm_mm = ft.TextField(
                hint_text="MM",
                width=36,
                input_filter=ft.NumbersOnlyInputFilter(),
                on_change=_new_cap2,
                border=ft.InputBorder.UNDERLINE,
                content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
                text_size=13,
                text_align=ft.TextAlign.CENTER,
                dense=True,
            )
            new_alarm_before_dd = ft.Dropdown(
                value="0",
                options=[ft.dropdown.Option(key=k, text=v, style=ft.ButtonStyle(color={
                    ft.ControlState.HOVERED:  ft.Colors.ORANGE_400,
                    ft.ControlState.FOCUSED:  ft.Colors.ORANGE_400,
                    ft.ControlState.DEFAULT:  ft.Colors.ON_SURFACE,
                })) for k, v in _NEW_ALARM_BEFORE_OPTS],
                width=155,
                border=ft.InputBorder.UNDERLINE,
                content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
                text_size=13,
                dense=True,
            )
            new_alarm_switch = ft.Switch(
                value=False,
                disabled=True,
                active_color=ft.Colors.GREEN_500,
            )

            def _new_alarm_time_str() -> str:
                h = (new_alarm_hh.value or "").strip().zfill(2)
                m = (new_alarm_mm.value or "").strip().zfill(2)
                return f"{h}:{m}"

            def _new_alarm_future_check(date_str: str, time_str: str) -> bool:
                d = date_str.strip()
                t = time_str.strip()
                # Require both date and a fully specified time (HH:MM)
                if not d or not t or t in (":", "00:", ":00"):
                    return False
                hh = (new_alarm_hh.value or "").strip()
                mm = (new_alarm_mm.value or "").strip()
                if not hh or not mm:
                    return False
                try:
                    return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M") > datetime.now()
                except ValueError:
                    return False

            def _new_refresh_alarm_switch() -> None:
                is_fut = _new_alarm_future_check(
                    new_alarm_date.value or "", _new_alarm_time_str()
                )
                new_alarm_switch.disabled = not is_fut
                new_alarm_switch.value    = is_fut
                page.update()

            def _new_build_alarm_at() -> str:
                d = (new_alarm_date.value or "").strip()
                t = _new_alarm_time_str()
                if not d:
                    return ""
                try:
                    datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                    return f"{d} {t}:00"
                except ValueError:
                    return ""

            def _new_on_alarm_change(_e=None) -> None:
                _new_refresh_alarm_switch()

            new_alarm_date.on_change = _new_on_alarm_change
            new_alarm_hh.on_change   = lambda e: (_new_cap2(e), _new_on_alarm_change())
            new_alarm_mm.on_change   = lambda e: (_new_cap2(e), _new_on_alarm_change())

            _new_date_picker = ft.DatePicker(
                first_date=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                last_date=datetime(2035, 12, 31),
            )
            page.overlay.append(_new_date_picker)

            def _on_new_date_picked(_e) -> None:
                if _new_date_picker.value:
                    new_alarm_date.value = _new_date_picker.value.strftime("%Y-%m-%d")
                    _new_refresh_alarm_switch()

            _new_date_picker.on_change = _on_new_date_picked

            def _open_new_calendar(_e) -> None:
                try:
                    _new_date_picker.value = datetime.strptime(
                        (new_alarm_date.value or "").strip(), "%Y-%m-%d"
                    )
                except ValueError:
                    _new_date_picker.value = None
                _new_date_picker.open = True
                page.update()

            new_cal_btn = ft.IconButton(
                icon=ft.Icons.CALENDAR_MONTH,
                icon_size=18,
                tooltip="Pick date",
                on_click=_open_new_calendar,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_alarm_clear_btn = ft.IconButton(
                icon=ft.Icons.ALARM_OFF,
                icon_size=16,
                tooltip="Clear alarm",
                on_click=lambda _: (
                    setattr(new_alarm_date, 'value', ''),
                    setattr(new_alarm_hh, 'value', ''),
                    setattr(new_alarm_mm, 'value', ''),
                    setattr(new_alarm_before_dd, 'value', '0'),
                    setattr(new_alarm_switch, 'disabled', True),
                    setattr(new_alarm_switch, 'value', False),
                    page.update(),
                ),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_alarm_section = ft.Column(
                [
                    ft.Text("Alarm", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    ft.Row(
                        [
                            new_alarm_date, new_cal_btn,
                            ft.Icon(ft.Icons.ACCESS_TIME, size=14, color=ft.Colors.GREY_500),
                            new_alarm_hh,
                            ft.Text(":", size=14, weight=ft.FontWeight.W_600),
                            new_alarm_mm,
                            new_alarm_before_dd,
                            new_alarm_clear_btn,
                            ft.Container(expand=True),
                            new_alarm_switch,
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
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

            # ── Related Tasks ─────────────────────────────────────────────────
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
                                on_click=lambda _, rid=rt["id"]: _new_remove_rel_task(rid),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                    for rt in _staged_rel_tasks
                ]
                page.update()

            def _new_remove_rel_task(rid: int) -> None:
                _staged_rel_tasks[:] = [r for r in _staged_rel_tasks if r["id"] != rid]
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
                    rid = int(raw)
                except ValueError:
                    new_rel_task_error.value   = "Enter a valid number"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                if any(r["id"] == rid for r in _staged_rel_tasks):
                    new_rel_task_error.value   = "Already added"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                all_t = fetch_all_tasks(output_path)
                target = next((t for t in all_t if t["id"] == rid), None)
                if not target:
                    new_rel_task_error.value   = "Task not found"
                    new_rel_task_error.visible = True
                    page.update()
                    return
                _staged_rel_tasks.append({"id": rid, "title": target["title"]})
                new_rel_task_input.value   = ""
                new_rel_task_error.visible = False
                _new_refresh_rel_tasks()

            new_rel_task_add_btn = ft.IconButton(
                icon=ft.Icons.CHECK,
                icon_size=17,
                icon_color=ft.Colors.GREEN_400,
                tooltip="Add relation",
                on_click=_new_add_rel_task,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_tasks_section = ft.Column(
                [
                    ft.Text("Related Tasks", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    staged_rel_tasks_col,
                    ft.Row(
                        [new_rel_task_input, new_rel_task_add_btn, new_rel_task_error],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
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
            new_rel_designs_section = ft.Column(
                [
                    ft.Text("Related Designs", size=12, weight=ft.FontWeight.W_600,
                            color=ft.Colors.GREY_600),
                    staged_rel_designs_col,
                    ft.Row(
                        [new_rel_design_input, new_rel_design_add_btn, new_rel_design_error],
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
                status  = status_dd.value
                if not title or not project or not status:
                    return
                task_id = create_task(output_path, title, project, status)
                # description
                desc = new_desc_field.value.strip()
                if desc:
                    update_task(output_path, task_id, description=desc)
                # alarm
                alarm_at = _new_build_alarm_at()
                if alarm_at:
                    update_task(
                        output_path, task_id,
                        alarm_at=alarm_at,
                        alarm_before=int(new_alarm_before_dd.value or 0),
                        alarm_fired=0 if new_alarm_switch.value else 1,
                    )
                # related tasks
                for rt in _staged_rel_tasks:
                    add_related_task(output_path, task_id, rt["id"])
                # related designs
                for rd in _staged_rel_designs:
                    add_task_design_link(output_path, task_id, rd["id"])
                # files
                if _staged_files:
                    _att_dir = Path(output_path) / "Memento" / "TaskTracker" / "attachments"
                    _att_dir.mkdir(parents=True, exist_ok=True)
                    for sf in _staged_files:
                        dest_name = f"{task_id}_{sf['name']}"
                        dest = _att_dir / dest_name
                        try:
                            shutil.copy2(str(sf["path"]), str(dest))
                            add_attachment(output_path, task_id, dest_name, sf["name"])
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
                title=ft.Text("New Task", weight=ft.FontWeight.BOLD),
                content=ft.Column(
                    [
                        # ── Required ──────────────────────────────────────────
                        title_field,
                        ft.Column([project_text, _proj_suggestions], spacing=0, tight=True),
                        status_dd,
                        ft.Divider(height=6),
                        # ── Optional ─────────────────────────────────────────
                        new_alarm_section,
                        ft.Divider(height=4),
                        new_desc_field,
                        ft.Divider(height=4),
                        new_rel_tasks_section,
                        ft.Divider(height=4),
                        new_rel_designs_section,
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

        # ── EXISTING TASK: editable title/project/status + description + files ─

        # ── Editable header ───────────────────────────────────────────────────
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

        header_title = ft.TextField(
            value=task["title"],
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        _hdr_projects = fetch_distinct_projects(output_path)
        _hdr_suggestions = ft.Column([], spacing=0, visible=False)
        header_project = ft.TextField(
            value=task["project"] or "",
            expand=True,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )

        def _on_hdr_project_change(e) -> None:
            typed = header_project.value.strip()
            matches = [p for p in _hdr_projects if typed.lower() and typed.lower() in p.lower()][:6]
            _hdr_suggestions.controls = [
                ft.Container(
                    content=ft.Text(p, size=13, color=ft.Colors.ORANGE_400),
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

        header_status = ft.Dropdown(
            value=task["status"],
            options=[ft.dropdown.Option(s, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.ORANGE_400, ft.ControlState.FOCUSED: ft.Colors.ORANGE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for s in STATUSES],
            width=160,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )

        def _on_hdr_title_change(_e) -> None:
            _update_save_btn()

        header_title.on_change = _on_hdr_title_change

        def _on_hdr_status_change(_e) -> None:
            _update_save_btn()

        header_status.on_select = _on_hdr_status_change

        header_col = ft.Column(
            [
                _label_row("Title:",   header_title),
                _label_row("Project:", ft.Column([header_project, _hdr_suggestions], spacing=0)),
                _label_row("Status:",  header_status),
            ],
            spacing=6,
        )

        # ── Alarm fields ──────────────────────────────────────────────────────
        _orig_alarm_at     = task.get("alarm_at") or ""
        _orig_alarm_before = int(task.get("alarm_before") or 0)
        _orig_alarm_fired  = int(task.get("alarm_fired") or 0)
        _alarm_date_init   = ""
        _alarm_time_init   = ""
        if _orig_alarm_at:
            try:
                _adt             = datetime.fromisoformat(_orig_alarm_at)
                _alarm_date_init = _adt.strftime("%Y-%m-%d")
                _alarm_time_init = _adt.strftime("%H:%M")
            except ValueError:
                pass

        _ALARM_BEFORE_OPTS = [
            ("0",   "At alarm time"),
            ("5",   "5 min before"),
            ("15",  "15 min before"),
            ("30",  "30 min before"),
            ("60",  "1 hour before"),
            ("120", "2 hours before"),
        ]

        def _alarm_future_check(date_str: str, time_str: str) -> bool:
            d = date_str.strip()
            t = time_str.strip() or "00:00"
            if not d:
                return False
            try:
                return datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M") > datetime.now()
            except ValueError:
                return False

        alarm_date_field = ft.TextField(
            value=_alarm_date_init,
            hint_text="YYYY-MM-DD",
            width=115,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        _h_init = _alarm_time_init[:2]  if _alarm_time_init else ""
        _m_init = _alarm_time_init[3:5] if _alarm_time_init else ""
        def _cap2(e) -> None:
            if len(e.control.value) > 2:
                e.control.value = e.control.value[:2]
                e.control.update()

        alarm_hour_field = ft.TextField(
            value=_h_init,
            hint_text="HH",
            width=36,
            input_filter=ft.NumbersOnlyInputFilter(),
            on_change=_cap2,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
            text_align=ft.TextAlign.CENTER,
        )
        alarm_min_field = ft.TextField(
            value=_m_init,
            hint_text="MM",
            width=36,
            input_filter=ft.NumbersOnlyInputFilter(),
            on_change=_cap2,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
            text_align=ft.TextAlign.CENTER,
        )
        alarm_before_dd = ft.Dropdown(
            value=str(_orig_alarm_before),
            options=[ft.dropdown.Option(key=k, text=v, style=ft.ButtonStyle(color={ft.ControlState.HOVERED: ft.Colors.ORANGE_400, ft.ControlState.FOCUSED: ft.Colors.ORANGE_400, ft.ControlState.DEFAULT: ft.Colors.ON_SURFACE})) for k, v in _ALARM_BEFORE_OPTS],
            width=155,
            border=ft.InputBorder.UNDERLINE,
            content_padding=ft.padding.symmetric(horizontal=4, vertical=4),
            text_size=13,
        )
        alarm_error_txt = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

        def _alarm_time_str() -> str:
            h = (alarm_hour_field.value or "").strip().zfill(2)
            m = (alarm_min_field.value  or "").strip().zfill(2)
            return f"{h}:{m}"

        _sw_future_init = _alarm_future_check(_alarm_date_init, _alarm_time_init or "00:00")
        _sw_value_init  = _sw_future_init and (_orig_alarm_fired == 0)
        alarm_switch = ft.Switch(
            value=_sw_value_init,
            disabled=not _sw_future_init,
            active_color=ft.Colors.GREEN_500,
        )

        # Calendar date picker
        _date_picker = ft.DatePicker(
            first_date=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            last_date=datetime(2035, 12, 31),
        )
        page.overlay.append(_date_picker)

        def _on_date_picked(_e) -> None:
            if _date_picker.value:
                alarm_date_field.value = _date_picker.value.strftime("%Y-%m-%d")
                _refresh_alarm_switch()
                _update_save_btn()

        _date_picker.on_change = _on_date_picked

        def _open_calendar(_e) -> None:
            try:
                _date_picker.value = datetime.strptime(
                    alarm_date_field.value.strip(), "%Y-%m-%d"
                )
            except ValueError:
                _date_picker.value = None
            _date_picker.open = True
            page.update()

        cal_btn = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            icon_size=18,
            tooltip="Pick date",
            on_click=_open_calendar,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _refresh_alarm_switch() -> None:
            is_fut = _alarm_future_check(alarm_date_field.value, _alarm_time_str())
            alarm_switch.disabled = not is_fut
            if not is_fut:
                alarm_switch.value = False
            else:
                alarm_switch.value = True   # auto-enable when date is in the future
            page.update()

        def _build_alarm_at() -> str | None:
            """Return ISO alarm string, '' if empty, None if format invalid."""
            d = alarm_date_field.value.strip()
            t = _alarm_time_str()
            if not d:
                return ""
            try:
                datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                return f"{d} {t}:00"
            except ValueError:
                return None

        def _on_clear_alarm(_e=None) -> None:
            alarm_date_field.value  = ""
            alarm_hour_field.value  = ""
            alarm_min_field.value   = ""
            alarm_before_dd.value   = "0"
            alarm_error_txt.visible = False
            alarm_switch.disabled   = True
            alarm_switch.value      = False
            _update_save_btn()

        alarm_clear_btn = ft.IconButton(
            icon=ft.Icons.ALARM_OFF,
            icon_size=16,
            tooltip="Clear alarm",
            on_click=_on_clear_alarm,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        alarm_section = ft.Column(
            [
                ft.Text("Alarm", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                ft.Row(
                    [
                        alarm_date_field,
                        cal_btn,
                        ft.Icon(ft.Icons.ACCESS_TIME, size=14, color=ft.Colors.GREY_500),
                        alarm_hour_field,
                        ft.Text(":", size=14, weight=ft.FontWeight.W_600),
                        alarm_min_field,
                        alarm_before_dd,
                        alarm_clear_btn,
                        ft.Container(expand=True),
                        alarm_switch,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alarm_error_txt,
            ],
            spacing=4,
        )

        # ── Description field with toolbar ────────────────────────────────────
        _current_desc = task.get("description", "") or ""
        _desc_has_content = bool(_current_desc.strip())
        # Shared refs to main action buttons (populated after they are created)
        _main_btns: dict = {"delete": None, "save": None}
        # Original values for dirty detection
        _orig = {
            "title":        task["title"],
            "project":      task.get("project", "") or "",
            "status":       task["status"],
            "description":  _current_desc,
            "alarm_at":     _orig_alarm_at,
            "alarm_before": _orig_alarm_before,
            "alarm_fired":  _orig_alarm_fired,
        }
        # dirty = at least one change confirmed; editing = unsaved edit in progress
        _edit_state = {"dirty": False, "editing": not _desc_has_content}

        def _update_save_btn() -> None:
            if _main_btns["save"]:
                header_changed = (
                    header_title.value.strip() != _orig["title"]
                    or header_project.value.strip() != _orig["project"]
                    or (header_status.value or "") != _orig["status"]
                )
                alarm_at_new = _build_alarm_at()
                new_fired = 0 if alarm_switch.value else 1
                alarm_changed = (
                    alarm_at_new is not None
                    and alarm_at_new != ""
                    and (
                        alarm_at_new != _orig["alarm_at"]
                        or int(alarm_before_dd.value or 0) != _orig["alarm_before"]
                        or new_fired != _orig["alarm_fired"]
                    )
                ) or (
                    alarm_at_new == "" and _orig["alarm_at"] != ""
                )
                can_save = header_changed or alarm_changed or (
                    _edit_state["dirty"] and not _edit_state["editing"]
                )
                _main_btns["save"].disabled = not can_save
            page.update()

        def _on_alarm_time_change(_e) -> None:
            _refresh_alarm_switch()
            _update_save_btn()

        alarm_date_field.on_change = _on_alarm_time_change
        alarm_hour_field.on_change = _on_alarm_time_change
        alarm_min_field.on_change  = _on_alarm_time_change
        alarm_before_dd.on_select  = lambda _e: _update_save_btn()
        alarm_switch.on_change     = lambda _e: _update_save_btn()

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
            update_task(output_path, task["id"], description=new_desc)
            has_content = bool(new_desc.strip())
            desc_display.spans = _build_rich_spans(new_desc)
            desc_display.visible = has_content
            desc_field.visible = not has_content
            desc_edit_btn.visible = has_content
            desc_save_btn.visible = not has_content
            desc_cancel_btn.visible = False
            desc_toolbar.visible = not has_content
            _edit_state["editing"] = False
            if new_desc != _orig["description"]:
                _edit_state["dirty"] = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()

        desc_save_btn.on_click = _on_desc_save

        def _on_desc_cancel(_e) -> None:
            """Restore previous description without saving."""
            desc_field.value = _current_desc
            has_content = bool(_current_desc.strip())
            desc_display.visible = has_content
            desc_field.visible = not has_content
            desc_edit_btn.visible = has_content
            desc_save_btn.visible = not has_content
            desc_cancel_btn.visible = False
            desc_toolbar.visible = not has_content
            _edit_state["editing"] = False
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()

        desc_cancel_btn.on_click = _on_desc_cancel

        async def _on_desc_edit(_e) -> None:
            desc_display.visible = False
            desc_field.visible = True
            desc_edit_btn.visible = False
            desc_save_btn.visible = True
            desc_cancel_btn.visible = True
            desc_toolbar.visible = True
            _edit_state["editing"] = True
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
                        desc_cancel_btn,
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

        # ── Related Tasks ─────────────────────────────────────────────────────
        _related_editing = {"active": False}
        related_list_col = ft.Column([], spacing=4)

        def _refresh_related() -> None:
            rels = fetch_related_tasks(output_path, task["id"])
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
                                    decoration=ft.TextDecoration.UNDERLINE,
                                ),
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
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
            all_t = fetch_all_tasks(output_path)
            target = next((t for t in all_t if t["id"] == rid), None)
            if target:
                open_task_dialog(target)

        def _remove_related(rid: int) -> None:
            remove_related_task(output_path, task["id"], rid)
            _edit_state["dirty"]   = True
            _edit_state["editing"] = False
            _update_save_btn()
            _refresh_related()

        # ── Add-relation input row ────────────────────────────────────────────
        related_input = ft.TextField(
            hint_text="Task #",
            width=90,
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
            _edit_state["editing"] = active
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
            ok = add_related_task(output_path, task["id"], rid)
            if not ok:
                related_error.value = (
                    "Task not found" if rid != task["id"] else "Cannot relate to self"
                )
                related_error.visible = True
                page.update()
                return
            related_input.value   = ""
            related_error.visible = False
            _edit_state["dirty"] = True
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
                ft.Text("Related Tasks", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                related_list_col,
                ft.Row(
                    [
                        related_input,
                        rel_save_btn,
                        rel_cancel_btn,
                        related_error,
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_related()

        # ── Related Designs ───────────────────────────────────────────────────
        _rel_designs_editing = {"active": False}
        rel_designs_list_col = ft.Column([], spacing=4)

        def _refresh_related_designs() -> None:
            links      = fetch_task_design_links(output_path, task["id"])
            all_d      = fetch_all_designs(output_path)
            design_map = {d["id"]: d for d in all_d}
            rows_d     = []
            for lnk in links:
                did    = lnk["design_id"]
                dtitle = design_map[did]["title"] if did in design_map else f"(design #{did} not found)"
                rows_d.append(
                    ft.Row(
                        [
                            ft.Text(f"#{did}", size=13, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.GREY_500, width=36),
                            ft.Text(dtitle, size=13, expand=True, no_wrap=False),
                            ft.IconButton(
                                icon=ft.Icons.LINK_OFF,
                                icon_size=15,
                                icon_color=ft.Colors.RED_400,
                                tooltip="Remove relation",
                                on_click=lambda _, did=did: _remove_related_design(did),
                                style=ft.ButtonStyle(padding=ft.padding.all(2)),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    )
                )
            rel_designs_list_col.controls = rows_d
            page.update()

        def _remove_related_design(did: int) -> None:
            remove_task_design_link(output_path, task["id"], did)
            _edit_state["dirty"]   = True
            _edit_state["editing"] = False
            _update_save_btn()
            _refresh_related_designs()

        rel_design_input = ft.TextField(
            hint_text="Design #",
            width=120,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=6,
        )
        rel_design_error = ft.Text("", size=11, color=ft.Colors.RED_400, visible=False)

        rel_design_save_btn = ft.IconButton(
            icon=ft.Icons.CHECK,
            icon_size=17,
            tooltip="Add design relation",
            icon_color=ft.Colors.GREEN_400,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        rel_design_cancel_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=17,
            tooltip="Cancel",
            icon_color=ft.Colors.GREY_500,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _set_rel_designs_editing(active: bool) -> None:
            _rel_designs_editing["active"] = active
            _edit_state["editing"]         = active
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = active
            if _main_btns["save"]:
                _main_btns["save"].disabled = active or not _edit_state["dirty"]

        def _on_rel_design_input_change(_e) -> None:
            rel_design_error.visible = False
            has_text = bool((rel_design_input.value or "").strip())
            _set_rel_designs_editing(has_text)
            _update_save_btn()
            page.update()

        rel_design_input.on_change = _on_rel_design_input_change

        def _on_rel_design_save(_e) -> None:
            raw = (rel_design_input.value or "").strip()
            if not raw:
                return
            try:
                did = int(raw)
            except ValueError:
                rel_design_error.value   = "Enter a valid number"
                rel_design_error.visible = True
                page.update()
                return
            all_d  = fetch_all_designs(output_path)
            if not any(d["id"] == did for d in all_d):
                rel_design_error.value   = "Design not found"
                rel_design_error.visible = True
                page.update()
                return
            ok = add_task_design_link(output_path, task["id"], did)
            if not ok:
                rel_design_error.value   = "Already linked"
                rel_design_error.visible = True
                page.update()
                return
            rel_design_input.value   = ""
            rel_design_error.visible = False
            _edit_state["dirty"]     = True
            _set_rel_designs_editing(False)
            _update_save_btn()
            _refresh_related_designs()

        def _on_rel_design_cancel(_e) -> None:
            rel_design_input.value   = ""
            rel_design_error.visible = False
            _set_rel_designs_editing(False)
            _update_save_btn()
            page.update()

        rel_design_save_btn.on_click   = _on_rel_design_save
        rel_design_cancel_btn.on_click = _on_rel_design_cancel

        related_designs_section = ft.Column(
            [
                ft.Text("Related Designs", size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                rel_designs_list_col,
                ft.Row(
                    [rel_design_input, rel_design_save_btn, rel_design_cancel_btn, rel_design_error],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        _refresh_related_designs()

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
            cancel_body_btn = ft.IconButton(
                icon=ft.Icons.CLOSE, icon_size=15,
                tooltip="Cancel",
                visible=False,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            del_entry_btn = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=15,
                icon_color=ft.Colors.RED_400,
                tooltip="Delete entry",
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

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
                _edit_state["dirty"] = True
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

            edit_body_btn.on_click = _on_edit_body
            save_body_btn.on_click = _on_save_body
            cancel_body_btn.on_click = _on_cancel_body
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
                                cancel_body_btn,
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
                bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
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
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE),
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
            _edit_state["editing"] = has_text
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = has_text
            _update_save_btn()

        new_entry_field.on_change = _on_new_entry_change

        def _add_history_entry(_e) -> None:
            text = new_entry_field.value or ""
            if not text.strip():
                return
            add_history_entry(output_path, task["id"], text)
            new_entry_field.value = ""
            add_entry_btn.icon = ft.Icons.ADD_COMMENT_OUTLINED
            add_entry_btn.tooltip = "Add update"
            _edit_state["editing"] = False
            _edit_state["dirty"] = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            _update_save_btn()
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

        # ── Actions ───────────────────────────────────────────────────────────
        _dlg_ref: dict = {"dlg": None}

        def _go_back() -> None:
            if on_close_task:
                on_close_task()
            elif _dlg_ref["dlg"]:
                _dlg_ref["dlg"].open = False
                _clear_selection()
                _refresh()

        def _save(_) -> None:
            alarm_at_val = _build_alarm_at()
            if alarm_at_val is None:
                alarm_error_txt.value   = "Invalid format \u2014 use YYYY-MM-DD and HH:MM"
                alarm_error_txt.visible = True
                page.update()
                return
            alarm_before_val = int(alarm_before_dd.value or 0)
            new_fired = 0 if (alarm_switch.value and alarm_at_val) else 1
            kwargs: dict = dict(
                title        = header_title.value.strip() or task["title"],
                project      = header_project.value.strip(),
                status       = header_status.value,
                description  = desc_field.value or "",
                alarm_at     = alarm_at_val,
                alarm_before = alarm_before_val,
                alarm_fired  = new_fired,
            )
            update_task(output_path, task["id"], **kwargs)
            _go_back()

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
        )
        _main_btns["delete"] = delete_btn
        _main_btns["save"]   = save_btn
        # Save always starts disabled; enabled only after a confirmed change
        save_btn.disabled = True

        if on_open_task:
            # ── Full-page navigation ──────────────────────────────────────────
            detail_view = ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    header_col,
                                    ft.Divider(height=4),
                                    alarm_section,
                                    ft.Divider(height=4),
                                    desc_section,
                                    ft.Divider(height=4),
                                    related_section,
                                    ft.Divider(height=4),
                                    related_designs_section,
                                    ft.Divider(height=4),
                                    files_section,
                                    ft.Divider(height=4),
                                    history_section,
                                    ft.Divider(height=16),
                                    ft.Row(
                                        [delete_btn, cancel_btn, save_btn],
                                        alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                                    ),
                                    ft.Divider(height=8),
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
            on_open_task(detail_view, f"Task  #{task['id']}")
        else:
            # ── Dialog fallback ───────────────────────────────────────────────
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Task  #{task['id']}", weight=ft.FontWeight.BOLD),
                content=ft.Container(
                    content=ft.Column(
                        [
                            header_col,
                            ft.Divider(height=4),
                            alarm_section,
                            ft.Divider(height=4),
                            desc_section,
                            ft.Divider(height=4),
                            related_section,
                            ft.Divider(height=4),
                            related_designs_section,
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
            _dlg_ref["dlg"] = dlg
            page.overlay.append(dlg)
            dlg.open = True
            _refresh_attach()
            page.update()

    # ── Table ────────────────────────────────────────────────────────────────

    _COL_HEADER = ft.FontWeight.BOLD

    data_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("#",        size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Text("Title",    size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Project",  size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Opened",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Modified", size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Closed",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text("Status",   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Text("Alarm",    size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
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
        def _c(ctrl): return ft.Container(content=ctrl, alignment=ft.alignment.Alignment(0, 0))
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
                        ft.DataCell(_c(ft.Text(str(task["id"]), size=13))),
                        ft.DataCell(
                            _c(ft.TextButton(
                                content=ft.Text(
                                    task["title"],
                                    size=13,
                                    color=ft.Colors.DEEP_ORANGE_400,
                                ),
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(0),
                                    overlay_color=ft.Colors.TRANSPARENT,
                                    mouse_cursor=ft.MouseCursor.CLICK,
                                ),
                                on_click=lambda _, t=task: open_task_dialog(t),
                            ))
                        ),
                        ft.DataCell(_c(ft.Text(_fmt(task["project"]),    size=13))),
                        ft.DataCell(_c(ft.Text(_fmt(task["opened_at"]),   size=12,
                                            color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(ft.Text(_fmt(task["modified_at"]), size=12,
                                            color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(ft.Text(_fmt(task["closed_at"]),   size=12,
                                            color=ft.Colors.GREY_500))),
                        ft.DataCell(_c(_status_chip(task["status"]))),
                        ft.DataCell(_c(_alarm_icon(task))),
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
            if chart_btn:
                chart_btn.disabled   = False
                chart_btn.icon_color = ft.Colors.PURPLE_400
        else:
            list_area.content = empty_state
            if chart_btn:
                chart_btn.disabled   = True
                chart_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400)
        page.update()

    # ── Chart dialog ─────────────────────────────────────────────────────────

    def _open_chart_dialog(_=None) -> None:  # noqa: C901
        import math
        import flet.canvas as cv

        _STATUS_COLORS = {
            "Open":        "#1E88E5",
            "In Progress": "#FB8C00",
            "On Hold":     "#8E24AA",
            "Closed":      "#43A047",
        }

        _SIZE   = 240   # canvas pixel size
        _CX     = _SIZE / 2
        _CY     = _SIZE / 2
        _R      = _SIZE / 2 - 6   # outer radius (leave a small margin)
        _HOLE_R = _R * 0.32        # inner hole radius for donut look

        _filter        = {"period": "day", "project": ""}
        all_tasks_snap = fetch_all_tasks(output_path)
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
                t for t in all_tasks_snap
                if (not project or t["project"] == project)
                and _parse_dt(t["opened_at"]) >= cutoff
            ]
            counts = {s: 0 for s in STATUSES}
            for t in filtered:
                if t["status"] in counts:
                    counts[t["status"]] += 1
            return counts, sum(counts.values())

        def _make_slice(cx, cy, r, hole_r, start_rad, sweep_rad, color):
            """Return a cv.Path that draws a donut slice."""
            end_rad    = start_rad + sweep_rad
            large_arc  = sweep_rad > math.pi

            # Outer arc start/end points
            ox1 = cx + r * math.cos(start_rad)
            oy1 = cy + r * math.sin(start_rad)
            ox2 = cx + r * math.cos(end_rad)
            oy2 = cy + r * math.sin(end_rad)

            # Inner arc start/end points (reversed direction for closing)
            ix1 = cx + hole_r * math.cos(end_rad)
            iy1 = cy + hole_r * math.sin(end_rad)
            ix2 = cx + hole_r * math.cos(start_rad)
            iy2 = cy + hole_r * math.sin(start_rad)

            return cv.Path(
                elements=[
                    cv.Path.MoveTo(ox1, oy1),
                    cv.Path.ArcTo(ox2, oy2, radius=r,
                                  large_arc=large_arc, clockwise=True),
                    cv.Path.LineTo(ix1, iy1),
                    cv.Path.ArcTo(ix2, iy2, radius=hole_r,
                                  large_arc=large_arc, clockwise=False),
                    cv.Path.Close(),
                ],
                paint=ft.Paint(
                    color=color,
                    style=ft.PaintingStyle.FILL,
                ),
            )

        def _update() -> None:
            counts, total = _compute(_filter["period"], _filter["project"])
            if total == 0:
                pie_canvas.shapes = [
                    cv.Circle(_CX, _CY, _R,
                               paint=ft.Paint(
                                   color=ft.Colors.OUTLINE_VARIANT,
                                   style=ft.PaintingStyle.FILL,
                               )),
                ]
                legend_col.controls = [
                    ft.Text(
                        "No data for the selected filters.",
                        size=13,
                        color=ft.Colors.GREY_500,
                        text_align=ft.TextAlign.CENTER,
                    )
                ]
            else:
                shapes       = []
                legend_items = []
                angle = -math.pi / 2   # start from 12 o'clock

                non_zero = [(s, counts[s]) for s in STATUSES if counts[s] > 0]
                for status, n in non_zero:
                    pct   = n / total * 100
                    color = _STATUS_COLORS[status]
                    sweep = 2 * math.pi * (n / total)

                    # A full-circle arc (sweep ≈ 2π) degenerates in path drawing;
                    # render it as two filled circles (donut) instead.
                    if len(non_zero) == 1:
                        shapes.append(
                            cv.Circle(_CX, _CY, _R,
                                      paint=ft.Paint(color=color,
                                                     style=ft.PaintingStyle.FILL))
                        )
                        shapes.append(
                            cv.Circle(_CX, _CY, _HOLE_R,
                                      paint=ft.Paint(
                                          color=ft.Colors.SURFACE,
                                          style=ft.PaintingStyle.FILL))
                        )
                    else:
                        shapes.append(_make_slice(_CX, _CY, _R, _HOLE_R, angle, sweep, color))

                    # Percentage label at the mid-angle of the slice
                    if pct >= 7:
                        mid  = angle + sweep / 2 if len(non_zero) > 1 else -math.pi / 2
                        lr   = (_R + _HOLE_R) / 2
                        lx   = _CX + lr * math.cos(mid)
                        ly   = _CY + lr * math.sin(mid)
                        shapes.append(
                            cv.Text(
                                x=lx, y=ly,
                                value=f"{pct:.1f}%",
                                alignment=ft.Alignment(0, 0),
                                style=ft.TextStyle(
                                    size=10,
                                    color="#FFFFFF",
                                    weight=ft.FontWeight.BOLD,
                                ),
                            )
                        )

                    angle += sweep
                    legend_items.append(
                        ft.Row(
                            [
                                ft.Container(
                                    width=14, height=14,
                                    bgcolor=color,
                                    border_radius=3,
                                ),
                                ft.Text(
                                    f"{status}  ·  {n}  ({pct:.1f}%)",
                                    size=13,
                                ),
                            ],
                            spacing=8,
                            tight=True,
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
                + [ft.DropdownOption(key=p, text=p)
                   for p in fetch_distinct_projects(output_path)]
            ),
            on_select=_on_project_change,
        )

        def _close_chart(_) -> None:
            chart_dlg.open = False
            page.update()

        chart_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.PIE_CHART, color=ft.Colors.PURPLE_400),
                    ft.Text("Status Distribution", weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Row([period_dd, project_dd], spacing=12),
                    ft.Divider(height=6),
                    ft.Row(
                        [
                            pie_area,
                            ft.Container(
                                content=legend_col,
                                expand=True,
                                padding=ft.padding.only(left=20),
                                alignment=ft.Alignment(-1, 0),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                tight=True,
                spacing=8,
                width=540,
            ),
            actions=[
                ft.TextButton("Close", on_click=_close_chart),
            ],
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
    if chart_btn:
        chart_btn.on_click = _open_chart_dialog

    # ── Root ─────────────────────────────────────────────────────────────────

    _start_alarm_checker(output_path, on_fired=_refresh)
    return list_area
