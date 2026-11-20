"""Utilitários Win32 via ctypes para detecção de múltiplos monitores, DPI e estilo da mini-barra."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from i18n import tr

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUNDSMALL = 3
MONITORINFOF_PRIMARY = 0x00000001
MDT_EFFECTIVE_DPI = 0


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(_RECT),
    wintypes.LPARAM,
)


@dataclass(frozen=True)
class MonitorInfo:
    """Metadados físicos e área útil de um monitor Windows."""

    index: int
    device_name: str
    is_primary: bool
    monitor_rect: tuple[int, int, int, int]
    work_rect: tuple[int, int, int, int]
    dpi: int

    @property
    def width(self) -> int:
        return self.monitor_rect[2] - self.monitor_rect[0]

    @property
    def height(self) -> int:
        return self.monitor_rect[3] - self.monitor_rect[1]

    @property
    def scale(self) -> float:
        return max(1.0, self.dpi / 96.0)

    def format_label(self, lang: str = "pt-BR") -> str:
        """Retorna rótulo legível do monitor no idioma especificado."""
        role = tr(lang, "monitor_primary" if self.is_primary else "monitor_secondary")
        return tr(
            lang,
            "monitor_label",
            index=self.index,
            role=role,
            width=self.width,
            height=self.height,
        )

    @property
    def label(self) -> str:
        return self.format_label("pt-BR")


def enable_dpi_awareness() -> None:
    """Ativa Per-Monitor V2 DPI Awareness antes de criar janelas Tkinter."""
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
    except Exception:
        pass

    try:
        shcore = ctypes.windll.shcore
        if hasattr(shcore, "SetProcessDpiAwareness"):
            shcore.SetProcessDpiAwareness(2)
            return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def enumerate_monitors() -> list[MonitorInfo]:
    """Enumera monitores ativos via EnumDisplayMonitors + GetMonitorInfoW + GetDpiForMonitor."""
    raw_items: list[tuple[str, bool, tuple[int, int, int, int], tuple[int, int, int, int], int]] = []
    try:
        user32 = ctypes.windll.user32
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_RECT),
            _MONITORENUMPROC,
            wintypes.LPARAM,
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL

        shcore = None
        try:
            shcore = ctypes.windll.shcore
            shcore.GetDpiForMonitor.argtypes = [
                wintypes.HMONITOR,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
        except Exception:
            shcore = None

        def _callback(hmonitor, _hdc, _lprect, _lparam) -> bool:
            info = _MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
            if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return True

            dpi_val = 96
            if shcore is not None:
                dx = wintypes.UINT(96)
                dy = wintypes.UINT(96)
                try:
                    if shcore.GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                        if dx.value > 0:
                            dpi_val = int(dx.value)
                except Exception:
                    pass

            mon_rect = (
                int(info.rcMonitor.left),
                int(info.rcMonitor.top),
                int(info.rcMonitor.right),
                int(info.rcMonitor.bottom),
            )
            work_rect = (
                int(info.rcWork.left),
                int(info.rcWork.top),
                int(info.rcWork.right),
                int(info.rcWork.bottom),
            )
            device_name = str(info.szDevice or "").strip() or f"DISPLAY_{len(raw_items) + 1}"
            is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
            raw_items.append((device_name, is_primary, mon_rect, work_rect, dpi_val))
            return True

        cb = _MONITORENUMPROC(_callback)
        user32.EnumDisplayMonitors(0, None, cb, 0)
    except Exception:
        raw_items = []

    if not raw_items:
        try:
            w = int(ctypes.windll.user32.GetSystemMetrics(0)) or 1920
            h = int(ctypes.windll.user32.GetSystemMetrics(1)) or 1080
        except Exception:
            w, h = 1920, 1080
        return [
            MonitorInfo(
                index=1,
                device_name="\\\\.\\DISPLAY1",
                is_primary=True,
                monitor_rect=(0, 0, w, h),
                work_rect=(0, 0, w, max(100, h - 48)),
                dpi=96,
            )
        ]

    # Principal primeiro, seguido pelos demais ordenados da esquerda para direita / topo para baixo
    raw_items.sort(key=lambda item: (0 if item[1] else 1, item[2][0], item[2][1]))
    return [
        MonitorInfo(
            index=idx,
            device_name=dev_name,
            is_primary=is_primary,
            monitor_rect=mon_rect,
            work_rect=work_rect,
            dpi=dpi_val,
        )
        for idx, (dev_name, is_primary, mon_rect, work_rect, dpi_val) in enumerate(raw_items, start=1)
    ]


def find_monitor_by_name(
    monitors: list[MonitorInfo], device_name: str
) -> MonitorInfo | None:
    """Encontra um monitor pelo device_name (ex.: \\\\.\\DISPLAY2)."""
    target = (device_name or "").strip().lower()
    if not target:
        return None
    for mon in monitors:
        if mon.device_name.strip().lower() == target:
            return mon
    return None


def get_primary_monitor(monitors: list[MonitorInfo]) -> MonitorInfo | None:
    """Retorna o monitor principal ou o primeiro disponível."""
    for mon in monitors:
        if mon.is_primary:
            return mon
    return monitors[0] if monitors else None


def get_virtual_desktop_bounds(monitors: list[MonitorInfo]) -> tuple[int, int, int, int]:
    """Retorna o retângulo envolvente (left, top, right, bottom) de todos os monitores."""
    if not monitors:
        return (0, 0, 1920, 1080)
    left = min(m.monitor_rect[0] for m in monitors)
    top = min(m.monitor_rect[1] for m in monitors)
    right = max(m.monitor_rect[2] for m in monitors)
    bottom = max(m.monitor_rect[3] for m in monitors)
    return (left, top, right, bottom)


def compute_taskbar_anchor(
    monitor: MonitorInfo,
    widget_w: int,
    widget_h: int,
    mode: str = "taskbar",
) -> tuple[int, int]:
    """Calcula a coordenada (x, y) da mini-barra junto à barra de tarefas do monitor."""
    ml, mt, mr, mb = monitor.monitor_rect
    wl, wt, wr, wb = monitor.work_rect
    scale = monitor.scale
    margin = int(round(10 * scale))
    gap = int(round(6 * scale))

    bottom_bar_h = mb - wb
    top_bar_h = wt - mt

    if bottom_bar_h >= widget_h + 4:
        if mode == "taskbar" and not monitor.is_primary:
            right_offset = int(round(104 * scale))
            x = mr - widget_w - right_offset
            y = wb + (bottom_bar_h - widget_h) // 2
        else:
            x = mr - widget_w - margin
            y = wb - widget_h - gap
    elif top_bar_h >= widget_h + 4:
        if mode == "taskbar" and not monitor.is_primary:
            right_offset = int(round(104 * scale))
            x = mr - widget_w - right_offset
            y = mt + (top_bar_h - widget_h) // 2
        else:
            x = mr - widget_w - margin
            y = wt + gap
    else:
        # Barra de tarefas lateral ou auto-oculta: ancora no canto inferior direito útil
        x = wr - widget_w - margin
        y = wb - widget_h - gap

    x = max(ml, min(x, mr - widget_w))
    y = max(mt, min(y, mb - widget_h))
    return (int(x), int(y))


def get_toplevel_hwnd(tk_window: object) -> int:
    """Obtém o HWND real de um Toplevel Tk (inclusive com overrideredirect)."""
    wid = int(tk_window.winfo_id())  # type: ignore[attr-defined]
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        parent = user32.GetParent(wintypes.HWND(wid))
        if parent:
            return int(parent)
    except Exception:
        pass
    return wid


def raise_widget_topmost(hwnd: int) -> None:
    """Mantém o widget acima da barra de tarefas sem roubar foco do usuário."""
    if not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
    except Exception:
        pass


def apply_taskbar_widget_styles(hwnd: int) -> None:
    """Configura janela como ToolWindow discreta, cantos arredondados Win11 e topmost."""
    if not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        get_wl = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_wl = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_wl.argtypes = [wintypes.HWND, ctypes.c_int]
        get_wl.restype = ctypes.c_ssize_t
        set_wl.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_wl.restype = ctypes.c_ssize_t

        ex_style = int(get_wl(wintypes.HWND(hwnd), GWL_EXSTYLE))
        new_style = (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if new_style != ex_style:
            set_wl(wintypes.HWND(hwnd), GWL_EXSTYLE, new_style)
    except Exception:
        pass

    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        pref = ctypes.c_int(DWMWCP_ROUNDSMALL)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        pass

    raise_widget_topmost(hwnd)
