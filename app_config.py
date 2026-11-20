"""Configuração persistente, pasta portátil HIDPower, logs, cache e inicialização."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from i18n import normalize_language

APP_NAME = "HIDPower"
STARTUP_SHORTCUT_NAME = "HIDPower.lnk"
LEGACY_STARTUP_SHORTCUT_NAME = "MonitorBateriaPerifericos.lnk"
POINTER_FILENAME = "HIDPower_path.txt"
MAX_LOG_BYTES = 512 * 1024

_ACTIVE_DATA_DIR: Path | None = None


def _get_roaming_appdata() -> Path:
    appdata = os.environ.get("APPDATA")
    return Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")


def get_pointer_file_path() -> Path:
    """Retorna o caminho do ponteiro de diretório configurado em %APPDATA%."""
    return _get_roaming_appdata() / POINTER_FILENAME


def normalize_hidpower_folder(chosen: Path) -> Path:
    """Garante que a pasta final se chame HIDPower (criando subpasta se necessário)."""
    base = Path(chosen).expanduser()
    if base.name.lower() == "hidpower":
        return base
    return base / APP_NAME


def _get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_existing_data_dir() -> Path | None:
    """Resolve a pasta HIDPower existente pelo ponteiro em %APPDATA% ou pasta local."""
    pointer = get_pointer_file_path()
    try:
        if pointer.exists():
            raw = pointer.read_text(encoding="utf-8").strip()
            if raw:
                cand = Path(raw).expanduser()
                if cand.is_dir():
                    return cand
    except Exception:
        pass

    base_dir = _get_app_base_dir()
    if base_dir.name.lower() == "hidpower" and (base_dir / "config.json").exists():
        return base_dir
    local_sub = base_dir / APP_NAME
    if local_sub.is_dir():
        return local_sub
    return None


def needs_first_run_setup() -> bool:
    """Indica se ainda não existe pasta HIDPower configurada para este usuário."""
    return resolve_existing_data_dir() is None


def _get_windows_documents_dir() -> Path:
    """Obtém a pasta Documentos real do usuário via SHGetFolderPathW (suporta OneDrive)."""
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHGetFolderPathW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
        ]
        shell32.SHGetFolderPathW.restype = ctypes.c_long
        buf = ctypes.create_unicode_buffer(260)
        if shell32.SHGetFolderPathW(0, 5, 0, 0, buf) == 0 and buf.value:
            cand = Path(buf.value)
            if cand.is_dir():
                return cand
    except Exception:
        pass
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


def is_ephemeral_exe_dir(folder: Path) -> bool:
    """Indica se o diretório é temporário/Downloads onde o usuário não costuma manter o app."""
    lowered_parts = {part.lower() for part in Path(folder).parts}
    return bool(lowered_parts & {"downloads", "temp", "tmp"})


def get_suggested_parent_dir() -> Path:
    """Sugere o diretório pai padrão no assistente de primeiro uso."""
    base_dir = _get_app_base_dir()
    if getattr(sys, "frozen", False) and is_ephemeral_exe_dir(base_dir):
        return _get_windows_documents_dir()
    return base_dir


def set_active_data_dir(folder: Path, persist_pointer: bool = True) -> Path:
    """Define e cria a pasta ativa de dados do HIDPower e opcionalmente grava o ponteiro."""
    global _ACTIVE_DATA_DIR
    resolved = Path(folder).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    _ACTIVE_DATA_DIR = resolved
    if persist_pointer:
        pointer = get_pointer_file_path()
        try:
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text(str(resolved), encoding="utf-8")
        except Exception:
            pass
    return resolved


def get_data_dir() -> Path:
    """Retorna o diretório ativo de dados (config.json, state.json, hidpower.log)."""
    if _ACTIVE_DATA_DIR is not None:
        return _ACTIVE_DATA_DIR
    resolved = resolve_existing_data_dir()
    if resolved is not None:
        return resolved
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else (Path.home() / "AppData" / "Local")
    return base / APP_NAME


def get_config_path() -> Path:
    """Retorna o caminho do arquivo config.json."""
    return get_data_dir() / "config.json"


def get_state_path() -> Path:
    """Retorna o caminho do arquivo state.json (cache da última carga)."""
    return get_data_dir() / "state.json"


def get_log_path() -> Path:
    """Retorna o caminho do arquivo de log do HIDPower."""
    return get_data_dir() / "hidpower.log"


def append_log(message: str) -> None:
    """Registra uma linha de log com rotação simples quando exceder 512 KB."""
    log_path = get_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            backup = log_path.with_suffix(".log.1")
            try:
                if backup.exists():
                    backup.unlink()
                log_path.replace(backup)
            except Exception:
                pass
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _parse_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


@dataclass
class AppConfig:
    """Preferências persistentes do HIDPower."""

    interval_seconds: int = 60
    hide_unsupported: bool = True
    show_guide_on_start: bool = True
    widget_monitor: str = ""
    widget_position_mode: str = "taskbar"
    widget_custom_x: int | None = None
    widget_custom_y: int | None = None
    language: str = "pt-BR"
    device_visibility: dict[str, bool] = field(default_factory=dict)

    def normalized(self) -> AppConfig:
        """Garante valores válidos dentro dos limites esperados."""
        self.interval_seconds = max(5, int(self.interval_seconds))
        self.hide_unsupported = bool(self.hide_unsupported)
        self.show_guide_on_start = bool(self.show_guide_on_start)
        self.widget_monitor = str(self.widget_monitor or "").strip()
        if self.widget_position_mode not in ("taskbar", "above"):
            self.widget_position_mode = "taskbar"
        self.widget_custom_x = _parse_optional_int(self.widget_custom_x)
        self.widget_custom_y = _parse_optional_int(self.widget_custom_y)
        self.language = normalize_language(self.language)
        clean_vis: dict[str, bool] = {}
        if isinstance(self.device_visibility, dict):
            for dev_id, vis in self.device_visibility.items():
                if isinstance(dev_id, str) and dev_id.strip():
                    clean_vis[dev_id] = bool(vis)
        self.device_visibility = clean_vis
        return self


def load_config() -> AppConfig:
    """Carrega config.json com fallback seguro para padrões."""
    path = get_config_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw_vis = raw.get("device_visibility")
                vis_map = raw_vis if isinstance(raw_vis, dict) else {}
                return AppConfig(
                    interval_seconds=int(raw.get("interval_seconds", 60)),
                    hide_unsupported=bool(raw.get("hide_unsupported", True)),
                    show_guide_on_start=bool(raw.get("show_guide_on_start", True)),
                    widget_monitor=str(raw.get("widget_monitor", "") or ""),
                    widget_position_mode=str(raw.get("widget_position_mode", "taskbar") or "taskbar"),
                    widget_custom_x=_parse_optional_int(raw.get("widget_custom_x")),
                    widget_custom_y=_parse_optional_int(raw.get("widget_custom_y")),
                    language=str(raw.get("language", "pt-BR") or "pt-BR"),
                    device_visibility=dict(vis_map),
                ).normalized()
    except Exception:
        pass
    return AppConfig().normalized()


def save_config(cfg: AppConfig) -> None:
    """Grava config.json sem interromper o app em caso de erro de E/S."""
    cfg.normalized()
    path = get_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_battery_state() -> dict[str, dict[str, object]]:
    """Carrega última porcentagem conhecida por device_id."""
    path = get_state_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                clean: dict[str, dict[str, object]] = {}
                for dev_id, info in raw.items():
                    if not isinstance(dev_id, str) or not isinstance(info, dict):
                        continue
                    pct = info.get("percentage")
                    updated_at = info.get("updated_at")
                    if isinstance(pct, int) and 0 <= pct <= 100:
                        clean[dev_id] = {
                            "percentage": pct,
                            "updated_at": str(updated_at or ""),
                        }
                return clean
    except Exception:
        pass
    return {}


def save_battery_state(state: dict[str, dict[str, object]]) -> None:
    """Salva última porcentagem conhecida por device_id."""
    path = get_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _get_startup_dir() -> Path:
    return (
        _get_roaming_appdata()
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def get_startup_shortcut_path() -> Path:
    """Retorna o caminho do atalho HIDPower.lnk na pasta shell:startup."""
    return _get_startup_dir() / STARTUP_SHORTCUT_NAME


def get_startup_target_and_args(
    exe_override: Path | None = None,
) -> tuple[str, str, str]:
    """Determina executável, argumentos e diretório de trabalho para o atalho Startup."""
    if exe_override is not None:
        resolved = Path(exe_override).resolve()
        return str(resolved), "--no-gui", str(resolved.parent)

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return str(exe_path), "--no-gui", str(exe_path.parent)

    py_exe = Path(sys.executable).resolve()
    pythonw = py_exe.with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else py_exe
    tray_script = Path(__file__).resolve().with_name("battery_tray.py")
    return str(target), f'"{tray_script}" --no-gui', str(tray_script.parent)


def is_startup_enabled() -> bool:
    """Indica se o atalho de inicialização automática com o Windows existe."""
    return get_startup_shortcut_path().exists()


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _remove_legacy_startup_shortcut() -> None:
    legacy = _get_startup_dir() / LEGACY_STARTUP_SHORTCUT_NAME
    try:
        if legacy.exists():
            legacy.unlink()
    except Exception:
        pass


def set_startup_enabled(
    enable: bool, exe_override: Path | None = None
) -> bool:
    """Cria ou remove o atalho HIDPower.lnk na pasta Startup do Windows."""
    _remove_legacy_startup_shortcut()
    shortcut_path = get_startup_shortcut_path()
    if not enable:
        if shortcut_path.exists():
            shortcut_path.unlink()
        return False

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    target, args, workdir = get_startup_target_and_args(exe_override=exe_override)
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{_ps_quote(str(shortcut_path))}'); "
        f"$sc.TargetPath = '{_ps_quote(target)}'; "
        f"$sc.Arguments = '{_ps_quote(args)}'; "
        f"$sc.WorkingDirectory = '{_ps_quote(workdir)}'; "
        "$sc.Description = 'HIDPower - Wireless Peripheral Battery Monitor'; "
        "$sc.Save()"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            ps_script,
        ],
        check=True,
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )
    return True


def toggle_startup() -> bool:
    """Alterna o estado do atalho em shell:startup e retorna o novo estado."""
    return set_startup_enabled(not is_startup_enabled())


def get_asset_path(relative_path: str) -> Path:
    """Resolve caminho de assets tanto em desenvolvimento quanto empacotado via PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative_path
