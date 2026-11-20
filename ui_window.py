"""Painel interativo e guia do HIDPower em Tkinter com atualização in-place e PT-BR/EN."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

from PIL import Image, ImageTk

from app_config import AppConfig, get_data_dir, is_startup_enabled
from battery_readers import DeviceBatteryStatus, scan_hid_summary
from i18n import LANGUAGE_LABELS, normalize_language, tr
from icon_renderer import render_app_badge_image, render_battery_icon, render_hip_emblem
from monitor_utils import enumerate_monitors, get_primary_monitor

BG_MAIN = "#0F172A"
BG_CARD = "#1E293B"
BG_ELEVATED = "#273549"
BORDER_COLOR = "#334155"
FG_TEXT = "#F8FAFC"
FG_MUTED = "#94A3B8"
ACCENT_BLUE = "#38BDF8"
ACCENT_GREEN = "#22C55E"
ACCENT_YELLOW = "#FACC15"
ACCENT_RED = "#EF4444"
BTN_SHOW_BG = "#0369A1"
BTN_SHOW_ACTIVE = "#0284C7"


@dataclass
class _DeviceCardWidgets:
    device_id: str
    card: tk.Frame
    icon_label: tk.Label
    pct_label: tk.Label
    vis_button: tk.Button
    title_label: tk.Label
    detail_label: tk.Label
    meta_label: tk.Label
    photo_ref: ImageTk.PhotoImage | None = None
    last_visual_key: tuple[object, ...] | None = None


def open_windows_taskbar_settings(lang: str = "pt-BR") -> None:
    """Abre Configurações > Barra de Tarefas no Windows 10/11."""
    try:
        os.startfile("ms-settings:taskbar")
    except Exception as exc:
        messagebox.showinfo(
            tr(lang, "taskbar_err_title"),
            tr(lang, "taskbar_err_msg", err=exc),
        )


def open_data_folder() -> None:
    """Abre a pasta ativa de dados do HIDPower no Windows Explorer."""
    folder = get_data_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))
    except Exception as exc:
        messagebox.showerror("HIDPower", str(exc))


class DashboardWindow:
    """Janela interativa do HIDPower com abas Dispositivos, Configurações, Fixação e Sobre."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        get_config: Callable[[], AppConfig],
        get_statuses: Callable[[], list[DeviceBatteryStatus]],
        should_show_device: Callable[[DeviceBatteryStatus, AppConfig], bool],
        on_refresh: Callable[[], None],
        on_toggle_startup: Callable[[], bool],
        on_toggle_hide_unsupported: Callable[[bool], None],
        on_change_interval: Callable[[int], None],
        on_change_show_on_start: Callable[[bool], None],
        on_change_widget_monitor: Callable[[str], None] | None = None,
        on_reset_widget_position: Callable[[], None] | None = None,
        on_change_language: Callable[[str], None] | None = None,
        on_toggle_device_visibility: Callable[[str, bool], None] | None = None,
    ) -> None:
        self._root = root
        self._get_config = get_config
        self._get_statuses = get_statuses
        self._should_show_device = should_show_device
        self._on_refresh = on_refresh
        self._on_toggle_startup = on_toggle_startup
        self._on_toggle_hide_unsupported = on_toggle_hide_unsupported
        self._on_change_interval = on_change_interval
        self._on_change_show_on_start = on_change_show_on_start
        self._on_change_widget_monitor = on_change_widget_monitor or (lambda _m: None)
        self._on_reset_widget_position = on_reset_widget_position or (lambda: None)
        self._on_change_language = on_change_language or (lambda _l: None)
        self._on_toggle_device_visibility = on_toggle_device_visibility or (
            lambda _did, _vis: None
        )

        self._top: tk.Toplevel | None = None
        self._notebook: ttk.Notebook | None = None
        self._cards_frame: tk.Frame | None = None
        self._cards_canvas: tk.Canvas | None = None
        self._window_icon_photo: ImageTk.PhotoImage | None = None
        self._header_emblem_photo: ImageTk.PhotoImage | None = None
        self._ui_scale: float = 1.0

        cfg = self._get_config()
        self._current_lang: str = normalize_language(cfg.language)

        self._startup_var = tk.BooleanVar(master=self._root, value=is_startup_enabled())
        self._hide_unsup_var = tk.BooleanVar(
            master=self._root, value=cfg.hide_unsupported
        )
        self._dont_show_var = tk.BooleanVar(
            master=self._root, value=not cfg.show_guide_on_start
        )
        self._interval_var = tk.StringVar(
            master=self._root, value=f"{cfg.interval_seconds}s"
        )
        self._lang_var = tk.StringVar(
            master=self._root, value=LANGUAGE_LABELS[self._current_lang]
        )
        self._widget_monitor_var = tk.StringVar(
            master=self._root, value=tr(self._current_lang, "widget_disabled")
        )
        self._data_dir_var = tk.StringVar(
            master=self._root, value=str(get_data_dir())
        )
        self._widget_monitor_combo: ttk.Combobox | None = None
        self._widget_monitor_map: dict[str, str] = {}

        # Cache de widgets dos cards para atualização in-place (zero flicker)
        self._card_widgets: dict[str, _DeviceCardWidgets] = {}
        self._rendered_order: list[str] = []
        self._empty_card: tk.Frame | None = None
        self._empty_title_lbl: tk.Label | None = None
        self._empty_sub_lbl: tk.Label | None = None

        # Referências de widgets traduzíveis dinamicamente
        self._tab_devices: tk.Frame | None = None
        self._tab_settings: tk.Frame | None = None
        self._tab_pin: tk.Frame | None = None
        self._tab_about: tk.Frame | None = None
        self._btn_refresh: tk.Button | None = None
        self._chk_dont_show: tk.Checkbutton | None = None
        self._btn_minimize: tk.Button | None = None
        self._settings_title_lbl: tk.Label | None = None
        self._lbl_lang: tk.Label | None = None
        self._lbl_interval: tk.Label | None = None
        self._lbl_monitor: tk.Label | None = None
        self._btn_reanchor: tk.Button | None = None
        self._chk_startup: tk.Checkbutton | None = None
        self._chk_hide_unsup: tk.Checkbutton | None = None
        self._lbl_folder_title: tk.Label | None = None
        self._btn_open_folder: tk.Button | None = None
        self._pin_heading_lbl: tk.Label | None = None
        self._pin_intro_lbl: tk.Label | None = None
        self._pin_step_widgets: list[tuple[tk.Label, tk.Label]] = []
        self._btn_taskbar_settings: tk.Button | None = None
        self._about_heading_lbl: tk.Label | None = None
        self._about_section_widgets: list[tuple[tk.Label, tk.Label]] = []
        self._btn_hid_diag: tk.Button | None = None

    def is_visible(self) -> bool:
        """Retorna True se a janela estiver criada e visível."""
        return bool(
            self._top is not None
            and self._top.winfo_exists()
            and self._top.state() != "withdrawn"
        )

    def show(self, tab_index: int = 0) -> None:
        """Abre ou traz a janela para frente na aba especificada."""
        if self._top is None or not self._top.winfo_exists():
            self._build_window()

        assert self._top is not None
        self.refresh_view()
        if self._notebook is not None and 0 <= tab_index < self._notebook.index("end"):
            self._notebook.select(tab_index)

        self._top.deiconify()
        self._top.lift()
        self._top.focus_force()

    def hide(self) -> None:
        """Oculta a janela mantendo o monitor ativo na bandeja."""
        if self._top is not None and self._top.winfo_exists():
            self._top.withdraw()

    def _configure_styles(self) -> None:
        style = ttk.Style(self._top)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Dark.TNotebook", background=BG_MAIN, borderwidth=0)
        style.configure(
            "Dark.TNotebook.Tab",
            background=BG_CARD,
            foreground=FG_MUTED,
            padding=(14, 8),
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", BG_ELEVATED)],
            foreground=[("selected", FG_TEXT)],
        )
        style.configure(
            "Dark.TCombobox",
            fieldbackground=BG_ELEVATED,
            background=BG_ELEVATED,
            foreground=FG_TEXT,
            arrowcolor=FG_TEXT,
            borderwidth=0,
        )

    def _build_window(self) -> None:
        primary = get_primary_monitor(enumerate_monitors())
        scale = primary.scale if primary else 1.0
        self._ui_scale = scale
        work_w = (primary.work_rect[2] - primary.work_rect[0]) if primary else 1280
        work_h = (primary.work_rect[3] - primary.work_rect[1]) if primary else 800
        win_w = min(int(round(760 * scale)), max(680, work_w - 40))
        win_h = min(int(round(610 * scale)), max(520, work_h - 60))

        top = tk.Toplevel(self._root)
        self._top = top
        top.title("HIDPower")
        top.geometry(f"{win_w}x{win_h}")
        top.minsize(min(680, win_w), min(520, win_h))
        top.configure(bg=BG_MAIN)
        top.protocol("WM_DELETE_WINDOW", self.hide)

        try:
            self._window_icon_photo = ImageTk.PhotoImage(
                render_app_badge_image(64), master=top
            )
            top.iconphoto(False, self._window_icon_photo)
        except Exception:
            pass

        self._configure_styles()

        # Cabeçalho enxuto com emblema H [Bateria-I] P + título HIDPower (sem subtítulo)
        header = tk.Frame(top, bg=BG_MAIN, padx=20, pady=12)
        header.pack(fill=tk.X)

        brand_row = tk.Frame(header, bg=BG_MAIN)
        brand_row.pack(fill=tk.X)

        try:
            emblem_h = max(28, int(round(36 * scale)))
            self._header_emblem_photo = ImageTk.PhotoImage(
                render_hip_emblem(height=emblem_h), master=top
            )
            tk.Label(brand_row, image=self._header_emblem_photo, bg=BG_MAIN).pack(
                side=tk.LEFT, padx=(0, 12)
            )
        except Exception:
            pass

        tk.Label(
            brand_row,
            text="HIDPower",
            bg=BG_MAIN,
            fg=FG_TEXT,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT)

        # Notebook com 4 abas
        notebook = ttk.Notebook(top, style="Dark.TNotebook")
        notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        self._notebook = notebook

        self._tab_devices = tk.Frame(notebook, bg=BG_MAIN)
        self._tab_settings = tk.Frame(notebook, bg=BG_MAIN)
        self._tab_pin = tk.Frame(notebook, bg=BG_MAIN)
        self._tab_about = tk.Frame(notebook, bg=BG_MAIN)

        notebook.add(self._tab_devices, text="")
        notebook.add(self._tab_settings, text="")
        notebook.add(self._tab_pin, text="")
        notebook.add(self._tab_about, text="")

        self._build_devices_tab(self._tab_devices)
        self._build_settings_tab(self._tab_settings)
        self._build_pin_tab(self._tab_pin)
        self._build_about_tab(self._tab_about)

        # Rodapé persistente
        footer = tk.Frame(
            top,
            bg=BG_CARD,
            padx=16,
            pady=10,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        footer.pack(fill=tk.X, side=tk.BOTTOM)

        self._chk_dont_show = tk.Checkbutton(
            footer,
            text="",
            variable=self._dont_show_var,
            command=self._handle_dont_show_toggle,
            bg=BG_CARD,
            fg=FG_TEXT,
            selectcolor=BG_MAIN,
            activebackground=BG_CARD,
            activeforeground=FG_TEXT,
            font=("Segoe UI", 9),
        )
        self._chk_dont_show.pack(side=tk.LEFT)

        self._btn_minimize = tk.Button(
            footer,
            text="",
            command=self.hide,
            bg=ACCENT_BLUE,
            fg="#0F172A",
            activebackground="#7DD3FC",
            activeforeground="#0F172A",
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_minimize.pack(side=tk.RIGHT)

        self._card_widgets.clear()
        self._rendered_order.clear()
        self._empty_card = None
        self.apply_language(self._current_lang)

    def _build_devices_tab(self, parent: tk.Frame) -> None:
        # Aba Dispositivos limpa: apenas botão Atualizar agora + lista de cards
        top_bar = tk.Frame(parent, bg=BG_MAIN, padx=4, pady=8)
        top_bar.pack(fill=tk.X)

        self._btn_refresh = tk.Button(
            top_bar,
            text="",
            command=self._handle_refresh,
            bg=ACCENT_GREEN,
            fg="#052E16",
            activebackground="#4ADE80",
            activeforeground="#052E16",
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_refresh.pack(side=tk.LEFT)

        list_wrap = tk.Frame(parent, bg=BG_MAIN)
        list_wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        canvas = tk.Canvas(list_wrap, bg=BG_MAIN, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=canvas.yview)
        cards_frame = tk.Frame(canvas, bg=BG_MAIN)

        cards_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=cards_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(window_id, width=e.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._cards_canvas = canvas
        self._cards_frame = cards_frame

    def _build_settings_tab(self, parent: tk.Frame) -> None:
        box = tk.Frame(
            parent,
            bg=BG_CARD,
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=(10, 4))

        self._settings_title_lbl = tk.Label(
            box,
            text="",
            bg=BG_CARD,
            fg=FG_TEXT,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self._settings_title_lbl.pack(fill=tk.X, pady=(0, 12))

        # Linha 1: Idioma + Intervalo
        row1 = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=10)
        row1.pack(fill=tk.X, pady=(0, 10))

        self._lbl_lang = tk.Label(
            row1,
            text="",
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            font=("Segoe UI", 9, "bold"),
        )
        self._lbl_lang.pack(side=tk.LEFT, padx=(0, 8))

        lang_combo = ttk.Combobox(
            row1,
            textvariable=self._lang_var,
            values=tuple(LANGUAGE_LABELS.values()),
            width=20,
            state="readonly",
            style="Dark.TCombobox",
        )
        lang_combo.pack(side=tk.LEFT)
        lang_combo.bind("<<ComboboxSelected>>", self._handle_language_change)

        int_combo = ttk.Combobox(
            row1,
            textvariable=self._interval_var,
            values=("15s", "30s", "60s", "120s"),
            width=7,
            state="readonly",
            style="Dark.TCombobox",
        )
        int_combo.pack(side=tk.RIGHT)
        int_combo.bind("<<ComboboxSelected>>", self._handle_interval_change)

        self._lbl_interval = tk.Label(
            row1,
            text="",
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            font=("Segoe UI", 9, "bold"),
        )
        self._lbl_interval.pack(side=tk.RIGHT, padx=(16, 8))

        # Linha 2: Exibir widget no Monitor + Reencaixar
        row2 = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=10)
        row2.pack(fill=tk.X, pady=(0, 10))

        self._lbl_monitor = tk.Label(
            row2,
            text="",
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            font=("Segoe UI", 9, "bold"),
        )
        self._lbl_monitor.pack(side=tk.LEFT, padx=(0, 8))

        mon_combo = ttk.Combobox(
            row2,
            textvariable=self._widget_monitor_var,
            values=(tr(self._current_lang, "widget_disabled"),),
            width=34,
            state="readonly",
            style="Dark.TCombobox",
        )
        mon_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        mon_combo.bind("<<ComboboxSelected>>", self._handle_widget_monitor_change)
        self._widget_monitor_combo = mon_combo

        self._btn_reanchor = tk.Button(
            row2,
            text="",
            command=self._handle_reset_widget_position,
            bg=BG_CARD,
            fg=FG_TEXT,
            activebackground=BORDER_COLOR,
            activeforeground=FG_TEXT,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        self._btn_reanchor.pack(side=tk.RIGHT, padx=(8, 0))

        # Linha 3: Checkboxes (Startup + Ocultar sem telemetria)
        row3 = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=10)
        row3.pack(fill=tk.X, pady=(0, 10))

        self._chk_startup = tk.Checkbutton(
            row3,
            text="",
            variable=self._startup_var,
            command=self._handle_startup_toggle,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            selectcolor=BG_MAIN,
            activebackground=BG_ELEVATED,
            activeforeground=FG_TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self._chk_startup.pack(fill=tk.X, pady=(0, 4))

        self._chk_hide_unsup = tk.Checkbutton(
            row3,
            text="",
            variable=self._hide_unsup_var,
            command=self._handle_hide_unsup_toggle,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            selectcolor=BG_MAIN,
            activebackground=BG_ELEVATED,
            activeforeground=FG_TEXT,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self._chk_hide_unsup.pack(fill=tk.X)

        # Linha 4: Pasta de dados HIDPower + botão Abrir pasta
        row4 = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=10)
        row4.pack(fill=tk.X)

        self._lbl_folder_title = tk.Label(
            row4,
            text="",
            bg=BG_ELEVATED,
            fg=ACCENT_BLUE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self._lbl_folder_title.pack(fill=tk.X, pady=(0, 4))

        path_row = tk.Frame(row4, bg=BG_ELEVATED)
        path_row.pack(fill=tk.X)

        tk.Label(
            path_row,
            textvariable=self._data_dir_var,
            bg=BG_MAIN,
            fg=FG_MUTED,
            font=("Consolas", 9),
            anchor="w",
            padx=8,
            pady=5,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._btn_open_folder = tk.Button(
            path_row,
            text="",
            command=open_data_folder,
            bg=ACCENT_BLUE,
            fg="#0F172A",
            activebackground="#7DD3FC",
            activeforeground="#0F172A",
            relief=tk.FLAT,
            padx=12,
            pady=5,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_open_folder.pack(side=tk.RIGHT)

    def _build_pin_tab(self, parent: tk.Frame) -> None:
        box = tk.Frame(
            parent,
            bg=BG_CARD,
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=(10, 4))

        self._pin_heading_lbl = tk.Label(
            box,
            text="",
            bg=BG_CARD,
            fg=FG_TEXT,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self._pin_heading_lbl.pack(fill=tk.X, pady=(0, 8))

        self._pin_intro_lbl = tk.Label(
            box,
            text="",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=int(round(650 * self._ui_scale)),
            anchor="w",
        )
        self._pin_intro_lbl.pack(fill=tk.X, pady=(0, 12))

        self._pin_step_widgets.clear()
        for _ in range(3):
            card = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=10)
            card.pack(fill=tk.X, pady=(0, 10))
            hl = tk.Label(
                card,
                text="",
                bg=BG_ELEVATED,
                fg=ACCENT_BLUE,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            hl.pack(fill=tk.X)
            bl = tk.Label(
                card,
                text="",
                bg=BG_ELEVATED,
                fg=FG_TEXT,
                font=("Segoe UI", 10),
                justify=tk.LEFT,
                wraplength=int(round(620 * self._ui_scale)),
                anchor="w",
            )
            bl.pack(fill=tk.X, pady=(4, 0))
            self._pin_step_widgets.append((hl, bl))

        self._btn_taskbar_settings = tk.Button(
            box,
            text="",
            command=lambda: open_windows_taskbar_settings(self._current_lang),
            bg=ACCENT_BLUE,
            fg="#0F172A",
            activebackground="#7DD3FC",
            activeforeground="#0F172A",
            relief=tk.FLAT,
            padx=14,
            pady=7,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self._btn_taskbar_settings.pack(anchor="w", pady=(4, 0))

    def _build_about_tab(self, parent: tk.Frame) -> None:
        box = tk.Frame(
            parent,
            bg=BG_CARD,
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=(10, 4))

        self._about_heading_lbl = tk.Label(
            box,
            text="",
            bg=BG_CARD,
            fg=FG_TEXT,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self._about_heading_lbl.pack(fill=tk.X, pady=(0, 8))

        self._about_section_widgets.clear()
        for _ in range(3):
            card = tk.Frame(box, bg=BG_ELEVATED, padx=12, pady=9)
            card.pack(fill=tk.X, pady=(0, 9))
            hl = tk.Label(
                card,
                text="",
                bg=BG_ELEVATED,
                fg=ACCENT_BLUE,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            hl.pack(fill=tk.X)
            bl = tk.Label(
                card,
                text="",
                bg=BG_ELEVATED,
                fg=FG_TEXT,
                font=("Segoe UI", 9),
                justify=tk.LEFT,
                wraplength=int(round(630 * self._ui_scale)),
                anchor="w",
            )
            bl.pack(fill=tk.X, pady=(3, 0))
            self._about_section_widgets.append((hl, bl))

        self._btn_hid_diag = tk.Button(
            box,
            text="",
            command=self._handle_open_hid_diag,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            activebackground=BORDER_COLOR,
            activeforeground=FG_TEXT,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_hid_diag.pack(anchor="w", pady=(4, 0))

    def apply_language(self, lang: str) -> None:
        """Aplica imediatamente as traduções PT-BR ou EN em todas as abas e controles."""
        lang = normalize_language(lang)
        self._current_lang = lang
        if self._top is None or not self._top.winfo_exists():
            return

        self._top.title(tr(lang, "app_title"))

        if self._notebook is not None:
            for idx, key in enumerate(
                ("tab_devices", "tab_settings", "tab_pin", "tab_about")
            ):
                self._notebook.tab(idx, text=tr(lang, key))

        if self._btn_refresh is not None:
            self._btn_refresh.configure(text=tr(lang, "btn_refresh"))
        if self._chk_dont_show is not None:
            self._chk_dont_show.configure(text=tr(lang, "chk_dont_show"))
        if self._btn_minimize is not None:
            self._btn_minimize.configure(text=tr(lang, "btn_minimize"))

        if self._settings_title_lbl is not None:
            self._settings_title_lbl.configure(text=tr(lang, "settings_title"))
        if self._lbl_lang is not None:
            self._lbl_lang.configure(text=tr(lang, "settings_language_label"))
        if self._lbl_interval is not None:
            self._lbl_interval.configure(text=tr(lang, "settings_interval_label"))
        if self._lbl_monitor is not None:
            self._lbl_monitor.configure(text=tr(lang, "settings_monitor_label"))
        if self._btn_reanchor is not None:
            self._btn_reanchor.configure(text=tr(lang, "btn_reanchor"))
        if self._chk_startup is not None:
            self._chk_startup.configure(text=tr(lang, "chk_startup"))
        if self._chk_hide_unsup is not None:
            self._chk_hide_unsup.configure(text=tr(lang, "chk_hide_unsupported"))
        if self._lbl_folder_title is not None:
            self._lbl_folder_title.configure(text=tr(lang, "settings_folder_title"))
        if self._btn_open_folder is not None:
            self._btn_open_folder.configure(text=tr(lang, "btn_open_folder"))

        if self._pin_heading_lbl is not None:
            self._pin_heading_lbl.configure(text=tr(lang, "pin_heading"))
        if self._pin_intro_lbl is not None:
            self._pin_intro_lbl.configure(text=tr(lang, "pin_intro"))
        for idx, (hl, bl) in enumerate(self._pin_step_widgets, start=1):
            hl.configure(text=tr(lang, f"pin_step{idx}_title"))
            bl.configure(text=tr(lang, f"pin_step{idx}_body"))
        if self._btn_taskbar_settings is not None:
            self._btn_taskbar_settings.configure(text=tr(lang, "btn_taskbar_settings"))

        if self._about_heading_lbl is not None:
            self._about_heading_lbl.configure(text=tr(lang, "about_heading"))
        for idx, (hl, bl) in enumerate(self._about_section_widgets, start=1):
            hl.configure(text=tr(lang, f"about_s{idx}_title"))
            bl.configure(text=tr(lang, f"about_s{idx}_body"))
        if self._btn_hid_diag is not None:
            self._btn_hid_diag.configure(text=tr(lang, "btn_hid_diag"))

        if self._empty_title_lbl is not None:
            self._empty_title_lbl.configure(text=tr(lang, "empty_title"))
        if self._empty_sub_lbl is not None:
            self._empty_sub_lbl.configure(text=tr(lang, "empty_subtitle"))

    def _create_device_card(self, parent: tk.Frame, device_id: str) -> _DeviceCardWidgets:
        card = tk.Frame(
            parent,
            bg=BG_CARD,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )

        lbl_icon = tk.Label(card, bg=BG_CARD)
        lbl_icon.pack(side=tk.LEFT, padx=(0, 14))

        right_col = tk.Frame(card, bg=BG_CARD)
        right_col.pack(side=tk.RIGHT, padx=(10, 0))

        pct_lbl = tk.Label(
            right_col,
            text="--",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 14, "bold"),
            anchor="e",
        )
        pct_lbl.pack(anchor="e")

        vis_btn = tk.Button(
            right_col,
            text="",
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            activebackground=BORDER_COLOR,
            activeforeground=FG_TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=3,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        vis_btn.pack(anchor="e", pady=(4, 0))

        mid_col = tk.Frame(card, bg=BG_CARD)
        mid_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_lbl = tk.Label(
            mid_col,
            text="",
            bg=BG_CARD,
            fg=FG_TEXT,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        title_lbl.pack(fill=tk.X)

        detail_lbl = tk.Label(
            mid_col,
            text="",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=int(round(430 * self._ui_scale)),
            justify=tk.LEFT,
        )
        detail_lbl.pack(fill=tk.X, pady=(2, 2))

        meta_lbl = tk.Label(
            mid_col,
            text="",
            bg=BG_CARD,
            fg=FG_MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        meta_lbl.pack(fill=tk.X)

        return _DeviceCardWidgets(
            device_id=device_id,
            card=card,
            icon_label=lbl_icon,
            pct_label=pct_lbl,
            vis_button=vis_btn,
            title_label=title_lbl,
            detail_label=detail_lbl,
            meta_label=meta_lbl,
        )

    def _update_device_card(
        self, cw: _DeviceCardWidgets, status: DeviceBatteryStatus, cfg: AppConfig
    ) -> None:
        lang = normalize_language(cfg.language)
        visual_key = (
            status.icon_kind,
            status.percentage,
            status.charging,
            status.is_sleeping,
            status.last_known_percentage if status.is_sleeping else None,
        )
        if cw.last_visual_key != visual_key:
            card_icon_px = max(40, int(round(48 * self._ui_scale)))
            pil_icon = render_battery_icon(
                status.icon_kind,
                status.percentage,
                charging=status.charging,
                sleeping=status.is_sleeping,
                last_known_percentage=status.last_known_percentage,
            ).resize((card_icon_px, card_icon_px), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(pil_icon, master=self._top)
            cw.photo_ref = photo
            cw.icon_label.configure(image=photo)
            cw.last_visual_key = visual_key

        if status.percentage is not None:
            pct_text = f"{status.percentage}%"
            if status.percentage > 20:
                pct_color = ACCENT_GREEN
            elif status.percentage >= 11:
                pct_color = ACCENT_YELLOW
            else:
                pct_color = ACCENT_RED
        elif status.is_sleeping:
            pct_text = (
                tr(lang, "card_sleep_with_pct", pct=status.last_known_percentage)
                if status.last_known_percentage is not None
                else tr(lang, "card_sleep")
            )
            pct_color = FG_MUTED
        else:
            pct_text = "--"
            pct_color = FG_MUTED

        cw.pct_label.configure(text=pct_text, fg=pct_color)

        visible_in_tray = self._should_show_device(status, cfg)
        if visible_in_tray:
            cw.vis_button.configure(
                text=tr(lang, "btn_hide"),
                bg=BG_ELEVATED,
                fg=FG_TEXT,
                activebackground=BORDER_COLOR,
                activeforeground=FG_TEXT,
                command=lambda d=status.device_id: self._on_toggle_device_visibility(d, False),
            )
        else:
            cw.vis_button.configure(
                text=tr(lang, "btn_show"),
                bg=BTN_SHOW_BG,
                fg=FG_TEXT,
                activebackground=BTN_SHOW_ACTIVE,
                activeforeground=FG_TEXT,
                command=lambda d=status.device_id: self._on_toggle_device_visibility(d, True),
            )

        cw.title_label.configure(text=f"{status.display_name}  ({status.vid_pid})")
        cw.detail_label.configure(text=status.localized_detail(lang))

        last_txt = (
            tr(
                lang,
                "last_reading_at",
                pct=status.last_known_percentage,
                when=status.last_known_at or "--",
            )
            if status.last_known_percentage is not None
            else tr(lang, "na")
        )
        cw.meta_label.configure(
            text=tr(lang, "card_last_updated", last=last_txt, updated=status.updated_at)
        )

    def refresh_view(self) -> None:
        """Atualiza controles e cartões in-place sem destruir widgets existentes."""
        if self._top is None or not self._top.winfo_exists():
            return

        cfg = self._get_config()
        lang = normalize_language(cfg.language)
        if lang != self._current_lang:
            self.apply_language(lang)

        self._startup_var.set(is_startup_enabled())
        self._hide_unsup_var.set(cfg.hide_unsupported)
        self._dont_show_var.set(not cfg.show_guide_on_start)
        self._interval_var.set(f"{cfg.interval_seconds}s")
        self._lang_var.set(LANGUAGE_LABELS[lang])
        self._data_dir_var.set(str(get_data_dir()))

        monitors = enumerate_monitors()
        disabled_label = tr(lang, "widget_disabled")
        options = [disabled_label]
        mon_map: dict[str, str] = {disabled_label: ""}
        selected_label = disabled_label
        for mon in monitors:
            lbl = mon.format_label(lang)
            options.append(lbl)
            mon_map[lbl] = mon.device_name
            if cfg.widget_monitor and mon.device_name.lower() == cfg.widget_monitor.lower():
                selected_label = lbl
        if cfg.widget_monitor and selected_label == disabled_label:
            offline_lbl = tr(lang, "widget_monitor_offline", device=cfg.widget_monitor)
            options.append(offline_lbl)
            mon_map[offline_lbl] = cfg.widget_monitor
            selected_label = offline_lbl
        self._widget_monitor_map = mon_map
        if self._widget_monitor_combo is not None:
            self._widget_monitor_combo["values"] = tuple(options)
        self._widget_monitor_var.set(selected_label)

        if self._cards_frame is None:
            return

        statuses = self._get_statuses()
        if not statuses:
            for cw in self._card_widgets.values():
                cw.card.destroy()
            self._card_widgets.clear()
            self._rendered_order.clear()

            if self._empty_card is None or not self._empty_card.winfo_exists():
                empty = tk.Frame(
                    self._cards_frame,
                    bg=BG_CARD,
                    padx=16,
                    pady=24,
                    highlightthickness=1,
                    highlightbackground=BORDER_COLOR,
                )
                empty.pack(fill=tk.X, pady=6)
                t_lbl = tk.Label(
                    empty,
                    text=tr(lang, "empty_title"),
                    bg=BG_CARD,
                    fg=FG_TEXT,
                    font=("Segoe UI", 10, "bold"),
                )
                t_lbl.pack(anchor="w")
                s_lbl = tk.Label(
                    empty,
                    text=tr(lang, "empty_subtitle"),
                    bg=BG_CARD,
                    fg=FG_MUTED,
                    font=("Segoe UI", 9),
                )
                s_lbl.pack(anchor="w", pady=(4, 0))
                self._empty_card = empty
                self._empty_title_lbl = t_lbl
                self._empty_sub_lbl = s_lbl
            else:
                if self._empty_title_lbl is not None:
                    self._empty_title_lbl.configure(text=tr(lang, "empty_title"))
                if self._empty_sub_lbl is not None:
                    self._empty_sub_lbl.configure(text=tr(lang, "empty_subtitle"))
            return

        if self._empty_card is not None:
            if self._empty_card.winfo_exists():
                self._empty_card.destroy()
            self._empty_card = None
            self._empty_title_lbl = None
            self._empty_sub_lbl = None

        new_order = [st.device_id for st in statuses]
        new_ids = set(new_order)

        for old_id in list(self._card_widgets.keys()):
            if old_id not in new_ids:
                self._card_widgets[old_id].card.destroy()
                del self._card_widgets[old_id]

        for did in new_order:
            if did not in self._card_widgets:
                self._card_widgets[did] = self._create_device_card(self._cards_frame, did)

        if new_order != self._rendered_order:
            for cw in self._card_widgets.values():
                cw.card.pack_forget()
            for did in new_order:
                self._card_widgets[did].card.pack(fill=tk.X, pady=(0, 8))
            self._rendered_order = new_order

        for status in statuses:
            self._update_device_card(self._card_widgets[status.device_id], status, cfg)

    def _handle_refresh(self) -> None:
        self._on_refresh()

    def _handle_startup_toggle(self) -> None:
        try:
            new_state = self._on_toggle_startup()
            self._startup_var.set(new_state)
        except Exception as exc:
            self._startup_var.set(is_startup_enabled())
            messagebox.showerror(
                tr(self._current_lang, "startup_err_title"),
                tr(self._current_lang, "startup_err_msg", err=exc),
                parent=self._top,
            )

    def _handle_hide_unsup_toggle(self) -> None:
        self._on_toggle_hide_unsupported(bool(self._hide_unsup_var.get()))

    def _handle_interval_change(self, _event: object = None) -> None:
        raw = self._interval_var.get().rstrip("s")
        try:
            seconds = int(raw)
        except ValueError:
            seconds = 60
        self._on_change_interval(seconds)

    def _handle_language_change(self, _event: object = None) -> None:
        selected_label = self._lang_var.get()
        lang_code = next(
            (code for code, text in LANGUAGE_LABELS.items() if text == selected_label),
            "pt-BR",
        )
        self._on_change_language(lang_code)

    def _handle_dont_show_toggle(self) -> None:
        self._on_change_show_on_start(not bool(self._dont_show_var.get()))

    def _handle_widget_monitor_change(self, _event: object = None) -> None:
        selected_label = self._widget_monitor_var.get()
        device_name = self._widget_monitor_map.get(selected_label, "")
        self._on_change_widget_monitor(device_name)

    def _handle_reset_widget_position(self) -> None:
        self._on_reset_widget_position()

    def _handle_open_hid_diag(self) -> None:
        def _worker() -> None:
            summary = scan_hid_summary()
            if self._top is not None and self._top.winfo_exists():
                self._top.after(0, lambda: self._show_hid_diag_popup(summary))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_hid_diag_popup(self, summary: str) -> None:
        if self._top is None or not self._top.winfo_exists():
            return
        popup = tk.Toplevel(self._top)
        popup.title(tr(self._current_lang, "hid_diag_title"))
        popup.geometry(
            f"{int(round(620 * self._ui_scale))}x{int(round(420 * self._ui_scale))}"
        )
        popup.configure(bg=BG_MAIN)

        txt = scrolledtext.ScrolledText(
            popup,
            bg=BG_CARD,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=10,
        )
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        txt.insert("1.0", summary)
        txt.configure(state=tk.DISABLED)
