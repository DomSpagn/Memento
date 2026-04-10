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
from translations import t
from datetime import datetime, timedelta, timezone
from pathlib import Path
from task_db import (
    STATUSES, init_db, fetch_all_tasks, fetch_distinct_projects,
    create_task, update_task, delete_task,
    fetch_task_attachments, add_attachment, remove_attachment,
    fetch_history, fetch_all_history, add_history_entry, update_history_entry,
    delete_history_entry, fetch_history_attachments,
    add_history_attachment, remove_history_attachment,
    fetch_related_tasks, add_related_task, remove_related_task,
    fetch_all_task_attachments, fetch_all_history_attachments_bulk,
    fetch_all_related_task_links,
    get_pending_alarms, mark_alarm_fired,
    find_tasks_with_attachment,
)
from design_db import (
    fetch_all_designs, fetch_task_design_links,
    add_task_design_link, remove_task_design_link,
    fetch_all_design_task_links_raw,
    init_db as _design_init_db,
    find_designs_with_attachment,
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
                       calendar_btn=None, filter_btn=None, search_btn=None,
                       on_open_task=None, on_close_task=None) -> ft.Column:
    """Return the Task Tracker UI and wire add_btn / edit_btn / del_btn / chart_btn / calendar_btn / filter_btn / search_btn."""

    output_path: str = config.get("OutputPath", "")
    init_db(output_path)
    _design_init_db(output_path)

    # ── Duplicate-attachment guard ────────────────────────────────────────────
    def _get_conflicts(orig_name: str) -> str:
        task_hits   = find_tasks_with_attachment(output_path, orig_name)
        design_hits = find_designs_with_attachment(output_path, orig_name)
        if not task_hits and not design_hits:
            return ""
        lines = []
        for h in task_hits:
            sfx = f" ({t('update')})" if h["in_history"] else ""
            lines.append(f"\u2022 Task #{h['task_id']} \u2013 {h['title']}{sfx}")
        for h in design_hits:
            sfx = f" ({t('update')})" if h["in_history"] else ""
            lines.append(f"\u2022 Design #{h['design_id']} \u2013 {h['title']}{sfx}")
        return "\n".join(lines)

    def _show_dup_alert(orig_name: str, conflicts: str) -> None:
        dlg_ref: dict = {}
        def _close_dup(_e=None):
            dlg_ref["d"].open = False
            page.update()
        _dup_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(t("File already attached"), weight=ft.FontWeight.BOLD),
            content=ft.Text(
                f"'{orig_name}' {t('is already attached to')}:\n\n{conflicts}",
            ),
            actions=[ft.TextButton("OK", on_click=_close_dup)],
        )
        dlg_ref["d"] = _dup_dlg
        page.overlay.append(_dup_dlg)
        _dup_dlg.open = True
        page.update()

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
    if calendar_btn:
        calendar_btn.disabled   = True
        calendar_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.GREEN_500)

    # ── Filter state ──────────────────────────────────────────────────────────
    _active_filters: dict = {
        "project": "", "opened": "", "modified": "", "closed": "", "status": "",
        "tags": []
    }

    # ── Search state ──────────────────────────────────────────────────────────
    _search_query: dict = {"q": ""}

    def _apply_filter(tasks: list[dict]) -> list[dict]:
        result = tasks
        if _active_filters["project"]:
            result = [t for t in result if t.get("project") == _active_filters["project"]]
        if _active_filters["status"]:
            result = [t for t in result if t.get("status") == _active_filters["status"]]
        if _active_filters["opened"]:
            result = [t for t in result if (t.get("opened_at") or "")[:10] == _active_filters["opened"]]
        if _active_filters["modified"]:
            result = [t for t in result if (t.get("modified_at") or "")[:10] == _active_filters["modified"]]
        if _active_filters["closed"]:
            result = [t for t in result if (t.get("closed_at") or "")[:10] == _active_filters["closed"]]
        if _active_filters["tags"]:
            all_hist = fetch_all_history(output_path)
            required = set(_active_filters["tags"])
            tagged_ids: set = set()
            for h in all_hist:
                found = {m.lstrip("#").lower() for m in re.findall(r"#\w+", h.get("body") or "")}
                if found & required:
                    tagged_ids.add(h["task_id"])
            result = [t for t in result if t["id"] in tagged_ids]
        return result

    def _apply_search(tasks: list[dict]) -> list[dict]:
        q = _search_query["q"]
        if not q:
            return tasks
        # Build per-task lookup maps with a single round of bulk DB queries
        all_hist     = fetch_all_history(output_path)
        all_h_atts   = fetch_all_history_attachments_bulk(output_path)
        all_t_atts   = fetch_all_task_attachments(output_path)
        all_rel_t    = fetch_all_related_task_links(output_path)
        all_dtlinks  = fetch_all_design_task_links_raw(output_path)
        designs_map  = {d["id"]: (d.get("title") or "").lower()
                        for d in fetch_all_designs(output_path)}

        hist_map: dict     = {}
        for h in all_hist:
            hist_map.setdefault(h["task_id"], []).append((h.get("body") or "").lower())

        h_att_map: dict = {}
        for ha in all_h_atts:
            h_att_map.setdefault(ha["task_id"], []).append((ha.get("orig_name") or "").lower())

        t_att_map: dict = {}
        for ta in all_t_atts:
            t_att_map.setdefault(ta["task_id"], []).append((ta.get("orig_name") or "").lower())

        rel_t_map: dict = {}
        for rt in all_rel_t:
            rel_t_map.setdefault(rt["task_id"], []).append((rt.get("related_title") or "").lower())

        rel_d_map: dict = {}
        for dtl in all_dtlinks:
            title = designs_map.get(dtl["design_id"], "")
            if title:
                rel_d_map.setdefault(dtl["task_id"], []).append(title)

        def _matches(task: dict) -> bool:
            tid = task["id"]
            haystack = " ".join(filter(None, [
                (task.get("title")       or "").lower(),
                (task.get("project")     or "").lower(),
                (task.get("status")      or "").lower(),
                (task.get("description") or "").lower(),
                " ".join(rel_t_map.get(tid, [])),
                " ".join(rel_d_map.get(tid, [])),
                " ".join(t_att_map.get(tid, [])),
                " ".join(hist_map.get(tid, [])),
                " ".join(h_att_map.get(tid, [])),
            ]))
            return q in haystack

        return [t for t in tasks if _matches(t)]

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
                           color=ft.Colors.RED_400, tooltip=t("No alarm"))
        if alarm_fired:
            return ft.Icon(ft.Icons.NOTIFICATIONS_OFF, size=16,
                           color=ft.Colors.RED_400, tooltip=f"{t('Alarm fired:')} {alarm_at}")
        return ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, size=16,
                       color=ft.Colors.GREEN_500, tooltip=f"{t('Alarm:')} {alarm_at}")

    # ── Detail / Edit dialog ─────────────────────────────────────────────────

    def open_task_dialog(task: dict | None = None) -> None:  # noqa: C901
        is_new = task is None

        # ── NEW TASK dialog ───────────────────────────────────────────────────
        if is_new:
            # ── Required fields ───────────────────────────────────────────────
            title_field = ft.TextField(
                label=t("Title"),
                value="",
                expand=True,
                autofocus=True,
                dense=True,
            )
            _new_projects = fetch_distinct_projects(output_path)
            _proj_suggestions = ft.Column([], spacing=0, visible=False)
            project_text = ft.TextField(label=t("Project"), value="", expand=True, dense=True)

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
                label=t("Status"),
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
                ("0",   t("At alarm time")),
                ("5",   t("5 min before")),
                ("15",  t("15 min before")),
                ("30",  t("30 min before")),
                ("60",  t("1 hour before")),
                ("120", t("2 hours before")),
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
                tooltip=t("Pick date"),
                on_click=_open_new_calendar,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_alarm_clear_btn = ft.IconButton(
                icon=ft.Icons.ALARM_OFF,
                icon_size=16,
                tooltip=t("Clear alarm"),
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
                    ft.Text(t("Alarm"), size=12, weight=ft.FontWeight.W_600,
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
                label=t("Description"),
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
                                tooltip=t("Remove"),
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
                    new_rel_task_error.value   = t("Enter a valid number")
                    new_rel_task_error.visible = True
                    page.update()
                    return
                if any(r["id"] == rid for r in _staged_rel_tasks):
                    new_rel_task_error.value   = t("Already added")
                    new_rel_task_error.visible = True
                    page.update()
                    return
                all_t = fetch_all_tasks(output_path)
                target = next((t for t in all_t if t["id"] == rid), None)
                if not target:
                    new_rel_task_error.value   = t("Task not found")
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
                tooltip=t("Add relation"),
                on_click=_new_add_rel_task,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_task_cancel_btn = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=17,
                icon_color=ft.Colors.GREY_500,
                tooltip=t("Cancel"),
                on_click=lambda _: (
                    setattr(new_rel_task_input, 'value', ''),
                    setattr(new_rel_task_error, 'visible', False),
                    page.update(),
                ),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_tasks_section = ft.Column(
                [
                    ft.Text(t("Related Tasks"), size=12, weight=ft.FontWeight.W_600,
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
                                tooltip=t("Remove"),
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
                    new_rel_design_error.value   = t("Enter a valid number")
                    new_rel_design_error.visible = True
                    page.update()
                    return
                if any(d["id"] == did for d in _staged_rel_designs):
                    new_rel_design_error.value   = t("Already added")
                    new_rel_design_error.visible = True
                    page.update()
                    return
                all_d = fetch_all_designs(output_path)
                target = next((d for d in all_d if d["id"] == did), None)
                if not target:
                    new_rel_design_error.value   = t("Design not found")
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
                tooltip=t("Add design relation"),
                on_click=_new_add_rel_design,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_design_cancel_btn = ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=17,
                icon_color=ft.Colors.GREY_500,
                tooltip=t("Cancel"),
                on_click=lambda _: (
                    setattr(new_rel_design_input, 'value', ''),
                    setattr(new_rel_design_error, 'visible', False),
                    page.update(),
                ),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            new_rel_designs_section = ft.Column(
                [
                    ft.Text(t("Related Designs"), size=12, weight=ft.FontWeight.W_600,
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
                                tooltip=t("Remove"),
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
                    if not f.path:
                        continue
                    src = Path(f.path)
                    conflicts = _get_conflicts(src.name)
                    if conflicts:
                        _show_dup_alert(src.name, conflicts)
                        continue
                    if not any(sf["name"] == src.name for sf in _staged_files):
                        _staged_files.append({"path": src, "name": src.name})
                _new_refresh_staged_files()

            new_attach_btn = ft.ElevatedButton(
                t("Attach File"),
                icon=ft.Icons.ATTACH_FILE,
                on_click=_new_attach_files,
                style=ft.ButtonStyle(elevation=0),
            )
            new_files_section = ft.Column(
                [
                    ft.Text(t("Files"), size=12, weight=ft.FontWeight.W_600,
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
                        _p = Path(sf["name"])
                        dest_name = f"{_p.stem}_Task_{task_id}{_p.suffix}"
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
                t("Save"),
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
                t("Cancel"),
                icon=ft.Icons.CLOSE,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_600, color=ft.Colors.WHITE),
                on_click=_new_cancel,
            )

            new_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(t("New Task"), weight=ft.FontWeight.BOLD),
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
            _autosave_headers()

        def _pick_hdr_project(name: str) -> None:
            header_project.value = name
            _hdr_suggestions.visible = False
            _autosave_headers()

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
            _autosave_headers()

        header_title.on_change = _on_hdr_title_change

        def _on_hdr_status_change(_e) -> None:
            _autosave_headers()

        header_status.on_select = _on_hdr_status_change

        header_col = ft.Column(
            [
                ft.Row(
                    [ft.Container(expand=True),
                     ft.IconButton(
                         icon=ft.Icons.DELETE_OUTLINE,
                         icon_color=ft.Colors.RED_400,
                         icon_size=18,
                         tooltip=t("Delete"),
                         on_click=lambda _e: _delete(_e),
                     )],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                _label_row(t("Title:"),   header_title),
                _label_row(t("Project:"), ft.Column([header_project, _hdr_suggestions], spacing=0)),
                _label_row(t("Status:"),  header_status),
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
            ("0",   t("At alarm time")),
            ("5",   t("5 min before")),
            ("15",  t("15 min before")),
            ("30",  t("30 min before")),
            ("60",  t("1 hour before")),
            ("120", t("2 hours before")),
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
                _autosave_headers()

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
            _autosave_headers()

        alarm_clear_btn = ft.IconButton(
            icon=ft.Icons.ALARM_OFF,
            icon_size=16,
            tooltip="Clear alarm",
            on_click=_on_clear_alarm,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )
        alarm_section = ft.Column(
            [
                ft.Text(t("Alarm"), size=12, weight=ft.FontWeight.W_600,
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
            page.update()

        def _autosave_headers() -> None:
            """Immediately persist header + alarm fields to DB."""
            alarm_at_val = _build_alarm_at()
            if alarm_at_val is None:
                alarm_error_txt.value   = "Invalid format \u2014 use YYYY-MM-DD and HH:MM"
                alarm_error_txt.visible = True
                update_task(output_path, task["id"],
                    title=header_title.value.strip() or task["title"],
                    project=header_project.value.strip(),
                    status=header_status.value,
                )
                page.update()
                return
            alarm_error_txt.visible = False
            alarm_before_val = int(alarm_before_dd.value or 0)
            new_fired = 0 if (alarm_switch.value and alarm_at_val) else 1
            update_task(output_path, task["id"],
                title=header_title.value.strip() or task["title"],
                project=header_project.value.strip(),
                status=header_status.value,
                alarm_at=alarm_at_val,
                alarm_before=alarm_before_val,
                alarm_fired=new_fired,
            )
            page.update()

        def _on_alarm_time_change(_e) -> None:
            _refresh_alarm_switch()
            _autosave_headers()

        alarm_date_field.on_change = _on_alarm_time_change
        alarm_hour_field.on_change = _on_alarm_time_change
        alarm_min_field.on_change  = _on_alarm_time_change
        alarm_before_dd.on_select  = lambda _e: _autosave_headers()
        alarm_switch.on_change     = lambda _e: _autosave_headers()

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
            tooltip=t("Edit description"),
            visible=_desc_has_content,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
        )

        desc_save_btn = ft.IconButton(
            icon=ft.Icons.SAVE_OUTLINED,
            icon_size=18,
            tooltip=t("Save description"),
            visible=not _desc_has_content,
            style=ft.ButtonStyle(
                padding=ft.padding.symmetric(horizontal=4, vertical=4),
                shape=ft.RoundedRectangleBorder(radius=4),
            ),
        )

        desc_cancel_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            tooltip=t("Cancel editing"),
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
            await desc_field.focus()

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
            await desc_field.focus()

        async def _apply_numbered(_e) -> None:
            cur = desc_field.value or ""
            count = len(re.findall(r"^\d+\.\s", cur, re.MULTILINE))
            await _apply_line_prefix(f"{count + 1}. ")

        async def _remove_quotes(_e) -> None:
            cur = desc_field.value or ""
            lines = [ln[4:] if ln.startswith("    ") else ln for ln in cur.splitlines()]
            desc_field.value = "\n".join(lines)
            page.update()
            await desc_field.focus()

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

        def _sym_tb_btn(label: str, tooltip: str, on_click_fn):
            return ft.TextButton(
                content=ft.Text(label, size=13, weight=ft.FontWeight.W_600),
                tooltip=tooltip,
                on_click=on_click_fn,
                style=ft.ButtonStyle(
                    padding=ft.padding.symmetric(horizontal=6, vertical=4),
                    shape=ft.RoundedRectangleBorder(radius=4),
                ),
            )

        _GREEK_UPPER_SYMS = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
        _GREEK_LOWER_SYMS = "αβγδεζηθικλμνξοπρστυφχψω"
        _MATH_SYMS        = "±∞≠~×÷∝≪≫≤≥∓≅≈≡∂√∪∩∅°∆∇∃∄∈∋←↑→↓↔∙⋯⟸⟹⟺"

        def _open_sym_picker(title_key: str, sym_groups: list, insert_fn) -> None:
            dlg_holder = [None]

            def _close(_e):
                dlg_holder[0].open = False
                page.update()

            def _mk_sym_handler(char):
                async def _h(_e):
                    dlg_holder[0].open = False
                    page.update()
                    await insert_fn(char)
                return _h

            group_widgets = []
            for group_label, chars in sym_groups:
                if group_label:
                    group_widgets.append(
                        ft.Text(t(group_label), size=11, weight=ft.FontWeight.W_600,
                                color=ft.Colors.GREY_600)
                    )
                group_widgets.append(
                    ft.Row(
                        [
                            ft.TextButton(
                                content=ft.Text(c, size=18),
                                tooltip=c,
                                on_click=_mk_sym_handler(c),
                                style=ft.ButtonStyle(
                                    padding=ft.padding.all(4),
                                    shape=ft.RoundedRectangleBorder(radius=4),
                                ),
                            )
                            for c in chars
                        ],
                        wrap=True,
                        spacing=2,
                        run_spacing=2,
                    )
                )

            dlg_holder[0] = ft.AlertDialog(
                modal=True,
                title=ft.Text(t(title_key), size=14, weight=ft.FontWeight.W_600),
                content=ft.Container(
                    content=ft.Column(group_widgets, spacing=6, tight=True),
                    width=340,
                ),
                actions=[ft.TextButton(t("Close"), on_click=_close)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(dlg_holder[0])
            dlg_holder[0].open = True
            page.update()

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
            tooltip=t("Text color"),
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

        async def _open_desc_greek(_e):
            _open_sym_picker(
                "Greek alphabet",
                [("Uppercase", _GREEK_UPPER_SYMS), ("Lowercase", _GREEK_LOWER_SYMS)],
                _insert_at_cursor,
            )

        async def _open_desc_math(_e):
            _open_sym_picker("Math symbols", [("", _MATH_SYMS)], _insert_at_cursor)

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
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _sym_tb_btn("Ω",    t("Greek alphabet"), _open_desc_greek),
                    _sym_tb_btn("f(x)", t("Math symbols"),   _open_desc_math),
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
                        ft.Text(t("Description"), size=12, weight=ft.FontWeight.W_600,
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
                related_error.value   = t("Enter a valid number")
                related_error.visible = True
                page.update()
                return
            if rid == task["id"]:
                related_error.value   = "Cannot relate to self"
                related_error.visible = True
                page.update()
                return
            # Check if already linked
            existing = fetch_related_tasks(output_path, task["id"])
            if any(r["id"] == rid for r in existing):
                related_error.value   = "Already linked"
                related_error.visible = True
                page.update()
                return
            ok = add_related_task(output_path, task["id"], rid)
            if not ok:
                related_error.value   = t("Task not found")
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
                ft.Text(t("Related Tasks"), size=12, weight=ft.FontWeight.W_600,
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
                rel_design_error.value   = t("Enter a valid number")
                rel_design_error.visible = True
                page.update()
                return
            all_d  = fetch_all_designs(output_path)
            if not any(d["id"] == did for d in all_d):
                rel_design_error.value   = t("Design not found")
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
                ft.Text(t("Related Designs"), size=12, weight=ft.FontWeight.W_600,
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
                if not f.path:
                    continue
                src = Path(f.path)
                conflicts = _get_conflicts(src.name)
                if conflicts:
                    _show_dup_alert(src.name, conflicts)
                    continue
                dest_name = f"{src.stem}_Task_{task['id']}{src.suffix}"
                dest = attach_dir / dest_name
                try:
                    shutil.copy2(str(src), str(dest))
                    add_attachment(output_path, task["id"], dest_name, src.name)
                except OSError:
                    pass
            _refresh_attach()
            _edit_state["dirty"] = True
            _update_save_btn()

        _refresh_attach()

        files_section = ft.Column(
            [
                ft.Text(t("Files"), size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                ft.ElevatedButton(
                    t("Attach File"),
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
                    return t("Today")
                if days == 1:
                    return t("Yesterday")
                return f"{days} {t('days ago')}"
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

            _body_cursor: dict = {"pos": 0}

            def _on_body_sel_change(e) -> None:
                sel = body_txt.selection
                if sel is not None:
                    _body_cursor["pos"] = sel.extent_offset

            body_txt = ft.TextField(
                value=entry["body"],
                multiline=True,
                min_lines=2,
                max_lines=6,
                read_only=True,
                border=ft.InputBorder.NONE,
                content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                expand=True,
                on_selection_change=_on_body_sel_change,
            )

            async def _entry_insert(text: str) -> None:
                cur = body_txt.value or ""
                pos = min(_body_cursor["pos"], len(cur))
                new_val = cur[:pos] + text + cur[pos:]
                new_pos = pos + len(text)
                body_txt.value = new_val
                body_txt.selection = ft.TextSelection(base_offset=new_pos, extent_offset=new_pos)
                _body_cursor["pos"] = new_pos
                page.update()
                await body_txt.focus()

            async def _entry_fmt(prefix: str, suffix: str, placeholder: str) -> None:
                await _entry_insert(f"{prefix}{placeholder}{suffix}")

            async def _entry_bold(_e):      await _entry_fmt("**",  "**",   "bold text")
            async def _entry_italic(_e):    await _entry_fmt("*",   "*",    "italic text")
            async def _entry_underline(_e): await _entry_fmt("<u>", "</u>", "underlined text")

            async def _entry_bullet(_e) -> None:
                cur = body_txt.value or ""
                pos = min(_body_cursor["pos"], len(cur))
                ls = cur.rfind('\n', 0, pos) + 1
                body_txt.value = cur[:ls] + "\u2022 " + cur[ls:]
                page.update()
                await body_txt.focus()

            async def _entry_numbered(_e) -> None:
                cur = body_txt.value or ""
                count = len(re.findall(r"^\d+\.\s", cur, re.MULTILINE))
                pos = min(_body_cursor["pos"], len(cur))
                ls = cur.rfind('\n', 0, pos) + 1
                body_txt.value = cur[:ls] + f"{count + 1}. " + cur[ls:]
                page.update()
                await body_txt.focus()

            async def _entry_quote(_e) -> None:
                cur = body_txt.value or ""
                pos = min(_body_cursor["pos"], len(cur))
                ls = cur.rfind('\n', 0, pos) + 1
                body_txt.value = cur[:ls] + "    " + cur[ls:]
                page.update()
                await body_txt.focus()

            async def _entry_remove_quotes(_e) -> None:
                cur = body_txt.value or ""
                lines = [ln[4:] if ln.startswith("    ") else ln for ln in cur.splitlines()]
                body_txt.value = "\n".join(lines)
                page.update()
                await body_txt.focus()

            def _make_entry_color_handler(hex_color):
                async def _h(_e): await _entry_fmt(f"[color={hex_color}]", "[/color]", "text")
                return _h

            entry_color_popup = ft.PopupMenuButton(
                icon=ft.Icons.FORMAT_COLOR_TEXT,
                icon_size=18,
                tooltip=t("Text color"),
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row(
                            [ft.Container(width=14, height=14, bgcolor=hx, border_radius=2),
                             ft.Text(nm, size=12)],
                            spacing=6,
                        ),
                        on_click=_make_entry_color_handler(hx),
                    )
                    for hx, nm in _COLOR_OPTS
                ],
            )

            async def _open_entry_greek(_e):
                _open_sym_picker(
                    "Greek alphabet",
                    [("Uppercase", _GREEK_UPPER_SYMS), ("Lowercase", _GREEK_LOWER_SYMS)],
                    _entry_insert,
                )

            async def _open_entry_math(_e):
                _open_sym_picker("Math symbols", [("", _MATH_SYMS)], _entry_insert)

            entry_edit_toolbar = ft.Container(
                visible=False,
                content=ft.Row(
                    [
                        _tb_btn(ft.Icons.FORMAT_BOLD,            "Bold",          _entry_bold),
                        _tb_btn(ft.Icons.FORMAT_ITALIC,          "Italic",        _entry_italic),
                        _tb_btn(ft.Icons.FORMAT_UNDERLINED,      "Underline",     _entry_underline),
                        ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                        _tb_btn(ft.Icons.FORMAT_LIST_BULLETED,   "Bullet list",   _entry_bullet),
                        _tb_btn(ft.Icons.FORMAT_LIST_NUMBERED,   "Numbered list", _entry_numbered),
                        ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                        entry_color_popup,
                        ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                        _tb_btn(ft.Icons.FORMAT_INDENT_INCREASE, "Quote",         _entry_quote),
                        _tb_btn(ft.Icons.FORMAT_INDENT_DECREASE, "Remove quote",  _entry_remove_quotes),
                        ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                        _sym_tb_btn("Ω",    t("Greek alphabet"), _open_entry_greek),
                        _sym_tb_btn("f(x)", t("Math symbols"),   _open_entry_math),
                    ],
                    spacing=0,
                    tight=True,
                ),
                border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
            )

            # ── Per-entry tag staging ──────────────────────────────────────
            _entry_staged_tags: list[str] = []
            _entry_tags_chips_row = ft.Row([], spacing=6, wrap=True)

            def _entry_refresh_chips() -> None:
                _entry_tags_chips_row.controls = [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(f"#{tn}", size=12, color=ft.Colors.BLUE_300,
                                        weight=ft.FontWeight.W_500, no_wrap=True),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE, icon_size=12,
                                    icon_color=ft.Colors.GREY_500,
                                    tooltip=t("Remove tag"),
                                    on_click=lambda _, tn=tn: _entry_remove_tag(tn),
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
                    )
                    for tn in _entry_staged_tags
                ]
                page.update()

            def _entry_remove_tag(tag: str) -> None:
                if tag in _entry_staged_tags:
                    _entry_staged_tags.remove(tag)
                _entry_refresh_chips()

            def _entry_on_tag_input_change(e) -> None:
                if " " in (e.control.value or ""):
                    e.control.value = (e.control.value or "").replace(" ", "")
                    e.control.update()

            entry_tag_input = ft.TextField(
                hint_text="#tag",
                width=120, dense=True, border_radius=6,
                content_padding=ft.padding.symmetric(horizontal=8, vertical=6),
                on_change=_entry_on_tag_input_change,
            )
            entry_add_tag_btn = ft.IconButton(
                icon=ft.Icons.ADD, icon_size=16,
                tooltip=t("Add tag"),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

            def _entry_do_add_tag(_e=None) -> None:
                raw = (entry_tag_input.value or "").strip().lstrip("#")
                if not raw:
                    return
                tag = raw.split()[0].lower()
                if tag and tag not in _entry_staged_tags:
                    _entry_staged_tags.append(tag)
                    _entry_refresh_chips()
                entry_tag_input.value = ""
                page.update()

            entry_tag_input.on_submit = lambda _e: _entry_do_add_tag()
            entry_add_tag_btn.on_click = _entry_do_add_tag

            entry_tags_section = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TAG, size=15, color=ft.Colors.GREY_500),
                            entry_tag_input,
                            entry_add_tag_btn,
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    _entry_tags_chips_row,
                ],
                spacing=4,
                visible=False,
            )

            entry_attach_btn = ft.IconButton(
                icon=ft.Icons.ATTACH_FILE, icon_size=15,
                tooltip=t("Attach file to this entry"),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

            del_entry_btn = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=15,
                icon_color=ft.Colors.RED_400,
                tooltip=t("Delete entry"),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

            _original_body: dict = {"val": ""}

            edit_body_btn = ft.IconButton(
                icon=ft.Icons.EDIT_NOTE, icon_size=15,
                tooltip=t("Edit"),
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )
            cancel_body_btn = ft.IconButton(
                icon=ft.Icons.CLOSE, icon_size=15,
                tooltip=t("Cancel"),
                visible=False,
                style=ft.ButtonStyle(padding=ft.padding.all(2)),
            )

            def _entry_reset_edit_ui():
                """Restore entry card to read-only state."""
                body_txt.read_only = True
                edit_body_btn.icon = ft.Icons.EDIT_NOTE
                edit_body_btn.tooltip = t("Edit")
                edit_body_btn.on_click = _on_edit_body
                cancel_body_btn.visible = False
                entry_edit_toolbar.visible = False
                entry_tags_section.visible = False
                _entry_staged_tags.clear()
                _entry_refresh_chips()
                _edit_state["editing"] = False
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = False
                if _main_btns["save"]:
                    _main_btns["save"].disabled = False
                _update_save_btn()

            def _on_edit_body(_e):
                _original_body["val"] = body_txt.value
                body_txt.read_only = False
                edit_body_btn.icon = ft.Icons.CHECK
                edit_body_btn.tooltip = t("Save")
                edit_body_btn.on_click = _on_save_body
                cancel_body_btn.visible = True
                entry_edit_toolbar.visible = True
                entry_tags_section.visible = True
                _edit_state["editing"] = True
                if _main_btns["delete"]:
                    _main_btns["delete"].disabled = True
                if _main_btns["save"]:
                    _main_btns["save"].disabled = True
                page.update()

            def _on_body_change(_e):
                page.update()

            body_txt.on_change = _on_body_change

            def _on_save_body(_e, eid=entry["id"]):
                text = body_txt.value or ""
                if _entry_staged_tags:
                    text = text.rstrip() + "\n" + " ".join(f"#{tg}" for tg in _entry_staged_tags)
                    body_txt.value = text
                update_history_entry(output_path, eid, text)
                _edit_state["dirty"] = True
                _entry_reset_edit_ui()
                _refresh_history()

            edit_body_btn.on_click = _on_edit_body

            def _on_cancel_body(_e):
                body_txt.value = _original_body["val"]
                _entry_reset_edit_ui()
                page.update()

            cancel_body_btn.on_click = _on_cancel_body

            def _on_del_entry(_e, eid=entry["id"]):
                for hatt in fetch_history_attachments(output_path, eid):
                    fname = remove_history_attachment(output_path, hatt["id"])
                    if fname:
                        try:
                            (history_attach_dir / fname).unlink(missing_ok=True)
                        except OSError:
                            pass
                delete_history_entry(output_path, eid)
                _refresh_history()

            del_entry_btn.on_click = _on_del_entry

            async def _attach_to_history(_e, eid=entry["id"], hac=h_att_col):
                fp = ft.FilePicker()
                files = await fp.pick_files(allow_multiple=True)
                if not files:
                    return
                history_attach_dir.mkdir(parents=True, exist_ok=True)
                for f in files:
                    if not f.path:
                        continue
                    src = Path(f.path)
                    conflicts = _get_conflicts(src.name)
                    if conflicts:
                        _show_dup_alert(src.name, conflicts)
                        continue
                    dest_name = f"{src.stem}_Task_{task['id']}{src.suffix}"
                    try:
                        shutil.copy2(str(src), str(history_attach_dir / dest_name))
                        add_history_attachment(output_path, eid, dest_name, src.name)
                    except OSError:
                        pass
                _edit_state["editing"] = False
                _edit_state["dirty"] = True
                _refresh_history()
                _update_save_btn()

            entry_attach_btn.on_click = _attach_to_history

            return ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(f"{t('Created')}: {_rel_date(entry['created_at'])}",
                                                size=11, color=ft.Colors.GREY_500),
                                    ] + (
                                        [ft.Text(f"{t('Modified')}: {_rel_date(entry['modified_at'])}",
                                                 size=11, color=ft.Colors.GREY_500)]
                                        if entry.get("modified_at") else []
                                    ),
                                    spacing=1,
                                    tight=True,
                                    expand=True,
                                ),
                                ft.Text(f"#{index}", size=11,
                                        color=ft.Colors.GREY_500,
                                        weight=ft.FontWeight.W_600),
                                entry_attach_btn,
                                del_entry_btn,
                                cancel_body_btn,
                                edit_body_btn,
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=2,
                        ),
                        entry_edit_toolbar,
                        body_txt,
                        h_att_col,
                        entry_tags_section,
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

        # ── History entry cursor tracking ──────────────────────────────────
        _cursor_hist: dict = {"pos": 0}

        def _on_hist_sel_change(e) -> None:
            sel = new_entry_field.selection
            if sel is not None:
                _cursor_hist["pos"] = sel.extent_offset

        async def _hist_insert(text: str) -> None:
            cur = new_entry_field.value or ""
            pos = min(_cursor_hist["pos"], len(cur))
            new_val = cur[:pos] + text + cur[pos:]
            new_pos = pos + len(text)
            new_entry_field.value = new_val
            new_entry_field.selection = ft.TextSelection(
                base_offset=new_pos, extent_offset=new_pos
            )
            _cursor_hist["pos"] = new_pos
            page.update()
            await new_entry_field.focus()

        async def _hist_fmt(prefix: str, suffix: str, placeholder: str) -> None:
            await _hist_insert(f"{prefix}{placeholder}{suffix}")

        async def _on_hist_bold(_e):      await _hist_fmt("**",  "**",    "bold text")
        async def _on_hist_italic(_e):    await _hist_fmt("*",   "*",     "italic text")
        async def _on_hist_underline(_e): await _hist_fmt("<u>", "</u>",  "underlined text")

        async def _on_hist_bullet(_e) -> None:
            cur = new_entry_field.value or ""
            pos = min(_cursor_hist["pos"], len(cur))
            ls = cur.rfind('\n', 0, pos) + 1
            new_entry_field.value = cur[:ls] + "\u2022 " + cur[ls:]
            page.update()
            await new_entry_field.focus()

        async def _on_hist_numbered(_e) -> None:
            cur = new_entry_field.value or ""
            count = len(re.findall(r"^\d+\.\s", cur, re.MULTILINE))
            pos = min(_cursor_hist["pos"], len(cur))
            ls = cur.rfind('\n', 0, pos) + 1
            new_entry_field.value = cur[:ls] + f"{count + 1}. " + cur[ls:]
            page.update()
            await new_entry_field.focus()

        async def _on_hist_quote(_e) -> None:
            cur = new_entry_field.value or ""
            pos = min(_cursor_hist["pos"], len(cur))
            ls = cur.rfind('\n', 0, pos) + 1
            new_entry_field.value = cur[:ls] + "    " + cur[ls:]
            page.update()
            await new_entry_field.focus()

        async def _on_hist_remove_quotes(_e) -> None:
            cur = new_entry_field.value or ""
            lines = [ln[4:] if ln.startswith("    ") else ln for ln in cur.splitlines()]
            new_entry_field.value = "\n".join(lines)
            page.update()
            await new_entry_field.focus()

        def _make_hist_color_handler(hex_color):
            async def _h(_e): await _hist_fmt(f"[color={hex_color}]", "[/color]", "text")
            return _h

        hist_color_popup = ft.PopupMenuButton(
            icon=ft.Icons.FORMAT_COLOR_TEXT,
            icon_size=18,
            tooltip=t("Text color"),
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [ft.Container(width=14, height=14, bgcolor=hx, border_radius=2),
                         ft.Text(nm, size=12)],
                        spacing=6,
                    ),
                    on_click=_make_hist_color_handler(hx),
                )
                for hx, nm in _COLOR_OPTS
            ],
        )

        async def _open_hist_greek(_e):
            _open_sym_picker(
                "Greek alphabet",
                [("Uppercase", _GREEK_UPPER_SYMS), ("Lowercase", _GREEK_LOWER_SYMS)],
                _hist_insert,
            )

        async def _open_hist_math(_e):
            _open_sym_picker("Math symbols", [("", _MATH_SYMS)], _hist_insert)

        hist_entry_toolbar = ft.Container(
            visible=False,
            content=ft.Row(
                [
                    _tb_btn(ft.Icons.FORMAT_BOLD,            "Bold",          _on_hist_bold),
                    _tb_btn(ft.Icons.FORMAT_ITALIC,          "Italic",        _on_hist_italic),
                    _tb_btn(ft.Icons.FORMAT_UNDERLINED,      "Underline",     _on_hist_underline),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _tb_btn(ft.Icons.FORMAT_LIST_BULLETED,   "Bullet list",   _on_hist_bullet),
                    _tb_btn(ft.Icons.FORMAT_LIST_NUMBERED,   "Numbered list", _on_hist_numbered),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    hist_color_popup,
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _tb_btn(ft.Icons.FORMAT_INDENT_INCREASE, "Quote",         _on_hist_quote),
                    _tb_btn(ft.Icons.FORMAT_INDENT_DECREASE, "Remove quote",  _on_hist_remove_quotes),
                    ft.VerticalDivider(width=8, color=ft.Colors.OUTLINE_VARIANT),
                    _sym_tb_btn("Ω",    t("Greek alphabet"), _open_hist_greek),
                    _sym_tb_btn("f(x)", t("Math symbols"),   _open_hist_math),
                ],
                spacing=0,
                tight=True,
            ),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
        )

        new_entry_field = ft.TextField(
            hint_text=t("Write an update…"),
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE),
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            on_selection_change=_on_hist_sel_change,
        )

        save_entry_btn = ft.FilledButton(
            t("Save update"),
            icon=ft.Icons.SAVE_OUTLINED,
            visible=False,
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.BLUE_600},
                color={ft.ControlState.DEFAULT: ft.Colors.WHITE},
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
                            ft.Text(f"#{tag_name}", size=12, color=ft.Colors.BLUE_300,
                                    weight=ft.FontWeight.W_500, no_wrap=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_size=12,
                                icon_color=ft.Colors.GREY_500,
                                tooltip=t("Remove tag"),
                                on_click=lambda _, tag=tag_name: _remove_tag(tag),
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
                )
                for tag_name in _staged_tags
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
            tooltip=t("Add tag"),
            disabled=True,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _do_add_tag(_e=None) -> None:
            raw = (tag_input.value or "").strip().lstrip("#")
            if not raw:
                return
            tag = raw.split()[0].lower()
            if tag and tag not in _staged_tags:
                _staged_tags.append(tag)
                _refresh_tag_chips()
            tag_input.value = ""
            page.update()

        tag_input.on_submit = lambda e: _do_add_tag()
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
            visible=False,
        )

        def _on_new_entry_change(_e) -> None:
            # edit state tracks whether the panel is active (always true when panel is open)
            pass

        new_entry_field.on_change = _on_new_entry_change

        _new_entry_attachments: list[str] = []
        _new_staged_files_col = ft.Column([], spacing=3)

        def _refresh_new_staged_files() -> None:
            _new_staged_files_col.controls = [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.ATTACH_FILE, size=13, color=ft.Colors.GREY_500),
                        ft.Text(Path(fp).name, size=12, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, icon_size=12,
                            tooltip=t("Remove"),
                            on_click=lambda _, p=fp: _remove_new_staged_att(p),
                            style=ft.ButtonStyle(padding=ft.padding.all(0)),
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for fp in _new_entry_attachments
            ]
            page.update()

        def _remove_new_staged_att(path: str) -> None:
            if path in _new_entry_attachments:
                _new_entry_attachments.remove(path)
            _refresh_new_staged_files()

        async def _on_new_attach(_e):
            fp = ft.FilePicker()
            files = await fp.pick_files(allow_multiple=True)
            if not files:
                return
            for f in files:
                if not f.path:
                    continue
                src = Path(f.path)
                conflicts = _get_conflicts(src.name)
                if conflicts:
                    _show_dup_alert(src.name, conflicts)
                    continue
                _new_entry_attachments.append(f.path)
            _refresh_new_staged_files()

        new_attach_btn = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE, icon_size=15,
            tooltip=t("Attach file to this entry"),
            on_click=_on_new_attach,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        def _hide_new_entry_panel() -> None:
            new_entry_field.value = ""
            _staged_tags.clear()
            _refresh_tag_chips()
            _new_entry_attachments.clear()
            _refresh_new_staged_files()
            save_entry_btn.visible     = False
            hist_entry_toolbar.visible = False
            tags_section.visible       = False
            new_attach_btn.visible     = False
            tag_input.disabled         = True
            add_tag_btn.disabled       = True
            new_entry_panel.visible    = False
            add_update_btn.visible     = True
            _edit_state["editing"]     = False
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = False
            if _main_btns["save"]:
                _main_btns["save"].disabled = False
            _update_save_btn()

        def _on_cancel_new_entry(_e) -> None:
            _hide_new_entry_panel()
            page.update()

        def _add_history_entry(_e) -> None:
            text = new_entry_field.value or ""
            if not text.strip() and not _new_entry_attachments:
                return
            if _staged_tags:
                text = text.rstrip() + "\n" + " ".join(f"#{tg}" for tg in _staged_tags)
            eid = add_history_entry(output_path, task["id"], text)
            if _new_entry_attachments:
                history_attach_dir.mkdir(parents=True, exist_ok=True)
                for fp in _new_entry_attachments:
                    src = Path(fp)
                    dest_name = f"{src.stem}_Task_{task['id']}{src.suffix}"
                    try:
                        shutil.copy2(str(src), str(history_attach_dir / dest_name))
                        add_history_attachment(output_path, eid, dest_name, src.name)
                    except OSError:
                        pass
            _edit_state["dirty"] = True
            _hide_new_entry_panel()
            _refresh_history()

        save_entry_btn.on_click = _add_history_entry

        cancel_new_entry_btn = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=15,
            tooltip=t("Cancel"),
            on_click=_on_cancel_new_entry,
            style=ft.ButtonStyle(padding=ft.padding.all(2)),
        )

        new_entry_panel = ft.Column(
            [
                hist_entry_toolbar,
                new_entry_field,
                _new_staged_files_col,
                tags_section,
                ft.Row(
                    [new_attach_btn, ft.Container(expand=True),
                     cancel_new_entry_btn, save_entry_btn],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=6,
            visible=False,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        add_update_btn = ft.OutlinedButton(
            t("New update"),
            icon=ft.Icons.ADD,
        )

        def _show_new_entry_panel(_e) -> None:
            hist_entry_toolbar.visible = True
            tags_section.visible       = True
            tag_input.disabled         = False
            add_tag_btn.disabled       = False
            save_entry_btn.visible     = True
            new_entry_panel.visible    = True
            add_update_btn.visible     = False
            _edit_state["editing"]     = True
            if _main_btns["delete"]:
                _main_btns["delete"].disabled = True
            if _main_btns["save"]:
                _main_btns["save"].disabled = True
            _update_save_btn()
            page.update()

        add_update_btn.on_click = _show_new_entry_panel

        history_section = ft.Column(
            [
                ft.Text(t("History"), size=12, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_600),
                history_entries_col,
                add_update_btn,
                new_entry_panel,
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
            t("Delete"),
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
            t("Cancel"),
            icon=ft.Icons.CLOSE,
            style=ft.ButtonStyle(bgcolor=ft.Colors.GREY_600, color=ft.Colors.WHITE),
            on_click=_cancel,
        )
        save_btn = ft.FilledButton(
            t("Save"),
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
                actions_alignment=ft.MainAxisAlignment.SPACE_EVENLY,
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
            ft.DataColumn(ft.Text(t("Title"),    size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text(t("Project"),  size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text(t("Opened"),   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text(t("Modified"), size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text(t("Closed"),   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Row([ft.Text(t("Status"),   size=13, weight=_COL_HEADER), ft.Icon(ft.Icons.UNFOLD_MORE, size=14, color=ft.Colors.GREY_500)], spacing=2), on_sort=_on_sort, heading_row_alignment=ft.MainAxisAlignment.CENTER),
            ft.DataColumn(ft.Text(t("Alarm"),    size=13, weight=_COL_HEADER), heading_row_alignment=ft.MainAxisAlignment.CENTER),
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

    _filter_banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.FILTER_LIST, size=16, color=ft.Colors.WHITE),
                ft.Text(t("Filter active"), size=13, color=ft.Colors.WHITE,
                        weight=ft.FontWeight.W_500),
                ft.Container(expand=True),
                ft.TextButton(
                    t("Clear"),
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
                    tooltip=t("Close search"),
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
        all_tasks = _apply_sort(fetch_all_tasks(output_path))
        tasks     = _apply_filter(all_tasks)
        tasks     = _apply_search(tasks)
        _filter_banner.visible = any(v for v in _active_filters.values())
        if tasks:
            data_table.rows = _build_rows(tasks)
            list_area.content = ft.ListView(
                [
                    ft.Container(
                        content=data_table,
                        padding=ft.padding.symmetric(horizontal=24, vertical=12),
                        expand=True,
                    )
                ],
                expand=True,
            )
            if chart_btn:
                chart_btn.disabled   = False
                chart_btn.icon_color = ft.Colors.PURPLE_400
            # Enable calendar btn only when there's at least one active alarm
            _has_alarm = any(
                t.get("alarm_at") and not int(t.get("alarm_fired") or 0)
                for t in tasks
            )
            if calendar_btn:
                if _has_alarm:
                    calendar_btn.disabled   = False
                    calendar_btn.icon_color = ft.Colors.GREEN_500
                else:
                    calendar_btn.disabled   = True
                    calendar_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.GREEN_500)
        else:
            list_area.content = empty_state
            if chart_btn:
                chart_btn.disabled   = True
                chart_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.PURPLE_400)
            if calendar_btn:
                calendar_btn.disabled   = True
                calendar_btn.icon_color = ft.Colors.with_opacity(0.3, ft.Colors.GREEN_500)
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
            label=t("Period"),
            value="day",
            width=165,
            options=[
                ft.DropdownOption(key="day",   text=t("Last Day")),
                ft.DropdownOption(key="week",  text=t("Last Week")),
                ft.DropdownOption(key="month", text=t("Last Month")),
                ft.DropdownOption(key="year",  text=t("Last Year")),
            ],
            on_select=_on_period_change,
        )

        project_dd = ft.Dropdown(
            label=t("Project"),
            value="",
            width=185,
            options=(
                [ft.DropdownOption(key="", text=t("All Projects"))]
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
                    ft.Text(t("Status Distribution"), weight=ft.FontWeight.BOLD),
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
                ft.TextButton(t("Close"), on_click=_close_chart),
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
        _task_id = _sel["task"]["id"]
        _att_dir = Path(output_path) / "Memento" / "TaskTracker" / "attachments"
        for att in fetch_task_attachments(output_path, _task_id):
            try:
                (_att_dir / att["filename"]).unlink(missing_ok=True)
            except OSError:
                pass
        for entry in fetch_history(output_path, _task_id):
            for hatt in fetch_history_attachments(output_path, entry["id"]):
                try:
                    (_att_dir / hatt["filename"]).unlink(missing_ok=True)
                except OSError:
                    pass
        delete_task(output_path, _task_id)
        _clear_selection()
        _refresh()

    def _cancel_confirm(_) -> None:
        _confirm_dlg.open = False
        page.update()

    _confirm_dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(t("Delete Task"), weight=ft.FontWeight.BOLD),
        content=ft.Text(t("Are you sure you want to permanently delete this task?")),
        actions=[
            ft.TextButton(t("Cancel"), on_click=_cancel_confirm),
            ft.FilledButton(
                t("Delete"),
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

    # ── Filter popup ─────────────────────────────────────────────────────────

    def _open_filter_popup(_=None) -> None:
        all_tasks    = fetch_all_tasks(output_path)
        projects     = sorted({t["project"] for t in all_tasks if t.get("project")})
        opened_dates = sorted({(t.get("opened_at") or "")[:10] for t in all_tasks if t.get("opened_at")}, reverse=True)
        mod_dates    = sorted({(t.get("modified_at") or "")[:10] for t in all_tasks if t.get("modified_at")}, reverse=True)
        closed_dates = sorted({(t.get("closed_at") or "")[:10] for t in all_tasks if t.get("closed_at")}, reverse=True)

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
        ) if all_tags else ft.Text(t("No tags found"), size=12, color=ft.Colors.GREY_500, italic=True)
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
                            ft.Text(t("Tags"), size=12, weight=ft.FontWeight.W_600,
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

        dd_project  = _dd(t("Project"),  "project",  projects)
        dd_opened   = _dd(t("Opened"),   "opened",   opened_dates)
        dd_modified = _dd(t("Modified"), "modified", mod_dates)
        dd_closed   = _dd(t("Closed"),   "closed",   closed_dates)
        dd_status   = _dd(t("Status"),   "status",   STATUSES, _STATUS_STYLE)

        def _apply(_) -> None:
            _active_filters["project"]  = dd_project.value  or ""
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
                 ft.Text(t("Filter Tasks"), weight=ft.FontWeight.BOLD)],
                spacing=10,
            ),
            content=ft.Column(
                [dd_project, dd_opened, dd_modified, dd_closed, dd_status, tags_section],
                tight=True, spacing=12, width=240,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(t("Reset"), on_click=_reset,
                              style=ft.ButtonStyle(color=ft.Colors.RED_400)),
                ft.TextButton(t("Cancel"), on_click=lambda _: (setattr(filter_dlg, "open", False), page.update())),
                ft.FilledButton(t("Apply"), on_click=_apply),
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

    # ── Calendar dialog ───────────────────────────────────────────────────────

    def _open_calendar_dialog(_=None) -> None:  # noqa: C901
        """Open the alarm calendar pop-up with daily/weekly/monthly views."""
        _cs = {
            "view": "weekly",
            "ref": datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
        }

        # English month/day name arrays (avoid locale-dependent strftime)
        _MONTHS_EN       = ["January", "February", "March", "April", "May", "June",
                            "July", "August", "September", "October", "November", "December"]
        _MONTHS_SHORT_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        _DAYS_EN         = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        _DAYS_SHORT_EN   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        def _get_alarm_tasks() -> list:
            return [
                t for t in fetch_all_tasks(output_path)
                if t.get("alarm_at") and not int(t.get("alarm_fired") or 0)
            ]

        def _alarm_dt(t: dict):
            try:
                return datetime.fromisoformat(t["alarm_at"])
            except (TypeError, ValueError):
                return None

        # ── Small task chip shown inside each calendar cell ───────────
        # Holds a reference to cal_dlg so chips can close it on double-tap
        _cal_ref: dict = {}

        def _open_task_from_cal(task: dict) -> None:
            dlg = _cal_ref.get("dlg")
            if dlg:
                dlg.open = False
            open_task_dialog(task)

        def _task_chip(task: dict, adt: datetime) -> ft.GestureDetector:
            chip = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            adt.strftime("%H:%M"),
                            size=10,
                            color=ft.Colors.GREEN_700,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            task["title"],
                            size=11,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            task.get("project") or "",
                            size=10,
                            color=ft.Colors.GREY_500,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=1,
                    tight=True,
                ),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.GREEN_500),
                border=ft.border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.GREEN_500)),
                border_radius=4,
                padding=ft.padding.symmetric(horizontal=5, vertical=3),
                margin=ft.margin.only(bottom=2),
                tooltip=t("Double-click to edit"),
            )
            return ft.GestureDetector(
                content=chip,
                on_double_tap=lambda _, t=task: _open_task_from_cal(t),
            )

        # ── Daily view ────────────────────────────────────────────────
        def _build_daily() -> ft.Control:
            ref = _cs["ref"]
            alarm_tasks = _get_alarm_tasks()
            day_tasks = [
                (t, adt) for t in alarm_tasks
                if (adt := _alarm_dt(t)) and adt.date() == ref.date()
            ]
            day_tasks.sort(key=lambda x: x[1])
            if day_tasks:
                chips = [_task_chip(t, adt) for t, adt in day_tasks]
            else:
                chips = [ft.Text(
                    "No active alarms for this day.",
                    size=13,
                    color=ft.Colors.GREY_500,
                    italic=True,
                )]
            return ft.Container(
                content=ft.Column(chips, spacing=6, scroll=ft.ScrollMode.AUTO),
                expand=True,
                padding=ft.padding.symmetric(horizontal=8, vertical=8),
                height=260,
            )

        # ── Weekly view ───────────────────────────────────────────────
        def _build_weekly() -> ft.Control:
            ref    = _cs["ref"]
            monday = ref - timedelta(days=ref.weekday())
            days   = [monday + timedelta(days=i) for i in range(7)]
            alarm_tasks = _get_alarm_tasks()
            today  = datetime.now().date()

            day_cols = []
            for i, day in enumerate(days):
                tasks_for_day = [
                    (t, adt) for t in alarm_tasks
                    if (adt := _alarm_dt(t)) and adt.date() == day.date()
                ]
                tasks_for_day.sort(key=lambda x: x[1])
                is_today = (day.date() == today)
                hdr_color = ft.Colors.ORANGE_400 if is_today else ft.Colors.ON_SURFACE_VARIANT

                chips = ft.Column(
                    [_task_chip(t, adt) for t, adt in tasks_for_day],
                    spacing=3,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                )
                day_col = ft.Container(
                    content=ft.Column(
                        [
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Text(
                                            _DAYS_SHORT_EN[i], size=11,
                                            color=hdr_color,
                                            weight=ft.FontWeight.W_600,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Container(
                                            content=ft.Text(
                                                str(day.day), size=16,
                                                color=hdr_color,
                                                weight=ft.FontWeight.BOLD,
                                                text_align=ft.TextAlign.CENTER,
                                            ),
                                            bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_400) if is_today else None,
                                            border_radius=14,
                                            width=28,
                                            height=28,
                                            alignment=ft.Alignment(0, 0),
                                        ),
                                    ],
                                    spacing=0,
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                padding=ft.padding.symmetric(vertical=4),
                                border=ft.border.only(
                                    bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                                ),
                            ),
                            chips,
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=4, vertical=4),
                    border=ft.border.only(
                        right=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                    ) if i < 6 else None,
                )
                day_cols.append(day_col)

            return ft.Container(
                content=ft.Row(day_cols, expand=True, spacing=0),
                expand=True,
                height=280,
            )

        # ── Monthly view ──────────────────────────────────────────────
        def _build_monthly() -> ft.Control:
            ref   = _cs["ref"]
            year  = ref.year
            month = ref.month

            first_day    = datetime(year, month, 1)
            start_offset = first_day.weekday()   # 0=Mon … 6=Sun
            if month == 12:
                next_m = datetime(year + 1, 1, 1)
            else:
                next_m = datetime(year, month + 1, 1)
            days_in_month = (next_m - first_day).days

            alarm_tasks = _get_alarm_tasks()
            today = datetime.now().date()

            # Build mapping day_number → list[(task, alarm_dt)]
            day_map: dict[int, list] = {}
            for t in alarm_tasks:
                adt = _alarm_dt(t)
                if adt and adt.year == year and adt.month == month:
                    day_map.setdefault(adt.day, []).append((t, adt))

            # Day-of-week header row
            hdr_row = ft.Row(
                [
                    ft.Container(
                        content=ft.Text(
                            d, size=11, weight=ft.FontWeight.W_600,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        expand=True,
                    )
                    for d in _DAYS_SHORT_EN
                ],
                spacing=0,
            )

            grid_rows = [hdr_row]
            week_cells: list = []
            day_num   = 1

            # Fill leading empty cells
            for _ in range(start_offset):
                week_cells.append(ft.Container(expand=True))

            while day_num <= days_in_month:
                cur_date = datetime(year, month, day_num).date()
                is_today = (cur_date == today)
                tasks_here = day_map.get(day_num, [])
                tasks_here.sort(key=lambda x: x[1])

                dot_row = ft.Row(
                    [
                        ft.Container(
                            width=6, height=6,
                            bgcolor=ft.Colors.GREEN_500,
                            border_radius=3,
                        )
                        for _ in tasks_here[:3]
                    ],
                    spacing=2,
                    tight=True,
                ) if tasks_here else ft.Container(height=6)

                tooltip_txt = "\n".join(
                    f"{adt.strftime('%H:%M')} – {t['title']}"
                    for t, adt in tasks_here
                ) if tasks_here else None

                cell = ft.Container(
                    content=ft.Column(
                        [
                            ft.Container(
                                content=ft.Text(
                                    str(day_num),
                                    size=12,
                                    color=ft.Colors.ORANGE_400 if is_today else ft.Colors.ON_SURFACE,
                                    weight=ft.FontWeight.BOLD if is_today else ft.FontWeight.NORMAL,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_400) if is_today else None,
                                border_radius=12,
                                width=24,
                                height=24,
                                alignment=ft.Alignment(0, 0),
                            ),
                            dot_row,
                        ],
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    padding=ft.padding.symmetric(horizontal=2, vertical=4),
                    border=ft.border.all(
                        1,
                        ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                    ),
                    border_radius=4,
                    tooltip=tooltip_txt,
                )
                week_cells.append(cell)
                day_num += 1

                if len(week_cells) == 7:
                    grid_rows.append(ft.Row(week_cells[:], expand=True, spacing=2))
                    week_cells = []

            # Pad last partial week
            if week_cells:
                while len(week_cells) < 7:
                    week_cells.append(ft.Container(expand=True))
                grid_rows.append(ft.Row(week_cells, expand=True, spacing=2))

            return ft.Container(
                content=ft.Column(grid_rows, spacing=3),
                padding=ft.padding.all(8),
            )

        # ── Period label helper ───────────────────────────────────────
        def _period_label() -> str:
            ref = _cs["ref"]
            v   = _cs["view"]
            if v == "daily":
                return f"{_DAYS_EN[ref.weekday()]}, {ref.day:02d} {_MONTHS_EN[ref.month - 1]} {ref.year}"
            elif v == "weekly":
                monday = ref - timedelta(days=ref.weekday())
                sunday = monday + timedelta(days=6)
                if monday.month == sunday.month:
                    return f"{monday.day} – {sunday.day} {_MONTHS_EN[sunday.month - 1]} {sunday.year}"
                return (f"{monday.day} {_MONTHS_SHORT_EN[monday.month - 1]} – "
                        f"{sunday.day} {_MONTHS_SHORT_EN[sunday.month - 1]} {sunday.year}")
            else:
                return f"{_MONTHS_EN[ref.month - 1]} {ref.year}"

        # ── Navigation ────────────────────────────────────────────────
        period_lbl = ft.Text(_period_label(), size=14, weight=ft.FontWeight.W_600, width=260, text_align=ft.TextAlign.CENTER)
        cal_body   = ft.Container(expand=True)

        def _rebuild() -> None:
            period_lbl.value = _period_label()
            year_btn.text = str(_cs["ref"].year)
            v = _cs["view"]
            if v == "daily":
                cal_body.content = _build_daily()
            elif v == "weekly":
                cal_body.content = _build_weekly()
            else:
                cal_body.content = _build_monthly()
            page.update()

        def _nav_prev(_) -> None:
            v = _cs["view"]
            if v == "daily":
                _cs["ref"] -= timedelta(days=1)
            elif v == "weekly":
                _cs["ref"] -= timedelta(weeks=1)
            else:
                ref = _cs["ref"]
                if ref.month == 1:
                    _cs["ref"] = ref.replace(year=ref.year - 1, month=12)
                else:
                    _cs["ref"] = ref.replace(month=ref.month - 1)
            _rebuild()

        def _nav_next(_) -> None:
            v = _cs["view"]
            if v == "daily":
                _cs["ref"] += timedelta(days=1)
            elif v == "weekly":
                _cs["ref"] += timedelta(weeks=1)
            else:
                ref = _cs["ref"]
                if ref.month == 12:
                    _cs["ref"] = ref.replace(year=ref.year + 1, month=1)
                else:
                    _cs["ref"] = ref.replace(month=ref.month + 1)
            _rebuild()

        def _nav_today(_) -> None:
            _cs["ref"] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            _rebuild()

        # ── View-switch buttons ───────────────────────────────────────
        _VIEW_KEYS   = ["daily", "weekly", "monthly"]
        _VIEW_LABELS = {"daily": t("Day"), "weekly": t("Week"), "monthly": t("Month")}
        _view_btns: dict = {}

        def _set_view(vk: str) -> None:
            _cs["view"] = vk
            for k, b in _view_btns.items():
                if k == vk:
                    b.style = ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_600,
                        color=ft.Colors.WHITE,
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    )
                else:
                    b.style = ft.ButtonStyle(
                        color=ft.Colors.GREEN_600,
                        side={ft.ControlState.DEFAULT: ft.BorderSide(1, ft.Colors.GREEN_600)},
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    )
            _rebuild()

        for vk in _VIEW_KEYS:
            b = ft.ElevatedButton(
                _VIEW_LABELS[vk],
                on_click=lambda _, v=vk: _set_view(v),
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.GREEN_600 if vk == "weekly" else ft.Colors.TRANSPARENT,
                    color=ft.Colors.WHITE if vk == "weekly" else ft.Colors.GREEN_600,
                    side=None if vk == "weekly" else {ft.ControlState.DEFAULT: ft.BorderSide(1, ft.Colors.GREEN_600)},
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                ),
                elevation=0 if vk != "weekly" else 2,
            )
            _view_btns[vk] = b

        # ── Year-month picker ─────────────────────────────────────────
        year_btn = ft.TextButton(
            str(_cs["ref"].year),
            style=ft.ButtonStyle(
                color=ft.Colors.ON_SURFACE,
                padding=ft.padding.symmetric(horizontal=6, vertical=4),
                text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600),
            ),
        )

        def _open_year_picker(_) -> None:
            _yp = {"year": _cs["ref"].year}
            year_lbl   = ft.Text(str(_yp["year"]), size=22, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, width=80)
            months_col = ft.Column([], spacing=4)

            def _refresh_months() -> None:
                selected_month = _cs["ref"].month if _yp["year"] == _cs["ref"].year else None
                rows = []
                for row_i in range(4):
                    cells = []
                    for col_i in range(3):
                        m = row_i * 3 + col_i + 1
                        is_sel = (m == selected_month)
                        cells.append(
                            ft.Container(
                                content=ft.Text(
                                    _MONTHS_SHORT_EN[m - 1],
                                    size=13,
                                    weight=ft.FontWeight.W_600 if is_sel else ft.FontWeight.NORMAL,
                                    color=ft.Colors.WHITE if is_sel else ft.Colors.ON_SURFACE,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                bgcolor=ft.Colors.GREEN_600 if is_sel else None,
                                border_radius=6,
                                border=ft.border.all(1, ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE)) if not is_sel else None,
                                width=68,
                                height=34,
                                alignment=ft.Alignment(0, 0),
                                ink=True,
                                on_click=lambda _, mo=m: _pick_month(mo),
                            )
                        )
                    rows.append(ft.Row(cells, spacing=6, alignment=ft.MainAxisAlignment.CENTER))
                months_col.controls = rows
                page.update()

            def _pick_month(m: int) -> None:
                y = _yp["year"]
                try:
                    _cs["ref"] = _cs["ref"].replace(year=y, month=m, day=1)
                except ValueError:
                    _cs["ref"] = _cs["ref"].replace(year=y, month=m, day=1)
                yp_dlg.open = False
                year_btn.text = str(y)
                _rebuild()

            def _year_up(_) -> None:
                _yp["year"] += 1
                year_lbl.value = str(_yp["year"])
                _refresh_months()

            def _year_down(_) -> None:
                _yp["year"] -= 1
                year_lbl.value = str(_yp["year"])
                _refresh_months()

            def _close_yp(_) -> None:
                yp_dlg.open = False
                page.update()

            _refresh_months()

            yp_dlg = ft.AlertDialog(
                modal=True,
                title=None,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.KEYBOARD_ARROW_UP,
                                    icon_size=22,
                                    tooltip=t("Next year"),
                                    on_click=_year_up,
                                ),
                                year_lbl,
                                ft.IconButton(
                                    icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                                    icon_size=22,
                                    tooltip=t("Previous year"),
                                    on_click=_year_down,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        ft.Divider(height=6),
                        months_col,
                    ],
                    tight=True,
                    spacing=8,
                    width=260,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                actions=[
                    ft.TextButton(t("Cancel"), on_click=_close_yp),
                ],
                actions_alignment=ft.MainAxisAlignment.CENTER,
            )
            page.overlay.append(yp_dlg)
            yp_dlg.open = True
            page.update()

        year_btn.on_click = _open_year_picker

        nav_row = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_size=20,
                    tooltip=t("Previous"),
                    on_click=_nav_prev,
                ),
                period_lbl,
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_size=20,
                    tooltip=t("Next"),
                    on_click=_nav_next,
                ),
                ft.Container(width=8),
                year_btn,
                ft.Container(width=4),
                ft.TextButton(
                    "Today",
                    on_click=_nav_today,
                    style=ft.ButtonStyle(color=ft.Colors.ORANGE_400),
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        )

        view_row = ft.Row(
            list(_view_btns.values()),
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        def _close_cal(_) -> None:
            cal_dlg.open = False
            page.update()

        # Build initial body
        cal_body.content = _build_weekly()

        cal_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.CALENDAR_MONTH, color=ft.Colors.GREEN_500),
                    ft.Text(t("Alarm Calendar"), weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Column(
                [
                    ft.Row(
                        [nav_row, ft.Container(expand=True), view_row],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=6),
                    cal_body,
                ],
                tight=True,
                spacing=8,
                width=680,
            ),
            actions=[
                ft.TextButton(t("Close"), on_click=_close_cal),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _cal_ref["dlg"] = cal_dlg
        page.overlay.append(cal_dlg)
        cal_dlg.open = True
        page.update()

    if calendar_btn:
        calendar_btn.on_click = _open_calendar_dialog

    # ── Root ─────────────────────────────────────────────────────────────────

    _start_alarm_checker(output_path, on_fired=_refresh)
    return ft.Column(
        [_search_banner, _filter_banner, list_area],
        spacing=0,
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
