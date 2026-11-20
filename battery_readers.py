"""Leitores modulares e descoberta automática de periféricos sem fio (2.4 GHz / XInput / Bluetooth)."""

from __future__ import annotations

from collections import defaultdict
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Protocol

import hid

from i18n import tr


def current_time_str() -> str:
    """Retorna horário local atual no formato HH:MM."""
    return datetime.now().strftime("%H:%M")


def clamp_tooltip(text: str, max_len: int = 120) -> str:
    """Garante que o tooltip do ícone na bandeja respeite o limite do Windows."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


@dataclass
class DeviceBatteryStatus:
    """Representa o estado de conexão e bateria de um periférico monitorado."""

    device_id: str
    display_name: str
    icon_kind: str
    short_tag: str
    accent_rgb: tuple[int, int, int]
    vid_pid: str
    connected: bool
    awake: bool
    percentage: int | None
    charging: bool | None
    telemetry_supported: bool
    detail: str
    raw_info: str
    last_known_percentage: int | None = None
    last_known_at: str | None = None
    updated_at: str = ""
    detail_key: str = ""
    detail_args: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = current_time_str()
        if self.percentage is not None:
            self.last_known_percentage = self.percentage
            self.last_known_at = self.updated_at

    @property
    def is_sleeping(self) -> bool:
        """Indica se um dispositivo suportado está desligado/sleep por inatividade."""
        return (
            self.connected
            and self.telemetry_supported
            and not self.awake
            and self.percentage is None
        )

    def merge_previous(self, prev: DeviceBatteryStatus | None) -> DeviceBatteryStatus:
        """Preserva a última porcentagem conhecida quando o periférico entra em sleep."""
        if self.percentage is not None:
            self.last_known_percentage = self.percentage
            self.last_known_at = self.updated_at
        elif prev is not None:
            self.last_known_percentage = prev.last_known_percentage
            self.last_known_at = prev.last_known_at
        return self

    def localized_detail(self, lang: str = "pt-BR") -> str:
        """Retorna a descrição de status traduzida para o idioma selecionado."""
        if self.detail_key:
            return tr(lang, self.detail_key, **self.detail_args)
        return self.detail

    def _last_known_suffix(self, lang: str = "pt-BR") -> str:
        if self.last_known_percentage is None:
            return ""
        if self.last_known_at:
            return tr(
                lang,
                "last_prefix_at",
                pct=self.last_known_percentage,
                when=self.last_known_at,
            )
        return tr(lang, "last_prefix", pct=self.last_known_percentage)

    def tooltip_text(self, lang: str = "pt-BR") -> str:
        """Gera texto conciso para tooltip do ícone na bandeja (<= 120 chars)."""
        if self.percentage is not None:
            if self.charging is True:
                state_desc = tr(lang, "state_charging")
            elif self.detail_key == "detail_xinput_wired" or "XInput Wired" in self.detail:
                state_desc = tr(lang, "state_xinput_wired")
            elif self.detail_key == "detail_bt_connected" or "Bluetooth" in self.detail:
                state_desc = tr(lang, "state_bluetooth")
            else:
                state_desc = tr(lang, "state_battery")
            return clamp_tooltip(f"{self.display_name}: {self.percentage}% ({state_desc})")

        last_text = self._last_known_suffix(lang)
        if self.is_sleeping:
            if last_text:
                return clamp_tooltip(
                    tr(lang, "tooltip_sleep_last", name=self.display_name, last=last_text)
                )
            return clamp_tooltip(tr(lang, "tooltip_sleep_move", name=self.display_name))

        if self.connected and not self.telemetry_supported:
            suffix = f" | {last_text}" if last_text else ""
            return clamp_tooltip(
                tr(lang, "tooltip_no_telemetry", name=self.display_name, suffix=suffix)
            )

        suffix = f" | {last_text}" if last_text else ""
        return clamp_tooltip(
            tr(lang, "tooltip_disconnected", name=self.display_name, suffix=suffix)
        )

    def menu_summary(self, lang: str = "pt-BR") -> str:
        """Gera resumo em linha única para o menu de contexto da bandeja."""
        detail_txt = self.localized_detail(lang)
        if self.percentage is not None:
            suffix = tr(lang, "state_charging") if self.charging is True else detail_txt
            return f"{self.display_name}: {self.percentage}% ({suffix})"

        if self.is_sleeping:
            last_part = (
                tr(lang, "last_prefix", pct=self.last_known_percentage)
                if self.last_known_percentage is not None
                else detail_txt
            )
            return tr(lang, "menu_sleep", name=self.display_name, last=last_part)

        last_suffix = (
            f" [{tr(lang, 'last_prefix', pct=self.last_known_percentage)}]"
            if self.last_known_percentage is not None
            else ""
        )
        return f"{self.display_name}: -- ({detail_txt}){last_suffix}"


class BatteryReader(Protocol):
    """Interface comum dos leitores individuais (compatível com probe_dispositivos.py)."""

    device_id: str
    display_name: str
    icon_kind: str
    short_tag: str
    accent_rgb: tuple[int, int, int]
    vid_pid: str

    def read_status(self) -> DeviceBatteryStatus:
        """Consulta o dispositivo e retorna o status atual."""
        ...


def _classify_icon_kind(name: str, fallback: str = "mouse") -> str:
    lower = name.lower()
    if any(k in lower for k in ("headset", "headphone", "morcego", "fone", "earbud", "buds", "audio")):
        return "headset"
    if any(k in lower for k in ("keyboard", "teclado", "keychron")):
        return "keyboard"
    if any(k in lower for k in ("gamepad", "controller", "controle", "xbox", "dualsense", "dualshock", "8bitdo")):
        return "gamepad"
    if "mouse" in lower:
        return "mouse"
    return fallback


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned[:28] or "device"


class CompxMouseReader:
    """Leitor para receptor 2.4 GHz ou cabo USB Compx/Areson (ex.: 0x25A7:0xFA07 / 0xFA08)."""

    VID = 0x25A7
    PID_WIRELESS = 0xFA07
    PID = PID_WIRELESS
    PID_WIRED = 0xFA08
    UNIFIED_DEVICE_ID = "bat_mouse_compx"
    UNIFIED_DISPLAY_NAME = "Mouse Compx"
    REPORT_ID_OUT = 0x08
    REPORT_ID_IN = 0x09
    CMD_ONLINE = 0x03
    CMD_BATTERY = 0x04

    def __init__(
        self,
        *,
        vid: int = VID,
        pid: int = PID,
        device_id: str | None = None,
        display_name: str | None = None,
        icon_kind: str = "mouse",
        wired_usb: bool | None = None,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.wired_usb = (
            bool(wired_usb)
            if wired_usb is not None
            else (vid, pid) == (self.VID, self.PID_WIRED)
        )
        if device_id is not None:
            self.device_id = device_id
        elif (vid, pid) in ((self.VID, self.PID_WIRELESS), (self.VID, self.PID_WIRED)):
            self.device_id = self.UNIFIED_DEVICE_ID
        else:
            self.device_id = f"bat_compx_{vid:04x}_{pid:04x}"

        if display_name is not None:
            self.display_name = display_name
        elif (vid, pid) in ((self.VID, self.PID_WIRELESS), (self.VID, self.PID_WIRED)):
            self.display_name = self.UNIFIED_DISPLAY_NAME
        else:
            self.display_name = f"Periférico Compx ({vid:04X}:{pid:04X})"

        self.icon_kind = icon_kind
        self.short_tag = "KB" if icon_kind == "keyboard" else "MS"
        self.accent_rgb = (56, 189, 248)
        self.vid_pid = f"{vid:04X}:{pid:04X}"

    def _base_status(
        self,
        *,
        connected: bool,
        awake: bool,
        percentage: int | None,
        charging: bool | None,
        detail: str,
        raw_info: str,
        detail_key: str = "",
        detail_args: dict[str, object] | None = None,
    ) -> DeviceBatteryStatus:
        return DeviceBatteryStatus(
            device_id=self.device_id,
            display_name=self.display_name,
            icon_kind=self.icon_kind,
            short_tag=self.short_tag,
            accent_rgb=self.accent_rgb,
            vid_pid=self.vid_pid,
            connected=connected,
            awake=awake,
            percentage=percentage,
            charging=charging,
            telemetry_supported=True,
            detail=detail,
            raw_info=raw_info,
            detail_key=detail_key,
            detail_args=detail_args or {},
        )

    @staticmethod
    def _build_packet(cmd: int) -> list[int]:
        packet = [CompxMouseReader.REPORT_ID_OUT, cmd] + [0x00] * 14
        checksum = (0x55 - sum(packet)) & 0xFF
        packet.append(checksum)
        return packet

    @staticmethod
    def _send_and_read(
        h_feat: hid.device, h_in: hid.device, cmd: int, timeout_ms: int = 450
    ) -> list[int] | None:
        packet = CompxMouseReader._build_packet(cmd)
        h_feat.send_feature_report(packet)
        for _ in range(4):
            reply = h_in.read(64, timeout_ms=timeout_ms)
            if not reply:
                return None
            if (
                len(reply) >= 17
                and reply[0] == CompxMouseReader.REPORT_ID_IN
                and reply[1] == cmd
            ):
                if (sum(reply[:17]) & 0xFF) == 0x55:
                    return [int(b) for b in reply[:17]]
        return None

    def read_status(self, interfaces: list[dict] | None = None) -> DeviceBatteryStatus:
        """Consulta estado online (0x03) e bateria (0x04) via HID 0xFF02/0xFF01."""
        entries = interfaces if interfaces is not None else hid.enumerate(self.vid, self.pid)
        paths = {
            int(entry.get("usage_page", 0) or 0): entry["path"]
            for entry in entries
        }
        path_in = paths.get(0xFF01)
        path_feat = paths.get(0xFF02)
        if not path_in or not path_feat:
            return self._base_status(
                connected=False,
                awake=False,
                percentage=None,
                charging=None,
                detail="Receptor 2.4G desconectado",
                raw_info="interfaces 0xFF01/0xFF02 ausentes",
                detail_key="detail_compx_disconnected",
            )

        h_in = hid.device()
        h_feat = hid.device()
        in_opened = False
        feat_opened = False
        try:
            # Abrir 0xFF01 antes de enviar na 0xFF02 garante captura do input report de resposta
            h_in.open_path(path_in)
            in_opened = True
            h_in.set_nonblocking(1)
            for _ in range(8):
                if not h_in.read(64):
                    break
            h_in.set_nonblocking(0)

            h_feat.open_path(path_feat)
            feat_opened = True

            online_reply = self._send_and_read(h_feat, h_in, self.CMD_ONLINE)
            online_hex = ""
            if online_reply is not None:
                online_hex = " ".join(f"{b:02X}" for b in online_reply)
                if not self.wired_usb and online_reply[2] == 0x00 and online_reply[6] == 0:
                    return self._base_status(
                        connected=True,
                        awake=False,
                        percentage=None,
                        charging=None,
                        detail="Desligado / Sleep por inatividade",
                        raw_info=f"online=0 ({online_hex})",
                        detail_key="detail_compx_sleep",
                    )
            elif not self.wired_usb:
                return self._base_status(
                    connected=True,
                    awake=False,
                    percentage=None,
                    charging=None,
                    detail="Desligado / Sleep (sem resposta)",
                    raw_info="timeout cmd=0x03",
                    detail_key="detail_compx_sleep_no_reply",
                )

            bat_reply = self._send_and_read(h_feat, h_in, self.CMD_BATTERY)
            if bat_reply is None:
                return self._base_status(
                    connected=True,
                    awake=False,
                    percentage=None,
                    charging=None,
                    detail=(
                        "Cabo USB conectado (sem resposta)"
                        if self.wired_usb
                        else "Desligado / Sleep (timeout bateria)"
                    ),
                    raw_info=(
                        "USB timeout cmd=0x03/0x04"
                        if not online_hex
                        else f"online={online_hex}; timeout cmd=0x04"
                    ),
                    detail_key=(
                        "detail_compx_usb_no_reply"
                        if self.wired_usb
                        else "detail_compx_sleep_timeout"
                    ),
                )

            bat_hex = " ".join(f"{b:02X}" for b in bat_reply)
            if bat_reply[2] != 0x00:
                return self._base_status(
                    connected=True,
                    awake=False,
                    percentage=None,
                    charging=None,
                    detail=(
                        "Cabo USB conectado (aguardando leitura)"
                        if self.wired_usb
                        else "Desligado / Sleep no momento"
                    ),
                    raw_info=f"status!=0 ({bat_hex})",
                    detail_key=(
                        "detail_compx_usb_waiting"
                        if self.wired_usb
                        else "detail_compx_sleep_moment"
                    ),
                )

            raw_level = bat_reply[6]
            raw_charging = bool(bat_reply[7])
            if bat_reply[5] == 2 and 0 <= raw_level <= 10:
                pct = min(100, raw_level * 10)
            else:
                pct = max(0, min(100, raw_level))

            if self.wired_usb:
                charging = True
                detail_key = (
                    "detail_compx_charging"
                    if (raw_charging or pct < 100)
                    else "detail_compx_charging_full"
                )
                detail = (
                    "Carregando via USB"
                    if (raw_charging or pct < 100)
                    else "Carregando via USB (carga completa)"
                )
                raw_info = f"USB cmd04: {bat_hex} (hw_chg={int(raw_charging)})"
            else:
                charging = raw_charging
                detail_key = "detail_compx_charging" if charging else "detail_compx_24g"
                detail = (
                    "Carregando via USB"
                    if charging
                    else "Conectado 2.4 GHz (passos de 10%)"
                )
                raw_info = f"cmd04: {bat_hex}"

            return self._base_status(
                connected=True,
                awake=True,
                percentage=pct,
                charging=charging,
                detail=detail,
                raw_info=raw_info,
                detail_key=detail_key,
            )
        except Exception as exc:
            return self._base_status(
                connected=True,
                awake=False,
                percentage=None,
                charging=None,
                detail="Erro ao consultar HID",
                raw_info=str(exc),
                detail_key="detail_compx_hid_err",
            )
        finally:
            if feat_opened:
                try:
                    h_feat.close()
                except Exception:
                    pass
            if in_opened:
                try:
                    h_in.close()
                except Exception:
                    pass


def resolve_compx_dual_mode(
    wired_status: DeviceBatteryStatus | None,
    wireless_status: DeviceBatteryStatus | None,
) -> DeviceBatteryStatus | None:
    """Prioriza o modo cabo USB (FA08) quando ativo e suprime a duplicata 2.4G (FA07)."""
    if wired_status is not None and (
        wired_status.percentage is not None or wired_status.awake
    ):
        return wired_status
    if wireless_status is not None:
        return wireless_status
    return wired_status


class UnifiedCompxMouseReader:
    """Leitor lógico unificado para Mouse Compx 2.4G (FA07) + Cabo USB (FA08)."""

    VID = CompxMouseReader.VID
    PID_WIRELESS = CompxMouseReader.PID_WIRELESS
    PID_WIRED = CompxMouseReader.PID_WIRED

    def __init__(self) -> None:
        self.device_id = CompxMouseReader.UNIFIED_DEVICE_ID
        self.display_name = CompxMouseReader.UNIFIED_DISPLAY_NAME
        self.icon_kind = "mouse"
        self.short_tag = "MS"
        self.accent_rgb = (56, 189, 248)
        self.vid_pid = "25A7:FA07 / 25A7:FA08"

    @staticmethod
    def has_compx_interfaces(entries: list[dict] | None) -> bool:
        """Verifica se as interfaces HID proprietárias Compx (0xFF01 e 0xFF02) estão presentes."""
        if not entries:
            return False
        pages = {int(e.get("usage_page", 0) or 0) for e in entries}
        return 0xFF01 in pages and 0xFF02 in pages

    def read_status(
        self, grouped_hid: dict[tuple[int, int], list[dict]] | None = None
    ) -> DeviceBatteryStatus:
        """Lê cabo USB (FA08) com prioridade e faz fallback para receptor 2.4G (FA07)."""
        if grouped_hid is not None:
            wired_entries = grouped_hid.get((self.VID, self.PID_WIRED), [])
            wireless_entries = grouped_hid.get((self.VID, self.PID_WIRELESS), [])
        else:
            wired_entries = hid.enumerate(self.VID, self.PID_WIRED)
            wireless_entries = hid.enumerate(self.VID, self.PID_WIRELESS)

        wired_status: DeviceBatteryStatus | None = None
        if self.has_compx_interfaces(wired_entries):
            wired_reader = CompxMouseReader(
                vid=self.VID,
                pid=self.PID_WIRED,
                device_id=self.device_id,
                display_name=self.display_name,
                icon_kind=self.icon_kind,
                wired_usb=True,
            )
            wired_status = wired_reader.read_status(interfaces=wired_entries)
            if wired_status.percentage is not None or wired_status.awake:
                resolved = resolve_compx_dual_mode(wired_status, None)
                assert resolved is not None
                return resolved

        wireless_status: DeviceBatteryStatus | None = None
        if self.has_compx_interfaces(wireless_entries):
            wireless_reader = CompxMouseReader(
                vid=self.VID,
                pid=self.PID_WIRELESS,
                device_id=self.device_id,
                display_name=self.display_name,
                icon_kind=self.icon_kind,
                wired_usb=False,
            )
            wireless_status = wireless_reader.read_status(interfaces=wireless_entries)

        resolved = resolve_compx_dual_mode(wired_status, wireless_status)
        if resolved is not None:
            return resolved

        return DeviceBatteryStatus(
            device_id=self.device_id,
            display_name=self.display_name,
            icon_kind=self.icon_kind,
            short_tag=self.short_tag,
            accent_rgb=self.accent_rgb,
            vid_pid=self.vid_pid,
            connected=False,
            awake=False,
            percentage=None,
            charging=None,
            telemetry_supported=True,
            detail="Receptor 2.4G / cabo USB desconectado",
            raw_info="25A7:FA07 e 25A7:FA08 ausentes",
            detail_key="detail_compx_disconnected",
        )


class _XInputBatteryInformation(ctypes.Structure):
    _fields_ = [
        ("BatteryType", ctypes.c_ubyte),
        ("BatteryLevel", ctypes.c_ubyte),
    ]


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_uint32),
        ("Gamepad", _XInputGamepad),
    ]


class GamepadXInputReader:
    """Leitor para controles XInput (0..3) e presença de receptor HORI/SHANWAN."""

    ERROR_SUCCESS = 0
    BATTERY_DEVTYPE_GAMEPAD = 0
    BATTERY_TYPE_DISCONNECTED = 0x00
    BATTERY_TYPE_WIRED = 0x01
    BATTERY_TYPE_ALKALINE = 0x02
    BATTERY_TYPE_NIMH = 0x03
    BATTERY_TYPE_UNKNOWN = 0xFF
    LEVEL_PCT_MAP = {0: 5, 1: 20, 2: 60, 3: 100}
    LEVEL_NAME_MAP = {0: "EMPTY", 1: "LOW", 2: "MEDIUM", 3: "FULL"}
    TYPE_NAME_MAP = {
        0x00: "DISCONNECTED",
        0x01: "WIRED",
        0x02: "ALKALINE",
        0x03: "NIMH",
        0xFF: "UNKNOWN",
    }

    def __init__(self) -> None:
        self.device_id = "bat_gamepad_xinput"
        self.display_name = "Controle Gamepad"
        self.icon_kind = "gamepad"
        self.short_tag = "GP"
        self.accent_rgb = (192, 132, 252)
        self.vid_pid = "045E:028E / 2563:0575"
        self._xinput = self._load_xinput()

    @staticmethod
    def _load_xinput():
        for dll_name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                lib = ctypes.windll.LoadLibrary(dll_name)
                if hasattr(lib, "XInputGetState") and hasattr(
                    lib, "XInputGetBatteryInformation"
                ):
                    lib.XInputGetState.argtypes = [
                        wintypes.DWORD,
                        ctypes.POINTER(_XInputState),
                    ]
                    lib.XInputGetState.restype = wintypes.DWORD
                    lib.XInputGetBatteryInformation.argtypes = [
                        wintypes.DWORD,
                        ctypes.c_ubyte,
                        ctypes.POINTER(_XInputBatteryInformation),
                    ]
                    lib.XInputGetBatteryInformation.restype = wintypes.DWORD
                    return lib
            except OSError:
                continue
        return None

    def _base_status(
        self,
        *,
        device_id: str | None = None,
        display_name: str | None = None,
        connected: bool,
        awake: bool,
        percentage: int | None,
        charging: bool | None,
        telemetry_supported: bool,
        detail: str,
        raw_info: str,
        detail_key: str = "",
        detail_args: dict[str, object] | None = None,
    ) -> DeviceBatteryStatus:
        return DeviceBatteryStatus(
            device_id=device_id or self.device_id,
            display_name=display_name or self.display_name,
            icon_kind=self.icon_kind,
            short_tag=self.short_tag,
            accent_rgb=self.accent_rgb,
            vid_pid=self.vid_pid,
            connected=connected,
            awake=awake,
            percentage=percentage,
            charging=charging,
            telemetry_supported=telemetry_supported,
            detail=detail,
            raw_info=raw_info,
            detail_key=detail_key,
            detail_args=detail_args or {},
        )

    def read_all_slots(
        self, grouped_hid: dict[tuple[int, int], list[dict]] | None = None
    ) -> list[DeviceBatteryStatus]:
        """Lê todos os slots XInput ativos (0..3) ou retorna status do receptor se presente."""
        if grouped_hid is not None:
            hid_present = (0x2563, 0x0575) in grouped_hid or (0x045E, 0x028E) in grouped_hid
        else:
            hid_present = bool(
                hid.enumerate(0x2563, 0x0575) or hid.enumerate(0x045E, 0x028E)
            )

        statuses: list[DeviceBatteryStatus] = []
        if self._xinput is not None:
            for slot in range(4):
                state = _XInputState()
                if self._xinput.XInputGetState(slot, ctypes.byref(state)) != self.ERROR_SUCCESS:
                    continue

                slot_id = self.device_id if slot == 0 else f"bat_gamepad_xinput_{slot}"
                slot_name = (
                    self.display_name if slot == 0 else f"Controle Gamepad (Slot {slot + 1})"
                )

                bat = _XInputBatteryInformation()
                bat_rc = self._xinput.XInputGetBatteryInformation(
                    slot, self.BATTERY_DEVTYPE_GAMEPAD, ctypes.byref(bat)
                )
                if bat_rc != self.ERROR_SUCCESS:
                    statuses.append(
                        self._base_status(
                            device_id=slot_id,
                            display_name=slot_name,
                            connected=True,
                            awake=True,
                            percentage=None,
                            charging=None,
                            telemetry_supported=False,
                            detail=f"Slot {slot} conectado (XInput sem bateria)",
                            raw_info=f"slot={slot} state_rc=0 bat_rc={bat_rc}",
                            detail_key="detail_xinput_no_bat",
                            detail_args={"slot": slot},
                        )
                    )
                    continue

                btype = int(bat.BatteryType)
                blevel = int(bat.BatteryLevel)
                type_name = self.TYPE_NAME_MAP.get(btype, f"0x{btype:02X}")
                level_name = self.LEVEL_NAME_MAP.get(blevel, f"0x{blevel:02X}")
                raw = f"slot={slot} type={btype}({type_name}) level={blevel}({level_name})"

                if btype == self.BATTERY_TYPE_DISCONNECTED:
                    statuses.append(
                        self._base_status(
                            device_id=slot_id,
                            display_name=slot_name,
                            connected=True,
                            awake=False,
                            percentage=None,
                            charging=None,
                            telemetry_supported=True,
                            detail=f"Slot {slot} sem bateria / standby",
                            raw_info=raw,
                            detail_key="detail_xinput_standby",
                            detail_args={"slot": slot},
                        )
                    )
                    continue

                pct = self.LEVEL_PCT_MAP.get(blevel)
                if btype == self.BATTERY_TYPE_WIRED:
                    statuses.append(
                        self._base_status(
                            device_id=slot_id,
                            display_name=slot_name,
                            connected=True,
                            awake=True,
                            percentage=pct,
                            charging=None,
                            telemetry_supported=True,
                            detail=f"Slot {slot} - Emulação XInput Wired (nível fixo)",
                            raw_info=raw,
                            detail_key="detail_xinput_wired",
                            detail_args={"slot": slot},
                        )
                    )
                elif btype in (self.BATTERY_TYPE_ALKALINE, self.BATTERY_TYPE_NIMH):
                    statuses.append(
                        self._base_status(
                            device_id=slot_id,
                            display_name=slot_name,
                            connected=True,
                            awake=True,
                            percentage=pct,
                            charging=False,
                            telemetry_supported=True,
                            detail=f"Slot {slot} - XInput Sem Fio ({type_name})",
                            raw_info=raw,
                            detail_key="detail_xinput_wireless",
                            detail_args={"slot": slot, "type_name": type_name},
                        )
                    )
                else:
                    statuses.append(
                        self._base_status(
                            device_id=slot_id,
                            display_name=slot_name,
                            connected=True,
                            awake=True,
                            percentage=pct,
                            charging=None,
                            telemetry_supported=pct is not None,
                            detail=f"Slot {slot} - XInput ({type_name})",
                            raw_info=raw,
                            detail_key="detail_xinput_generic",
                            detail_args={"slot": slot, "type_name": type_name},
                        )
                    )

        if statuses:
            return statuses

        if hid_present:
            return [
                self._base_status(
                    connected=True,
                    awake=False,
                    percentage=None,
                    charging=None,
                    telemetry_supported=True,
                    detail="Receptor conectado (sleep/desligado)",
                    raw_info="XInput slots inativos; HID presente",
                    detail_key="detail_gamepad_sleep",
                )
            ]

        return [
            self._base_status(
                connected=False,
                awake=False,
                percentage=None,
                charging=None,
                telemetry_supported=True,
                detail="Desconectado",
                raw_info="XInput e HID ausentes",
                detail_key="detail_disconnected",
            )
        ]

    def read_status(self) -> DeviceBatteryStatus:
        """Retorna o primeiro controle XInput ou estado do receptor."""
        return self.read_all_slots()[0]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", _GUID),
        ("pid", wintypes.ULONG),
    ]


_DEVPKEY_NAME = _DEVPROPKEY(
    _GUID(
        0xB725F130,
        0x47EF,
        0x101A,
        (ctypes.c_ubyte * 8)(0xA5, 0xF1, 0x02, 0x60, 0x8C, 0x9E, 0xEB, 0xAC),
    ),
    10,
)
_DEVPKEY_FRIENDLY_NAME = _DEVPROPKEY(
    _GUID(
        0xA45C254E,
        0xDF1C,
        0x4EFD,
        (ctypes.c_ubyte * 8)(0x80, 0x20, 0x67, 0xD1, 0x46, 0xA8, 0x50, 0xE0),
    ),
    14,
)
_DEVPKEY_BLUETOOTH_BATTERY = _DEVPROPKEY(
    _GUID(
        0x104EA319,
        0x6EE2,
        0x4701,
        (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5),
    ),
    2,
)


def scan_bluetooth_batteries() -> list[tuple[str, int, str]]:
    """Lista dispositivos Bluetooth conectados que expõem DEVPKEY_Bluetooth_Battery."""
    try:
        cfg = ctypes.windll.LoadLibrary("cfgmgr32.dll")
        cfg.CM_Get_Device_ID_List_SizeW.argtypes = [
            ctypes.POINTER(wintypes.ULONG),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]
        cfg.CM_Get_Device_ID_List_SizeW.restype = wintypes.DWORD
        cfg.CM_Get_Device_ID_ListW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.ULONG,
            wintypes.ULONG,
        ]
        cfg.CM_Get_Device_ID_ListW.restype = wintypes.DWORD
        cfg.CM_Locate_DevNodeW.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPCWSTR,
            wintypes.ULONG,
        ]
        cfg.CM_Locate_DevNodeW.restype = wintypes.DWORD
        cfg.CM_Get_DevNode_PropertyW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_DEVPROPKEY),
            ctypes.POINTER(wintypes.ULONG),
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(wintypes.ULONG),
            wintypes.ULONG,
        ]
        cfg.CM_Get_DevNode_PropertyW.restype = wintypes.DWORD
    except Exception:
        return []

    flags = 0x00000101  # CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
    found_by_name: dict[str, tuple[str, int, str]] = {}

    for enumerator in ("BTHENUM", "BTHLE", "BTHLEDEVICE"):
        try:
            list_size = wintypes.ULONG(0)
            if (
                cfg.CM_Get_Device_ID_List_SizeW(
                    ctypes.byref(list_size), enumerator, flags
                )
                != 0
                or list_size.value <= 1
            ):
                continue

            id_buf = ctypes.create_unicode_buffer(list_size.value)
            if (
                cfg.CM_Get_Device_ID_ListW(
                    enumerator, id_buf, list_size.value, flags
                )
                != 0
            ):
                continue

            device_ids = [
                s
                for s in ctypes.wstring_at(id_buf, list_size.value).split("\x00")
                if s
            ]
            for dev_id in device_ids:
                devnode = wintypes.DWORD(0)
                if cfg.CM_Locate_DevNodeW(ctypes.byref(devnode), dev_id, 0) != 0:
                    continue

                prop_type = wintypes.ULONG(0)
                buf_len = wintypes.ULONG(16)
                bat_buf = (ctypes.c_ubyte * 16)()
                rc_bat = cfg.CM_Get_DevNode_PropertyW(
                    devnode,
                    ctypes.byref(_DEVPKEY_BLUETOOTH_BATTERY),
                    ctypes.byref(prop_type),
                    bat_buf,
                    ctypes.byref(buf_len),
                    0,
                )
                if rc_bat != 0 or buf_len.value < 1:
                    continue

                pct = int(bat_buf[0])
                if not (0 <= pct <= 100):
                    continue

                dev_name = ""
                for prop_key in (_DEVPKEY_FRIENDLY_NAME, _DEVPKEY_NAME):
                    p_type = wintypes.ULONG(0)
                    s_len = wintypes.ULONG(512)
                    str_buf = (ctypes.c_ubyte * 512)()
                    rc = cfg.CM_Get_DevNode_PropertyW(
                        devnode,
                        ctypes.byref(prop_key),
                        ctypes.byref(p_type),
                        str_buf,
                        ctypes.byref(s_len),
                        0,
                    )
                    if rc == 0 and s_len.value >= 2:
                        val = ctypes.wstring_at(
                            ctypes.addressof(str_buf), s_len.value // 2
                        ).rstrip("\x00").strip()
                        if val:
                            dev_name = val
                            break

                clean_name = dev_name or dev_id
                dedup_key = clean_name.lower()
                if dedup_key not in found_by_name:
                    found_by_name[dedup_key] = (clean_name, pct, enumerator)
        except Exception:
            continue

    return list(found_by_name.values())


class MorcegoHeadsetReader:
    """Leitor para headset Fallen Morcego Pro Wireless (0x3206:0x0881)."""

    VID = 0x3206
    PID = 0x0881

    def __init__(self) -> None:
        self.device_id = "bat_headset_morcego"
        self.display_name = "Headset Morcego Pro"
        self.icon_kind = "headset"
        self.short_tag = "HS"
        self.accent_rgb = (251, 146, 60)
        self.vid_pid = "3206:0881"

    def _base_status(
        self,
        *,
        connected: bool,
        awake: bool,
        percentage: int | None,
        telemetry_supported: bool,
        detail: str,
        raw_info: str,
        detail_key: str = "",
    ) -> DeviceBatteryStatus:
        return DeviceBatteryStatus(
            device_id=self.device_id,
            display_name=self.display_name,
            icon_kind=self.icon_kind,
            short_tag=self.short_tag,
            accent_rgb=self.accent_rgb,
            vid_pid=self.vid_pid,
            connected=connected,
            awake=awake,
            percentage=percentage,
            charging=None,
            telemetry_supported=telemetry_supported,
            detail=detail,
            raw_info=raw_info,
            detail_key=detail_key,
        )

    def read_status(
        self,
        bt_devices: list[tuple[str, int, str]] | None = None,
        dongle_present: bool | None = None,
    ) -> DeviceBatteryStatus:
        """Verifica bateria via Bluetooth PnP ou presença do dongle USB 2.4 GHz."""
        bt_list = bt_devices if bt_devices is not None else scan_bluetooth_batteries()
        for bt_name, pct, enum_name in bt_list:
            if "morcego" in bt_name.lower():
                return self._base_status(
                    connected=True,
                    awake=True,
                    percentage=pct,
                    telemetry_supported=True,
                    detail="Conectado via Bluetooth",
                    raw_info=f"BT PnP ({enum_name}: {bt_name}): {pct}%",
                    detail_key="detail_bt_connected",
                )

        has_dongle = (
            dongle_present
            if dongle_present is not None
            else bool(hid.enumerate(self.VID, self.PID))
        )
        if has_dongle:
            return self._base_status(
                connected=True,
                awake=True,
                percentage=None,
                telemetry_supported=False,
                detail="Conectado 2.4 GHz (dongle USB sem telemetria; conecte via Bluetooth para %)",
                raw_info="HID MI_03 apenas Consumer (0x000C); USBAudio sem bateria",
                detail_key="detail_morcego_no_telemetry",
            )

        return self._base_status(
            connected=False,
            awake=False,
            percentage=None,
            telemetry_supported=False,
            detail="Desconectado",
            raw_info="Dongle 3206:0881 e Bluetooth ausentes",
            detail_key="detail_disconnected",
        )


def _group_hid_devices() -> dict[tuple[int, int], list[dict]]:
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for entry in hid.enumerate():
        vid = int(entry.get("vendor_id", 0) or 0)
        pid = int(entry.get("product_id", 0) or 0)
        grouped[(vid, pid)].append(entry)
    return grouped


def discover_and_read_all() -> list[DeviceBatteryStatus]:
    """Descobre automaticamente receptores 2.4 GHz, XInput e Bluetooth e lê o status."""
    grouped_hid = _group_hid_devices()
    bt_devices = scan_bluetooth_batteries()
    statuses: list[DeviceBatteryStatus] = []

    # 1) Mouse Compx unificado (FA07 receptor 2.4 GHz + FA08 cabo USB)
    unified_compx = UnifiedCompxMouseReader()
    has_compx_pair = any(
        UnifiedCompxMouseReader.has_compx_interfaces(grouped_hid.get((UnifiedCompxMouseReader.VID, p)))
        for p in (UnifiedCompxMouseReader.PID_WIRED, UnifiedCompxMouseReader.PID_WIRELESS)
    )
    if has_compx_pair:
        statuses.append(unified_compx.read_status(grouped_hid=grouped_hid))

    # 1b) Outros receptores/periféricos Compx/Areson compatíveis (0xFF01 + 0xFF02)
    for (vid, pid), entries in sorted(grouped_hid.items()):
        if (vid, pid) in (
            (UnifiedCompxMouseReader.VID, UnifiedCompxMouseReader.PID_WIRELESS),
            (UnifiedCompxMouseReader.VID, UnifiedCompxMouseReader.PID_WIRED),
        ):
            continue
        usage_pages = {int(e.get("usage_page", 0) or 0) for e in entries}
        mfg = " ".join(str(e.get("manufacturer_string") or "") for e in entries).lower()
        prod = next(
            (str(e.get("product_string") or "").strip() for e in entries if str(e.get("product_string") or "").strip()),
            "",
        )
        is_compx = (vid == 0x25A7 or "compx" in mfg or "areson" in mfg) and (
            0xFF01 in usage_pages and 0xFF02 in usage_pages
        )
        if not is_compx:
            continue

        prod_lower = prod.lower()
        kind = (
            "keyboard"
            if ("keyboard" in prod_lower or "teclado" in prod_lower) and "mouse" not in prod_lower
            else "mouse"
        )
        display = f"{prod or 'Periférico Compx'} ({vid:04X}:{pid:04X})"
        reader = CompxMouseReader(vid=vid, pid=pid, display_name=display, icon_kind=kind)
        statuses.append(reader.read_status(interfaces=entries))

    # 2) Controles XInput (Slots 0..3) ou receptor HORI/SHANWAN conectado
    gamepad_reader = GamepadXInputReader()
    gp_statuses = gamepad_reader.read_all_slots(grouped_hid=grouped_hid)
    for st in gp_statuses:
        if st.connected:
            statuses.append(st)

    # 3) Dispositivos Bluetooth com DEVPKEY_Bluetooth_Battery
    morcego_via_bt = False
    for bt_name, pct, enum_name in bt_devices:
        if "morcego" in bt_name.lower():
            morcego_via_bt = True
            statuses.append(
                MorcegoHeadsetReader().read_status(bt_devices=bt_devices, dongle_present=False)
            )
            continue

        kind = _classify_icon_kind(bt_name, fallback="headset")
        statuses.append(
            DeviceBatteryStatus(
                device_id=f"bat_bt_{_slugify(bt_name)}",
                display_name=bt_name,
                icon_kind=kind,
                short_tag="BT",
                accent_rgb=(96, 165, 250),
                vid_pid=f"Bluetooth ({enum_name})",
                connected=True,
                awake=True,
                percentage=pct,
                charging=None,
                telemetry_supported=True,
                detail="Conectado via Bluetooth",
                raw_info=f"BT PnP ({enum_name}: {bt_name}): {pct}%",
                detail_key="detail_bt_connected",
            )
        )

    # 4) Dongle 2.4 GHz Morcego Pro Wireless (caso não esteja conectado via Bluetooth)
    if not morcego_via_bt and (MorcegoHeadsetReader.VID, MorcegoHeadsetReader.PID) in grouped_hid:
        statuses.append(
            MorcegoHeadsetReader().read_status(bt_devices=[], dongle_present=True)
        )

    return statuses


def scan_hid_summary() -> str:
    """Gera resumo legível dos grupos HID conectados no momento para diagnóstico rápido."""
    grouped = _group_hid_devices()
    if not grouped:
        return "Nenhum dispositivo HID encontrado."

    lines = [f"Dispositivos HID detectados ({len(grouped)} grupos VID:PID):", ""]
    for (vid, pid), entries in sorted(grouped.items()):
        mfg = next(
            (str(e.get("manufacturer_string") or "").strip() for e in entries if str(e.get("manufacturer_string") or "").strip()),
            "(sem fabricante)",
        )
        prod = next(
            (str(e.get("product_string") or "").strip() for e in entries if str(e.get("product_string") or "").strip()),
            "(sem nome)",
        )
        pages = sorted({f"0x{int(e.get('usage_page', 0) or 0):04X}" for e in entries})
        lines.append(
            f"• 0x{vid:04X}:0x{pid:04X} — {mfg} | {prod}\n"
            f"  Interfaces: {len(entries)} | Usage Pages: {', '.join(pages)}"
        )

    bt = scan_bluetooth_batteries()
    lines.append("")
    if bt:
        lines.append("Dispositivos Bluetooth com bateria PnP:")
        for name, pct, enum_name in bt:
            lines.append(f"• {name} ({enum_name}): {pct}%")
    else:
        lines.append("Dispositivos Bluetooth com bateria PnP: nenhum detectado no momento.")

    return "\n".join(lines)


def create_default_readers() -> list[BatteryReader]:
    """Retorna os 3 leitores padrão (compatibilidade com probe_dispositivos.py)."""
    return [
        UnifiedCompxMouseReader(),
        GamepadXInputReader(),
        MorcegoHeadsetReader(),
    ]
