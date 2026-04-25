"""Regression tests for the TLV decoder + per-device status parsers.

Inputs here are verbatim subDeviceStatus payloads captured from the
rathga@gmail.com home's hub + sensors (see api-sniffing/captures/) — any
change that breaks these will break the live integration.
"""

from __future__ import annotations

from homgarapi.devices import (
    RainPoint2ZoneTimer_V2,
    RainPointDisplayHubV2,
    RainPointRainSensor,
    parse_tlv_d_value,
)


# --- TLV parser ------------------------------------------------------------


def test_tlv_parse_with_dpid_prefix_htv213():
    """HTV213 timer (model 288) — each record is dp_id(1) + header + payload."""
    value = (
        "11#17E1C20018DC0119D8001AD8001D201E2021B70000000022B7000000"
        "0025AD000026AD0000299FD41400002A9F00000000FEFF0F102E2319"
    )
    recs = parse_tlv_d_value(value, has_dpid_prefix=True)
    by_dpid_code = {(r.dp_id, r.type_code): r for r in recs}
    # STA_RSSI — dp_id 0x17, type_code 32, 2-byte payload, low byte is signed dBm.
    assert by_dpid_code[(0x17, 32)].payload == b"\xc2\x00"
    # STA_BAT — dp_id 0x18, type_code 31, value 1 (normal).
    assert by_dpid_code[(0x18, 31)].payload == b"\x01"
    # STA_WKSTATE — dp_id 0x19 (port 1) and 0x1A (port 2), type_code 30.
    assert by_dpid_code[(0x19, 30)].payload == b"\x00"
    assert by_dpid_code[(0x1A, 30)].payload == b"\x00"
    # STA_LASTUSAGE — dp_id 0x29 port 1, 4-byte payload.
    assert by_dpid_code[(0x29, 15)].payload == b"\xd4\x14\x00\x00"
    # Trailing extended-type record (type_code=54) exercises i15==31 path.
    assert any(r.type_code == 54 for r in recs)


def test_tlv_parse_no_dpid_prefix_rain_sensor():
    """HCS012ARF rain sensor — no dp_id byte per record.

    Captured value decodes to (type_code, payload):
      (32, 0x0000)  RSSI        — low byte signed dBm = 0
      (43, 0x0000)  STA_HOUR_RAIN   = 0.0 mm
      (44, 0x0000)  STA_DAY_RAIN    = 0.0 mm
      (45, 0x0000)  STA_7DAY_RAIN   = 0.0 mm
      (31, 0x01)    STA_BAT         = 1 (normal)
      (13, 0x00000564) STA_TOTAL_RAIN   = 1380 (0.1 mm) = 138.0 mm
      (54, 0x16D28895) unknown — exercises i15==31 extended path
    """
    value = "00#E10000FD040000FD050000FD060000DC019764050000FF0F9588D216"
    recs = parse_tlv_d_value(value, has_dpid_prefix=False)
    type_codes = [r.type_code for r in recs]
    assert type_codes == [32, 43, 44, 45, 31, 13, 54]
    by_tc = {r.type_code: r for r in recs}
    assert by_tc[31].payload == b"\x01"
    assert by_tc[13].payload == b"\x64\x05\x00\x00"


# --- RainPoint2ZoneTimer_V2 ------------------------------------------------


def test_v2_timer_decodes_captured_d01():
    value = (
        "11#17E1C20018DC0119D8001AD8001D201E2021B70000000022B7000000"
        "0025AD000026AD0000299FD41400002A9F00000000FEFF0F102E2319"
    )
    sub = RainPoint2ZoneTimer_V2(
        model="HTV213FRF",
        model_code=288,
        name="Timer",
        did=1,
        mid=148701,
        alerts=None,
        address=1,
        port_number=2,
    )
    sub._parse_device_specific_status_d_value(value)
    assert sub.rf_rssi == -62  # 0xC2 low byte as signed = -62 dBm
    assert sub.battery_state == 1
    # Both zones idle, last-usage 0.
    assert sub.ports[1].wkstate == 0
    assert sub.ports[2].wkstate == 0
    assert sub.ports[1].running is False
    # Last usage: 0x14D4 = 5332, in 0.1 L units = 533.2 L.
    assert sub.ports[1].last_usage_dl == 5332
    assert sub.ports[2].last_usage_dl == 0


# --- RainPoint1ZoneTimer_V2 (HTV113FRF) -----------------------------------


def test_v2_1zone_timer_decodes_captured_payload():
    """HTV113FRF — single-zone mains top-up valve, paramVersion>=16 TLV.

    Payload captured 2026-04-24 from the live hub while the valve was
    idle (see api-sniffing/notes/htv113frf-probe-2026-04-24.md). Key
    distinction from the 2-zone model: the `10#` wire prefix carries
    NO dp_id byte per record (unlike the 2-zone's `11#`), matching the
    HCS012ARF rain sensor packing rather than the HTV213/214 one.
    Exercises the RainPoint1ZoneTimer_V2 subclass's HAS_DPID_PREFIX=False
    dispatch path through the parent class.
    """
    from homgarapi.devices import RainPoint1ZoneTimer_V2

    value = "10#E1C000DC01D80020B700000000AD00009F93020000FF0F87412F19"
    sub = RainPoint1ZoneTimer_V2(
        model="HTV113FRF",
        model_code=259,
        name="Tank Topup",
        did=3,
        mid=148701,
        alerts=None,
        address=3,
        port_number=1,
    )
    sub._parse_device_specific_status_d_value(value)

    # Exactly one port exists (PORT_COUNT=1 on this subclass).
    assert set(sub.ports.keys()) == {1}

    # Device-wide
    assert sub.rf_rssi == -64            # low byte of 0xC000 as signed = -64 dBm
    assert sub.battery_state == 1        # normal

    # Port 1 — all per-port identities must be parsed via the
    # HAS_DPID_PREFIX=False dispatch branch (which picks port 1 from the
    # identity alone). Including multiple ports' identities to confirm
    # the dispatch actually routes each one, not just the first.
    p = sub.ports[1]
    assert p.wkstate == 0                # idle (bit0 = running, 0 = off)
    assert p.alarm == 0                  # short-form record, low-nibble=0
    assert p.ev_time == 0
    assert p.duration_s == 0
    assert p.last_usage_dl == 659        # 0.1 L units → 65.9 L last cycle


# --- port_label fallback rules --------------------------------------------


def test_port_label_multi_port_with_describe():
    sub = RainPoint2ZoneTimer_V2(
        model="HTV213FRF", model_code=288, name="Timer", did=1,
        mid=148701, alerts=None, address=1, port_number=2,
        port_describe="Sprinklers|Dripline",
    )
    assert sub.port_label(1) == "Sprinklers"
    assert sub.port_label(2) == "Dripline"


def test_port_label_multi_port_without_describe_uses_port_n():
    sub = RainPoint2ZoneTimer_V2(
        model="HTV213FRF", model_code=288, name="Timer", did=1,
        mid=148701, alerts=None, address=1, port_number=2,
        port_describe="",
    )
    assert sub.port_label(1) == "Port 1"
    assert sub.port_label(2) == "Port 2"


def test_port_label_single_port_without_describe_is_empty():
    """For 1-zone devices the helper returns "" so callers can render
    entity names from the device label alone (HTV113FRF in the wild
    surfaces its identity at the device level only — no portDescribe)."""
    from homgarapi.devices import RainPoint1ZoneTimer_V2
    sub = RainPoint1ZoneTimer_V2(
        model="HTV113FRF", model_code=259, name="Tank Topup", did=3,
        mid=148701, alerts=None, address=3, port_number=1,
        port_describe="",
    )
    assert sub.port_label(1) == ""


def test_port_label_single_port_with_describe_uses_describe():
    from homgarapi.devices import RainPoint1ZoneTimer_V2
    sub = RainPoint1ZoneTimer_V2(
        model="HTV113FRF", model_code=259, name="Tank Topup", did=3,
        mid=148701, alerts=None, address=3, port_number=1,
        port_describe="Mains top-up",
    )
    assert sub.port_label(1) == "Mains top-up"


# --- RainPointRainSensor ---------------------------------------------------


def _make_rain_sensor():
    return RainPointRainSensor(
        model="HCS012ARF",
        model_code=87,
        name="Rain",
        did=2,
        mid=148701,
        alerts=None,
        address=2,
        port_number=1,
    )


def test_rain_sensor_tlv_format():
    sub = _make_rain_sensor()
    sub._parse_status_d_value("00#E10000FD040000FD050000FD060000DC019764050000FF0F9588D216")
    # All window counters zero, total 138.0 mm, battery normal, RSSI low byte
    # of 0x0000 = 0 dBm (sensor apparently doesn't populate this field).
    assert sub.rainfall_mm_hour == 0.0
    assert sub.rainfall_mm_daily == 0.0
    assert sub.rainfall_mm_7days == 0.0
    assert sub.rainfall_mm_total == 138.0
    assert sub.battery_state == 1
    assert sub.rf_rssi == 0


def test_rain_sensor_legacy_format():
    """Older firmware: ``<general>;R=total(hour/24h/7d)`` in 0.1 mm units."""
    sub = _make_rain_sensor()
    sub._parse_status_d_value("1,-81,1;R=270(0/0/270)")
    assert sub.rf_rssi == -81
    assert sub.rainfall_mm_total == 27.0
    assert sub.rainfall_mm_7days == 27.0
    assert sub.rainfall_mm_hour == 0.0
    assert sub.rainfall_mm_daily == 0.0


def test_rain_sensor_bad_payload_does_not_raise():
    """Per-sub parse errors are swallowed in the base class so one
    mis-formatted device doesn't blow up the whole poll."""
    sub = _make_rain_sensor()
    sub._parse_status_d_value("garbage")  # must not raise
    assert sub.rainfall_mm_total is None


# --- RainPointDisplayHubV2 (HWG023WRF) -------------------------------------


def _make_hub_v2():
    return RainPointDisplayHubV2(
        model="HWG023WRF",
        model_code=273,
        name="Hub",
        did=1,
        mid=148701,
        alerts=None,
        subdevices=[],
    )


def test_hub_v2_parses_state_and_connected():
    hub = _make_hub_v2()
    # "state" = "<battery>,<rssi_dbm>" — captured verbatim from the API.
    hub.set_device_status({"id": "state", "value": "0,-81"})
    hub.set_device_status({"id": "connected", "value": "1"})
    assert hub.battery_state == 0
    assert hub.wifi_rssi == -81
    assert hub.connected is True


def test_hub_v2_ignores_null_and_malformed_values():
    hub = _make_hub_v2()
    hub.set_device_status({"id": "state", "value": None})       # null
    hub.set_device_status({"id": "connected", "value": "maybe"})  # garbage
    # Neither should raise, and neither should populate the field.
    assert hub.battery_state is None
    assert hub.wifi_rssi is None
    assert hub.connected is None
