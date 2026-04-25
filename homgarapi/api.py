import binascii
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional, List

import requests

from homgarapi.devices import HomgarHome, MODEL_CODE_MAPPING, HomgarHubDevice
from homgarapi.logutil import TRACE, get_logger

logger = get_logger(__file__)


class HomgarApiException(Exception):
    def __init__(self, code, msg):
        super().__init__()
        self.code = code
        self.msg = msg

    def __str__(self):
        s = f"HomGar API returned code {self.code}"
        if self.msg:
            s += f" ('{self.msg}')"
        return s


class HomgarApi:
    def __init__(
            self,
            auth_cache: Optional[dict] = None,
            api_base_url: str = "https://region3.homgarus.com",
            requests_session: requests.Session = None
    ):
        """
        Create an object for interacting with the Homgar API
        :param auth_cache: A dictionary in which authentication information will be stored.
            Save this dict on exit and supply it again next time constructing this object to avoid logging in
            if a valid token is still present.
        :param api_base_url: The base URL for the Homgar API. Omit trailing slash.
        :param requests_session: Optional requests lib session to use. New session is created if omitted.
        """
        self.session = requests_session or requests.Session()
        self.cache = auth_cache or {}
        self.base = api_base_url

    #: Headers the current RainPoint Home app (1.16.1057) sends with every
    #: authenticated request. `appCode=2` replaced `appCode=1` on newer
    #: firmware — the server rejects `appCode=1` logins from some accounts
    #: with `code 2001 "Wrong account or password"` even when the password
    #: is correct. The `version` and `sceneType` values were captured from
    #: the app and treated as opaque client-identification headers.
    DEFAULT_HEADERS = {
        "lang": "en",
        "appCode": "2",
        "version": "1.16.1057",
        "sceneType": "1",
    }

    # (connect, read) seconds. Without an explicit timeout, a half-open
    # TCP connection from the HomGar cloud can block the caller forever —
    # in a DataUpdateCoordinator that means no further polls ever fire.
    DEFAULT_TIMEOUT = (10, 30)

    def _request(self, method, url, with_auth=True, headers=None, **kwargs):
        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        if with_auth:
            headers["auth"] = self.cache["token"]
        kwargs.setdefault("timeout", self.DEFAULT_TIMEOUT)
        response = self.session.request(method, url, headers=headers, **kwargs)
        logger.log(TRACE, "-[%03d]-> %s", response.status_code, response.text)
        return response

    def _request_json(self, method, path, **kwargs):
        response = self._request(method, self.base + path, **kwargs).json()
        code = response.get('code')
        if code != 0:
            raise HomgarApiException(code, response.get('msg'))
        return response.get('data')

    def _get_json(self, path, **kwargs):
        return self._request_json("GET", path, **kwargs)

    def _post_json(self, path, body, **kwargs):
        return self._request_json("POST", path, json=body, **kwargs)

    def login(self, email: str, password: str, area_code="31") -> None:
        """
        Perform a new login.
        :param email: Account e-mail
        :param password: Account password
        :param area_code: Seems to need to be the phone country code associated with the account, e.g. "31" for NL
        """
        data = self._post_json("/auth/basic/app/login", {
            "areaCode": area_code,
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode('utf-8')
        }, with_auth=False)
        self.cache['email'] = email
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.utcnow().timestamp() + data.get('tokenExpired')
        self.cache['refresh_token'] = data.get('refreshToken')

    def refresh_token(self) -> None:
        """
        Exchange the cached refresh token for a fresh access token.

        Avoids re-logging in (which kicks the account off its phones).
        Mirrors ``HomgarClient.refreshToken`` in the RainPoint Home APK.
        """
        rt = self.cache.get('refresh_token')
        if not rt:
            raise HomgarApiException(-1, "No refresh_token in cache; call login() first")
        data = self._post_json(
            "/auth/basic/app/token/refresh",
            {"refreshToken": rt},
            with_auth=False,
        )
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = (
            datetime.utcnow().timestamp() + data.get('tokenExpired', 0)
        )
        # Some deployments rotate the refresh token too.
        if data.get('refreshToken'):
            self.cache['refresh_token'] = data['refreshToken']

    def logout(self) -> None:
        """POST /auth/basic/app/logOut. Invalidates the access token."""
        self._post_json("/auth/basic/app/logOut", {})
        self.cache.pop('token', None)
        self.cache.pop('token_expires', None)
        self.cache.pop('refresh_token', None)

    def get_homes(self) -> List[HomgarHome]:
        """
        Retrieves all HomgarHome objects associated with the logged in account.
        Requires first logging in.
        :return: List of HomgarHome objects
        """
        data = self._get_json("/app/member/appHome/list")
        return [HomgarHome(hid=h.get('hid'), name=h.get('homeName')) for h in data]

    def get_devices_for_hid(self, hid: str) -> List[HomgarHubDevice]:
        """
        Retrieves a device tree associated with the home identified by the given hid (home ID).
        This function returns a list of hubs associated with the home. Each hub contains associated
        subdevices that use the hub as gateway.
        :param hid: The home ID to retrieve hubs and associated subdevices for
        :return: List of hubs with associated subdevicse
        """
        data = self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})
        hubs = []

        def device_base_props(dev_data):
            return dict(
                model=dev_data.get('model'),
                model_code=dev_data.get('modelCode'),
                name=dev_data.get('name'),
                did=dev_data.get('did'),
                mid=dev_data.get('mid'),
                address=dev_data.get('addr'),
                port_number=dev_data.get('portNumber'),
                alerts=dev_data.get('alerts'),
                device_name=dev_data.get('deviceName'),
                product_key=dev_data.get('productKey'),
                iot_id=dev_data.get('iotId'),
                sid=dev_data.get('sid'),
                port_describe=dev_data.get('portDescribe'),
            )

        def get_device_class(dev_data):
            model_code = dev_data.get('modelCode')
            if model_code not in MODEL_CODE_MAPPING:
                logger.warning("Unknown device '%s' with modelCode %d", dev_data.get('model'), model_code)
                return None
            return MODEL_CODE_MAPPING[model_code]

        for hub_data in data:
            subdevices = []
            for subdevice_data in hub_data.get('subDevices', []):
                did = subdevice_data.get('did')
                if did == 1:
                    # Display hub
                    continue
                subdevice_class = get_device_class(subdevice_data)
                if subdevice_class is None:
                    continue
                subdevices.append(subdevice_class(**device_base_props(subdevice_data)))

            hub_class = get_device_class(hub_data)
            if hub_class is None:
                hub_class = HomgarHubDevice

            hubs.append(hub_class(
                **device_base_props(hub_data),
                subdevices=subdevices
            ))

        return hubs

    def get_device_status(self, hub: HomgarHubDevice) -> None:
        """
        Updates the device status of all subdevices associated with the given hub device.
        :param hub: The hub to update
        """
        data = self._get_json("/app/device/getDeviceStatus", params={"mid": str(hub.mid)})
        id_map = {status_id: device for device in [hub, *hub.subdevices] for status_id in device.get_device_status_ids()}

        for subdevice_status in data['subDeviceStatus']:
            device = id_map.get(subdevice_status['id'])
            if device is not None:
                device.set_device_status(subdevice_status)

    def control_zone(
        self,
        hub: HomgarHubDevice,
        sub_addr: int,
        port: int,
        mode: int,
        duration: int,
    ) -> dict:
        """
        Send a manual control command to one zone/port of a sub-device.

        :param hub: The hub (``HomgarHubDevice``) that the sub-device is paired
            with — supplies ``mid``, ``deviceName`` and ``productKey``.
        :param sub_addr: Sub-device RF address (``addr`` on a subdevice,
            ``1`` for most users' only timer).
        :param port: 1-based port number. 2-zone timer: 1=Sprinklers, 2=Dripline.
        :param mode: 0 = off/cancel, 1 = manual on, 2 = scheduled.
        :param duration: Run duration in seconds. The RainPoint Home UI
            enforces a 60 s minimum — below that the valve + pump take
            a beating without delivering meaningful water.
        :return: Decoded ``data`` field of the response — includes the new
            device status string under ``state`` and a ``timestamp``.

        Mirrors ``HomgarClient.setDeviceMode`` — the server relays the
        command to the device via Aliyun IoT Link. No MQTT client required
        on our side.
        """
        # We need ``productKey`` and ``deviceName`` off the hub, which come
        # from ``getDeviceByHid``. ``get_devices_for_hid`` already unpacks
        # those into the base props but they're not exposed on the class
        # — fetch from the cache dict the caller set, falling back to
        # attributes we might add later.
        device_name = getattr(hub, "device_name", None) or hub.__dict__.get("deviceName")
        product_key = getattr(hub, "product_key", None) or hub.__dict__.get("productKey")
        if not device_name or not product_key:
            raise HomgarApiException(
                -1,
                "Hub is missing deviceName/productKey — did you call "
                "get_devices_for_hid() first?",
            )
        body = {
            "deviceName": device_name,
            "productKey": product_key,
            "mid": str(hub.mid),
            "addr": sub_addr,
            "port": port,
            "mode": mode,
            "duration": duration,
            "param": "",
        }
        return self._post_json("/app/device/controlWorkMode", body)

    def ensure_logged_in(self, email: str, password: str, area_code: str = "31") -> None:
        """
        Ensures this API object has valid credentials.
        Attempts to verify the token stored in the auth cache. If invalid, attempts to login.
        See login() for parameter info.
        """
        if (
                self.cache.get('email') != email or
                datetime.fromtimestamp(self.cache.get('token_expires', 0)) - datetime.utcnow() < timedelta(minutes=60)
        ):
            self.login(email, password, area_code=area_code)
