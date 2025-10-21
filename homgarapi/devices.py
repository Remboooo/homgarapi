"""Device model definitions for the HomGar API client."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, ClassVar, Final

from .dp_decoder import decode_status_payload
from .logutil import get_logger

ParsedStats = tuple[int | None, int | None, int | None, int | None]

STATS_VALUE_REGEX: Final[re.Pattern[str]] = re.compile(r"^(\d+)\((\d+)/(\d+)/(\d+)\)")

_LOGGER = get_logger(__file__)


@dataclass(frozen=True)
class DeviceSensorMapping:
    """Mapping between a sensor key and the function providing its value."""

    key: str
    value_fn: Callable[[Any], Any]
    allow_none: bool = True

    def is_available(self, device: Any) -> bool:
        """Return True if the sensor has data available on the device."""
        try:
            value = self.value_fn(device)
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        return value is not None or self.allow_none


def attr_mapping(
    key: str,
    *,
    attr: str | None = None,
    allow_none: bool = True,
) -> DeviceSensorMapping:
    """Build a device sensor mapping backed by a simple attribute lookup."""

    attr_name = attr or key

    def _lookup(device: Any) -> Any:
        return getattr(device, attr_name, None)

    return DeviceSensorMapping(key, _lookup, allow_none=allow_none)


def _convert_signal_strength(raw: float) -> int:
    """Convert signal strength readings to signed dBm values when required."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(raw) if isinstance(raw, bool) else 0
    # HomGar reports RSSI as unsigned where values > 127 should be interpreted as negative.
    if value > 127:
        return value - 256
    return value


def _battery_percentage_from_state(raw: Any) -> int | None:
    """Convert the common battery state datapoint (1=full, 2=medium, 3=low) to percentage."""
    value = _safe_int(raw)
    if value is None:
        return None
    return {1: 100, 2: 50, 3: 0}.get(value, value)


def _append_detail_text(base: str, detail: str) -> str:
    """Append a formatted detail segment to the base description."""
    detail = detail.strip()
    if not detail:
        return base
    return f"{base}: {detail}" if ":" not in base else f"{base} / {detail}"


def _safe_int(value: Any) -> int | None:
    """Return ``int(value)`` or ``None`` if conversion fails."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    """Return ``float(value)`` or ``None`` if conversion fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mk_to_celsius(value: int | None) -> float | None:
    """Convert millikelvin to Celsius."""
    if value is None:
        return None
    return round(value * 1e-3 - 273.15, 1)


def _parse_stats_value(value: str) -> ParsedStats:
    """Parse a stats string of the format 'value(max/min/trend)'."""
    match = STATS_VALUE_REGEX.fullmatch(value)
    if match:
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )
    return (None, None, None, None)


def _temp_to_mk(raw_fahrenheit_tenths: str | int) -> int:
    """Convert tenths of degrees Fahrenheit to millikelvin."""
    raw_value = int(raw_fahrenheit_tenths)
    celsius = (raw_value * 0.1 - 32.0) * 5 / 9
    return round((celsius + 273.15) * 1000)


def _celsius_to_mk(value: float) -> int:
    """Convert degrees Celsius to millikelvin."""
    return round((value + 273.15) * 1000)


def _decode_packed_fahrenheit_extrema(raw_value: int | str | None) -> tuple[int | None, int | None]:
    """Decode packed Fahrenheit extrema into millikelvin maxima and minima."""
    if raw_value is None:
        return (None, None)
    packed = _safe_int(raw_value)
    if packed is None:
        return (None, None)
    max_f = (packed >> 16) & 0xFFFF
    min_f = packed & 0xFFFF
    return (_temp_to_mk(max_f), _temp_to_mk(min_f))


class HomgarHome:
    """Representation of a HomGar home."""

    hid: str
    name: str

    def __init__(self, hid: str | int, name: str | None) -> None:
        """Initialise the home model."""
        self.hid = str(hid)
        self.name = name or ""


class HomgarDevice:
    """Base class for HomGar devices."""

    FRIENDLY_DESC: ClassVar[str] = "Unknown HomGar device"
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = True
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = True

    def __init__(
        self,
        *,
        model: str | None,
        model_code: int | None,
        name: str | None,
        did: str | int | None,
        mid: str | int | None,
        alerts: Iterable[Any] | None = None,
        device_name: str | None = None,
        product_key: str | None = None,
        **_: Any,
    ) -> None:
        """Initialise a device with metadata returned by the API."""
        self.model: str | None = model
        self.model_code: int | None = (
            int(model_code) if model_code is not None else None
        )
        self.name: str = name or "Unknown"
        self.did: str = str(did) if did is not None else "unknown"
        self.mid: str = str(mid) if mid is not None else "unknown"
        self.alerts: list[Any] = list(alerts or [])
        self.device_name: str | None = device_name
        self.product_key: str | None = product_key
        self.status_fields: dict[str, Any] = {}
        self.last_status_payload: Mapping[str, Any] | None = None
        self.last_seen: str | None = None
        self.last_seen_ts: float | None = None

        self.address: int | None = None
        self.rf_rssi: int | None = None
        self.updated_in_last_poll: bool = False

    def __str__(self) -> str:
        """Return a human readable description."""
        return f'{self.FRIENDLY_DESC} "{self.name}" (DID {self.did})'

    def get_device_status_ids(self) -> list[str]:
        """Return status identifiers that apply to this device."""
        return []

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Update the device state with data from the API."""
        self.last_status_payload = api_obj
        time_val = api_obj.get("time")
        timestamp: float | None = None
        if isinstance(time_val, (int, float)):
            timestamp = float(time_val)
        elif isinstance(time_val, str):
            try:
                timestamp = float(time_val)
            except ValueError:
                timestamp = None
        if timestamp is not None:
            if timestamp > 1e12:
                timestamp /= 1000
            try:
                seen_dt = datetime.fromtimestamp(timestamp, tz=UTC)
            except (OverflowError, OSError, ValueError):
                seen_dt = None
            if seen_dt is not None:
                self.last_seen_ts = timestamp
                self.last_seen = seen_dt.isoformat()
        if self.address is None:
            return
        if api_obj.get("id") == f"D{self.address:02d}":
            value = api_obj.get("value", "")
            if isinstance(value, str):
                self._parse_status_d_value(value)

    def supports_sensor(self, sensor_key: str) -> bool:
        """Return True if this device supports the requested sensor key."""
        return True

    def _parse_status_d_value(self, payload: str) -> None:
        """Parse the common and device-specific sections of a status payload."""
        if ";" not in payload:
            self._parse_general_status_d_value(payload)
            # Also process device-specific data when the payload does not contain
            # a dedicated separator (newer TLV payloads use this format).
            self._parse_device_specific_status_d_value(payload)
            return
        general_str, specific_str = payload.split(";", 1)
        self._parse_general_status_d_value(general_str)
        self._parse_device_specific_status_d_value(specific_str)

    def _parse_general_status_d_value(self, value: str) -> None:
        """Parse the general section, capturing the RF RSSI if present."""
        parts = value.split(",")
        if len(parts) >= 2:
            try:
                self.rf_rssi = int(parts[1])
            except ValueError:
                self.rf_rssi = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the device-specific section of the payload."""
        raise NotImplementedError

    def _decode_tlv_payload(
        self,
        value: str,
        *,
        model_code: int,
        log_label: str | None = None,
    ) -> dict[str, Any] | None:
        """Decode a TLV payload, updating status fields and returning values."""
        if not value.startswith(("10#", "11#")):
            return None

        decoded = decode_status_payload(value, model_code=model_code)
        vals = decoded.values
        self.status_fields.update(vals)

        if hasattr(self, "raw_status"):
            setattr(self, "raw_status", value)

        if log_label:
            _LOGGER.debug("Decoded %s payload for %s: %s", log_label, self.did, vals)

        return vals

    def _update_signal_strength(self, value: Any) -> None:
        """Update signal strength attributes from a raw reading."""
        strength = _safe_int(value)
        if strength is None:
            return
        converted = _convert_signal_strength(strength)
        self.rf_rssi = converted
        if hasattr(self, "signal_strength"):
            setattr(self, "signal_strength", converted)

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings for common device metrics."""
        if self.rf_rssi is not None:
            yield attr_mapping("rf_rssi", allow_none=False)

        if self.INCLUDE_BASE_TEMPERATURE and hasattr(type(self), "temperature_c"):
            yield attr_mapping("temperature", attr="temperature_c")

        if self.INCLUDE_BASE_HUMIDITY and hasattr(type(self), "humidity_pct"):
            yield attr_mapping("humidity", attr="humidity_pct")

        if getattr(self, "HAS_BATTERY", True):
            if hasattr(self, "battery_level"):
                yield attr_mapping(
                    "battery",
                    attr="battery_level",
                )
            if hasattr(self, "battery_state"):
                yield attr_mapping(
                    "battery_state",
                    attr="battery_state",
                )

        if self.last_seen_ts is not None:
            yield DeviceSensorMapping(
                "last_seen",
                lambda dev: datetime.fromtimestamp(dev.last_seen_ts, tz=UTC)
                if getattr(dev, "last_seen_ts", None) is not None
                else None,
            )


class HomgarHubDevice(HomgarDevice):
    """A hub acts as a gateway for sensors and actuators."""

    def __init__(
        self, *, subdevices: Iterable[HomgarDevice] | None = None, **kwargs: Any
    ) -> None:
        """Initialise the hub and store its subdevices."""
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices: list[HomgarDevice] = list(subdevices or [])

    def __str__(self) -> str:
        """Return a human readable description for the hub."""
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store raw payload data produced by the hub."""
        self.alerts.append({"raw_status": value})


class HomgarSubDevice(HomgarDevice):
    """A device that is associated with a hub."""

    def __init__(self, *, address: int, port_number: int, **kwargs: Any) -> None:
        """Initialise the subdevice address and port metadata."""
        super().__init__(**kwargs)
        self.address = address
        self.port_number = port_number
        self.signal_strength: int | None = None

    def __str__(self) -> str:
        """Return a human readable description for the subdevice."""
        return f"{super().__str__()} at address {self.address}"

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for status updates relevant to this device."""
        return [f"D{self.address:02d}"]

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store raw payload for subclasses that do not override parsing."""
        self.alerts.append({"raw_status": value})


class RainPointDisplayHub(HomgarHubDevice):
    """RainPoint irrigation display hub."""

    MODEL_CODES: ClassVar[list[int]] = [264]
    FRIENDLY_DESC: ClassVar[str] = "Irrigation Display Hub"
    HAS_BATTERY: ClassVar[bool] = False
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = False
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the display hub."""
        super().__init__(**kwargs)
        self.wifi_rssi: int | None = None
        self.battery_state: int | None = None
        self.connected: bool | None = None

        self.temp_mk_current: int | None = None
        self.temp_mk_daily_max: int | None = None
        self.temp_mk_daily_min: int | None = None
        self.temp_trend: int | None = None
        self.hum_current: int | None = None
        self.hum_daily_max: int | None = None
        self.hum_daily_min: int | None = None
        self.hum_trend: int | None = None
        self.press_pa_current: int | None = None
        self.press_pa_daily_max: int | None = None
        self.press_pa_daily_min: int | None = None
        self.press_trend: int | None = None
        self.raw_status: str | None = None

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for hub-specific status updates."""
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Handle hub-specific updates before delegating to the base class."""
        dev_id = api_obj.get("id")
        val = api_obj.get("value")
        if dev_id == "state" and isinstance(val, str):
            parts = [segment for segment in val.split(",") if segment]
            if len(parts) >= 2:
                try:
                    self.wifi_rssi = int(parts[1])
                except ValueError:
                    self.wifi_rssi = None
        elif dev_id == "connected":
            self.connected = str(val) == "1"
        else:
            super().set_device_status(api_obj)

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the display hub payload into temperature, humidity, and pressure statistics.

        Observed example value: ``781(781/723/1),52(64/50/1),P=10213(10222/10205/1)``.

        Deduced meaning: temperature, humidity, and pressure with day statistics.
        """

        parts = value.split(",")
        if len(parts) < 3:
            self.raw_status = value
            return
        temp_str, hum_str, press_str = parts[0], parts[1], parts[2]
        temp_stats = _parse_stats_value(temp_str)
        converted_temp = tuple(
            _temp_to_mk(stat) if stat is not None else None for stat in temp_stats
        )
        (
            self.temp_mk_current,
            self.temp_mk_daily_max,
            self.temp_mk_daily_min,
            self.temp_trend,
        ) = converted_temp
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = (
            _parse_stats_value(hum_str)
        )
        press_stats = _parse_stats_value(press_str[2:])
        (
            self.press_pa_current,
            self.press_pa_daily_max,
            self.press_pa_daily_min,
            self.press_trend,
        ) = press_stats

    def __str__(self) -> str:
        """Return a human readable description including current readings."""
        base = super().__str__()
        if self.temp_mk_current is not None:
            celsius = self.temp_mk_current * 1e-3 - 273.15
            base += (
                f": {celsius:.1f}°C / {self.hum_current}% / {self.press_pa_current}Pa"
            )
        return base

    @property
    def temperature_c(self) -> float | None:
        """Return current temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_current)

    @property
    def temperature_c_max(self) -> float | None:
        """Return daily maximum temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_daily_max)

    @property
    def temperature_c_min(self) -> float | None:
        """Return daily minimum temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_daily_min)

    @property
    def humidity_pct(self) -> int | None:
        """Return current relative humidity percentage."""
        return self.hum_current

    @property
    def humidity_pct_max(self) -> int | None:
        """Return daily maximum relative humidity percentage."""
        return self.hum_daily_max

    @property
    def humidity_pct_min(self) -> int | None:
        """Return daily minimum relative humidity percentage."""
        return self.hum_daily_min

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the display hub."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("pressure", attr="press_pa_current")
        yield attr_mapping("wifi_rssi", attr="wifi_rssi", allow_none=False)


class RainPointGatewayHub(HomgarHubDevice):
    """RainPoint gateway hub used by newer hardware revisions."""

    MODEL_CODES: ClassVar[list[int]] = [273, 289]
    FRIENDLY_DESC: ClassVar[str] = "RainPoint Gateway Hub"
    HAS_BATTERY: ClassVar[bool] = False
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = False
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the gateway hub."""
        super().__init__(**kwargs)
        self.battery_level: int | None = None
        self.wifi_rssi: int | None = None
        self.connected: bool | None = None

    def get_device_status_ids(self) -> list[str]:
        """Return identifiers for gateway-specific status updates."""
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj: Mapping[str, Any]) -> None:
        """Handle gateway specific updates before delegating to the base class."""
        dev_id = api_obj.get("id")
        val = api_obj.get("value")
        if dev_id == "state" and isinstance(val, str):
            parts = [segment for segment in val.split(",") if segment]
            if len(parts) > 1:
                try:
                    self.wifi_rssi = int(parts[1])
                except ValueError:
                    self.wifi_rssi = None
        elif dev_id == "connected":
            self.connected = str(val) == "1"
        else:
            super().set_device_status(api_obj)

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the gateway hub."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("wifi_rssi", attr="wifi_rssi", allow_none=False)
        yield DeviceSensorMapping(
            "battery_state",
            lambda dev: dev.status_fields.get("battery_state")
            if getattr(dev, "status_fields", None)
            else None,
            allow_none=False,
        )


class RainPointSoilMoistureSensor(HomgarSubDevice):
    """RainPoint soil moisture sensor."""

    MODEL_CODES: ClassVar[list[int]] = [72]
    FRIENDLY_DESC: ClassVar[str] = "Soil Moisture Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the soil sensor."""
        super().__init__(**kwargs)
        self.temp_mk_current: int | None = None
        self.moist_percent_current: int | None = None
        self.light_lux_current: float | None = None
        self.battery_state: str | None = None
        self.battery_level_raw: int | None = None
        self.battery_level: int | None = None
        self.signal_strength: int | None = None
        self.raw_status: str | None = None

    def _apply_decoded_values(self, values: Mapping[str, Any]) -> None:
        """Apply decoded sensor values to attributes and diagnostics."""

        def _store(field: str, val: Any) -> None:
            if val is None:
                self.status_fields.pop(field, None)
            else:
                self.status_fields[field] = val

        temp_in_values = False
        temp_c: float | None = None

        if "temperature_mk" in values:
            temp_in_values = True
            temp_mk = _safe_int(values.get("temperature_mk"))
            self.temp_mk_current = temp_mk
            if temp_mk is not None:
                temp_c = _mk_to_celsius(temp_mk)

        if "temperature_c" in values:
            temp_in_values = True
            temp_c = _safe_float(values.get("temperature_c"))
            if temp_c is not None:
                self.temp_mk_current = _celsius_to_mk(temp_c)
            else:
                self.temp_mk_current = None
        elif "temperature_f" in values and not temp_in_values:
            temp_in_values = True
            temp_f = _safe_float(values.get("temperature_f"))
            if temp_f is not None:
                temp_c = round((temp_f - 32.0) * 5.0 / 9.0, 1)
                self.temp_mk_current = _celsius_to_mk(temp_c)
            else:
                self.temp_mk_current = None

        if temp_in_values:
            _store("temperature_c", temp_c)

        if "humidity_pct" in values:
            moist = _safe_int(values.get("humidity_pct"))
            self.moist_percent_current = moist
            _store("humidity_pct", moist)

        if "illuminance_lux" in values:
            lux = _safe_float(values.get("illuminance_lux"))
            self.light_lux_current = lux
            _store("illuminance_lux", lux)

        battery_raw_present = "battery_state_raw" in values
        if battery_raw_present:
            battery_raw = _safe_int(values.get("battery_state_raw"))
            self.battery_level_raw = battery_raw
            _store("battery_state_raw", battery_raw)
            self.battery_level = _battery_percentage_from_state(battery_raw)
            _store("battery_level", self.battery_level)
        elif "battery_level" in values:
            battery_level = _safe_int(values.get("battery_level"))
            self.battery_level = battery_level
            _store("battery_level", battery_level)

        if "battery_state" in values:
            battery_state = values.get("battery_state")
            self.battery_state = (
                str(battery_state) if battery_state is not None else None
            )
            _store("battery_state", self.battery_state)
        elif battery_raw_present and self.battery_state is not None:
            # Keep decoder-derived state when raw value disappears.
            _store("battery_state", self.battery_state)

        if "signal_strength" in values:
            signal = values.get("signal_strength")
            if signal is not None:
                self._update_signal_strength(signal)
                _store("signal_strength", self.signal_strength)
                _store("rf_rssi", self.rf_rssi)
            else:
                self.rf_rssi = None
                self.signal_strength = None
                _store("signal_strength", None)
                _store("rf_rssi", None)

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the soil moisture payload into temperature, soil, and light readings."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=72,
            log_label="soil",
        )) is not None:
            self._apply_decoded_values(vals)
            return

        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including current readings."""
        base = super().__str__()
        temp_c = self.temperature_c
        moisture = self.moist_percent_current
        if temp_c is not None and moisture is not None:
            detail_parts = [f"{temp_c:.1f}°C", f"{moisture}%"]
            if self.light_lux_current is not None:
                detail_parts.append(f"{self.light_lux_current:.1f}lx")
            base = _append_detail_text(base, " / ".join(detail_parts))
        elif self.light_lux_current is not None:
            base = _append_detail_text(base, f"{self.light_lux_current:.1f}lx")
        if self.battery_level is not None:
            base = _append_detail_text(base, f"Battery {self.battery_level}%")
        return base

    @property
    def temperature_c(self) -> float | None:
        """Return current soil temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_current)

    @property
    def humidity_pct(self) -> int | None:
        """Return soil humidity percentage if available."""
        return self.moist_percent_current

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the soil sensor."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("light", attr="light_lux_current")


class RainPointRainSensor(HomgarSubDevice):
    """RainPoint rainfall sensor."""

    MODEL_CODES: ClassVar[list[int]] = [87]
    FRIENDLY_DESC: ClassVar[str] = "High Precision Rain Sensor"
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = False
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the rain sensor."""
        super().__init__(**kwargs)
        self.rainfall_mm_total: float | None = None
        self.rainfall_mm_hour: float | None = None
        self.rainfall_mm_daily: float | None = None
        self.rainfall_mm_7days: float | None = None
        self.battery_level_raw: int | None = None
        self.battery_level: int | None = None
        self.battery_state: str | None = None
        self.signal_strength: int | None = None
        self.raw_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the rainfall payload into rolling accumulation metrics."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=87,
            log_label="rain",
        )) is not None:
            def _scaled(name: str) -> float | None:
                measured = _safe_float(vals.get(name))
                return measured * 0.1 if measured is not None else None

            if (total := _scaled("STA_TOTAL_RAIN")) is not None:
                self.rainfall_mm_total = total
            if (hour := _scaled("STA_HOUR_RAIN")) is not None:
                self.rainfall_mm_hour = hour
            if (daily := _scaled("STA_DAY_RAIN")) is not None:
                self.rainfall_mm_daily = daily
            if (seven_day := _scaled("STA_7DAY_RAIN")) is not None:
                self.rainfall_mm_7days = seven_day

            if (signal := vals.get("signal_strength")) is not None:
                self._update_signal_strength(signal)

            if (battery_raw := vals.get("battery_state_raw")) is not None:
                battery_raw_int = _safe_int(battery_raw)
                self.battery_level_raw = battery_raw_int
                self.battery_level = _battery_percentage_from_state(battery_raw_int)
                if self.battery_level is not None:
                    self.status_fields["battery_level"] = self.battery_level
            if "battery_state" in vals:
                battery_state = vals["battery_state"]
                self.battery_state = str(battery_state) if battery_state is not None else None
            return

        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including rainfall totals."""
        base = super().__str__()
        detail_parts: list[str] = []
        if self.rainfall_mm_total is not None:
            detail_parts.append(f"{self.rainfall_mm_total}mm total")
        if self.rainfall_mm_hour is not None:
            detail_parts.append(f"{self.rainfall_mm_hour}mm 1h")
        if self.rainfall_mm_daily is not None:
            detail_parts.append(f"{self.rainfall_mm_daily}mm 24h")
        if self.rainfall_mm_7days is not None:
            detail_parts.append(f"{self.rainfall_mm_7days}mm 7days")
        if detail_parts:
            base = _append_detail_text(base, " / ".join(detail_parts))
        if self.battery_level is not None:
            base = _append_detail_text(base, f"Battery {self.battery_level}%")
        return base

    def supports_sensor(self, sensor_key: str) -> bool:
        """Disable RF RSSI sensor when the API does not provide it."""
        if sensor_key == "rf_rssi":
            return False
        return super().supports_sensor(sensor_key)

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the rain sensor."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("rainfall_total", attr="rainfall_mm_total")
        yield attr_mapping("rainfall_hourly", attr="rainfall_mm_hour")
        yield attr_mapping("rainfall_daily", attr="rainfall_mm_daily")
        yield attr_mapping("rainfall_weekly", attr="rainfall_mm_7days")


class RainPointAirSensor(HomgarSubDevice):
    """RainPoint outdoor air sensor."""

    MODEL_CODES: ClassVar[list[int]] = [262]
    FRIENDLY_DESC: ClassVar[str] = "Outdoor Air Humidity Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the air sensor."""
        super().__init__(**kwargs)
        self.temp_mk_current: int | None = None
        self.temp_mk_daily_max: int | None = None
        self.temp_mk_daily_min: int | None = None
        self.temp_trend: int | None = None
        self.hum_current: int | None = None
        self.hum_daily_max: int | None = None
        self.hum_daily_min: int | None = None
        self.hum_trend: int | None = None
        self.battery_state: str | None = None
        self.battery_level_raw: int | None = None
        self.battery_level: int | None = None
        self.raw_status: str | None = None
        self.temp_c_max: float | None = None
        self.temp_c_min: float | None = None
        self.hum_pct_max: int | None = None
        self.hum_pct_min: int | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Parse the air sensor payload into temperature and humidity statistics."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=262,
            log_label="air",
        )) is not None:
            max_mk, min_mk = _decode_packed_fahrenheit_extrema(vals.get("MAX_TEM"))
            if max_mk is not None:
                self.temp_mk_daily_max = max_mk
                self.temp_c_max = _mk_to_celsius(max_mk)
            if min_mk is not None:
                self.temp_mk_daily_min = min_mk
                self.temp_c_min = _mk_to_celsius(min_mk)

            if (temp_c := _safe_float(vals.get("temperature_c"))) is not None:
                self.temp_mk_current = _celsius_to_mk(temp_c)
                self.temp_c_max = self.temp_c_max or temp_c
                self.temp_c_min = self.temp_c_min or temp_c

            if (humidity := _safe_int(vals.get("humidity_pct"))) is not None:
                self.hum_current = humidity
                self.hum_pct_max = self.hum_pct_max or self.hum_current
                self.hum_pct_min = self.hum_pct_min or self.hum_current

            if (humidity_stats := _safe_int(vals.get("MAX_RH"))) is not None:
                self.hum_daily_max = (humidity_stats >> 8) & 0xFF
                self.hum_daily_min = humidity_stats & 0xFF
                self.hum_pct_max = self.hum_daily_max
                self.hum_pct_min = self.hum_daily_min

            if (battery_raw := _safe_int(vals.get("battery_state_raw"))) is not None:
                self.battery_level_raw = battery_raw
                self.battery_level = _battery_percentage_from_state(battery_raw)
                if self.battery_level is not None:
                    self.status_fields["battery_level"] = self.battery_level
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            return

        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including temperature and humidity."""
        base = super().__str__()
        temp_c = self.temperature_c
        if temp_c is not None:
            detail_parts = [f"{temp_c:.1f}°C"]
            if self.hum_current is not None:
                detail_parts.append(f"{self.hum_current}%")
            base = _append_detail_text(base, " / ".join(detail_parts))
        elif self.hum_current is not None:
            base = _append_detail_text(base, f"{self.hum_current}%")
        if self.battery_level is not None:
            base = _append_detail_text(base, f"Battery {self.battery_level}%")
        return base

    @property
    def temperature_c(self) -> float | None:
        """Return current air temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_current)

    @property
    def temperature_c_max(self) -> float | None:
        """Return daily maximum air temperature in Celsius."""
        return self.temp_c_max or _mk_to_celsius(self.temp_mk_daily_max)

    @property
    def temperature_c_min(self) -> float | None:
        """Return daily minimum air temperature in Celsius."""
        return self.temp_c_min or _mk_to_celsius(self.temp_mk_daily_min)

    @property
    def humidity_pct(self) -> int | None:
        """Return current relative humidity percentage."""
        return self.hum_current

    @property
    def humidity_pct_max(self) -> int | None:
        """Return daily maximum relative humidity percentage."""
        return self.hum_pct_max or self.hum_daily_max

    @property
    def humidity_pct_min(self) -> int | None:
        """Return daily minimum relative humidity percentage."""
        return self.hum_pct_min or self.hum_daily_min

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the air sensor."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("temperature_max", attr="temperature_c_max")
        yield attr_mapping("temperature_min", attr="temperature_c_min")
        yield attr_mapping("humidity_max", attr="humidity_pct_max")
        yield attr_mapping("humidity_min", attr="humidity_pct_min")


class RainPointCO2Sensor(HomgarSubDevice):
    """RainPoint CO₂ sensor."""

    MODEL_CODES: ClassVar[list[int]] = [89]
    FRIENDLY_DESC: ClassVar[str] = "CO₂ Sensor"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the CO₂ sensor."""
        super().__init__(**kwargs)
        self.temp_mk_current: int | None = None
        self.hum_current: int | None = None
        self.co2_ppm: int | None = None
        self.co2_min_ppm: int | None = None
        self.co2_max_ppm: int | None = None
        self.co2_alert_ppm: int | None = None
        self.battery_state: str | None = None
        self.battery_level_raw: int | None = None
        self.battery_level: int | None = None
        self.raw_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Decode TLV payload with CO₂, temperature and humidity measurements."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=89,
            log_label="CO₂",
        )) is not None:
            if (co2_int := _safe_int(vals.get("STA_CO2"))) is not None:
                self.co2_ppm = co2_int & 0xFFFF
                self.co2_alert_ppm = (co2_int >> 16) & 0xFFFF
                self.status_fields["co2_ppm"] = self.co2_ppm
                self.status_fields["co2_alert_ppm"] = self.co2_alert_ppm

            if (limits_int := _safe_int(vals.get("MAX_CO2"))) is not None:
                self.co2_max_ppm = limits_int & 0xFFFF
                self.co2_min_ppm = (limits_int >> 16) & 0xFFFF
            elif (
                (co2_bytes := vals.get("dp_8"))
                and isinstance(co2_bytes, bytes)
                and len(co2_bytes) >= 4
            ):
                self.co2_min_ppm = int.from_bytes(co2_bytes[0:2], "little")
                self.co2_max_ppm = int.from_bytes(co2_bytes[2:4], "little")

            if self.co2_min_ppm is not None:
                self.status_fields["co2_min_ppm"] = self.co2_min_ppm
            if self.co2_max_ppm is not None:
                self.status_fields["co2_max_ppm"] = self.co2_max_ppm

            if (temp_c := _safe_float(vals.get("temperature_c"))) is not None:
                self.temp_mk_current = _celsius_to_mk(temp_c)
            if (humidity := _safe_int(vals.get("humidity_pct"))) is not None:
                self.hum_current = humidity
            if (battery_raw := _safe_int(vals.get("battery_state_raw"))) is not None:
                self.battery_level_raw = battery_raw
                self.battery_level = _battery_percentage_from_state(battery_raw)
                if self.battery_level is not None:
                    self.status_fields["battery_level"] = self.battery_level
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            return

        self.raw_status = value

    @property
    def temperature_c(self) -> float | None:
        """Return current ambient temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_current)

    @property
    def humidity_pct(self) -> int | None:
        """Return current relative humidity percentage."""
        return self.hum_current

    def supports_sensor(self, sensor_key: str) -> bool:
        """Expose extra CO₂-specific sensors while keeping default handling."""
        if sensor_key.startswith("co2"):
            return True
        return super().supports_sensor(sensor_key)

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the CO₂ sensor."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("co2", attr="co2_ppm")
        yield attr_mapping("co2_min", attr="co2_min_ppm")
        yield attr_mapping("co2_max", attr="co2_max_ppm")
        yield attr_mapping("co2_alert", attr="co2_alert_ppm")

    def __str__(self) -> str:
        """Return human readable description including CO₂, temperature, humidity."""
        base = super().__str__()
        details: list[str] = []
        if self.co2_ppm is not None:
            details.append(f"{self.co2_ppm}ppm CO₂")
        temp = self.temperature_c
        if temp is not None:
            details.append(f"{temp:.1f}°C")
        if self.hum_current is not None:
            details.append(f"{self.hum_current}% RH")
        if self.battery_level is not None:
            details.append(f"Battery {self.battery_level}%")
        if not details:
            return base
        return f"{base}: {', '.join(details)}"


class DiivooWaterFlowMeter(HomgarSubDevice):
    """Diivoo water usage meter."""

    MODEL_CODES: ClassVar[list[int]] = [277]
    FRIENDLY_DESC: ClassVar[str] = "Diivoo Water Flow Meter"
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = False
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the water meter."""
        super().__init__(**kwargs)
        self.flow_rate_lpm: float | None = None
        self.water_usage_total_liters: float | None = None
        self.water_usage_today_liters: float | None = None
        self.water_last_usage_liters: float | None = None
        self.water_other_total_liters: float | None = None
        self.current_duration_seconds: int | None = None
        self.last_duration_seconds: int | None = None
        self.last_event_time: int | None = None
        self.battery_level: int | None = None
        self.battery_level_raw: int | None = None
        self.battery_state: str | None = None
        self.raw_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Decode TLV payload with flow and water usage metrics."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=277,
            log_label="diivoo_water",
        )) is not None:
            def _scaled(name: str, scale: float = 0.1) -> float | None:
                measured = _safe_float(vals.get(name))
                return measured * scale if measured is not None else None

            if (total := _scaled("STA_WATER_TOTAL")) is not None:
                self.water_usage_total_liters = total
                self.status_fields["water_usage_total_liters"] = total
            if (today := _scaled("STA_TOTAL_TODAY")) is not None:
                self.water_usage_today_liters = today
                self.status_fields["water_usage_today_liters"] = today
            if (last := _scaled("STA_LASTUSAGE")) is not None:
                self.water_last_usage_liters = last
                self.status_fields["water_last_usage_liters"] = last
            if (other_total := _safe_float(vals.get("STA_OTHER_TOTAL"))) is not None:
                self.water_other_total_liters = other_total
                self.status_fields["water_other_total_liters"] = other_total
            if (flow := _scaled("STA_CUR_FLOW")) is not None:
                self.flow_rate_lpm = flow
                self.status_fields["water_flow_lpm"] = flow

            if (duration := _safe_int(vals.get("STA_DURATION"))) is not None:
                self.current_duration_seconds = duration
                self.status_fields["watering_duration_seconds"] = duration
            if (last_duration := _safe_int(vals.get("STA_LAST_DURATION"))) is not None:
                self.last_duration_seconds = last_duration
                self.status_fields["watering_last_duration_seconds"] = last_duration
            if (event_time := _safe_int(vals.get("STA_EVTIME"))) is not None:
                self.last_event_time = event_time
                self.status_fields["last_event_epoch"] = event_time

            if (signal := vals.get("signal_strength")) is not None:
                self._update_signal_strength(signal)

            if (battery_raw := _safe_int(vals.get("battery_state_raw"))) is not None:
                self.battery_level = _battery_percentage_from_state(battery_raw)
                self.battery_level_raw = battery_raw
                if self.battery_level is not None:
                    self.status_fields["battery_level"] = self.battery_level

            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            return

        self.raw_status = value

    def __str__(self) -> str:
        """Return a human readable description including flow and totals."""
        base = super().__str__()
        details: list[str] = []
        if self.water_usage_total_liters is not None:
            details.append(f"{self.water_usage_total_liters:.1f} L total")
        if self.water_usage_today_liters is not None:
            details.append(f"{self.water_usage_today_liters:.1f} L today")
        if self.flow_rate_lpm is not None:
            details.append(f"{self.flow_rate_lpm:.1f} L/min")
        if details:
            base = _append_detail_text(base, " / ".join(details))
        return base

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the water meter."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("water_usage_total", attr="water_usage_total_liters")
        yield attr_mapping("water_usage_today", attr="water_usage_today_liters")
        yield attr_mapping("water_usage_last", attr="water_last_usage_liters")
        yield attr_mapping("water_flow", attr="flow_rate_lpm")
        yield attr_mapping("watering_duration", attr="current_duration_seconds")
        yield attr_mapping("watering_last_duration", attr="last_duration_seconds")


class RainPointPoolSensor(HomgarSubDevice):
    """RainPoint pool temperature sensor."""

    MODEL_CODES: ClassVar[list[int]] = [268]
    FRIENDLY_DESC: ClassVar[str] = "Pool Temperature Sensor"
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = True
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the pool sensor."""
        super().__init__(**kwargs)
        self.water_temp_c: float | None = None
        self.temp_mk_current: int | None = None
        self.temp_mk_daily_max: int | None = None
        self.temp_mk_daily_min: int | None = None
        self.water_temp_f: float | None = None
        self.battery_level: int | None = None
        self.battery_level_raw: int | None = None
        self.raw_status: str | None = None
        self.trend_raw: int | None = None
        self.battery_state: str | None = None
        self.signal_strength: int | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Decode the raw payload using the product model definitions."""
        if (vals := self._decode_tlv_payload(
            value,
            model_code=268,
            log_label="pool",
        )) is not None:
            if (temp_c := _safe_float(vals.get("temperature_c"))) is not None:
                self.water_temp_c = temp_c
                self.temp_mk_current = _celsius_to_mk(temp_c)
            if (temp_f := _safe_float(vals.get("temperature_f"))) is not None:
                self.water_temp_f = temp_f

            max_mk, min_mk = _decode_packed_fahrenheit_extrema(vals.get("MAX_TEM"))
            if max_mk is not None:
                self.temp_mk_daily_max = max_mk
            if min_mk is not None:
                self.temp_mk_daily_min = min_mk

            if (battery_raw := _safe_int(vals.get("battery_state_raw"))) is not None:
                self.battery_level = _battery_percentage_from_state(battery_raw)
                self.battery_level_raw = battery_raw
                if self.battery_level is not None:
                    self.status_fields["battery_level"] = self.battery_level
            if "battery_state" in vals:
                self.battery_state = vals["battery_state"]
            if (signal := vals.get("signal_strength")) is not None:
                self._update_signal_strength(signal)
            if (trend := _safe_int(vals.get("trend_raw"))) is not None:
                self.trend_raw = trend
            return

        self.raw_status = value

    @property
    def temperature_c(self) -> float | None:
        """Return current pool temperature in Celsius for compatibility."""
        return _mk_to_celsius(self.temp_mk_current)

    @property
    def water_temperature_c(self) -> float | None:
        """Return current pool water temperature in Celsius."""
        return self.water_temp_c

    @property
    def water_temperature_c_max(self) -> float | None:
        """Return daily maximum pool water temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_daily_max)

    @property
    def water_temperature_c_min(self) -> float | None:
        """Return daily minimum pool water temperature in Celsius."""
        return _mk_to_celsius(self.temp_mk_daily_min)

    def supports_sensor(self, sensor_key: str) -> bool:
        """Disable RF RSSI sensor when not reported by the device."""
        if sensor_key == "rf_rssi":
            return False
        return super().supports_sensor(sensor_key)

    def __str__(self) -> str:
        """Return human readable description including water temperature."""
        base = super().__str__()
        details: list[str] = []
        if self.water_temp_c is not None:
            details.append(f"{self.water_temp_c:.1f}°C water")
        if self.water_temp_f is not None:
            details.append(f"{self.water_temp_f:.1f}°F water")
        if details:
            base = _append_detail_text(base, " / ".join(details))
        if self.battery_level is not None:
            base = _append_detail_text(base, f"Battery {self.battery_level}%")
        return base

    def iter_sensor_mappings(self) -> Iterable[DeviceSensorMapping]:
        """Return sensor mappings exposed by the pool sensor."""
        yield from super().iter_sensor_mappings()
        yield attr_mapping("pool_water_temp_max", attr="water_temperature_c_max")
        yield attr_mapping("pool_water_temp_min", attr="water_temperature_c_min")


class DiivooGatewayHub(HomgarHubDevice):
    """Diivoo Wi-Fi gateway hub."""

    MODEL_CODES: ClassVar[list[int]] = [256]
    FRIENDLY_DESC: ClassVar[str] = "Diivoo WiFi Hub"
    HAS_BATTERY: ClassVar[bool] = False
    INCLUDE_BASE_TEMPERATURE: ClassVar[bool] = False
    INCLUDE_BASE_HUMIDITY: ClassVar[bool] = False


class RainPoint2ZoneTimer(HomgarSubDevice):
    """RainPoint two-zone water timer."""

    MODEL_CODES: ClassVar[list[int]] = [261]
    FRIENDLY_DESC: ClassVar[str] = "2-Zone Water Timer"

    def __init__(self, **kwargs: Any) -> None:
        """Initialise placeholder attributes for the timer."""
        super().__init__(**kwargs)
        self.zone_status: str | None = None

    def _parse_device_specific_status_d_value(self, value: str) -> None:
        """Store the raw zone status for further analysis.

        Observed example value: ``0,9,0,0,0,0|0,1291,0,0,0,0``.
        """

        self.zone_status = value


MODEL_CODE_MAPPING: dict[int, type[HomgarDevice]] = {
    code: device_class
    for device_class in (
        RainPointDisplayHub,
        RainPointGatewayHub,
        RainPointSoilMoistureSensor,
        RainPointRainSensor,
        RainPointAirSensor,
        RainPointCO2Sensor,
        DiivooWaterFlowMeter,
        RainPointPoolSensor,
        DiivooGatewayHub,
        RainPoint2ZoneTimer,
    )
    for code in device_class.MODEL_CODES
}
