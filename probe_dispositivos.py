"""Diagnostico focado nos 3 perifericos sem fio 2.4 GHz confirmados."""

from __future__ import annotations

import sys

import hid

from battery_readers import create_default_readers


def configure_utf8_stdio() -> None:
    """Garante saida UTF-8 segura quando ha console anexado."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def read_compx_ff04_feature06() -> str:
    """Le o Feature Report 0x06 da interface 0xFF04 do receptor Compx para referencia."""
    matches = [
        entry
        for entry in hid.enumerate(0x25A7, 0xFA07)
        if int(entry.get("usage_page", 0) or 0) == 0xFF04
    ]
    if not matches:
        return "interface 0xFF04 ausente"

    dev = hid.device()
    opened = False
    try:
        dev.open_path(matches[0]["path"])
        opened = True
        data = dev.get_feature_report(0x06, 17)
        if not data:
            return "vazio"
        hex_str = " ".join(f"{int(b):02X}" for b in data)
        dec_list = [int(b) for b in data]
        return f"hex=[{hex_str}] dec={dec_list}"
    except Exception as exc:
        return f"erro: {exc}"
    finally:
        if opened:
            try:
                dev.close()
            except Exception:
                pass


def read_shanwan_fff0_sample() -> str:
    """Le uma amostra passiva da interface 0xFFF0:0x0040 do HORI/SHANWAN 0x2563:0x0575."""
    matches = [
        entry
        for entry in hid.enumerate(0x2563, 0x0575)
        if int(entry.get("usage_page", 0) or 0) == 0xFFF0
        and int(entry.get("usage", 0) or 0) == 0x0040
    ]
    if not matches:
        return "interface 0xFFF0:0x0040 ausente"

    dev = hid.device()
    opened = False
    try:
        dev.open_path(matches[0]["path"])
        opened = True
        data = dev.read(64, timeout_ms=200)
        if not data:
            return "vazio (timeout)"
        nz = [(idx, f"0x{int(val):02X}({int(val)})") for idx, val in enumerate(data) if val]
        return f"{len(data)}B nao-zerados={nz}"
    except Exception as exc:
        return f"erro: {exc}"
    finally:
        if opened:
            try:
                dev.close()
            except Exception:
                pass


def main() -> int:
    """Executa leitura diagnostica dos 3 perifericos e exibe detalhes tecnicos."""
    configure_utf8_stdio()
    readers = create_default_readers()

    print("=" * 80)
    print("SONDAGEM DIAGNOSTICA DOS 3 PERIFERICOS SEM FIO")
    print("=" * 80)

    for idx, reader in enumerate(readers, start=1):
        status = reader.read_status()
        pct_str = f"{status.percentage}%" if status.percentage is not None else "--"
        if status.charging is True:
            charge_str = "Sim"
        elif status.charging is False:
            charge_str = "Nao"
        else:
            charge_str = "N/A"

        print(f"\n[{idx}] {status.display_name} ({status.vid_pid}) [{status.short_tag}]")
        print(f"    Conectado : {'Sim' if status.connected else 'Nao'} | Acordado: {'Sim' if status.awake else 'Nao'}")
        print(f"    Bateria   : {pct_str} | Carregando: {charge_str}")
        print(f"    Detalhe   : {status.detail}")
        print(f"    Raw       : {status.raw_info}")
        print(f"    Tooltip   : {status.tooltip_text()}")

    print("\n" + "-" * 80)
    print("LEITURAS COMPLEMENTARES DE REFERENCIA")
    print("-" * 80)
    print(f"Compx 25A7:FA07 (0xFF04 feature 0x06): {read_compx_ff04_feature06()}")
    print(f"HORI/SHANWAN 2563:0575 (0xFFF0:0x0040): {read_shanwan_fff0_sample()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
