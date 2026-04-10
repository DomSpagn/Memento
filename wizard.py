"""
wizard.py
First-run setup wizard shown when mem_conf.json does not yet exist.

Steps:
  1. Language selection
  2. Theme selection
  3. Installation folder
  4. Auto-start
  5. Starting application (tracker choice)
"""

import flet as ft
import subprocess
import sys
from pathlib import Path
from typing import Callable

import translations
from translations import t


def show_wizard(page: ft.Page, on_complete: Callable[[dict], None]) -> None:
    """Display the first-run setup wizard and call *on_complete* with the
    resulting configuration dictionary when the user finishes."""

    config: dict = {
        "Language":   "en",
        "Theme":      "Dark",
        "OutputPath": str(Path.home() / "Documents"),
        "StartWith":  "TaskTracker",
        "AutoStart":  False,
    }
    state: dict = {"step": 0}

    _img_dir = Path(__file__).parent / "Images"
    TOTAL = 5

    # â”€â”€ File picker (reused across rebuilds of step 3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    dir_picker = ft.FilePicker()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 0 â€“ Language  (never rebuilt / never translated)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    _sel = {"lang": "en"}

    def _lang_btn_style(code: str) -> ft.ButtonStyle:
        sel = _sel["lang"] == code
        return ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_100 if sel else ft.Colors.TRANSPARENT,
            side=ft.BorderSide(
                width=2,
                color=ft.Colors.BLUE_400 if sel else ft.Colors.OUTLINE,
            ),
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.padding.symmetric(horizontal=20, vertical=14),
        )

    btn_eng = ft.ElevatedButton(
        content=ft.Column(
            [
                ft.Image(src=str(_img_dir / "eng.png"), width=56, height=56),
                ft.Text("English", size=13, weight=ft.FontWeight.W_500),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        ),
        style=_lang_btn_style("en"),
    )
    btn_ita = ft.ElevatedButton(
        content=ft.Column(
            [
                ft.Image(src=str(_img_dir / "ita.png"), width=56, height=56),
                ft.Text("Italiano", size=13, weight=ft.FontWeight.W_500),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            tight=True,
        ),
        style=_lang_btn_style("it"),
    )

    step0_title = ft.Text("Language", size=20, weight=ft.FontWeight.BOLD)
    step0_sub = ft.Text(
        f"Step 1 of {TOTAL}  \u2014  Choose your preferred language",
        size=12,
        color=ft.Colors.GREY_600,
    )

    step_0 = ft.Column(
        [
            step0_title,
            step0_sub,
            ft.Divider(height=16),
            ft.Row(
                [btn_eng, btn_ita],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=20,
            ),
        ],
        spacing=10,
    )

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # TRANSLATED STEP BUILDERS  (rebuilt when language changes)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def _make_step_theme() -> ft.Column:
        radio = ft.RadioGroup(
            value=config["Theme"],
            on_change=lambda e: _on_theme(e),
            content=ft.Column(
                [
                    ft.Radio(value="Dark",  label=t("Dark Mode  \U0001f319")),
                    ft.Radio(value="Light", label=t("Light Mode  \u2600\ufe0f")),
                ],
                spacing=10,
            ),
        )
        return ft.Column(
            [
                ft.Text(t("Theme Selection"), size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"{t('Step')} 2 {t('of')} {TOTAL}  \u2014  {t('Choose your preferred display mode')}",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Divider(height=16),
                radio,
            ],
            spacing=10,
        )

    def _on_theme(e) -> None:
        config["Theme"] = e.data
        page.theme_mode = (
            ft.ThemeMode.LIGHT if e.data == "Light" else ft.ThemeMode.DARK
        )
        page.update()

    def _make_step_path() -> ft.Column:
        path_field = ft.TextField(
            label=t("Archive Path"),
            value=config["OutputPath"],
            expand=True,
            on_change=lambda e: config.update({"OutputPath": e.data}),
        )

        async def browse(_) -> None:
            path = await dir_picker.get_directory_path(
                dialog_title=t("Select Archive Path")
            )
            if path:
                config["OutputPath"] = path
                path_field.value = path
                page.update()

        return ft.Column(
            [
                ft.Text(t("Archive Path"), size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"{t('Step')} 3 {t('of')} {TOTAL}  \u2014  {t('Select where Memento will save its files')}",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Divider(height=16),
                ft.Text(
                    t('A "Memento" folder will be created at the chosen path, containing TaskTracker and DesignTracker subfolders.'),
                    size=12,
                    color=ft.Colors.GREY_500,
                ),
                ft.Row(
                    [
                        path_field,
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip=t("Browse\u2026"),
                            on_click=browse,
                        ),
                    ]
                ),
            ],
            spacing=10,
        )

    def _make_step_autostart() -> ft.Column:
        switch = ft.Switch(
            value=config.get("AutoStart", False),
            active_color=ft.Colors.GREEN_400,
            on_change=lambda e: config.update({"AutoStart": e.control.value}),
        )
        return ft.Column(
            [
                ft.Text(t("Auto-start"), size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"{t('Step')} 4 {t('of')} {TOTAL}  \u2014  {t('Enable automatic startup at system boot')}",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Divider(height=16),
                ft.Text(
                    t("If enabled, Memento's system-tray process will start automatically when Windows boots."),
                    size=12,
                    color=ft.Colors.GREY_500,
                ),
                ft.Row(
                    [
                        ft.Text(t("Enable automatic startup at system boot"), size=13),
                        switch,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            spacing=10,
        )

    def _make_step_tracker() -> ft.Column:
        task_card = ft.Container(
            content=ft.Image(
                src=str(_img_dir / "TaskTracker.png"),
                fit=ft.BoxFit.FILL,
                expand=True,
            ),
            width=200, height=150,
            border=ft.border.all(
                2,
                ft.Colors.BLUE_400
                if config["StartWith"] == "TaskTracker"
                else ft.Colors.with_opacity(0.25, ft.Colors.GREY),
            ),
            border_radius=10,
            padding=0,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ink=True,
        )
        design_card = ft.Container(
            content=ft.Image(
                src=str(_img_dir / "DesignTracker.png"),
                fit=ft.BoxFit.FILL,
                expand=True,
            ),
            width=200, height=150,
            border=ft.border.all(
                2,
                ft.Colors.BLUE_400
                if config["StartWith"] == "DesignTracker"
                else ft.Colors.with_opacity(0.25, ft.Colors.GREY),
            ),
            border_radius=10,
            padding=0,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ink=True,
        )

        # Store refs so _on_resize can update the latest instances
        state["task_card"]   = task_card
        state["design_card"] = design_card

        def _select_tracker(key: str) -> None:
            config["StartWith"] = key
            task_card.border = ft.border.all(
                2,
                ft.Colors.BLUE_400
                if key == "TaskTracker"
                else ft.Colors.with_opacity(0.25, ft.Colors.GREY),
            )
            design_card.border = ft.border.all(
                2,
                ft.Colors.BLUE_400
                if key == "DesignTracker"
                else ft.Colors.with_opacity(0.25, ft.Colors.GREY),
            )
            page.update()

        task_card.on_click   = lambda _: _select_tracker("TaskTracker")
        design_card.on_click = lambda _: _select_tracker("DesignTracker")

        return ft.Column(
            [
                ft.Text(t("Starting Application"), size=20, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"{t('Step')} 5 {t('of')} {TOTAL}  \u2014  {t('Choose which tracker to open at startup')}",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.Divider(height=16),
                ft.Row(
                    [
                        ft.Column(
                            [
                                # "Task Tracker" and "Design Tracker" intentionally NOT translated
                                ft.Text(
                                    "Task Tracker",
                                    size=14,
                                    weight=ft.FontWeight.W_500,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                task_card,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=8,
                        ),
                        ft.Container(width=40),
                        ft.Column(
                            [
                                ft.Text(
                                    "Design Tracker",
                                    size=14,
                                    weight=ft.FontWeight.W_500,
                                    text_align=ft.TextAlign.CENTER,
                                ),
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

    # â”€â”€ Initial steps list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    steps = [
        step_0,
        _make_step_theme(),
        _make_step_path(),
        _make_step_autostart(),
        _make_step_tracker(),
    ]

    # â”€â”€ Navigation widgets â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    step_label   = ft.Text("Step 1 of 5", size=12, color=ft.Colors.GREY_600)
    progress_bar = ft.ProgressBar(value=1 / TOTAL, expand=True)
    header_sub   = ft.Text(t("First-time setup wizard"), size=12, color=ft.Colors.GREY_600)

    _txt_back   = ft.Text(f"\u2190 {t('Back')}")
    _txt_next   = ft.Text(f"{t('Next')} \u2192")
    _txt_finish = ft.Text(f"{t('Finish')}  \u2713")
    btn_back   = ft.OutlinedButton(content=_txt_back,   visible=False)
    btn_next   = ft.ElevatedButton(content=_txt_next)
    btn_finish = ft.ElevatedButton(content=_txt_finish, visible=False)

    content_area = ft.Container(content=steps[0], expand=True)

    # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _refresh_nav() -> None:
        n = state["step"]
        step_label.value   = f"{t('Step')} {n + 1} {t('of')} {TOTAL}"
        progress_bar.value = (n + 1) / TOTAL
        btn_back.visible   = n > 0
        btn_next.visible   = n < TOTAL - 1
        btn_finish.visible = n == TOTAL - 1
        _txt_back.value   = f"\u2190 {t('Back')}"
        _txt_next.value   = f"{t('Next')} \u2192"
        _txt_finish.value = f"{t('Finish')}  \u2713"
        header_sub.value  = t("First-time setup wizard")

    def navigate_to(step: int) -> None:
        state["step"]        = step
        content_area.content = steps[step]
        _refresh_nav()
        page.update()

    # â”€â”€ Language selection callback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _select_lang(code: str) -> None:
        _sel["lang"] = code
        config["Language"] = code
        translations.set_lang(code)
        btn_eng.style = _lang_btn_style("en")
        btn_ita.style = _lang_btn_style("it")
        # Update translatable texts in the static Language step
        step0_title.value = t("Language")
        step0_sub.value = (
            f"{t('Step')} 1 {t('of')} {TOTAL}  \u2014"
            f"  {t('Choose your preferred language')}"
        )
        # Rebuild all translated steps in-place
        steps[1] = _make_step_theme()
        steps[2] = _make_step_path()
        steps[3] = _make_step_autostart()
        steps[4] = _make_step_tracker()
        # If we are already past step 0, refresh displayed content
        if state["step"] > 0:
            content_area.content = steps[state["step"]]
        _refresh_nav()
        page.update()

    btn_eng.on_click = lambda _: _select_lang("en")
    btn_ita.on_click = lambda _: _select_lang("it")

    # â”€â”€ Navigation callbacks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def on_next(_) -> None:
        if state["step"] < TOTAL - 1:
            navigate_to(state["step"] + 1)

    def on_back(_) -> None:
        navigate_to(state["step"] - 1)

    def _create_structure(base: str) -> None:
        root = Path(base) / "Memento"
        for tracker in ("TaskTracker", "DesignTracker"):
            for sub in ("db", "attachments"):
                (root / tracker / sub).mkdir(parents=True, exist_ok=True)

    def on_finish(_) -> None:
        _create_structure(config["OutputPath"])
        config["OutputPath"] = str(Path(config["OutputPath"]) / "Memento")
        if config.get("AutoStart", False):
            if getattr(sys, 'frozen', False):
                # Packaged: launch the installed MementoTray.exe
                tray_exe = str(Path(sys.executable).parent / "MementoTray.exe")
                subprocess.Popen([tray_exe, "--install"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                script = str(Path(__file__).parent / "tray_app.py")
                subprocess.Popen(
                    [sys.executable, script, "--install"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
        on_complete(config)

    btn_back.on_click   = on_back
    btn_next.on_click   = on_next
    btn_finish.on_click = on_finish

    # â”€â”€ Wizard card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                                header_sub,
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

    # â”€â”€ Responsive resize â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_resize(e=None) -> None:
        w = page.window.width or 800
        img_w = max(110, min(240, int((w - 160) / 2)))
        img_h = int(img_w * 0.75)
        if "task_card" in state:
            state["task_card"].width    = img_w
            state["task_card"].height   = img_h
            state["design_card"].width  = img_w
            state["design_card"].height = img_h
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
