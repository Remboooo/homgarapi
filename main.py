import logging
import pickle
from argparse import ArgumentParser

import yaml

from homgarapi.api import HomgarApi
from homgarapi.logutil import get_logger, TRACE

logging.addLevelName(TRACE, "TRACE")
logger = get_logger(__file__)


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
