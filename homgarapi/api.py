"""Client wrapper for the HomGar REST API."""

from __future__ import annotations

import binascii
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, cast

import requests

from .auth import AuthRetryManager, AuthRetryPolicy
from .constants import build_model_list
from .devices import MODEL_CODE_MAPPING, HomgarDevice, HomgarHome, HomgarHubDevice
from .logutil import TRACE, get_logger

logger = get_logger(__file__)
class HomgarApiException(Exception):
    """Raised when the HomGar API returns a non-success response."""

    def __init__(self, code: int, message: str | None) -> None:
        """Store the API error information."""
        super().__init__(code, message)
        self.code = code
        self.message = message or ""

    def __str__(self) -> str:
        """Return a readable representation of the error."""
        base = f"HomGar API returned code {self.code}"
        return f"{base} ('{self.message}')" if self.message else base
class HomgarApi:
    """Thin client around the HomGar REST endpoints."""

    def __init__(
        self,
        auth_cache: MutableMapping[str, Any] | None = None,
        api_base_url: str = "https://region3.homgarus.com",
        requests_session: requests.Session | None = None,
    ) -> None:
        """Initialise the API client.

        :param auth_cache: Mutable mapping used to persist authentication data between runs.
        :param api_base_url: Base URL for the HomGar API, without a trailing slash.
        :param requests_session: Optional `requests.Session` to reuse; a new one is created when omitted.
        """
        self.session: requests.Session = requests_session or requests.Session()
        self.cache: MutableMapping[str, Any] = auth_cache or {}
        self.base = api_base_url.rstrip("/")
        self._auth_manager = AuthRetryManager(policy=AuthRetryPolicy())
        self._unknown_devices: dict[
            tuple[str | None, str | None, str | None], dict[str, Any]
        ] = {}
        self._unknown_device_status: dict[tuple[str | None, str], list[str]] = {}

    def _request(
        self,
        method: str,
        url: str,
        *,
        with_auth: bool = True,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an HTTP request against the HomGar API.

        :param method: HTTP verb to use (GET, POST, ...).
        :param url: Fully qualified URL to call.
        :param with_auth: Whether to include the cached authentication token.
        :param headers: Additional HTTP headers to include with the request.
        :param kwargs: Extra keyword arguments forwarded to `requests.Session.request`.
        :returns: The HTTP response object.
        """
        request_headers = {"lang": "en", "appCode": "1", **(headers or {})}
        if with_auth:
            token = self.cache.get("token")
            if not token:
                msg = "Authentication token missing from cache"
                raise HomgarApiException(-1, msg)
            request_headers["auth"] = str(token)

        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        response = self.session.request(method, url, headers=request_headers, **kwargs)
        logger.log(TRACE, "-[%03d]-> %s", response.status_code, response.text)
        return response

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform a JSON request and return the inner `data` payload.

        :param method: HTTP verb to use (GET, POST, ...).
        :param path: Path relative to the configured base URL.
        :param kwargs: Extra keyword arguments forwarded to `_request`.
        :returns: The JSON `data` field when the call succeeds.
        :raises HomgarApiException: If the API reports a non-zero code.
        """
        response = self._request(method, f"{self.base}{path}", **kwargs).json()
        code = int(response.get("code", -1))
        if code != 0:
            raise HomgarApiException(code, response.get("msg"))
        return response.get("data")

    def _get_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("GET", path, **kwargs)

    def _post_json(self, path: str, body: Mapping[str, Any], **kwargs: Any) -> Any:
        return self._request_json("POST", path, json=body, **kwargs)

    def get_product_models(self) -> Mapping[str, Any]:
        """Retrieve the list of supported product models from the API.

        :returns: Mapping containing model metadata (`version`, `modelCodes`, `models`, ...).
        """
        return cast(
            Mapping[str, Any], self._get_json("/app/common/core/productModel/json")
        )

    def get_dictionary(self) -> Mapping[str, Any]:
        """Retrieve platform dictionary metadata (currency, soil types, etc.)."""
        data = self._get_json("/app/common/core/dict")
        return cast(Mapping[str, Any], data or {})

    def login(self, email: str, password: str, area_code: str = "31") -> None:
        """Perform a login and cache the resulting tokens.

        :param email: HomGar account e-mail address.
        :param password: HomGar account password.
        :param area_code: Phone country code associated with the account (for example ``"31"`` for NL).
        """
        payload = {
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode("utf-8"),
        }
        data = self._post_json("/auth/basic/app/login", payload, with_auth=False)
        expires_in: int = int(data.get("tokenExpired", 0))
        self.cache["email"] = email
        self.cache["token"] = data.get("token")
        self.cache["token_expires"] = datetime.now(tz=UTC).timestamp() + expires_in
        self.cache["refresh_token"] = data.get("refreshToken")

    def get_homes(self) -> list[HomgarHome]:
        """Return all homes linked to the current account.

        :returns: List of `HomgarHome` instances.
        """
        data = self._get_json("/app/member/appHome/list")
        homes_data: Sequence[Mapping[str, Any]] = data or []
        result: list[HomgarHome] = []
        for home in homes_data:
            hid_value = home.get("hid")
            if not isinstance(hid_value, (str, int)):
                hid_value = "" if hid_value is None else str(hid_value)
            name_value = home.get("homeName")
            if not isinstance(name_value, str):
                name_value = "" if name_value is None else str(name_value)
            result.append(HomgarHome(hid=hid_value, name=name_value))
        return result

    def get_devices_for_hid(self, hid: str) -> list[HomgarHubDevice]:
        """Return hubs and subdevices for the provided home id.

        :param hid: The home identifier supplied by HomGar.
        :returns: List of `HomgarHubDevice` objects populated with subdevices.
        """
        data = self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})
        hubs: list[HomgarHubDevice] = []
        devices: Sequence[Mapping[str, Any]] = data or []

        def device_base_props(dev_data: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "model": dev_data.get("model"),
                "model_code": dev_data.get("modelCode"),
                "name": dev_data.get("name"),
                "did": dev_data.get("did"),
                "mid": dev_data.get("mid"),
                "address": dev_data.get("addr"),
                "port_number": dev_data.get("portNumber"),
                "alerts": dev_data.get("alerts"),
                "device_name": dev_data.get("deviceName"),
                "product_key": dev_data.get("productKey"),
            }

        def get_device_class(dev_data: Mapping[str, Any]) -> type[HomgarDevice] | None:
            model_code_value = dev_data.get("modelCode")
            if not isinstance(model_code_value, (str, int)):
                return None
            try:
                model_code_int = int(model_code_value)
            except (TypeError, ValueError):
                return None

            device_class = MODEL_CODE_MAPPING.get(model_code_int)
            if device_class is None:
                logger.warning(
                    "Unknown device '%s' with modelCode %s",
                    dev_data.get("model"),
                    model_code_value,
                )
            return device_class

        for hub_data in devices:
            subdevices: list[HomgarDevice] = []
            for subdevice_data in hub_data.get("subDevices", []):
                did = subdevice_data.get("did")
                if did == 1:  # display hub
                    continue
                subdevice_class = get_device_class(subdevice_data)
                if subdevice_class is None:
                    self._record_unknown_device(subdevice_data)
                    continue
                subdevice = subdevice_class(**device_base_props(subdevice_data))
                self._enrich_device_metadata(subdevice, subdevice_data)
                subdevices.append(subdevice)

            hub_class = get_device_class(hub_data)
            if hub_class is not None and issubclass(hub_class, HomgarHubDevice):
                hub_instance = hub_class(
                    **device_base_props(hub_data),
                    subdevices=subdevices,
                )
            else:
                hub_instance = HomgarHubDevice(
                    **device_base_props(hub_data),
                    subdevices=subdevices,
                )
                self._record_unknown_device(hub_data)
            self._enrich_device_metadata(hub_instance, hub_data)
            hubs.append(hub_instance)

        return hubs

    def get_device_status(self, hub: HomgarHubDevice) -> None:
        """Request status updates for all devices attached to a hub.

        :param hub: Hub whose subdevices should be updated in place.
        """
        status_payload: Sequence[Mapping[str, Any]] | None = None

        if hub.device_name and hub.product_key:
            body = {
                "devices": [
                    {
                        "deviceName": hub.device_name,
                        "mid": str(hub.mid),
                        "productKey": hub.product_key,
                    }
                ]
            }
            try:
                response = self._post_json("/app/device/multipleDeviceStatus", body)
                if isinstance(response, Sequence) and response:
                    first_entry = response[0]
                    if isinstance(first_entry, Mapping):
                        raw_status = first_entry.get("status", [])
                        if isinstance(raw_status, Sequence):
                            status_payload = [
                                item for item in raw_status if isinstance(item, Mapping)
                            ]
            except HomgarApiException as err:
                logger.debug("multipleDeviceStatus failed: %s", err)

        if status_payload is None:
            data = self._get_json(
                "/app/device/getDeviceStatus", params={"mid": str(hub.mid)}
            )
            raw_status = (
                data.get("subDeviceStatus", []) if isinstance(data, Mapping) else []
            )
            if isinstance(raw_status, Sequence):
                status_payload = [
                    item for item in raw_status if isinstance(item, Mapping)
                ]
            else:
                status_payload = []

        id_map: dict[str, HomgarDevice] = {}
        for homgar_device in (hub, *hub.subdevices):
            homgar_device.updated_in_last_poll = False
            status_ids = list(homgar_device.get_device_status_ids())
            device_did = getattr(homgar_device, "did", None)
            if device_did is not None:
                status_ids.append(str(device_did))
            for status_id in status_ids:
                id_map[str(status_id)] = homgar_device

        for subdevice_status in status_payload:
            status_id_raw = subdevice_status.get("id")
            if status_id_raw is None:
                continue
            status_key = str(status_id_raw)
            matched_device: HomgarDevice | None = (
                id_map.get(status_key)
                or id_map.get(status_key.upper())
                or id_map.get(status_key.lower())
            )
            if matched_device is None:
                self._record_unknown_status(hub, status_key, subdevice_status)
                logger.debug(
                    "Unmatched status entry for hub %s (%s): id=%s payload=%s",
                    getattr(hub, "name", hub.mid),
                    hub.mid,
                    status_key,
                    subdevice_status,
                )
                continue
            matched_device.set_device_status(subdevice_status)
            matched_device.updated_in_last_poll = True

    def ensure_logged_in(
        self, email: str, password: str, area_code: str = "31"
    ) -> None:
        """Ensure a valid token is present, refreshing if required.

        :param email: HomGar account e-mail address.
        :param password: HomGar account password.
        :param area_code: Phone country code associated with the account.
        """
        cache_email = self.cache.get("email")
        expires_at = float(self.cache.get("token_expires", 0))
        remaining = datetime.fromtimestamp(expires_at, tz=UTC) - datetime.now(tz=UTC)
        if cache_email != email or remaining < timedelta(minutes=60):
            self.login(email, password, area_code=area_code)

    def ensure_logged_in_with_retries(
        self,
        email: str,
        password: str,
        area_code: str = "31",
        *,
        max_retries: int | None = None,
    ) -> None:
        """Ensure a valid session exists with retry/backoff behaviour."""
        policy = self._auth_manager.policy
        original_max = policy.max_retries
        if max_retries is not None:
            policy.max_retries = max_retries

        def attempt() -> None:
            self.ensure_logged_in(email, password, area_code)

        def wrap(reason: str, detail: float | None) -> HomgarApiException:
            if reason == "rate_limited":
                wait_msg = (
                    f"Too many login failures, please wait {detail:.1f}s before retrying"
                    if detail is not None
                    else "Too many login failures, please wait before retrying"
                )
                return HomgarApiException(-1, wait_msg)
            return HomgarApiException(-1, reason)

        attempt_limit = max(1, policy.max_retries)
        attempt_count = 0
        last_error: HomgarApiException | None = None
        success = False

        try:
            while attempt_count < attempt_limit:
                attempt_count += 1
                attempt_ts = datetime.now(tz=UTC).timestamp()
                try:
                    self._auth_manager.execute(
                        attempt_ts=attempt_ts,
                        func=attempt,
                        wrap_exception=wrap,
                    )
                    success = True
                    if attempt_count > 1:
                        logger.debug(
                            "Successfully logged in to HomGar API after %d attempts",
                            attempt_count,
                        )
                    break
                except HomgarApiException as err:
                    last_error = err
                    error_code = getattr(err, "code", None)
                    error_message = str(getattr(err, "message", "")).lower()
                    if error_code == "invalid_auth":
                        raise
                    if "too many login failures" in error_message:
                        break
                    if attempt_count >= attempt_limit:
                        break
                    backoff = min(
                        float(policy.max_backoff),
                        float(policy.min_backoff) * (2 ** (attempt_count - 1)),
                    )
                    logger.debug(
                        "Login attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt_count,
                        attempt_limit,
                        err,
                        backoff,
                    )
                    time.sleep(backoff)
        finally:
            policy.max_retries = original_max
        if not success:
            if last_error is not None:
                raise last_error
            raise HomgarApiException(-1, "login_failed")
        logger.debug("Successfully logged in to HomGar API")

    def health_check(self) -> bool:
        """Return True if the API responds to a basic call."""
        try:
            self.get_homes()
        except HomgarApiException:
            return False
        return True

    def get_unknown_devices(self) -> list[Mapping[str, Any]]:
        """Return all device payloads that could not be classified."""
        result: list[Mapping[str, Any]] = []
        for key, payload in self._unknown_devices.items():
            mid_str, did_str, addr_str = key
            candidate_keys: list[tuple[str | None, str]] = []
            if mid_str is not None and did_str is not None:
                candidate_keys.append((mid_str, did_str.upper()))
            if mid_str is not None and addr_str is not None:
                try:
                    addr_int = int(addr_str)
                except (TypeError, ValueError):
                    formatted_addr: str | None = None
                    if isinstance(addr_str, str) and addr_str.upper().startswith("D"):
                        formatted_addr = addr_str.upper()
                    else:
                        formatted_addr = None
                    if formatted_addr is not None:
                        candidate_keys.append((mid_str, formatted_addr))
                    elif isinstance(addr_str, str):
                        candidate_keys.append((mid_str, addr_str.upper()))
                else:
                    candidate_keys.append((mid_str, f"D{addr_int:02d}"))
                    candidate_keys.append((mid_str, f"D{addr_int}"))
                    candidate_keys.append((mid_str, str(addr_str).upper()))
            status_values: list[str] = []
            for candidate in candidate_keys:
                values = self._unknown_device_status.get(candidate)
                if values:
                    for value in values:
                        if value not in status_values:
                            status_values.append(value)
            enriched = dict(payload)
            if status_values:
                enriched["status_values"] = status_values
            result.append(enriched)
        return result

    def _record_unknown_device(self, payload: Mapping[str, Any]) -> None:
        """Record a device payload that lacks a known model mapping."""
        key = self._build_unknown_device_key(payload)
        existing = self._unknown_devices.get(key)
        payload_copy = dict(payload)
        if existing is not None:
            existing.update(payload_copy)
        else:
            self._unknown_devices[key] = payload_copy
        logger.warning(
            "Encountered unsupported device (model=%s, modelCode=%s).",
            payload.get("model"),
            payload.get("modelCode"),
        )

    def _enrich_device_metadata(
        self, device: HomgarDevice, payload: Mapping[str, Any]
    ) -> None:
        """Populate additional metadata on device objects when available."""
        mac = payload.get("mac")
        if isinstance(mac, str) and mac:
            setattr(device, "mac", mac)
        soft_ver = payload.get("softVer")
        if isinstance(soft_ver, str) and soft_ver:
            setattr(device, "soft_version", soft_ver)

    def _build_unknown_device_key(
        self, payload: Mapping[str, Any]
    ) -> tuple[str | None, str | None, str | None]:
        """Return a stable key for an unknown device payload."""
        mid_raw = payload.get("mid")
        did_raw = payload.get("did")
        addr_raw = payload.get("addr")
        return (
            self._stringify_identifier(mid_raw),
            self._stringify_identifier(did_raw),
            self._stringify_identifier(addr_raw),
        )

    @staticmethod
    def _stringify_identifier(value: Any) -> str | None:
        """Coerce identifiers to string form for dictionary keys."""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)

    def _record_unknown_status(
        self,
        hub: HomgarHubDevice,
        status_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Track raw status payloads for devices without model mappings."""
        value = payload.get("value")
        if not isinstance(value, str):
            return
        mid = getattr(hub, "mid", None)
        mid_str = self._stringify_identifier(mid)
        status_norm = status_key.strip().upper()
        key = (mid_str, status_norm)
        values = self._unknown_device_status.setdefault(key, [])
        if value not in values:
            values.append(value)
def load_product_models(
    path: str | os.PathLike[str] | None = None,
) -> Mapping[int, Mapping[str, Any]]:
    """Load product model metadata from the bundled JSON file."""

    if path is not None:
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        models: list[Mapping[str, Any]] = payload["data"]["models"]
        return {int(model["modelCode"]): model for model in models}

    models = build_model_list()
    return {int(model["modelCode"]): model for model in models}
