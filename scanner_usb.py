"""Diagnostico e descoberta de dispositivos HID conectados no Windows (Fase 1).

Lista todos os dispositivos via hid.enumerate(), salva um relatorio completo
em scan_report.json e executa sondagem passiva (somente leitura) nas interfaces
proprietarias / de energia / consumidor.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import hid

PROBE_USAGE_PAGES = {0x000C, 0x0084, 0x0085}

USAGE_PAGE_LABELS = {
    0x0001: "Generic Desktop",
    0x000C: "Consumer",
    0x000D: "Digitizer",
    0x0084: "Power Device",
    0x0085: "Battery System",
}


def configure_utf8_stdio() -> None:
    """Garante saida UTF-8 segura no console do Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def usage_page_label(usage_page: int) -> str:
    """Retorna um rotulo legivel para a usage_page HID."""
    if usage_page in USAGE_PAGE_LABELS:
        return USAGE_PAGE_LABELS[usage_page]
    if usage_page >= 0xFF00:
        return "Vendor-Defined"
    return f"UsagePage 0x{usage_page:04X}"


def decode_path(raw_path: bytes | str | None) -> str:
    """Converte o caminho HID (bytes) para string UTF-8 segura."""
    if raw_path is None:
        return ""
    if isinstance(raw_path, bytes):
        return raw_path.decode("utf-8", errors="replace")
    return str(raw_path)


def serialize_hid_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normaliza um dicionario retornado por hid.enumerate() para JSON."""
    usage_page = int(entry.get("usage_page", 0) or 0)
    usage = int(entry.get("usage", 0) or 0)
    vid = int(entry.get("vendor_id", 0) or 0)
    pid = int(entry.get("product_id", 0) or 0)
    release_number = int(entry.get("release_number", 0) or 0)

    return {
        "vendor_id": vid,
        "vendor_id_hex": f"0x{vid:04X}",
        "product_id": pid,
        "product_id_hex": f"0x{pid:04X}",
        "manufacturer_string": entry.get("manufacturer_string") or "",
        "product_string": entry.get("product_string") or "",
        "serial_number": entry.get("serial_number") or "",
        "release_number": release_number,
        "release_number_hex": f"0x{release_number:04X}",
        "interface_number": entry.get("interface_number"),
        "usage_page": usage_page,
        "usage_page_hex": f"0x{usage_page:04X}",
        "usage_page_label": usage_page_label(usage_page),
        "usage": usage,
        "usage_hex": f"0x{usage:04X}",
        "bus_type": entry.get("bus_type"),
        "path": decode_path(entry.get("path")),
    }


def is_probe_candidate(usage_page: int) -> bool:
    """Indica se a interface deve passar por sondagem passiva somente leitura."""
    return usage_page >= 0xFF00 or usage_page in PROBE_USAGE_PAGES


def format_bytes_hex(data: list[int]) -> str:
    """Formata uma lista de bytes como string hexadecimal separada por espacos."""
    return " ".join(f"{b:02X}" for b in data)


def candidate_pct_indices(data: list[int], start_index: int = 0) -> list[dict[str, int]]:
    """Retorna indices com valores entre 1 e 100 (possiveis porcentagens)."""
    return [
        {"index": idx, "value": val}
        for idx, val in enumerate(data)
        if idx >= start_index and 1 <= val <= 100
    ]


def save_report(report_path: Path, report_data: dict[str, Any]) -> None:
    """Grava o relatorio completo em disco no formato JSON UTF-8."""
    report_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def print_enumeration(serialized: list[dict[str, Any]]) -> None:
    """Imprime o inventario HID agrupado por (VID, PID)."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for item in serialized:
        grouped[(item["vendor_id"], item["product_id"])].append(item)

    print("=" * 80)
    print(
        f"DISPOSITIVOS HID ENCONTRADOS: {len(grouped)} grupos (VID:PID), "
        f"{len(serialized)} interfaces no total"
    )
    print("=" * 80)

    for (vid, pid), interfaces in sorted(grouped.items()):
        mfg = next((i["manufacturer_string"] for i in interfaces if i["manufacturer_string"]), "(sem fabricante)")
        prod = next((i["product_string"] for i in interfaces if i["product_string"]), "(sem nome)")
        serial = next((i["serial_number"] for i in interfaces if i["serial_number"]), "(sem serial)")
        rel = interfaces[0]["release_number_hex"]

        print(f"\n[VID 0x{vid:04X} | PID 0x{pid:04X}] {mfg} - {prod}")
        print(f"  Serial: {serial} | Release: {rel} | Interfaces: {len(interfaces)}")

        for idx, iface in enumerate(interfaces, start=1):
            probe_tag = " [CANDIDATA SONDA]" if is_probe_candidate(iface["usage_page"]) else ""
            print(
                f"  ({idx}) if={iface['interface_number']} | "
                f"usage_page={iface['usage_page_hex']} ({iface['usage_page_label']}) | "
                f"usage={iface['usage_hex']}{probe_tag}"
            )
            print(f"      path: {iface['path']}")


def probe_interface(raw_path: bytes | str, serialized_entry: dict[str, Any]) -> dict[str, Any]:
    """Executa leitura passiva (read + get_feature_report) em uma interface HID."""
    result: dict[str, Any] = {
        "vendor_id_hex": serialized_entry["vendor_id_hex"],
        "product_id_hex": serialized_entry["product_id_hex"],
        "manufacturer_string": serialized_entry["manufacturer_string"],
        "product_string": serialized_entry["product_string"],
        "interface_number": serialized_entry["interface_number"],
        "usage_page_hex": serialized_entry["usage_page_hex"],
        "usage_page_label": serialized_entry["usage_page_label"],
        "usage_hex": serialized_entry["usage_hex"],
        "path": serialized_entry["path"],
        "open_ok": False,
        "open_error": None,
        "interrupt_read": None,
        "interrupt_read_error": None,
        "feature_reports": [],
    }

    dev = hid.device()
    opened = False
    try:
        dev.open_path(raw_path)
        opened = True
        result["open_ok"] = True

        # 1) Leitura passiva de interrupt report (timeout curto)
        try:
            read_data = dev.read(64, timeout_ms=200)
            if read_data:
                byte_list = [int(b) for b in read_data]
                result["interrupt_read"] = {
                    "length": len(byte_list),
                    "hex": format_bytes_hex(byte_list),
                    "bytes": byte_list,
                    "candidate_pct_bytes": candidate_pct_indices(byte_list, start_index=0),
                }
        except OSError as exc:
            result["interrupt_read_error"] = str(exc)

        # 2) Leitura de feature reports (somente get_feature_report, sem envio/escrita)
        for report_id in range(0x00, 0x20):
            try:
                feat_data = dev.get_feature_report(report_id, 65)
            except OSError:
                continue

            if not feat_data:
                continue

            byte_list = [int(b) for b in feat_data]
            payload_after_id = byte_list[1:]
            all_zero_payload = all(b == 0 for b in payload_after_id)
            result["feature_reports"].append(
                {
                    "report_id": report_id,
                    "report_id_hex": f"0x{report_id:02X}",
                    "length": len(byte_list),
                    "hex": format_bytes_hex(byte_list),
                    "bytes": byte_list,
                    "all_zero_payload": all_zero_payload,
                    "candidate_pct_bytes": candidate_pct_indices(byte_list, start_index=1),
                }
            )
    except Exception as exc:
        result["open_error"] = str(exc)
    finally:
        if opened:
            try:
                dev.close()
            except Exception:
                pass

    return result


def run_passive_probe(
    raw_entries: list[dict[str, Any]],
    serialized_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Executa a sondagem passiva em todas as interfaces candidatas."""
    candidates = [
        (raw, ser)
        for raw, ser in zip(raw_entries, serialized_entries)
        if is_probe_candidate(ser["usage_page"])
    ]

    print("\n" + "=" * 80)
    print(f"SONDAGEM PASSIVA (SOMENTE LEITURA): {len(candidates)} interfaces candidatas")
    print("=" * 80, flush=True)

    probe_results: list[dict[str, Any]] = []
    for idx, (raw, ser) in enumerate(candidates, start=1):
        label = (
            f"{ser['vendor_id_hex']}:{ser['product_id_hex']} "
            f"({ser['product_string'] or 'sem nome'}) "
            f"if={ser['interface_number']} up={ser['usage_page_hex']} u={ser['usage_hex']}"
        )
        print(f"[{idx}/{len(candidates)}] Testando {label} ...", flush=True)
        res = probe_interface(raw["path"], ser)
        probe_results.append(res)

        if not res["open_ok"]:
            print(f"    -> Falha ao abrir: {res['open_error']}", flush=True)
            continue

        non_zero_feats = [f for f in res["feature_reports"] if not f["all_zero_payload"]]
        print(
            f"    -> Aberta OK | read={'SIM' if res['interrupt_read'] else 'vazio'} | "
            f"feature_reports={len(res['feature_reports'])} "
            f"(nao-zerados={len(non_zero_feats)})",
            flush=True,
        )

    return probe_results


def print_probe_summary(probe_results: list[dict[str, Any]]) -> None:
    """Exibe resumo limpo das interfaces que retornaram dados nao-zerados."""
    print("\n" + "=" * 80)
    print("RESUMO DE DADOS NAO-ZERADOS NA SONDAGEM PASSIVA")
    print("=" * 80)

    any_hits = False
    for res in probe_results:
        read_hit = res.get("interrupt_read")
        non_zero_feats = [
            f for f in res.get("feature_reports", []) if not f["all_zero_payload"]
        ]
        if not read_hit and not non_zero_feats:
            continue

        any_hits = True
        print(
            f"\n[{res['vendor_id_hex']}:{res['product_id_hex']}] "
            f"{res['manufacturer_string']} - {res['product_string']} "
            f"(if={res['interface_number']}, up={res['usage_page_hex']}, u={res['usage_hex']})"
        )
        if read_hit:
            print(
                f"  interrupt_read ({read_hit['length']}B): {read_hit['hex']}"
            )
            if read_hit["candidate_pct_bytes"]:
                print(f"    bytes 1..100: {read_hit['candidate_pct_bytes']}")
        for feat in non_zero_feats:
            print(
                f"  feature {feat['report_id_hex']} ({feat['length']}B): {feat['hex']}"
            )
            if feat["candidate_pct_bytes"]:
                print(f"    bytes 1..100 (apos id): {feat['candidate_pct_bytes']}")

    if not any_hits:
        print(
            "\nNenhuma interface candidata retornou bytes nao-zerados na sondagem passiva."
        )


def parse_args() -> argparse.Namespace:
    """Processa argumentos de linha de comando."""
    parser = argparse.ArgumentParser(
        description="Scanner HID e sonda passiva de dispositivos USB 2.4 GHz."
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="Lista dispositivos via hid.enumerate() sem executar leitura/feature reports.",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do scanner HID."""
    configure_utf8_stdio()
    args = parse_args()

    raw_entries = hid.enumerate()
    serialized_entries = [serialize_hid_entry(entry) for entry in raw_entries]

    report_path = Path(__file__).resolve().parent / "scan_report.json"
    report_data: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_interfaces": len(serialized_entries),
        "devices": serialized_entries,
        "probe_results": [],
    }
    save_report(report_path, report_data)

    print_enumeration(serialized_entries)
    print(f"\nRelatorio de enumeracao salvo em: {report_path}", flush=True)

    if args.no_probe:
        print("\nSondagem passiva ignorada (--no-probe).")
        return 0

    probe_results = run_passive_probe(raw_entries, serialized_entries)
    report_data["probe_results"] = probe_results
    save_report(report_path, report_data)

    print_probe_summary(probe_results)
    print(f"\nRelatorio completo atualizado em: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
