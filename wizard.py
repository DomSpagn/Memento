"""
wizard.py
First-run setup wizard shown when mem_conf.json does not yet exist.
Guides the user through two steps:
  1. Theme selection (Dark / Light)
  2. Output folder selection
"""

import flet as ft
import subprocess
import sys
from pathlib import Path
from typing import Callable


def show_wizard(page: ft.Page, on_complete: Callable[[dict], None]) -> None:
    """Display the first-run setup wizard and call *on_complete* with the
    resulting configuration dictionary when the user finishes."""

    config: dict = {
        "Theme": "Dark",
        "OutputPath": str(Path.home() / "Documents"),
        "StartWith": "TaskTracker",
        "AutoStart": False,
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
                "Step 1 of 4  —  Choose your preferred display mode",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            theme_radio,
        ],
        spacing=10,
    )

    # ── Step 2 – Output folder ───────────────────────────────────
    path_field = ft.TextField(
        label="Installation Path",
        value=config["OutputPath"],
        expand=True,
        on_change=lambda e: config.update({"OutputPath": e.data}),
    )

    async def browse_output(_) -> None:
        path = await dir_picker.get_directory_path(dialog_title="Select Output Folder")
        if path:
            config["OutputPath"] = path
            path_field.value = path
            page.update()

    step_2 = ft.Column(
        [
            ft.Text("Output Folder", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Step 2 of 4  —  Select where Memento will save its files",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            ft.Text(
                "A \"Memento\" folder will be created at the chosen path, "
                "containing TaskTracker and DesignTracker subfolders.",
                size=12,
                color=ft.Colors.GREY_500,
            ),
            ft.Row(
                [
                    path_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip="Browse…",
                        on_click=browse_output,
                    ),
                ]
            ),
        ],
        spacing=10,
    )

    steps = [step_1, step_2]

    # ── Step 3 – Starting application ────────────────────────────
    _assets = Path(__file__).parent

    task_card = ft.Container(
        content=ft.Image(
            src=str(_assets / "Images" / "TaskTracker.png"),
            fit=ft.BoxFit.FILL,
            expand=True,
        ),
        width=200, height=150,
        border=ft.border.all(2, ft.Colors.BLUE_400),
        border_radius=10,
        padding=0,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        ink=True,
        on_click=lambda _: _select_tracker("TaskTracker"),
    )
    design_card = ft.Container(
        content=ft.Image(
            src=str(_assets / "Images" / "DesignTracker.png"),
            fit=ft.BoxFit.FILL,
            expand=True,
        ),
        width=200, height=150,
        border=ft.border.all(2, ft.Colors.with_opacity(0.25, ft.Colors.GREY)),
        border_radius=10,
        padding=0,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        ink=True,
        on_click=lambda _: _select_tracker("DesignTracker"),
    )

    def _select_tracker(key: str) -> None:
        config["StartWith"] = key
        task_card.border   = ft.border.all(2, ft.Colors.BLUE_400 if key == "TaskTracker"   else ft.Colors.with_opacity(0.25, ft.Colors.GREY))
        design_card.border = ft.border.all(2, ft.Colors.BLUE_400 if key == "DesignTracker" else ft.Colors.with_opacity(0.25, ft.Colors.GREY))
        page.update()

    step_3 = ft.Column(
        [
            ft.Text("Starting Application", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Step 4 of 4  —  Choose which tracker to open at startup",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Task Tracker", size=14, weight=ft.FontWeight.W_500,
                                    text_align=ft.TextAlign.CENTER),
                            task_card,
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    ft.Container(width=40),
                    ft.Column(
                        [
                            ft.Text("Design Tracker", size=14, weight=ft.FontWeight.W_500,
                                    text_align=ft.TextAlign.CENTER),
                            design_card,
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        ],
        spacing=10,
    )

    # ── Step 4 – Auto-start ──────────────────────────────────────
    autostart_switch = ft.Switch(
        value=False,
        active_color=ft.Colors.GREEN_400,
        on_change=lambda e: config.update({"AutoStart": e.control.value}),
    )

    step_4 = ft.Column(
        [
            ft.Text("Auto-start", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Step 3 of 4  —  Enable automatic startup at system boot",
                size=12,
                color=ft.Colors.GREY_600,
            ),
            ft.Divider(height=16),
            ft.Text(
                "If enabled, Memento's system-tray process will start automatically "
                "when Windows boots.",
                size=12,
                color=ft.Colors.GREY_500,
            ),
            ft.Row(
                [
                    ft.Text("Enable automatic startup at system boot", size=13),
                    autostart_switch,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ],
        spacing=10,
    )

    steps = [step_1, step_2, step_4, step_3]

    # ── Navigation widgets ───────────────────────────────────────
    step_label   = ft.Text("Step 1 of 4", size=12, color=ft.Colors.GREY_600)
    progress_bar = ft.ProgressBar(value=1/4, expand=True)
    btn_back     = ft.OutlinedButton("← Back",    visible=False)
    btn_next     = ft.ElevatedButton("Next →")
    btn_finish   = ft.ElevatedButton("Finish  ✓", visible=False)

    # Container that swaps step content on navigation
    content_area = ft.Container(content=steps[0], expand=True)

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

    def _create_structure(base: str) -> None:
        root = Path(base) / "Memento"
        for tracker in ("TaskTracker", "DesignTracker"):
            for sub in ("db", "attachments"):
                (root / tracker / sub).mkdir(parents=True, exist_ok=True)

    def on_finish(_) -> None:
        _create_structure(config["OutputPath"])
        if config.get("AutoStart", False):
            script = str(Path(__file__).parent / "tray_app.py")
            subprocess.Popen(
                [sys.executable, script, "--install"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
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
            expand=True,
        ),
        padding=40,
        border_radius=14,
        expand=True,
        margin=ft.margin.symmetric(horizontal=40, vertical=30),
    )

    def _on_resize(e=None) -> None:
        w = page.window.width or 800
        img_w = max(110, min(240, int((w - 160) / 2)))
        img_h = int(img_w * 0.75)
        task_card.width    = img_w
        task_card.height   = img_h
        design_card.width  = img_w
        design_card.height = img_h
        page.update()

    page.on_resize = _on_resize
    _on_resize()

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
