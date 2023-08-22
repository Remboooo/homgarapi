import binascii
from datetime import datetime, timedelta
import hashlib
import os
import pickle
from pathlib import Path

import requests
import logging

import yaml

TRACE = logging.DEBUG - 1
logging.addLevelName(TRACE, "TRACE")

logger = logging.getLogger(Path(__file__).stem)


class HomgarHome:
    def __init__(self, hid, name):
        self.hid = hid
        self.name = name


class HomgarDevice:
    FRIENDLY_DESC = "Unknown HomGar device"

    def __init__(self, model, model_code, name, did, mid, alerts, **kwargs):
        self.model = model
        self.model_code = model_code
        self.name = name
        self.did = did  # the unique device identifier of this device itself
        self.mid = mid  # the unique identifier of the sensor network
        self.alerts = alerts

    def __str__(self):
        return f"{self.FRIENDLY_DESC} \"{self.name}\""


class HomgarHubDevice(HomgarDevice):
    def __init__(self, subdevices, **kwargs):
        super().__init__(**kwargs)
        self.subdevices = subdevices

    def __str__(self):
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"


class HomgarSubDevice(HomgarDevice):
    def __init__(self, address, port_number, **kwargs):
        super().__init__(**kwargs)
        self.address = address  # device address within the sensor network
        self.port_number = port_number  # the number of ports on the device, e.g. 2 for the 2-zone water timer

    def __str__(self):
        return f"{super().__str__()} at address {self.address}"


class RainPointDisplayHub(HomgarHubDevice):
    MODEL_CODES = [264]
    FRIENDLY_DESC = "Irrigation Display Hub"


class RainPointSoilMoistureSensor(HomgarSubDevice):
    MODEL_CODES = [72]
    FRIENDLY_DESC = "Soil Moisture Sensor"


class RainPointRainSensor(HomgarSubDevice):
    MODEL_CODES = [87]
    FRIENDLY_DESC = "High Precision Rain Sensor"


class RainPointAirSensor(HomgarSubDevice):
    MODEL_CODES = [262]
    FRIENDLY_DESC = "Outdoor Air Humidity Sensor"


class RainPoint2ZoneTimer(HomgarSubDevice):
    MODEL_CODES = [261]
    FRIENDLY_DESC = "2-Zone Water Timer"


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


MODEL_CODE_MAPPING = {
    code: clazz
    for clazz in (
        RainPointDisplayHub,
        RainPointSoilMoistureSensor,
        RainPointRainSensor,
        RainPointAirSensor,
        RainPoint2ZoneTimer
    ) for code in clazz.MODEL_CODES
}


class HomgarApi:
    def __init__(self, cache):
        self.session = requests.Session()
        self.cache = cache
        self.base = "https://region3.homgarus.com"

    def _request(self, method, url, with_auth=True, headers=None, **kwargs):
        logger.log(TRACE, "%s %s %s", method, url, kwargs)
        headers = {"lang": "en", "appCode": "1", **(headers or {})}
        if with_auth:
            headers["auth"] = self.cache["token"]
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

    def login(self, email, password):
        data = self._post_json("/auth/basic/app/login", {
            "areaCode": "31",
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode('utf-8')
        }, with_auth=False)
        self.cache['email'] = email
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.utcnow().timestamp() + data.get('tokenExpired')
        self.cache['refresh_token'] = data.get('refreshToken')

    def get_homes(self) -> [HomgarHome]:
        data = self._get_json("/app/member/appHome/list")
        return [HomgarHome(hid=h.get('hid'), name=h.get('homeName')) for h in data]

    def get_devices_for_home(self, hid):
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

    def get_device_status(self, mid):
        return self._get_json("/app/device/getDeviceStatus", params={"mid": str(mid)})

    def ensure_logged_in(self, email, password):
        if (
                self.cache.get('email') != email or
                datetime.fromtimestamp(self.cache.get('token_expires', 0)) - datetime.utcnow() < timedelta(minutes=60)
        ):
            self.login(email, password)


def demo(api: HomgarApi, config):
    api.ensure_logged_in(config['email'], config['password'])
    for home in api.get_homes():
        print(f"({home.hid}) {home.name}:")

        for hub in api.get_devices_for_home(home.hid):
            print(f"  - {hub}")
            for subdevice in hub.subdevices:
                print(f"    + {subdevice}")


def main():
    logging.basicConfig(level=TRACE)

    cache = {}
    try:
        with open('cache.pickle', 'rb') as f:
            cache = pickle.load(f)
    except OSError as e:
        logger.info("Could not load cache, starting fresh")

    with open('config.yml', 'rb') as f:
        config = yaml.unsafe_load(f)

    try:
        api = HomgarApi(cache)
        demo(api, config)
    finally:
        with open('cache.pickle', 'wb') as f:
            pickle.dump(cache, f)


if __name__ == '__main__':
    main()
