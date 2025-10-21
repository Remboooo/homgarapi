"""Static datapoint definitions for supported HomGar devices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Minimal datapoint specifications required for supported devices.
# Keys: model code -> datapoint code -> specification details used by the decoder.
PRODUCT_MODEL_SPECS: Mapping[int, Mapping[int, Mapping[str, Any]]] = {
    72: {
        2: {"identity": "S_SMART_VOICE", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        9: {"identity": "STA_TEM", "dataType": 1, "dataTypeSub": 6, "length": 2, "decimal": 1},
        10: {"identity": "STA_RH", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": 0},
        25: {"identity": "STA_ILLUMINANCE", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": 1},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        32: {"identity": "STA_RSSI", "dataType": 1, "dataTypeSub": 2, "length": 1, "decimal": None},
    },
    87: {
        13: {"identity": "STA_TOTAL_RAIN", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        32: {"identity": "STA_RSSI", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        43: {"identity": "STA_HOUR_RAIN", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": 1},
        44: {"identity": "STA_DAY_RAIN", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": 1},
        45: {"identity": "STA_7DAY_RAIN", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": 1},
    },
    89: {
        2: {"identity": "S_SMART_VOICE", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        9: {"identity": "STA_TEM", "dataType": 1, "dataTypeSub": 6, "length": 2, "decimal": 1},
        10: {"identity": "STA_RH", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": 0},
        22: {"identity": "STA_TREND", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        27: {"identity": "STA_CO2", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        33: {"identity": "MAX_TEM", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        34: {"identity": "MAX_RH", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": None},
        47: {"identity": "MAX_CO2", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
    },
    261: {
        1: {"identity": "CTL_WATER", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": None},
        2: {"identity": "STA_ALARM", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        11: {"identity": "CTL_SET_DELAY", "dataType": 0, "dataTypeSub": 0, "length": None, "decimal": None},
        13: {"identity": "ATTR_SHARE_FLOW", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        15: {"identity": "STA_LASTUSAGE", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        19: {"identity": "STA_DURATION", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        21: {"identity": "STA_EVTIME", "dataType": 5, "dataTypeSub": 10, "length": 4, "decimal": None},
        30: {"identity": "STA_WKSTATE", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        32: {"identity": "STA_RSSI", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": None},
        51: {"identity": "STA_RSSI2", "dataType": 1, "dataTypeSub": 5, "length": 1, "decimal": None},
        52: {"identity": "STA_EVTIME2", "dataType": 5, "dataTypeSub": 10, "length": 4, "decimal": None},
    },
    262: {
        2: {"identity": "S_SMART_VOICE", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        9: {"identity": "STA_TEM", "dataType": 1, "dataTypeSub": 6, "length": 2, "decimal": 1},
        10: {"identity": "STA_RH", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": 0},
        22: {"identity": "STA_TREND", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        33: {"identity": "MAX_TEM", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        34: {"identity": "MAX_RH", "dataType": 1, "dataTypeSub": 2, "length": 2, "decimal": None},
    },
    268: {
        9: {"identity": "STA_TEM", "dataType": 1, "dataTypeSub": 6, "length": 2, "decimal": 1},
        22: {"identity": "STA_TREND", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        33: {"identity": "MAX_TEM", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
    },
    277: {
        32: {"identity": "STA_RSSI", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        31: {"identity": "STA_BAT", "dataType": 1, "dataTypeSub": 1, "length": 1, "decimal": None},
        14: {"identity": "STA_VFLOW", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        21: {"identity": "STA_EVTIME", "dataType": 5, "dataTypeSub": 10, "length": 4, "decimal": None},
        46: {"identity": "STA_CUR_FLOW", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": 1},
        19: {"identity": "STA_DURATION", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        15: {"identity": "STA_LASTUSAGE", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": 1},
        49: {"identity": "STA_LAST_DURATION", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
        26: {"identity": "STA_TOTAL_TODAY", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": 1},
        20: {"identity": "STA_WATER_TOTAL", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": 1},
        50: {"identity": "STA_OTHER_TOTAL", "dataType": 1, "dataTypeSub": 4, "length": 4, "decimal": None},
    },
    264: {},
    273: {},
    289: {},
}


def build_model_list() -> list[Mapping[str, Any]]:
    """Return a list of synthetic model entries compatible with the API metadata schema."""

    models: list[Mapping[str, Any]] = []
    for model_code, dps in PRODUCT_MODEL_SPECS.items():
        models.append(
            {
                "modelCode": model_code,
                "dp": [
                    {"dpCode": dp_code, "identity": spec["identity"], "specs": dict(spec)}
                    for dp_code, spec in sorted(dps.items())
                ],
            }
        )
    return models
