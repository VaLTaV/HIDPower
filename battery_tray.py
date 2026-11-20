"""Aplicativo principal do HIDPower na bandeja do sistema do Windows."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk

import pystray
import PIL._tkinter_finder  # noqa: F401
if sys.platform == "win32":
    import pystray._win32  # noqa: F401

from app_config import (
    AppConfig,
    append_log,
    get_startup_shortcut_path,
    get_startup_target_and_args,
    is_ephemeral_exe_dir,
    is_startup_enabled,
    load_battery_state,
    load_config,
    needs_first_run_setup,
    normalize_hidpower_folder,
    save_battery_state,
    save_config,
    toggle_startup,
)
from battery_readers import (
    DeviceBatteryStatus,
    discover_and_read_all,
    resolve_compx_dual_mode,
)
from i18n import normalize_language, tr
from icon_renderer import (
    render_app_badge_image,
    render_battery_icon,
    render_github_logo_banner,
    render_hip_emblem,
    save_icon_preview,
)
from monitor_utils import compute_taskbar_anchor, enable_dpi_awareness, enumerate_monitors
from setup_wizard import (
    FirstRunWizardDialog,
    apply_first_run_setup,
    run_first_run_wizard,
)
from taskbar_widget import TaskbarWidgetWindow
from ui_window import DashboardWindow

MUTEX_NAME = "Local\\HIDPower_SingleInstance_Mutex"
APP_TITLE = "HIDPower"
HUB_ICON_ID = "bat_monitor_hub"
FAST_SLEEP_POLL_SECONDS = 8


def configure_utf8_stdio() -> None:
    """Garante UTF-8 quando há console, sem falhar em pythonw/--noconsole."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _safe_print(*args: object) -> None:
    """Imprime apenas quando há stdout disponível (seguro em --noconsole)."""
    if sys.stdout is not None:
        try:
            print(*args)
        except Exception:
            pass


def show_message_box_async(
    message: str, title: str = APP_TITLE, flags: int = 0x40
) -> None:
    """Exibe MessageBoxW em thread separada para não bloquear o loop Win32 da bandeja."""

    def _runner() -> None:
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, flags)
        except Exception:
            pass

    threading.Thread(target=_runner, daemon=True).start()


def should_show_in_tray(status: DeviceBatteryStatus, cfg: AppConfig) -> bool:
    """Define se o dispositivo deve exibir ícone próprio na bandeja e no widget."""
    if not status.connected and status.percentage is None:
        return False
    if status.device_id in cfg.device_visibility:
        return bool(cfg.device_visibility[status.device_id])
    if status.percentage is not None:
        return True
    if status.connected and status.telemetry_supported:
        return True
    if status.connected and not status.telemetry_supported:
        return not cfg.hide_unsupported
    return False


def build_clean_subprocess_env(
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Remove variáveis internas do PyInstaller (--onefile) ao relançar outro .exe."""
    source = base_env if base_env is not None else os.environ
    return {
        key: val
        for key, val in source.items()
        if not key.startswith("_PYI_") and not key.startswith("_MEIPASS")
    }


class SingleInstanceMutex:
    """Garante apenas uma instância interativa do HIDPower na bandeja."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def acquire(self, retries: int = 1, delay: float = 0.2) -> bool:
        """Tenta adquirir o mutex; retorna False se outra instância já estiver ativa."""
        attempts = max(1, int(retries))
        for idx in range(attempts):
            handle = self._kernel32.CreateMutexW(None, True, self._name)
            err = ctypes.get_last_error()
            if not handle:
                return True
            if err == self.ERROR_ALREADY_EXISTS:
                self._kernel32.CloseHandle(handle)
                if idx + 1 < attempts:
                    time.sleep(delay)
                    continue
                return False
            self._handle = handle
            return True
        return False

    def release(self) -> None:
        """Libera o handle do mutex ao encerrar."""
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            finally:
                self._handle = None


class BatteryTrayApp:
    """Orquestrador multi-ícone na bandeja, descoberta automática, widget e painel Tkinter."""

    def __init__(
        self,
        *,
        interval_override: int | None = None,
        open_guide_override: bool | None = None,
    ) -> None:
        self._config: AppConfig = load_config()
        if interval_override is not None:
            self._config.interval_seconds = max(5, int(interval_override))
        self._open_guide_override = open_guide_override

        self._lock = threading.Lock()
        self._tray_lock = threading.RLock()
        self._statuses_order: list[str] = []
        self._statuses: dict[str, DeviceBatteryStatus] = {}
        self._cached_state: dict[str, dict[str, object]] = load_battery_state()
        self._last_visual_key: dict[str, tuple[object, ...]] = {}
        self._icons: dict[str, pystray.Icon] = {}
        self._hub_icon: pystray.Icon | None = None

        self._refresh_event = threading.Event()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None

        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._root: tk.Tk | None = None
        self._dashboard: DashboardWindow | None = None
        self._widget: TaskbarWidgetWindow | None = None

    def get_config(self) -> AppConfig:
        """Retorna cópia atual das configurações."""
        with self._lock:
            return AppConfig(
                interval_seconds=self._config.interval_seconds,
                hide_unsupported=self._config.hide_unsupported,
                show_guide_on_start=self._config.show_guide_on_start,
                widget_monitor=self._config.widget_monitor,
                widget_position_mode=self._config.widget_position_mode,
                widget_custom_x=self._config.widget_custom_x,
                widget_custom_y=self._config.widget_custom_y,
                language=self._config.language,
                device_visibility=dict(self._config.device_visibility),
            )

    def get_statuses_snapshot(self) -> list[DeviceBatteryStatus]:
        """Retorna lista ordenada dos status mais recentes."""
        with self._lock:
            return [
                self._statuses[did]
                for did in self._statuses_order
                if did in self._statuses
            ]

    def enqueue_ui(self, action: str, payload: object = None) -> None:
        """Enfileira ação para execução segura na thread principal do Tkinter."""
        self._ui_queue.put((action, payload))

    def _make_monitor_select_action(self, device_name: str):
        return lambda _ic, _it: self._on_select_widget_monitor(device_name)

    def _make_monitor_checked_cb(self, device_name: str):
        return lambda _item: (
            self.get_config().widget_monitor.lower() == device_name.lower()
        )

    def _build_monitor_submenu_items(self) -> tuple[pystray.MenuItem, ...]:
        cfg = self.get_config()
        lang = cfg.language
        monitors = enumerate_monitors()
        items: list[pystray.MenuItem] = [
            pystray.MenuItem(
                tr(lang, "widget_disabled"),
                self._make_monitor_select_action(""),
                radio=True,
                checked=lambda _item: not self.get_config().widget_monitor,
            )
        ]
        for mon in monitors:
            items.append(
                pystray.MenuItem(
                    mon.format_label(lang),
                    self._make_monitor_select_action(mon.device_name),
                    radio=True,
                    checked=self._make_monitor_checked_cb(mon.device_name),
                )
            )
        if monitors:
            items.append(pystray.Menu.SEPARATOR)
            items.append(
                pystray.MenuItem(
                    tr(lang, "menu_reanchor_widget"),
                    lambda _ic, _it: self._on_reset_widget_position(),
                    enabled=lambda _item: bool(self.get_config().widget_monitor),
                )
            )
        return tuple(items)

    def _build_menu_items(self) -> tuple[pystray.MenuItem, ...]:
        cfg = self.get_config()
        lang = cfg.language
        snapshot = self.get_statuses_snapshot()
        if snapshot:
            status_items = [
                pystray.MenuItem(st.menu_summary(lang), action=None, enabled=False)
                for st in snapshot
            ]
        else:
            status_items = [
                pystray.MenuItem(
                    tr(lang, "tray_no_devices"), action=None, enabled=False
                )
            ]

        return (
            *status_items,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                tr(lang, "menu_open_dashboard"),
                self._on_open_dashboard,
                default=True,
            ),
            pystray.MenuItem(
                tr(lang, "menu_pin_guide"),
                self._on_open_pin_guide,
            ),
            pystray.MenuItem(
                tr(lang, "menu_widget_monitor"),
                pystray.Menu(self._build_monitor_submenu_items),
            ),
            pystray.MenuItem(tr(lang, "menu_refresh"), self._on_refresh_now),
            pystray.MenuItem(
                tr(lang, "menu_hide_unsupported"),
                self._on_toggle_hide_unsupported,
                checked=lambda _item: self.get_config().hide_unsupported,
            ),
            pystray.MenuItem(
                tr(lang, "menu_startup"),
                self._on_toggle_startup,
                checked=lambda _item: is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr(lang, "menu_quit"), self._on_exit),
        )

    def _create_menu(self) -> pystray.Menu:
        return pystray.Menu(self._build_menu_items)

    def _on_open_dashboard(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.enqueue_ui("SHOW_UI", 0)

    def _on_open_pin_guide(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.enqueue_ui("SHOW_UI", 2)

    def _on_refresh_now(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._refresh_event.set()

    def _clear_unsupported_overrides_locked(self) -> None:
        unsupported_ids = {
            did for did, st in self._statuses.items() if not st.telemetry_supported
        }
        for did in unsupported_ids:
            self._config.device_visibility.pop(did, None)

    def _on_toggle_hide_unsupported(
        self, _icon: pystray.Icon, _item: pystray.MenuItem
    ) -> None:
        with self._lock:
            self._config.hide_unsupported = not self._config.hide_unsupported
            self._clear_unsupported_overrides_locked()
            save_config(self._config)
        self._sync_tray_icons(self.get_statuses_snapshot())
        self.enqueue_ui("REFRESH_UI", None)

    def _on_toggle_startup(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        lang = self.get_config().language
        try:
            toggle_startup()
            self._update_all_menus()
            self.enqueue_ui("REFRESH_UI", None)
        except Exception as exc:
            show_message_box_async(
                tr(lang, "startup_tray_err", err=exc),
                flags=0x10,
            )

    def _on_exit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self.enqueue_ui("QUIT", None)

    def _set_widget_monitor_pref(self, device_name: str) -> None:
        with self._lock:
            self._config.widget_monitor = str(device_name or "").strip()
            self._config.widget_custom_x = None
            self._config.widget_custom_y = None
            save_config(self._config)
        self._update_all_menus()

    def _on_select_widget_monitor(self, device_name: str) -> None:
        self._set_widget_monitor_pref(device_name)
        self.enqueue_ui("SYNC_WIDGET", None)
        self.enqueue_ui("REFRESH_UI", None)

    def _on_reset_widget_position(self) -> None:
        with self._lock:
            self._config.widget_custom_x = None
            self._config.widget_custom_y = None
            save_config(self._config)
        self.enqueue_ui("SYNC_WIDGET", None)

    def _update_all_menus(self) -> None:
        with self._tray_lock:
            for icon in list(self._icons.values()):
                try:
                    if icon.visible:
                        icon.update_menu()
                except Exception:
                    pass
            if self._hub_icon is not None:
                try:
                    if self._hub_icon.visible:
                        self._hub_icon.update_menu()
                except Exception:
                    pass

    def _spawn_icon(
        self,
        icon_id: str,
        image: object,
        title: str,
        visible: bool = True,
    ) -> pystray.Icon:
        ready_ev = threading.Event()
        icon = pystray.Icon(
            name=icon_id,
            icon=image,
            title=title,
            menu=self._create_menu(),
        )

        def _setup(ic: pystray.Icon) -> None:
            ic.visible = visible
            ready_ev.set()

        icon.run_detached(setup=_setup)
        ready_ev.wait(timeout=3.0)
        return icon

    def _sync_tray_icons(self, statuses: list[DeviceBatteryStatus]) -> None:
        with self._tray_lock:
            if self._stop_event.is_set():
                return

            cfg = self.get_config()
            lang = cfg.language
            visible_count = 0
            seen_ids: set[str] = set()

            for status in statuses:
                seen_ids.add(status.device_id)
                show = should_show_in_tray(status, cfg)
                visual_key = (
                    status.icon_kind,
                    status.percentage,
                    status.charging,
                    status.is_sleeping,
                    status.last_known_percentage if status.is_sleeping else None,
                )

                existing = self._icons.get(status.device_id)
                if not show:
                    if existing is not None and existing.visible:
                        existing.visible = False
                    continue

                visible_count += 1
                tooltip = status.tooltip_text(lang)
                if existing is None:
                    img = render_battery_icon(
                        status.icon_kind,
                        status.percentage,
                        charging=status.charging,
                        sleeping=status.is_sleeping,
                        last_known_percentage=status.last_known_percentage,
                    )
                    self._icons[status.device_id] = self._spawn_icon(
                        status.device_id, img, tooltip, visible=True
                    )
                    self._last_visual_key[status.device_id] = visual_key
                else:
                    if self._last_visual_key.get(status.device_id) != visual_key:
                        existing.icon = render_battery_icon(
                            status.icon_kind,
                            status.percentage,
                            charging=status.charging,
                            sleeping=status.is_sleeping,
                            last_known_percentage=status.last_known_percentage,
                        )
                        self._last_visual_key[status.device_id] = visual_key
                    existing.title = tooltip
                    if not existing.visible:
                        existing.visible = True

            for dev_id, icon in list(self._icons.items()):
                if dev_id not in seen_ids and icon.visible:
                    icon.visible = False

            if visible_count == 0:
                hub_title = tr(lang, "tray_no_visible")
                if self._hub_icon is None:
                    hub_img = render_battery_icon("hub", None, sleeping=True)
                    self._hub_icon = self._spawn_icon(
                        HUB_ICON_ID,
                        hub_img,
                        hub_title,
                        visible=True,
                    )
                else:
                    self._hub_icon.title = hub_title
                    if not self._hub_icon.visible:
                        self._hub_icon.visible = True
            elif self._hub_icon is not None and self._hub_icon.visible:
                self._hub_icon.visible = False

            self._update_all_menus()

    def poll_once(self, update_tray: bool = True) -> list[DeviceBatteryStatus]:
        """Executa descoberta e leitura de todos os dispositivos e atualiza cache/bandeja."""
        raw_statuses = discover_and_read_all()
        merged_list: list[DeviceBatteryStatus] = []
        state_dirty = False

        with self._lock:
            new_order: list[str] = []
            for st in raw_statuses:
                prev = self._statuses.get(st.device_id)
                if prev is None and st.device_id in self._cached_state:
                    cached = self._cached_state[st.device_id]
                    st.last_known_percentage = int(cached["percentage"])  # type: ignore[arg-type]
                    st.last_known_at = str(cached.get("updated_at") or "")
                st.merge_previous(prev)

                if st.percentage is not None:
                    prev_cached = self._cached_state.get(st.device_id)
                    if (
                        prev_cached is None
                        or prev_cached.get("percentage") != st.percentage
                        or prev_cached.get("updated_at") != st.updated_at
                    ):
                        self._cached_state[st.device_id] = {
                            "percentage": st.percentage,
                            "updated_at": st.updated_at,
                        }
                        state_dirty = True

                self._statuses[st.device_id] = st
                new_order.append(st.device_id)
                merged_list.append(st)

            self._statuses_order = new_order

        if state_dirty:
            save_battery_state(dict(self._cached_state))

        if update_tray and not self._stop_event.is_set():
            self._sync_tray_icons(merged_list)
            self.enqueue_ui("REFRESH_UI", None)

        return merged_list

    def _compute_next_wait(self, statuses: list[DeviceBatteryStatus]) -> float:
        base_interval = self.get_config().interval_seconds
        any_sleeping = any(st.is_sleeping for st in statuses)
        if any_sleeping:
            return float(min(base_interval, FAST_SLEEP_POLL_SECONDS))
        return float(base_interval)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            wait_s = self._compute_next_wait(self.get_statuses_snapshot())
            triggered = self._refresh_event.wait(timeout=wait_s)
            if triggered:
                self._refresh_event.clear()
            if self._stop_event.is_set():
                break
            try:
                self.poll_once(update_tray=True)
            except Exception as exc:
                append_log(f"Poll error: {exc}")

    def _ui_change_interval(self, seconds: int) -> None:
        with self._lock:
            self._config.interval_seconds = max(5, int(seconds))
            save_config(self._config)
        self._refresh_event.set()

    def _ui_change_hide_unsupported(self, hide: bool) -> None:
        with self._lock:
            self._config.hide_unsupported = bool(hide)
            self._clear_unsupported_overrides_locked()
            save_config(self._config)
        self._sync_tray_icons(self.get_statuses_snapshot())
        if self._widget is not None:
            self._widget.sync()
        if self._dashboard is not None and self._dashboard.is_visible():
            self._dashboard.refresh_view()

    def _ui_change_show_on_start(self, show_on_start: bool) -> None:
        with self._lock:
            self._config.show_guide_on_start = bool(show_on_start)
            save_config(self._config)

    def _ui_toggle_startup(self) -> bool:
        new_state = toggle_startup()
        self._update_all_menus()
        return new_state

    def _ui_change_language(self, lang: str) -> None:
        new_lang = normalize_language(lang)
        with self._lock:
            self._config.language = new_lang
            save_config(self._config)
        self._sync_tray_icons(self.get_statuses_snapshot())
        if self._widget is not None:
            self._widget.sync()
        if self._dashboard is not None and self._dashboard.is_visible():
            self._dashboard.refresh_view()

    def _ui_toggle_device_visibility(self, device_id: str, visible: bool) -> None:
        with self._lock:
            self._config.device_visibility[device_id] = bool(visible)
            save_config(self._config)
        self._sync_tray_icons(self.get_statuses_snapshot())
        if self._widget is not None:
            self._widget.sync()
        if self._dashboard is not None and self._dashboard.is_visible():
            self._dashboard.refresh_view()

    def _ui_change_widget_monitor(self, device_name: str) -> None:
        self._set_widget_monitor_pref(device_name)
        if self._widget is not None:
            self._widget.sync()
        if self._dashboard is not None and self._dashboard.is_visible():
            self._dashboard.refresh_view()

    def _ui_toggle_widget_position_mode(self) -> None:
        with self._lock:
            self._config.widget_position_mode = (
                "above" if self._config.widget_position_mode == "taskbar" else "taskbar"
            )
            self._config.widget_custom_x = None
            self._config.widget_custom_y = None
            save_config(self._config)
        if self._widget is not None:
            self._widget.sync()

    def _ui_reset_widget_position(self) -> None:
        with self._lock:
            self._config.widget_custom_x = None
            self._config.widget_custom_y = None
            save_config(self._config)
        if self._widget is not None:
            self._widget.sync()

    def _ui_save_widget_custom_position(self, x: int, y: int) -> None:
        with self._lock:
            self._config.widget_custom_x = int(x)
            self._config.widget_custom_y = int(y)
            save_config(self._config)

    def _drain_ui_queue(self) -> None:
        if self._root is None:
            return

        while True:
            try:
                action, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            if action == "SHOW_UI":
                if self._dashboard is not None:
                    self._dashboard.show(int(payload or 0))
            elif action == "REFRESH_UI":
                if self._dashboard is not None and self._dashboard.is_visible():
                    self._dashboard.refresh_view()
                if self._widget is not None:
                    self._widget.sync()
            elif action == "SYNC_WIDGET":
                if self._widget is not None:
                    self._widget.sync()
            elif action == "QUIT":
                self.stop_all()
                return

        if not self._stop_event.is_set():
            self._root.after(150, self._drain_ui_queue)

    def request_stop(self) -> None:
        """Sinaliza encerramento limpo para polling e loop principal."""
        self._stop_event.set()
        self._refresh_event.set()

    def stop_all(self) -> None:
        """Encerra todos os ícones da bandeja, widget e o loop Tkinter."""
        self.request_stop()
        with self._tray_lock:
            for icon in list(self._icons.values()):
                try:
                    icon.stop()
                except Exception:
                    pass
            if self._hub_icon is not None:
                try:
                    self._hub_icon.stop()
                except Exception:
                    pass
        if self._widget is not None:
            try:
                self._widget.destroy()
            except Exception:
                pass
        if self._root is not None:
            try:
                self._root.quit()
            except Exception:
                pass

    def run_forever(self, max_seconds: float = 0.0) -> None:
        """Inicializa polling inicial, ícones na bandeja e loop Tkinter."""
        root = tk.Tk()
        root.withdraw()
        self._root = root

        self._dashboard = DashboardWindow(
            root,
            get_config=self.get_config,
            get_statuses=self.get_statuses_snapshot,
            should_show_device=should_show_in_tray,
            on_refresh=lambda: self._refresh_event.set(),
            on_toggle_startup=self._ui_toggle_startup,
            on_toggle_hide_unsupported=self._ui_change_hide_unsupported,
            on_change_interval=self._ui_change_interval,
            on_change_show_on_start=self._ui_change_show_on_start,
            on_change_widget_monitor=self._ui_change_widget_monitor,
            on_reset_widget_position=self._ui_reset_widget_position,
            on_change_language=self._ui_change_language,
            on_toggle_device_visibility=self._ui_toggle_device_visibility,
        )

        self._widget = TaskbarWidgetWindow(
            root,
            get_config=self.get_config,
            get_statuses=self.get_statuses_snapshot,
            should_show_device=should_show_in_tray,
            on_refresh=lambda: self._refresh_event.set(),
            on_open_dashboard=lambda: self.enqueue_ui("SHOW_UI", 0),
            on_select_monitor=self._ui_change_widget_monitor,
            on_toggle_position_mode=self._ui_toggle_widget_position_mode,
            on_reset_position=self._ui_reset_widget_position,
            on_save_custom_position=self._ui_save_widget_custom_position,
        )

        initial_statuses = self.poll_once(update_tray=False)
        self._sync_tray_icons(initial_statuses)
        self._widget.sync()

        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="BatteryPollThread",
            daemon=True,
        )
        self._poll_thread.start()

        should_open_guide = (
            self._open_guide_override
            if self._open_guide_override is not None
            else self.get_config().show_guide_on_start
        )
        if should_open_guide and max_seconds <= 0:
            root.after(200, lambda: self.enqueue_ui("SHOW_UI", 0))

        if max_seconds > 0:
            root.after(int(max_seconds * 1000), lambda: self.enqueue_ui("QUIT", None))

        root.after(150, self._drain_ui_queue)
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_all()
            try:
                root.destroy()
            except Exception:
                pass


def _schedule_old_exe_cleanup(old_path_str: str) -> None:
    def _worker() -> None:
        old_path = Path(old_path_str)
        if old_path.suffix.lower() != ".exe":
            return
        try:
            current_exe = Path(sys.executable).resolve()
            if old_path.resolve() == current_exe:
                return
        except Exception:
            pass
        last_err: Exception | None = None
        for _ in range(60):
            try:
                if not old_path.exists():
                    return
                old_path.unlink()
                append_log(f"Removed previous exe: {old_path}")
                return
            except Exception as exc:
                last_err = exc
                time.sleep(0.25)
        if old_path.exists():
            append_log(f"Failed to remove previous exe {old_path}: {last_err}")

    threading.Thread(target=_worker, daemon=True).start()


def run_self_test(interval_seconds: int, preview_path: str | None = None) -> int:
    """Valida ícones, emblema HIP, in-place UI, i18n, unificação Compx e descoberta ao vivo."""
    _safe_print("=" * 72)
    _safe_print("AUTO-TESTE: HIDPower (ícones, HIP, in-place, i18n, widget e hardware)")
    _safe_print("=" * 72)

    test_cases = [
        ("mouse", 100, False, False, None, "mouse verde 100%"),
        ("mouse", 80, True, False, None, "mouse verde carregando 80%"),
        ("gamepad", 20, False, False, None, "gamepad amarelo 20%"),
        ("keyboard", 10, False, False, None, "keyboard vermelho 10%"),
        ("mouse", None, False, True, 90, "mouse sleep com ultima 90%"),
        ("mouse", None, False, True, None, "mouse sleep sem historico"),
        ("headset", None, False, False, None, "headset sem telemetria"),
        ("hub", None, False, True, None, "hub fallback"),
    ]
    for kind, pct, chg, slp, last_pct, label in test_cases:
        img = render_battery_icon(
            kind,
            pct,
            charging=chg,
            sleeping=slp,
            last_known_percentage=last_pct,
        )
        assert img.size == (64, 64), f"Tamanho inesperado para {label}: {img.size}"
        assert img.mode == "RGBA", f"Modo inesperado para {label}: {img.mode}"
        _safe_print(f"[OK] Ícone 64x64 RGBA gerado para: {label}")

    emblem = render_hip_emblem(44)
    assert emblem.mode == "RGBA" and emblem.height == 44
    badge = render_app_badge_image(64)
    assert badge.size == (64, 64) and badge.mode == "RGBA"
    banner = render_github_logo_banner()
    assert banner.size == (960, 240) and banner.mode == "RGBA"
    _safe_print("[OK] Emblema HIP, badge 64x64 e banner 960x240 RGBA gerados em memória")

    sim_sleep_mouse = DeviceBatteryStatus(
        device_id="sim_mouse",
        display_name="Mouse Compx",
        icon_kind="mouse",
        short_tag="MS",
        accent_rgb=(56, 189, 248),
        vid_pid="25A7:FA07",
        connected=True,
        awake=False,
        percentage=None,
        charging=None,
        telemetry_supported=True,
        detail="Desligado / Sleep por inatividade",
        raw_info="online=0",
        last_known_percentage=90,
        last_known_at="20:45",
        detail_key="detail_compx_sleep",
    )
    sim_unsupported_headset = DeviceBatteryStatus(
        device_id="sim_headset",
        display_name="Headset Morcego Pro",
        icon_kind="headset",
        short_tag="HS",
        accent_rgb=(251, 146, 60),
        vid_pid="3206:0881",
        connected=True,
        awake=True,
        percentage=None,
        charging=None,
        telemetry_supported=False,
        detail="2.4G sem telemetria USB",
        raw_info="HID MI_03 Consumer",
        detail_key="detail_morcego_no_telemetry",
    )
    assert sim_sleep_mouse.is_sleeping is True
    cfg_hide = AppConfig(hide_unsupported=True)
    cfg_show = AppConfig(hide_unsupported=False)
    assert should_show_in_tray(sim_sleep_mouse, cfg_hide) is True
    assert should_show_in_tray(sim_unsupported_headset, cfg_hide) is False
    assert should_show_in_tray(sim_unsupported_headset, cfg_show) is True

    cfg_override_hide_mouse = AppConfig(
        hide_unsupported=True, device_visibility={"sim_mouse": False}
    )
    cfg_override_show_hs = AppConfig(
        hide_unsupported=True, device_visibility={"sim_headset": True}
    )
    assert should_show_in_tray(sim_sleep_mouse, cfg_override_hide_mouse) is False
    assert should_show_in_tray(sim_unsupported_headset, cfg_override_show_hs) is True
    _safe_print("[OK] Regras de visibilidade e override por card (Ocultar/Exibir) validadas")

    # Valida traduções PT-BR e EN
    assert "Off/Sleep" in sim_sleep_mouse.tooltip_text("en")
    assert "Desligado/Sleep" in sim_sleep_mouse.tooltip_text("pt-BR")
    assert tr("en", "tab_settings") == "Settings"
    assert tr("pt-BR", "tab_settings") == "Configurações"
    _safe_print("[OK] Traduções PT-BR e EN validadas (tooltips, menus e UI)")

    # Valida unificação Compx (FA07 sem fio + FA08 cabo USB)
    sim_fa08_wired = DeviceBatteryStatus(
        device_id="bat_mouse_compx",
        display_name="Mouse Compx",
        icon_kind="mouse",
        short_tag="MS",
        accent_rgb=(56, 189, 248),
        vid_pid="25A7:FA08",
        connected=True,
        awake=True,
        percentage=85,
        charging=True,
        telemetry_supported=True,
        detail="Carregando via USB",
        raw_info="USB cmd04",
        detail_key="detail_compx_charging",
    )
    sim_fa07_active = DeviceBatteryStatus(
        device_id="bat_mouse_compx",
        display_name="Mouse Compx",
        icon_kind="mouse",
        short_tag="MS",
        accent_rgb=(56, 189, 248),
        vid_pid="25A7:FA07",
        connected=True,
        awake=True,
        percentage=90,
        charging=False,
        telemetry_supported=True,
        detail="Conectado 2.4 GHz (passos de 10%)",
        raw_info="cmd04",
        detail_key="detail_compx_24g",
    )
    sim_fa08_unresponsive = DeviceBatteryStatus(
        device_id="bat_mouse_compx",
        display_name="Mouse Compx",
        icon_kind="mouse",
        short_tag="MS",
        accent_rgb=(56, 189, 248),
        vid_pid="25A7:FA08",
        connected=True,
        awake=False,
        percentage=None,
        charging=None,
        telemetry_supported=True,
        detail="Cabo USB conectado (sem resposta)",
        raw_info="USB timeout",
        detail_key="detail_compx_usb_no_reply",
    )
    res_wired = resolve_compx_dual_mode(sim_fa08_wired, sim_sleep_mouse)
    assert res_wired is not None and res_wired.vid_pid == "25A7:FA08" and res_wired.charging is True
    res_wireless_only = resolve_compx_dual_mode(None, sim_fa07_active)
    assert res_wireless_only is not None and res_wireless_only.vid_pid == "25A7:FA07"
    res_fallback = resolve_compx_dual_mode(sim_fa08_unresponsive, sim_fa07_active)
    assert res_fallback is not None and res_fallback.vid_pid == "25A7:FA07"
    res_sleep_only = resolve_compx_dual_mode(None, sim_sleep_mouse)
    assert res_sleep_only is not None and res_sleep_only.is_sleeping is True
    _safe_print("[OK] Unificação Compx (25A7:FA07 + 25A7:FA08) validada em todos os cenários")

    assert normalize_hidpower_folder(Path("C:/Apps")) == Path("C:/Apps/HIDPower")
    assert normalize_hidpower_folder(Path("C:/Apps/HIDPower")) == Path("C:/Apps/HIDPower")
    assert is_ephemeral_exe_dir(Path("C:/Users/test/Downloads")) is True
    assert is_ephemeral_exe_dir(Path("F:/Apps/HIDPower")) is False
    clean_env = build_clean_subprocess_env(
        {
            "PATH": "C:\\Windows",
            "_PYI_ARCHIVE_FILE": "C:\\Downloads\\HIDPower.exe",
            "_PYI_APPLICATION_HOME_DIR": "C:\\Temp\\_MEI123",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_MEIPASS": "C:\\Temp\\_MEI123",
        }
    )
    assert clean_env == {"PATH": "C:\\Windows"}
    _safe_print("[OK] Normalização portátil, detecção de pasta efêmera e limpeza de ambiente PyInstaller validadas")

    monitors = enumerate_monitors()
    assert len(monitors) >= 1
    for mon in monitors:
        for mode in ("taskbar", "above"):
            ax, ay = compute_taskbar_anchor(mon, 160, 34, mode=mode)
            ml, mt, mr, mb = mon.monitor_rect
            assert ml <= ax <= mr - 160 and mt <= ay <= mb - 34
        _safe_print(f"[OK] {mon.label} | dev={mon.device_name} | dpi={mon.dpi} | rect={mon.monitor_rect}")

    if preview_path:
        out = Path(preview_path)
        save_icon_preview(out)
        _safe_print(f"[OK] Pré-visualização salva em: {out}")

    app = BatteryTrayApp(interval_override=interval_seconds, open_guide_override=False)
    live_statuses = app.poll_once(update_tray=False)
    live_cfg = app.get_config()
    _safe_print(f"[OK] Dispositivos descobertos ao vivo: {len(live_statuses)}")
    for status in live_statuses:
        tooltip = status.tooltip_text(live_cfg.language)
        assert len(tooltip) <= 120, f"Tooltip acima de 120 chars: {len(tooltip)}"
        visible = should_show_in_tray(status, live_cfg)
        _safe_print(
            f"[OK] {status.display_name} ({status.vid_pid}) [{status.icon_kind}]: "
            f"pct={status.percentage} | sleep={status.is_sleeping} | "
            f"visivel_bandeja={visible} | tooltip='{tooltip}'"
        )
        _safe_print(f"     menu='{status.menu_summary(live_cfg.language)}' | raw='{status.raw_info}'")

    # Validação da UI in-place (sem flicker), troca dinâmica de idioma, widget e wizard
    ui_statuses = live_statuses if live_statuses else [sim_sleep_mouse, sim_unsupported_headset]
    ui_cfg = AppConfig(
        interval_seconds=interval_seconds,
        hide_unsupported=True,
        show_guide_on_start=False,
        language="pt-BR",
    )

    test_root = tk.Tk()
    test_root.withdraw()
    try:
        dash = DashboardWindow(
            test_root,
            get_config=lambda: ui_cfg,
            get_statuses=lambda: ui_statuses,
            should_show_device=should_show_in_tray,
            on_refresh=lambda: None,
            on_toggle_startup=is_startup_enabled,
            on_toggle_hide_unsupported=lambda _hide: None,
            on_change_interval=lambda _sec: None,
            on_change_show_on_start=lambda _show: None,
            on_change_widget_monitor=lambda _mon: None,
            on_reset_widget_position=lambda: None,
            on_change_language=lambda _lang: None,
            on_toggle_device_visibility=lambda _did, _vis: None,
        )
        dash._build_window()
        if dash._top is not None and dash._top.winfo_exists():
            dash._top.withdraw()
        dash.refresh_view()
        first_cards = {did: cw.card for did, cw in dash._card_widgets.items()}
        assert len(first_cards) == len(ui_statuses)

        # Segunda atualização com mesma lista deve manter EXATAMENTE os mesmos widgets
        dash.refresh_view()
        second_cards = {did: cw.card for did, cw in dash._card_widgets.items()}
        for did, frame in first_cards.items():
            assert second_cards[did] is frame, f"Card {did} foi recriado indevidamente!"

        # Troca dinâmica de idioma EN -> PT-BR preservando os mesmos cards
        ui_cfg.language = "en"
        dash.refresh_view()
        assert dash._notebook is not None
        assert dash._notebook.tab(1, "text") == "Settings"
        assert dash._card_widgets[ui_statuses[0].device_id].vis_button.cget("text") in ("Hide", "Show")

        ui_cfg.language = "pt-BR"
        dash.refresh_view()
        assert dash._notebook.tab(1, "text") == "Configurações"
        for did, frame in first_cards.items():
            assert dash._card_widgets[did].card is frame

        test_root.update_idletasks()
        if dash._top is not None and dash._top.winfo_exists():
            dash._top.destroy()

        target_mon = monitors[1] if len(monitors) > 1 else monitors[0]
        for lang_code in ("pt-BR", "en"):
            widget_cfg = AppConfig(
                interval_seconds=interval_seconds,
                hide_unsupported=True,
                show_guide_on_start=False,
                widget_monitor=target_mon.device_name,
                widget_position_mode="taskbar",
                language=lang_code,
            )
            widget = TaskbarWidgetWindow(
                test_root,
                get_config=lambda c=widget_cfg: c,
                get_statuses=lambda: ui_statuses,
                should_show_device=should_show_in_tray,
                on_refresh=lambda: None,
                on_open_dashboard=lambda: None,
                on_select_monitor=lambda _mon: None,
                on_toggle_position_mode=lambda: None,
                on_reset_position=lambda: None,
                on_save_custom_position=lambda _x, _y: None,
            )
            widget.sync()
            test_root.update_idletasks()
            assert widget.is_visible()
            widget.destroy()

        wizard = FirstRunWizardDialog(
            test_root,
            current_exe=Path("C:/Downloads/HIDPower.exe"),
            initial_lang="pt-BR",
            show_window=False,
        )
        assert wizard._exe_action_var.get() == "move"
        wizard.apply_language("en")
        assert wizard._btn_continue.cget("text") == "Continue"
        wizard.apply_language("pt-BR")
        assert wizard._btn_continue.cget("text") == "Continuar"
        wizard.destroy()
    finally:
        test_root.destroy()
    _safe_print("[OK] DashboardWindow (in-place + i18n), TaskbarWidgetWindow e Wizard validados sem .ico")

    shortcut_path = get_startup_shortcut_path()
    target, args, workdir = get_startup_target_and_args()
    _safe_print(f"[OK] Startup path: {shortcut_path} (ativo={is_startup_enabled()})")
    _safe_print(f"     Target: {target} | Args: {args} | Workdir: {workdir}")
    return 0


def parse_args() -> argparse.Namespace:
    """Processa argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        description="HIDPower — Monitor de bateria de periféricos sem fio na bandeja do Windows."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Sobrescreve o intervalo entre leituras em segundos (mínimo: 5).",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Inicia minimizado na bandeja sem abrir a janela de painel/guia.",
    )
    parser.add_argument(
        "--setup-wizard",
        action="store_true",
        help="Abre o assistente para escolher/alterar a pasta portátil HIDPower.",
    )
    parser.add_argument(
        "--cleanup-old-exe",
        type=str,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Valida ícones, logo HIP, in-place UI, i18n, widget e descoberta ao vivo.",
    )
    parser.add_argument(
        "--save-preview",
        type=str,
        default=None,
        help="Opcional com --self-test: salva folha de contato PNG dos ícones em 64x64 e 20x20.",
    )
    parser.add_argument(
        "--smoke-tray",
        type=float,
        default=0.0,
        help="Executa a bandeja real + Tk por N segundos para teste e encerra.",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada principal do aplicativo."""
    configure_utf8_stdio()
    enable_dpi_awareness()
    args = parse_args()

    if args.cleanup_old_exe:
        _schedule_old_exe_cleanup(args.cleanup_old_exe)

    if args.self_test:
        return run_self_test(args.interval or 60, preview_path=args.save_preview)

    if args.smoke_tray > 0:
        app = BatteryTrayApp(
            interval_override=args.interval,
            open_guide_override=False,
        )
        app.run_forever(max_seconds=args.smoke_tray)
        _safe_print(f"Smoke test concluído ({args.smoke_tray}s) com encerramento limpo.")
        return 0

    mutex = SingleInstanceMutex()
    if not mutex.acquire(retries=15 if args.cleanup_old_exe else 1, delay=0.2):
        lang = load_config().language
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                tr(lang, "already_running"),
                APP_TITLE,
                0x40,
            )
        except Exception:
            pass
        return 0

    try:
        if args.setup_wizard or (not args.no_gui and needs_first_run_setup()):
            current_exe = (
                Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
            )
            setup_res = run_first_run_wizard(
                current_exe=current_exe,
                initial_lang=load_config().language,
            )
            if setup_res is None:
                return 0
            relaunch_exe, old_exe = apply_first_run_setup(
                setup_res, current_exe=current_exe
            )
            if relaunch_exe is not None:
                mutex.release()
                launch_cmd = [str(relaunch_exe)]
                if old_exe:
                    launch_cmd.extend(["--cleanup-old-exe", old_exe])
                creationflags = (
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                subprocess.Popen(
                    launch_cmd,
                    cwd=str(relaunch_exe.parent),
                    env=build_clean_subprocess_env(),
                    close_fds=True,
                    creationflags=creationflags,
                )
                return 0

        append_log("HIDPower started")
        app = BatteryTrayApp(
            interval_override=args.interval,
            open_guide_override=False if args.no_gui else None,
        )
        app.run_forever()
    finally:
        mutex.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
