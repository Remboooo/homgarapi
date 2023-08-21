import binascii
import datetime
import hashlib
import os
import pickle
from pathlib import Path

import requests
import logging

import yaml

TRACE = logging.DEBUG-1
logging.addLevelName(TRACE, "TRACE")

logger = logging.getLogger(Path(__file__).stem)


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

    def _get_json(self, path, **kwargs):
        return self._request("GET", self.base + path, **kwargs).json()

    def _post_json(self, path, body, **kwargs):
        return self._request("POST", self.base + path, json=body, **kwargs).json()

    def login(self, email, password):
        response = self._post_json("/auth/basic/app/login", {
            "areaCode": "31",
            "phoneOrEmail": email,
            "password": hashlib.md5(password.encode('utf-8')).hexdigest(),
            "deviceId": binascii.b2a_hex(os.urandom(16)).decode('utf-8')
        }, with_auth=False)
        data = response.get('data', {})
        self.cache['token'] = data.get('token')
        self.cache['token_expires'] = datetime.datetime.utcnow() + datetime.timedelta(seconds=int(data.get('tokenExpired')))
        self.cache['refresh_token'] = data.get('refreshToken')

    def get_homes(self):
        return self._get_json("/app/member/appHome/list")['data']

    def get_devices_for_home(self, hid):
        return self._get_json("/app/device/getDeviceByHid", params={"hid": str(hid)})['data']

    def get_device_status(self, mid):
        return self._get_json("/app/device/getDeviceStatus", params={"mid": str(mid)})['data']


def demo(api: HomgarApi, config):
    api.login(config['email'], config['password'])
    hid = api.get_homes()[0]['hid']
    import pprint
    devices = api.get_devices_for_home(hid)
    pprint.pprint(devices)
    mid = devices[0]['mid']
    status = api.get_device_status(mid)
    pprint.pprint(status)

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