"""Helpers for decoding HomGar/Tuya raw device status payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .dp_spec_builder import get_model_dp_specs


@dataclass(frozen=True)
class DecodedStatus:
    """Container with decoded datapoint values."""

    values: dict[str, Any]
    raw_items: list[tuple[int, bytes]]


@lru_cache(maxsize=64)
def _get_dp_specs_by_model(model_code: int) -> dict[int, Mapping[str, Any]]:
    """Return datapoint specifications for the provided model code."""
    raw_specs = get_model_dp_specs(model_code)
    return {dp_code: dict(spec) for dp_code, spec in raw_specs.items()}

_DP_OVERRIDES: dict[int, dict[int, str]] = {
    87: {
        4: "STA_HOUR_RAIN",
        5: "STA_DAY_RAIN",
        6: "STA_7DAY_RAIN",
    },
    268: {10: "signal_strength"},
}

_BATTERY_STATE_LABELS: dict[int, str] = {
    1: "normal",
    2: "low",
    3: "critical",
}


def _strip_prefix(value: str) -> tuple[bytes, bool]:
    """Strip the leading header (`10#…`) and return bytes + z3 flag."""
    if not value:
        return b"", False

    z3 = False
    payload_hex = value
    if "#" in value:
        hdr, payload_hex = value.split("#", 1)
        if len(hdr) >= 2:
            z3 = hdr[1] == "1"
    payload_hex = payload_hex.strip()
    if len(payload_hex) % 2 == 1:
        payload_hex = "0" + payload_hex
    return bytes.fromhex(payload_hex), z3


def _iter_tlv_items(data: bytes, z3: bool) -> list[tuple[int, bytes]]:
    """Yield `(dp_code, raw_bytes)` pairs from the encoded payload."""
    items: list[tuple[int, bytes]] = []
    idx = 0

    if z3 and idx < len(data):
        idx += 1  # drop leading dp id for z3 streams

    while idx < len(data):
        header = data[idx]
        idx += 1

        if (header >> 7) & 1 == 0:
            dp_code = (header >> 4) & 0x07
            items.append((dp_code, b""))
            continue

        code_bits = (header >> 2) & 0x1F
        length = (header & 0x03) + 1

        if code_bits <= 30:
            dp_code = code_bits + 8
        else:
            if idx >= len(data):
                break
            dp_code = data[idx]
            idx += 1

        if idx + length > len(data):
            break

        value = data[idx : idx + length]
        idx += length
        items.append((dp_code, value))

    return items


def _decode_numeric(value: bytes, specs: Mapping[str, Any]) -> float | int:
    """Decode Tuya numeric value respecting decimal and signedness."""
    decimal_raw = specs.get("decimal")
    decimal: int
    if isinstance(decimal_raw, int):
        decimal = decimal_raw
    elif isinstance(decimal_raw, str) and decimal_raw.isdigit():
        decimal = int(decimal_raw)
    else:
        decimal = 0

    data_type_sub = specs.get("dataTypeSub")
    signed = str(data_type_sub) == "6"

    raw: int = int.from_bytes(value, byteorder="little", signed=signed)
    if decimal:
        result: float = float(raw) / (10**decimal)
        return result
    return raw


def decode_status_payload(
    value: str,
    *,
    model_code: int,
    prefer_celsius: bool = True,
) -> DecodedStatus:
    """Decode a HomGar raw status payload."""
    data, z3 = _strip_prefix(value)
    items = _iter_tlv_items(data, z3)
    specs_map = _get_dp_specs_by_model(model_code)

    decoded: dict[str, Any] = {}

    for dp_code, raw in items:
        specs = specs_map.get(dp_code)
        identity = specs.get("identity") if specs else None
        override_identity = _DP_OVERRIDES.get(model_code, {}).get(dp_code)
        if override_identity:
            identity = override_identity

        if not identity:
            decoded[f"dp_{dp_code}"] = raw
            continue

        data_type = specs.get("dataType") if specs else None

        processed: Any
        if identity == "signal_strength":
            processed = int.from_bytes(raw or b"\x00", byteorder="little", signed=False)
        elif data_type == 1 and raw and specs:
            processed = _decode_numeric(raw, specs)
        elif data_type == 2 and raw:
            processed = int.from_bytes(raw, byteorder="little", signed=False)
        else:
            processed = raw

        if identity == "STA_TEM":
            temp_f = float(processed)
            decoded["temperature_f"] = temp_f
            if prefer_celsius:
                decoded["temperature_c"] = round((temp_f - 32.0) * 5.0 / 9.0, 1)
            else:
                decoded["temperature_c"] = temp_f
        elif identity in {"STA_HOUR_RAIN", "STA_DAY_RAIN", "STA_7DAY_RAIN"}:
            if isinstance(processed, bytes):
                processed_value = int.from_bytes(processed, byteorder="little", signed=False)
            else:
                processed_value = int(processed)
            decoded[identity] = processed_value
        elif identity == "STA_RH":
            decoded["humidity_pct"] = processed
        elif identity == "STA_ILLUMINANCE":
            decoded["illuminance_lux"] = processed
        elif identity == "STA_CO2":
            if isinstance(processed, bytes):
                processed_value = int.from_bytes(
                    processed,
                    byteorder="little",
                    signed=False,
                )
            else:
                processed_value = int(processed)
            decoded[identity] = processed_value
            continue
        elif identity == "STA_BAT":
            decoded["battery_state_raw"] = processed
            decoded["battery_state"] = _BATTERY_STATE_LABELS.get(processed, processed)
        elif identity == "STA_RSSI":
            decoded["signal_strength"] = processed
        elif identity == "STA_TREND":
            decoded["trend_raw"] = processed
        else:
            decoded[identity] = processed

    return DecodedStatus(values=decoded, raw_items=items)
