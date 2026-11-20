"""Mini-barra flutuante discreta para exibir bateria na barra de tarefas de outro monitor."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from app_config import AppConfig
from battery_readers import DeviceBatteryStatus
from i18n import tr
from icon_renderer import render_battery_icon
from monitor_utils import (
    MonitorInfo,
    apply_taskbar_widget_styles,
    compute_taskbar_anchor,
    enumerate_monitors,
    find_monitor_by_name,
    get_toplevel_hwnd,
    get_virtual_desktop_bounds,
    raise_widget_topmost,
)

BG_BAR = "#1C1C1C"
BORDER_BAR = "#333333"
DIVIDER = "#333333"
FG_TEXT = "#F8FAFC"
FG_MUTED = "#94A3B8"
ACCENT_GREEN = "#22C55E"
ACCENT_YELLOW = "#FACC15"
ACCENT_RED = "#EF4444"
MENU_BG = "#202020"
MENU_ACTIVE_BG = "#334155"


def _pct_color(status: DeviceBatteryStatus) -> str:
    if status.percentage is None:
        return FG_MUTED
    if status.percentage > 20:
        return ACCENT_GREEN
    if status.percentage >= 11:
        return ACCENT_YELLOW
    return ACCENT_RED


def _pct_text(status: DeviceBatteryStatus) -> str:
    if status.percentage is not None:
        return f"{status.percentage}%"
    if status.is_sleeping:
        if status.last_known_percentage is not None:
            return f"{status.last_known_percentage}%"
        return "Zzz"
    return "--"


class TaskbarWidgetWindow:
    """Mini-barra compacta (overrideredirect + topmost) para monitor escolhido."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        get_config: Callable[[], AppConfig],
        get_statuses: Callable[[], list[DeviceBatteryStatus]],
        should_show_device: Callable[[DeviceBatteryStatus, AppConfig], bool],
        on_refresh: Callable[[], None],
        on_open_dashboard: Callable[[], None],
        on_select_monitor: Callable[[str], None],
        on_toggle_position_mode: Callable[[], None],
        on_reset_position: Callable[[], None],
        on_save_custom_position: Callable[[int, int], None],
    ) -> None:
        self._root = root
        self._get_config = get_config
        self._get_statuses = get_statuses
        self._should_show_device = should_show_device
        self._on_refresh = on_refresh
        self._on_open_dashboard = on_open_dashboard
        self._on_select_monitor = on_select_monitor
        self._on_toggle_position_mode = on_toggle_position_mode
        self._on_reset_position = on_reset_position
        self._on_save_custom_position = on_save_custom_position

        self._top: tk.Toplevel | None = None
        self._container: tk.Frame | None = None
        self._photo_refs: list[ImageTk.PhotoImage] = []
        self._hwnd: int = 0
        self._styles_applied: bool = False
        self._topmost_after_id: str | None = None

        self._dragging: bool = False
        self._drag_moved: bool = False
        self._drag_start_root_x: int = 0
        self._drag_start_root_y: int = 0
        self._drag_win_x: int = 0
        self._drag_win_y: int = 0
        self._drag_bounds: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self._menu_open: bool = False
        self._last_size: tuple[int, int] = (120, 34)

    def is_visible(self) -> bool:
        """Indica se o widget está visível na tela."""
        return bool(
            self._top is not None
            and self._top.winfo_exists()
            and self._top.state() != "withdrawn"
        )

    def _cancel_topmost_timer(self) -> None:
        if self._topmost_after_id is not None:
            try:
                self._root.after_cancel(self._topmost_after_id)
            except Exception:
                pass
            self._topmost_after_id = None

    def _schedule_topmost_timer(self) -> None:
        self._cancel_topmost_timer()
        if self._top is not None and self._top.winfo_exists() and self.is_visible():
            self._topmost_after_id = self._root.after(2500, self._keep_topmost)

    def _keep_topmost(self) -> None:
        self._topmost_after_id = None
        if not self.is_visible():
            return
        if not self._dragging and not self._menu_open and self._hwnd:
            raise_widget_topmost(self._hwnd)
        self._schedule_topmost_timer()

    def _ensure_window(self) -> tk.Toplevel:
        if self._top is not None and self._top.winfo_exists():
            return self._top

        top = tk.Toplevel(self._root)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(bg=BORDER_BAR)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.96)
        except tk.TclError:
            pass

        container = tk.Frame(top, bg=BG_BAR)
        container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self._top = top
        self._container = container
        self._styles_applied = False
        self._hwnd = 0
        return top

    def hide(self) -> None:
        """Oculta a mini-barra mantendo a preferência salva."""
        self._cancel_topmost_timer()
        if self._top is not None and self._top.winfo_exists():
            self._top.withdraw()

    def destroy(self) -> None:
        """Destrói completamente a janela e libera recursos."""
        self._cancel_topmost_timer()
        self._photo_refs.clear()
        if self._top is not None:
            try:
                if self._top.winfo_exists():
                    self._top.destroy()
            except Exception:
                pass
        self._top = None
        self._container = None
        self._hwnd = 0
        self._styles_applied = False

    def _bind_interactive(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        widget.bind("<ButtonRelease-1>", self._on_drag_end, add="+")
        widget.bind("<Double-Button-1>", self._on_double_click, add="+")
        widget.bind("<Button-3>", self._on_right_click, add="+")
        for child in widget.winfo_children():
            self._bind_interactive(child)

    def _rebuild_content(self, monitor: MonitorInfo, cfg: AppConfig) -> None:
        assert self._top is not None and self._container is not None
        for child in self._container.winfo_children():
            child.destroy()
        self._photo_refs.clear()

        scale = monitor.scale
        icon_px = max(16, int(round(20 * scale)))
        font_px = max(10, int(round(12 * scale)))
        pad_x = max(5, int(round(8 * scale)))
        pad_y = max(3, int(round(5 * scale)))
        gap_x = max(3, int(round(4 * scale)))
        sep_pad = max(3, int(round(5 * scale)))

        all_statuses = self._get_statuses()
        visible_statuses = [
            st for st in all_statuses if self._should_show_device(st, cfg)
        ]

        row = tk.Frame(self._container, bg=BG_BAR)
        row.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=pad_y)

        if not visible_statuses:
            hub_img = render_battery_icon("hub", None, sleeping=True).resize(
                (icon_px, icon_px), Image.Resampling.LANCZOS
            )
            hub_photo = ImageTk.PhotoImage(hub_img, master=self._top)
            self._photo_refs.append(hub_photo)
            tk.Label(row, image=hub_photo, bg=BG_BAR).pack(side=tk.LEFT)
            tk.Label(
                row,
                text="--",
                bg=BG_BAR,
                fg=FG_MUTED,
                font=("Segoe UI", -font_px, "bold"),
            ).pack(side=tk.LEFT, padx=(gap_x, 0))
        else:
            for idx, st in enumerate(visible_statuses):
                if idx > 0:
                    sep = tk.Frame(row, bg=DIVIDER, width=1)
                    sep.pack(side=tk.LEFT, fill=tk.Y, padx=sep_pad, pady=1)

                item_frame = tk.Frame(row, bg=BG_BAR)
                item_frame.pack(side=tk.LEFT)

                pil_img = render_battery_icon(
                    st.icon_kind,
                    st.percentage,
                    charging=st.charging,
                    sleeping=st.is_sleeping,
                    last_known_percentage=st.last_known_percentage,
                ).resize((icon_px, icon_px), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(pil_img, master=self._top)
                self._photo_refs.append(photo)

                tk.Label(item_frame, image=photo, bg=BG_BAR).pack(side=tk.LEFT)
                tk.Label(
                    item_frame,
                    text=_pct_text(st),
                    bg=BG_BAR,
                    fg=_pct_color(st),
                    font=("Segoe UI", -font_px, "bold"),
                ).pack(side=tk.LEFT, padx=(gap_x, 0))

        self._bind_interactive(self._top)

    def sync(self) -> None:
        """Atualiza conteúdo, posição e visibilidade conforme configuração e dispositivos."""
        cfg = self._get_config()
        if not cfg.widget_monitor:
            self.hide()
            return

        monitors = enumerate_monitors()
        target_mon = find_monitor_by_name(monitors, cfg.widget_monitor)
        if target_mon is None:
            # Monitor desconectado no momento: oculta sem apagar a preferência
            self.hide()
            return

        top = self._ensure_window()
        self._rebuild_content(target_mon, cfg)
        top.update_idletasks()

        req_w = max(60, int(top.winfo_reqwidth()))
        req_h = max(24, int(top.winfo_reqheight()))
        self._last_size = (req_w, req_h)

        if not self._dragging:
            if cfg.widget_custom_x is not None and cfg.widget_custom_y is not None:
                vx1, vy1, vx2, vy2 = get_virtual_desktop_bounds(monitors)
                x = max(vx1, min(int(cfg.widget_custom_x), vx2 - req_w))
                y = max(vy1, min(int(cfg.widget_custom_y), vy2 - req_h))
            else:
                x, y = compute_taskbar_anchor(
                    target_mon, req_w, req_h, mode=cfg.widget_position_mode
                )
            top.geometry(f"{req_w}x{req_h}+{x}+{y}")

        if top.state() == "withdrawn":
            top.deiconify()
        top.update_idletasks()

        self._hwnd = get_toplevel_hwnd(top)
        if not self._styles_applied and self._hwnd:
            apply_taskbar_widget_styles(self._hwnd)
            self._styles_applied = True
        elif self._hwnd:
            raise_widget_topmost(self._hwnd)

        self._schedule_topmost_timer()

    def _on_drag_start(self, event: tk.Event) -> None:
        if self._top is None or not self._top.winfo_exists():
            return
        self._dragging = True
        self._drag_moved = False
        self._drag_start_root_x = int(event.x_root)
        self._drag_start_root_y = int(event.y_root)
        self._drag_win_x = int(self._top.winfo_x())
        self._drag_win_y = int(self._top.winfo_y())
        self._drag_bounds = get_virtual_desktop_bounds(enumerate_monitors())

    def _on_drag_motion(self, event: tk.Event) -> None:
        if not self._dragging or self._top is None or not self._top.winfo_exists():
            return
        dx = int(event.x_root) - self._drag_start_root_x
        dy = int(event.y_root) - self._drag_start_root_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_moved = True

        w = max(60, int(self._top.winfo_width()) or self._last_size[0])
        h = max(24, int(self._top.winfo_height()) or self._last_size[1])
        vx1, vy1, vx2, vy2 = self._drag_bounds
        new_x = max(vx1, min(self._drag_win_x + dx, vx2 - w))
        new_y = max(vy1, min(self._drag_win_y + dy, vy2 - h))
        self._top.geometry(f"+{new_x}+{new_y}")

    def _on_drag_end(self, _event: tk.Event) -> None:
        if not self._dragging:
            return
        self._dragging = False
        if self._drag_moved and self._top is not None and self._top.winfo_exists():
            self._on_save_custom_position(
                int(self._top.winfo_x()),
                int(self._top.winfo_y()),
            )
        if self._hwnd:
            raise_widget_topmost(self._hwnd)

    def _on_double_click(self, _event: tk.Event) -> None:
        self._dragging = False
        self._on_open_dashboard()

    def _on_right_click(self, event: tk.Event) -> None:
        if self._top is None or not self._top.winfo_exists():
            return

        cfg = self._get_config()
        lang = cfg.language
        statuses = self._get_statuses()
        monitors = enumerate_monitors()

        menu = tk.Menu(
            self._top,
            tearoff=0,
            bg=MENU_BG,
            fg=FG_TEXT,
            activebackground=MENU_ACTIVE_BG,
            activeforeground=FG_TEXT,
            disabledforeground=FG_MUTED,
            bd=1,
        )

        if statuses:
            for st in statuses:
                menu.add_command(label=st.menu_summary(lang), state=tk.DISABLED)
        else:
            menu.add_command(label=tr(lang, "tray_no_devices"), state=tk.DISABLED)

        menu.add_separator()
        menu.add_command(label=tr(lang, "menu_refresh"), command=self._on_refresh)
        menu.add_command(label=tr(lang, "menu_open_dashboard"), command=self._on_open_dashboard)
        menu.add_separator()

        mode_label = (
            tr(lang, "widget_pos_above")
            if cfg.widget_position_mode == "taskbar"
            else tr(lang, "widget_pos_over")
        )
        menu.add_command(label=mode_label, command=self._on_toggle_position_mode)
        menu.add_command(
            label=tr(lang, "widget_reanchor"),
            command=self._on_reset_position,
        )

        mon_menu = tk.Menu(
            menu,
            tearoff=0,
            bg=MENU_BG,
            fg=FG_TEXT,
            activebackground=MENU_ACTIVE_BG,
            activeforeground=FG_TEXT,
            bd=1,
        )
        for mon in monitors:
            prefix = "✓ " if mon.device_name.lower() == cfg.widget_monitor.lower() else "   "
            mon_menu.add_command(
                label=f"{prefix}{mon.format_label(lang)}",
                command=lambda d=mon.device_name: self._on_select_monitor(d),
            )
        menu.add_cascade(label=tr(lang, "widget_move_monitor"), menu=mon_menu)

        menu.add_separator()
        menu.add_command(
            label=tr(lang, "widget_close"),
            command=lambda: self._on_select_monitor(""),
        )

        self._menu_open = True
        try:
            menu.tk_popup(int(event.x_root), int(event.y_root))
        finally:
            self._menu_open = False
            try:
                menu.grab_release()
                menu.destroy()
            except Exception:
                pass
            if self._hwnd and self.is_visible():
                raise_widget_topmost(self._hwnd)
