import logging
import pickle
from argparse import ArgumentParser
from pathlib import Path
from platformdirs import user_cache_dir

import yaml

from homgarapi.api import HomgarApi
from homgarapi.logutil import get_logger, TRACE

logging.addLevelName(TRACE, "TRACE")
logger = get_logger(__file__)


def demo(api: HomgarApi, config):
    api.ensure_logged_in(config['email'], config['password'])
    for home in api.get_homes():
        print(f"({home.hid}) {home.name}:")

        for hub in api.get_devices_for_hid(home.hid):
            print(f"  - {hub}")
            api.get_device_status(hub)
            for subdevice in hub.subdevices:
                print(f"    + {subdevice}")


def main():
    argparse = ArgumentParser(
        description="Demo of HomGar API client library",
        prog="homgarapi"
    )
    argparse.add_argument("-v", "--verbose", action='store_true', help="Verbose (DEBUG) mode")
    argparse.add_argument("-vv", "--very-verbose", action='store_true', help="Very verbose (TRACE) mode")
    argparse.add_argument("-c", "--cache", type=Path, help="Cache file to use. Should be writable, will be created if it does not exist.")
    argparse.add_argument("config", type=Path, help="Yaml file containing email and password to use to log in")
    args = argparse.parse_args()

    logging.basicConfig(level=TRACE if args.very_verbose else logging.DEBUG if args.verbose else logging.INFO)

    cache_file = args.cache or (Path(user_cache_dir("homgarapi", ensure_exists=True)) / "cache.pickle")
    config_file = args.config

    cache = {}
    try:
        with open(cache_file, 'rb') as f:
            cache = pickle.load(f)
    except OSError as e:
        logger.info("Could not load cache, starting fresh")

    with open(config_file, 'rb') as f:
        config = yaml.unsafe_load(f)

    try:
        api = HomgarApi(cache)
        demo(api, config)
    finally:
        with open(cache_file, 'wb') as f:
            pickle.dump(cache, f)


if __name__ == '__main__':
    main()
