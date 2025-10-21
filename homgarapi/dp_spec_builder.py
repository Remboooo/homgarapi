"""Utilities for constructing dynamic datapoint specs from product model metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any

from .constants import PRODUCT_MODEL_SPECS

_DEFAULT_PRODUCT_MODELS_PATH = Path(__file__).parent / "product_models.json"
_DEFAULT_MODEL_SPECS_PATH = Path(__file__).parent / "model_specs.json"

_DYNAMIC_MODEL_SPECS: dict[int, dict[int, dict[str, Any]]] = {}
_MODEL_SPEC_CACHE_STATE: dict[str, bool] = {"loaded": False}
_MODELS_PAYLOAD_CACHE: dict[str, list[Mapping[str, Any]]] = {}


def _ensure_cached_model_specs_loaded() -> None:
    """Populate dynamic specs from the generated cache file if present."""

    if _MODEL_SPEC_CACHE_STATE["loaded"]:
        return
    _MODEL_SPEC_CACHE_STATE["loaded"] = True
    if not _DEFAULT_MODEL_SPECS_PATH.exists():
        return
    try:
        payload = json.loads(_DEFAULT_MODEL_SPECS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(payload, Mapping):
        return

    for model_code_str, dp_map in payload.items():
        try:
            model_code = int(model_code_str)
        except (TypeError, ValueError):
            continue
        if model_code in PRODUCT_MODEL_SPECS:
            continue
        if not isinstance(dp_map, Mapping):
            continue
        converted: dict[int, dict[str, Any]] = {}
        for dp_code_str, spec in dp_map.items():
            try:
                dp_code = int(dp_code_str)
            except (TypeError, ValueError):
                continue
            if isinstance(spec, Mapping):
                converted[dp_code] = dict(spec)
        if converted:
            _DYNAMIC_MODEL_SPECS[model_code] = converted


def _load_product_models_payload(path: Path) -> list[Mapping[str, Any]]:
    """Return the list of model definitions from a product models JSON file."""

    source_key = str(path.resolve())
    if source_key in _MODELS_PAYLOAD_CACHE:
        return _MODELS_PAYLOAD_CACHE[source_key]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    models_candidate: Any = []
    if isinstance(raw, Mapping):
        if isinstance(raw.get("models"), list):
            models_candidate = raw["models"]
        else:
            data = raw.get("data")
            if isinstance(data, Mapping) and isinstance(data.get("models"), list):
                models_candidate = data["models"]

    if isinstance(models_candidate, list):
        models: list[Mapping[str, Any]] = [
            entry for entry in models_candidate if isinstance(entry, Mapping)
        ]
    else:
        models = []

    _MODELS_PAYLOAD_CACHE[source_key] = models
    return models


def load_product_models_payload(path: Path | None = None) -> list[Mapping[str, Any]]:
    """Load the raw product models payload from disk."""

    target = path or _DEFAULT_PRODUCT_MODELS_PATH
    if not target.exists():
        return []
    return list(_load_product_models_payload(target))


def extract_model_specs(
    models: Iterable[Mapping[str, Any]],
    model_codes: Iterable[int],
) -> dict[int, dict[int, dict[str, Any]]]:
    """Build a trimmed datapoint spec mapping for the requested model codes."""

    requested = {int(code) for code in model_codes}
    include_all = not requested
    result: dict[int, dict[int, dict[str, Any]]] = {}

    for model in models:
        model_code_raw = model.get("modelCode")
        if isinstance(model_code_raw, int):
            model_code = model_code_raw
        elif isinstance(model_code_raw, str) and model_code_raw.isdigit():
            model_code = int(model_code_raw)
        else:
            continue
        if not include_all and model_code not in requested:
            continue
        dp_entries = model.get("dp")
        if not isinstance(dp_entries, list):
            continue
        specs_map: dict[int, dict[str, Any]] = {}
        for dp in dp_entries:
            if not isinstance(dp, Mapping):
                continue
            dp_code_raw = dp.get("dpCode")
            if isinstance(dp_code_raw, int):
                dp_code = dp_code_raw
            elif isinstance(dp_code_raw, str) and dp_code_raw.isdigit():
                dp_code = int(dp_code_raw)
            else:
                continue
            raw_specs = dp.get("specs")
            specs_mapping = raw_specs if isinstance(raw_specs, Mapping) else {}
            specs_map[dp_code] = {
                "identity": dp.get("identity"),
                "dataType": specs_mapping.get("dataType"),
                "dataTypeSub": specs_mapping.get("dataTypeSub"),
                "length": specs_mapping.get("length"),
                "decimal": specs_mapping.get("decimal"),
            }
        result[model_code] = specs_map
    return result


def ensure_model_specs(
    model_codes: Iterable[int],
    *,
    source_path: Path | None = None,
) -> dict[int, dict[int, dict[str, Any]]]:
    """Ensure datapoint specs are available for the requested model codes."""

    codes = [int(code) for code in model_codes]
    _ensure_cached_model_specs_loaded()

    resolved: dict[int, dict[int, dict[str, Any]]] = {}
    missing: set[int] = set()

    for code in codes:
        if code in PRODUCT_MODEL_SPECS:
            resolved[code] = {
                int(dp_code): dict(spec)
                for dp_code, spec in PRODUCT_MODEL_SPECS[code].items()
            }
        elif code in _DYNAMIC_MODEL_SPECS:
            resolved[code] = _DYNAMIC_MODEL_SPECS[code]
        else:
            missing.add(code)

    if not missing:
        return resolved

    path = source_path or _DEFAULT_PRODUCT_MODELS_PATH
    if not path.exists():
        return resolved

    models = _load_product_models_payload(path)
    extracted = extract_model_specs(models, missing)

    for code in missing:
        specs = extracted.get(code, {})
        if code not in PRODUCT_MODEL_SPECS:
            _DYNAMIC_MODEL_SPECS[code] = specs
        resolved[code] = specs

    return resolved


def get_model_dp_specs(
    model_code: int,
    *,
    source_path: Path | None = None,
) -> dict[int, dict[str, Any]]:
    """Return datapoint specifications for a single model code."""

    specs = ensure_model_specs([model_code], source_path=source_path)
    return specs.get(model_code, {})


def save_model_specs(
    specs: Mapping[int, Mapping[int, Mapping[str, Any]]],
    path: Path | None = None,
    *,
    update_cache: bool = True,
) -> None:
    """Persist a trimmed spec cache to disk."""

    target = path or _DEFAULT_MODEL_SPECS_PATH
    serialisable = {
        str(model_code): {str(dp_code): dict(dp_spec) for dp_code, dp_spec in dp_map.items()}
        for model_code, dp_map in specs.items()
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(serialisable, indent=2, sort_keys=True), encoding="utf-8")

    if update_cache and (path is None or target == _DEFAULT_MODEL_SPECS_PATH):
        _ensure_cached_model_specs_loaded()
        for model_code, dp_map in specs.items():
            if model_code in PRODUCT_MODEL_SPECS:
                continue
            converted_specs: dict[int, dict[str, Any]] = {}
            for dp_code, spec in dp_map.items():
                try:
                    dp_code_int = int(dp_code)
                except (TypeError, ValueError):
                    continue
                converted_specs[dp_code_int] = dict(spec)
            _DYNAMIC_MODEL_SPECS[int(model_code)] = converted_specs
