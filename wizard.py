"""
wizard.py
First-run setup wizard shown when mem_conf.json does not yet exist.
Guides the user through two steps:
  1. Theme selection (Dark / Light)
  2. Output folder selection
"""

import flet as ft
from pathlib import Path
from typing import Callable


def show_wizard(page: ft.Page, on_complete: Callable[[dict], None]) -> None:
    """Display the first-run setup wizard and call *on_complete* with the
    resulting configuration dictionary when the user finishes."""

    config: dict = {
        "Theme": "Dark",
        "TaskTrackerPath": str(Path.home() / "Documents" / "MemTaskTracker"),
        "DesignTrackerPath": str(Path.home() / "Documents" / "MemDesignTracker"),
    }
    state: dict = {"step": 0}

    # ── File picker (directory selection for step 2) ─────────────
    dir_picker = ft.FilePicker()
    # NOTE: do NOT add to page.overlay – in Flet 0.80+ get_directory_path
    # is a coroutine that returns the path directly, no overlay needed.

    # ── Step 1 – Theme ───────────────────────────────────────────
    def on_theme_change(e):
        config.update({"Theme": e.data})
        page.theme_mode = (
            ft.ThemeMode.LIGHT if e.data == "Light"
            else ft.ThemeMode.DARK
        )
        page.update()

    theme_radio = ft.RadioGroup(
        value="Dark",
        on_change=on_theme_change,
        content=ft.Column(
            [
                ft.Radio(value="Dark",  label="Dark Mode  🌙"),
                ft.Radio(value="Light", label="Light Mode  ☀️"),
            ],
            spacing=10,
        ),
    )

    step_1 = ft.Column(
        [
            ft.Text("Theme Selection", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Step 1 of 2  —  Choose your preferred display mode",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            theme_radio,
        ],
        spacing=10,
    )

    # ── Step 2 – Output folders ──────────────────────────────────
    task_field = ft.TextField(
        label="Task Tracker Output Path",
        value=config["TaskTrackerPath"],
        expand=True,
        on_change=lambda e: config.update({"TaskTrackerPath": e.data}),
    )
    design_field = ft.TextField(
        label="Design Tracker Output Path",
        value=config["DesignTrackerPath"],
        expand=True,
        on_change=lambda e: config.update({"DesignTrackerPath": e.data}),
    )

    async def browse_task(_) -> None:
        path = await dir_picker.get_directory_path(dialog_title="Select Task Tracker Output Folder")
        if path:
            config["TaskTrackerPath"] = path
            task_field.value = path
            page.update()

    async def browse_design(_) -> None:
        path = await dir_picker.get_directory_path(dialog_title="Select Design Tracker Output Folder")
        if path:
            config["DesignTrackerPath"] = path
            design_field.value = path
            page.update()

    step_2 = ft.Column(
        [
            ft.Text("Output Folders", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Step 2 of 2  —  Select where Memento will save its files",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            ft.Row(
                [
                    task_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip="Browse…",
                        on_click=browse_task,
                    ),
                ]
            ),
            ft.Row(
                [
                    design_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip="Browse…",
                        on_click=browse_design,
                    ),
                ]
            ),
        ],
        spacing=10,
    )

    steps = [step_1, step_2]

    # ── Navigation widgets ───────────────────────────────────────
    step_label   = ft.Text("Step 1 of 2", size=12, color=ft.Colors.GREY_600)
    progress_bar = ft.ProgressBar(value=0.5, expand=True)
    btn_back     = ft.OutlinedButton("← Back",    visible=False)
    btn_next     = ft.ElevatedButton("Next →")
    btn_finish   = ft.ElevatedButton("Finish  ✓", visible=False)

    # Container that swaps step content on navigation
    content_area = ft.Container(content=steps[0], height=300)

    def navigate_to(step: int) -> None:
        state["step"]        = step
        content_area.content = steps[step]
        step_label.value     = f"Step {step + 1} of {len(steps)}"
        progress_bar.value   = (step + 1) / len(steps)
        btn_back.visible     = step > 0
        btn_next.visible     = step < len(steps) - 1
        btn_finish.visible   = step == len(steps) - 1
        page.update()

    def on_next(_) -> None:
        cur = state["step"]
        if cur < len(steps) - 1:
            navigate_to(cur + 1)

    def on_back(_)   -> None: navigate_to(state["step"] - 1)
    def _create_tracker_dirs(base: str) -> None:
        p = Path(base)
        (p / "db").mkdir(parents=True, exist_ok=True)
        (p / "attachments").mkdir(parents=True, exist_ok=True)

    def on_finish(_) -> None:
        _create_tracker_dirs(config["TaskTrackerPath"])
        _create_tracker_dirs(config["DesignTrackerPath"])
        on_complete(config)

    btn_back.on_click   = on_back
    btn_next.on_click   = on_next
    btn_finish.on_click = on_finish

    # ── Wizard card layout ───────────────────────────────────────
    card = ft.Container(
        content=ft.Column(
            [
                # Header
                ft.Row(
                    [
                        ft.Icon(ft.Icons.HISTORY_EDU, size=38, color=ft.Colors.BLUE_400),
                        ft.Column(
                            [
                                ft.Text("Memento", size=26, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    "First-time setup wizard",
                                    size=12,
                                    color=ft.Colors.GREY_600,
                                ),
                            ],
                            spacing=2,
                        ),
                    ],
                    spacing=14,
                ),
                ft.Divider(),
                # Step content (swapped on navigation)
                content_area,
                ft.Divider(),
                # Progress row
                ft.Row([step_label, progress_bar], spacing=12),
                # Navigation buttons
                ft.Row(
                    [btn_back, ft.Container(expand=True), btn_next, btn_finish],
                    spacing=8,
                ),
            ],
            spacing=16,
            width=560,
        ),
        padding=40,
        border_radius=14,
    )

    page.controls.clear()
    page.add(
        ft.Column(
            [card],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )
    )
    page.update()
