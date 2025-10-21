"""Command line entry point for the HomGar API demo."""

from argparse import ArgumentParser
from collections.abc import Mapping, MutableMapping
import json
import logging
from pathlib import Path
import pickle
from typing import Any

from platformdirs import user_cache_dir
import yaml

from .api import HomgarApi
from .devices import MODEL_CODE_MAPPING
from .dp_spec_builder import (
    extract_model_specs,
    load_product_models_payload,
    save_model_specs,
)
from .logutil import TRACE, get_logger

logging.addLevelName(TRACE, "TRACE")
logger = get_logger(__file__)


def _extract_models_from_payload(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the list of models contained in a product models payload."""

    models = payload.get("models")
    if isinstance(models, list):
        return models
    data_section = payload.get("data")
    if isinstance(data_section, Mapping):
        nested_models = data_section.get("models")
        if isinstance(nested_models, list):
            return nested_models
    return []


def _generate_model_specs_if_requested(
    api: HomgarApi,
    *,
    output_path: Path,
    model_codes: list[int] | None,
    source_path: Path | None,
    product_models_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Generate a trimmed datapoint cache when triggered by the CLI."""

    codes = sorted({int(code) for code in model_codes}) if model_codes else sorted(MODEL_CODE_MAPPING.keys())

    models_payload: list[Mapping[str, Any]] = []
    if source_path is not None:
        models_payload = load_product_models_payload(source_path)
        if not models_payload:
            logger.error(
                "No product models were loaded from %s; skipping model spec generation",
                source_path,
            )
            return product_models_payload
    else:
        if product_models_payload is None:
            product_models_payload = api.get_product_models()
        models_payload = _extract_models_from_payload(product_models_payload)
        if not models_payload:
            logger.warning(
                "Product models payload did not contain model entries; unable to generate specs",
            )
            return product_models_payload

    trimmed_specs = extract_model_specs(models_payload, codes)
    if not trimmed_specs:
        logger.warning(
            "No datapoint specifications generated for model codes: %s",
            ", ".join(str(code) for code in codes),
        )
        return product_models_payload

    save_model_specs(trimmed_specs, output_path)
    logger.info(
        "Wrote model specs for %d model codes to %s",
        len(trimmed_specs),
        output_path,
    )
    return product_models_payload


def demo(api: HomgarApi, config: Mapping[str, str]) -> None:
    """Run a simple demonstration against the HomGar API.

    :param api: Instantiated `HomgarApi` client.
    :param config: Mapping containing at least ``email`` and ``password`` keys.
    """
    api.ensure_logged_in(config["email"], config["password"])
    for home in api.get_homes():
        logger.info("Home (%s) %s", home.hid, home.name)

        for hub in api.get_devices_for_hid(home.hid):
            logger.info("  Hub %s", hub)
            api.get_device_status(hub)
            for subdevice in hub.subdevices:
                description = str(subdevice)
                updated = getattr(subdevice, "updated_in_last_poll", False)
                if not updated:
                    description = f"{description} [offline]"
                logger.info("    Subdevice %s", description)


def main() -> None:
    """Parse CLI arguments and run the demo.

    :raises TypeError: If the configuration file does not contain a mapping.
    """
    argparse = ArgumentParser(
        description="Demo of HomGar API client library",
        prog="homgarapi",
    )
    argparse.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose (DEBUG) mode"
    )
    argparse.add_argument(
        "-vv", "--very-verbose", action="store_true", help="Very verbose (TRACE) mode"
    )
    argparse.add_argument(
        "-c",
        "--cache",
        type=Path,
        help="Cache file to use. Should be writable, will be created if it does not exist.",
    )
    argparse.add_argument(
        "--email",
        help="HomGar account email address (overrides value in configuration file)",
    )
    argparse.add_argument(
        "--password",
        help="HomGar account password (overrides value in configuration file)",
    )
    argparse.add_argument(
        "--unknown-output",
        type=Path,
        help="Optional path to write unsupported device report (YAML)",
    )
    argparse.add_argument(
        "--dictionary-output",
        nargs="?",
        type=Path,
        const=Path("dictionary.json"),
        help=(
            "Write the platform dictionary response to disk. Supply an optional path, "
            "or omit to use './dictionary.json'."
        ),
    )
    argparse.add_argument(
        "--product-models-output",
        nargs="?",
        type=Path,
        const=Path("product_models.json"),
        help=(
            "Write the product models response to disk. Supply an optional path, "
            "or omit to use './product_models.json'."
        ),
    )
    argparse.add_argument(
        "--model-specs-output",
        nargs="?",
        type=Path,
        const=Path("model_specs.json"),
        help=(
            "Generate trimmed datapoint specifications for supported model codes. "
            "Supply an optional path, or omit to use './model_specs.json'."
        ),
    )
    argparse.add_argument(
        "--model-specs-code",
        action="append",
        type=int,
        dest="model_specs_codes",
        help="Model code to include when generating model specs. Can be provided multiple times.",
    )
    argparse.add_argument(
        "--model-specs-source",
        type=Path,
        help=(
            "Optional path to an existing product_models.json file to use when "
            "generating model specs. When omitted, data is fetched from the API."
        ),
    )
    argparse.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Optional YAML file containing authentication details",
    )
    args = argparse.parse_args()

    logging.basicConfig(
        level=TRACE
        if args.very_verbose
        else logging.DEBUG
        if args.verbose
        else logging.INFO
    )

    cache_file: Path = args.cache or (
        Path(user_cache_dir("homgarapi", ensure_exists=True)) / "cache.pickle"
    )
    config_file: Path | None = args.config

    cache: MutableMapping[str, Any] = {}
    try:
        with cache_file.open("rb") as cache_handle:
            cache = pickle.load(cache_handle)
    except OSError:
        logger.info("Could not load cache, starting fresh")

    config_mapping: dict[str, str] = {}
    if config_file is not None:
        with config_file.open("rb") as config_handle:
            try:
                config = yaml.safe_load(config_handle)
            except yaml.YAMLError as exc:
                raise ValueError(
                    f"Failed parsing configuration file {config_file}"
                ) from exc
        if not isinstance(config, Mapping):
            msg = f"Configuration file {config_file} must contain a mapping"
            raise TypeError(msg)
        config_mapping.update({str(key): str(value) for key, value in config.items()})

    if args.email is not None:
        config_mapping["email"] = args.email
    if args.password is not None:
        config_mapping["password"] = args.password

    required_keys = {"email", "password"}
    missing = required_keys - set(config_mapping)
    if missing:
        msg = (
            "Authentication details must include both email and password. "
            f"Missing: {', '.join(sorted(missing))}"
        )
        raise ValueError(msg)

    try:
        api = HomgarApi(cache)
        product_models_payload: Mapping[str, Any] | None = None

        demo(api, config_mapping)

        def _write_json(output_path: Path, payload: Any, description: str) -> None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as output_handle:
                json.dump(payload, output_handle, indent=2, sort_keys=True)
            logger.info("Wrote %s to %s", description, output_path)

        if args.dictionary_output:
            dictionary_payload = api.get_dictionary()
            _write_json(args.dictionary_output, dictionary_payload, "dictionary data")

        if args.product_models_output:
            product_models_payload = api.get_product_models()
            _write_json(
                args.product_models_output,
                product_models_payload,
                "product models data",
            )

        if args.model_specs_output:
            product_models_payload = _generate_model_specs_if_requested(
                api,
                output_path=args.model_specs_output,
                model_codes=args.model_specs_codes,
                source_path=args.model_specs_source,
                product_models_payload=product_models_payload,
            )

        unknown_devices_raw = api.get_unknown_devices()
        if unknown_devices_raw:
            unknown_devices: list[dict[str, Any]] = []
            for device in unknown_devices_raw:
                enriched = dict(device)
                if status_values := enriched.pop("status_values", None):
                    enriched["status_payloads"] = status_values
                unknown_devices.append(enriched)
            output_path = args.unknown_output or cache_file.with_name(
                "unknown_devices.yaml"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as output_handle:
                yaml.safe_dump(
                    {"unknown_devices": unknown_devices},
                    output_handle,
                    sort_keys=False,
                    allow_unicode=True,
                )
            logger.warning(
                "Unsupported devices detected. Details written to %s. "
                "Please share this file when requesting support for new hardware.",
                output_path,
            )
    finally:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as cache_write_handle:
            pickle.dump(cache, cache_write_handle)


if __name__ == "__main__":
    main()
