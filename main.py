import binascii
import hashlib
import logging
import os
import pickle
import re
from argparse import ArgumentParser
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml

TRACE = logging.DEBUG - 1
logging.addLevelName(TRACE, "TRACE")

logger = logging.getLogger(Path(__file__).stem)


STATS_VALUE_REGEX = re.compile(r'^(\d+)\((\d+)/(\d+)/(\d+)\)')


def _parse_stats_value(s):
    if match := STATS_VALUE_REGEX.fullmatch(s):
        return int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    else:
        return None, None, None, None


def _temp_to_mk(f):
    return round(1000 * ((int(f) * .1 - 32) * 5 / 9 + 273.15))


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

        self.address = None
        self.rf_rssi = None

    def __str__(self):
        return f"{self.FRIENDLY_DESC} \"{self.name}\" (DID {self.did})"

    def get_device_status_ids(self):
        return []

    def set_device_status(self, api_obj):
        if api_obj['id'] == f"D{self.address:02d}":
            self._parse_status_d_value(api_obj['value'])

    def _parse_status_d_value(self, val):
        general_str, specific_str = val.split(';')
        self._parse_general_status_d_value(general_str)
        self._parse_device_specific_status_d_value(specific_str)

    def _parse_general_status_d_value(self, s):
        # unknowns are all '1' in my case, possibly battery state + connected state
        unknown_1, rf_rssi, unknown_2 = s.split(',')
        self.rf_rssi = int(rf_rssi)

    def _parse_device_specific_status_d_value(self, s):
        raise NotImplementedError()


class HomgarHubDevice(HomgarDevice):
    def __init__(self, subdevices, **kwargs):
        super().__init__(**kwargs)
        self.address = 1
        self.subdevices = subdevices

    def __str__(self):
        return f"{super().__str__()} with {len(self.subdevices)} subdevices"

    def _parse_device_specific_status_d_value(self, s):
        pass


class HomgarSubDevice(HomgarDevice):
    def __init__(self, address, port_number, **kwargs):
        super().__init__(**kwargs)
        self.address = address  # device address within the sensor network
        self.port_number = port_number  # the number of ports on the device, e.g. 2 for the 2-zone water timer

    def __str__(self):
        return f"{super().__str__()} at address {self.address}"

    def get_device_status_ids(self):
        return [f"D{self.address:02d}"]

    def _parse_device_specific_status_d_value(self, s):
        pass


class RainPointDisplayHub(HomgarHubDevice):
    MODEL_CODES = [264]
    FRIENDLY_DESC = "Irrigation Display Hub"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.wifi_rssi = None
        self.battery_state = None
        self.connected = None

        self.temp_mk_current = None
        self.temp_mk_daily_max = None
        self.temp_mk_daily_min = None
        self.temp_trend = None
        self.hum_current = None
        self.hum_daily_max = None
        self.hum_daily_min = None
        self.hum_trend = None
        self.press_pa_current = None
        self.press_pa_daily_max = None
        self.press_pa_daily_min = None
        self.press_trend = None

    def get_device_status_ids(self):
        return ["connected", "state", "D01"]

    def set_device_status(self, api_obj):
        dev_id = api_obj['id']
        val = api_obj['value']
        if dev_id == "state":
            self.battery_state, self.wifi_rssi = [int(s) for s in val.split(',')]
        elif dev_id == "connected":
            self.connected = int(val) == 1
        else:
            super().set_device_status(api_obj)

    def _parse_device_specific_status_d_value(self, s):
        # 781(781/723/1),52(64/50/1),P=10213(10222/10205/1),
        # temp[.1F](day-max/day-min/trend?),humidity[%](day-max/day-min/trend?),P=pressure[Pa](day-max/day-min/trend?),
        temp_str, hum_str, press_str, *_ = s.split(',')
        self.temp_mk_current, self.temp_mk_daily_max, self.temp_mk_daily_min, self.temp_trend = [_temp_to_mk(v) for v in _parse_stats_value(temp_str)]
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)
        self.press_pa_current, self.press_pa_daily_max, self.press_pa_daily_min, self.press_trend = _parse_stats_value(press_str[2:])

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3:.1f}K / {self.hum_current}% / {self.press_pa_current}Pa"
        return s


class RainPointSoilMoistureSensor(HomgarSubDevice):
    MODEL_CODES = [72]
    FRIENDLY_DESC = "Soil Moisture Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.moist_percent_current = None
        self.light_lux_current = None

    def _parse_device_specific_status_d_value(self, s):
        # 766,52,G=31351
        # temp[.1F],soil-moisture[%],G=light[.1lux]
        temp_str, moist_str, light_str = s.split(',')
        self.temp_mk_current = _temp_to_mk(temp_str)
        self.moist_percent_current = int(moist_str)
        self.light_lux_current = int(light_str[2:]) * .1

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3-273.15:.1f}°C / {self.moist_percent_current}% / {self.light_lux_current:.1f}lx"
        return s


class RainPointRainSensor(HomgarSubDevice):
    MODEL_CODES = [87]
    FRIENDLY_DESC = "High Precision Rain Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rainfall_mm_total = None
        self.rainfall_mm_hour = None
        self.rainfall_mm_daily = None
        self.rainfall_mm_total = None

    def _parse_device_specific_status_d_value(self, s):
        # R=270(0/0/270)
        # R=total?[.1mm](hour?[.1mm]/24hours?[.1mm]/7days?[.1mm])
        self.rainfall_mm_total, self.rainfall_mm_hour, self.rainfall_mm_daily, self.rainfall_mm_7days = [.1*v for v in _parse_stats_value(s[2:])]

    def __str__(self):
        s = super().__str__()
        if self.rainfall_mm_total:
            s += f": {self.rainfall_mm_total}mm total / {self.rainfall_mm_hour}mm 1h / {self.rainfall_mm_daily}mm 24h / {self.rainfall_mm_7days}mm 7days"
        return s


class RainPointAirSensor(HomgarSubDevice):
    MODEL_CODES = [262]
    FRIENDLY_DESC = "Outdoor Air Humidity Sensor"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.temp_mk_current = None
        self.temp_mk_daily_max = None
        self.temp_mk_daily_min = None
        self.temp_trend = None
        self.hum_current = None
        self.hum_daily_max = None
        self.hum_daily_min = None
        self.hum_trend = None

    def _parse_device_specific_status_d_value(self, s):
        # 755(1020/588/1),54(91/24/1),
        # temp[.1F](day-max/day-min/trend?),humidity[%](day-max/day-min/trend?)
        temp_str, hum_str, *_ = s.split(',')
        self.temp_mk_current, self.temp_mk_daily_max, self.temp_mk_daily_min, self.temp_trend = [_temp_to_mk(v) for v in _parse_stats_value(temp_str)]
        self.hum_current, self.hum_daily_max, self.hum_daily_min, self.hum_trend = _parse_stats_value(hum_str)

    def __str__(self):
        s = super().__str__()
        if self.temp_mk_current:
            s += f": {self.temp_mk_current*1e-3-273.15:.1f}°C / {self.hum_current}%"
        return s


class RainPoint2ZoneTimer(HomgarSubDevice):
    MODEL_CODES = [261]
    FRIENDLY_DESC = "2-Zone Water Timer"

    def _parse_device_specific_status_d_value(self, s):
        # 0,9,0,0,0,0|0,1291,0,0,0,0
        # left|right, each:
        # ?,last-usage[.1l],?,?,?,?
        pass


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

    def get_device_status(self, hub: HomgarHubDevice):
        data = self._get_json("/app/device/getDeviceStatus", params={"mid": str(hub.mid)})
        id_map = {status_id: device for device in [hub, *hub.subdevices] for status_id in device.get_device_status_ids()}

        for subdevice_status in data['subDeviceStatus']:
            device = id_map.get(subdevice_status['id'])
            if device is not None:
                device.set_device_status(subdevice_status)

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
            api.get_device_status(hub)
            for subdevice in hub.subdevices:
                print(f"    + {subdevice}")


def main():
    argparse = ArgumentParser(description="Demo of HomGar API client library")
    argparse.add_argument("-v", "--verbose", action='store_true', help="Verbose (DEBUG) mode")
    argparse.add_argument("-vv", "--very-verbose", action='store_true', help="Very verbose (TRACE) mode")
    args = argparse.parse_args()

    logging.basicConfig(level=TRACE if args.very_verbose else logging.DEBUG if args.verbose else logging.INFO)

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
