"""Audit-only technical-dependency contract for model TA/OHLC features.

This module is deliberately detached from Redis, mutable ``ta_closed``/
``ta_full`` payloads, trainer admission, feature publication, and execution.
It freezes the current model-facing TA inventory, declared TA-Lib lookbacks,
strict latest-output semantics, and the deployed TA-Lib environment identity.

The row minima are mathematical implementation dependencies, not market,
liquidity, risk, leverage, or strategy thresholds.  Satisfying this contract
does not prove point-in-time source provenance and grants no downstream action.
The existing 71-row ``trainer_core_ta_minimum_coverage_v1`` contract remains a
separate invariant for native core transforms; this contract does not replace
or modify it.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, NoReturn

MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION: Final = (
    "trainer_model_ta_derivation_minimum_coverage_v1"
)
MODEL_TA_MULTI_TIMEFRAME_DEPENDENCY_VERSION: Final = "trainer_ta_multi_timeframe_derivation_v1"
DEPENDENCY_CLASSIFICATION: Final = "MODEL_TA_DERIVATION_TECHNICAL_DEPENDENCY_MINIMUM"
DEPENDENCY_SCOPE: Final = "MODEL_TA_OHLC_ABI_LEAVES_CURRENT_TIMEFRAME_AND_TRUE_1H"

MODEL_FEATURE_ABI_SCHEMA_VERSION: Final = "ordered_feature_tensor_abi_v3"
MODEL_FEATURE_ABI_SHA256: Final = "e81b6dd95bfba930d67e694941f21a6d4ab5432142c25595848148c8bb42ddf9"
TA_OHLC_ABI_LEAF_MANIFEST_VERSION: Final = "trainer_model_ta_ohlcv_abi_leaves_v1"
TA_FULL_FEATURE_MAP_MANIFEST_VERSION: Final = "trainer_ta_full_feature_map_v1"
TA_FULL_FIELD_MANIFEST_VERSION: Final = "trainer_current_timeframe_ta_full_fields_v1"
LOOKBACK_MANIFEST_VERSION: Final = "trainer_model_ta_declared_lookbacks_v1"
TALIB_ENVIRONMENT_IDENTITY_VERSION: Final = "trainer_deployed_talib_environment_v1"
TALIB_FUNCTION_CATALOG_VERSION: Final = "talib_abstract_function_catalog_v1"

EXISTING_CORE_CONTRACT_VERSION: Final = "trainer_core_ta_minimum_coverage_v1"
EXISTING_CORE_MINIMUM_SOURCE_ROWS: Final = 71
CURRENT_TIMEFRAME_TA_FULL_MINIMUM_ROWS: Final = 89
CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS: Final = 89
TRUE_1H_TA_MINIMUM_ROWS: Final = 34

CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256: Final = (
    "69b0a9f7552cdb886ac0d071bc85e9f374ebe82fbd4363f74aca998bdde1f948"
)
CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256: Final = (
    "050b791b325411d99b1d60d3b31514c88d965ed4327e6dfe88293a5609e97d41"
)
TA_OHLC_ABI_LEAVES_SHA256: Final = (
    "6017414a3db0567cb46e593a4fbd166501520b0ef2fa49a486f61866dad8cac7"
)
LOOKBACK_MANIFEST_SHA256: Final = "81b12ddc44df88ee8daa2f81c94154a041952f1f62db41a9ff76bdef0da62359"
DEPLOYED_TALIB_ENVIRONMENT_SHA256: Final = (
    "caa8f6484cfb000afe0e6981e73e9f54a6b1519580cc4469a3d5e87389a931bc"
)
MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256: Final = (
    "056d7a74f598539d1833118bd629859ba5ab2d5d3220c40664b12a3402a7ea0f"
)

STRICT_LATEST_OUTPUT_SEMANTICS: Final = (
    "OUTPUT_MUST_BE_ONE_DIMENSIONAL_WITH_LENGTH_EQUAL_TO_EXACT_SOURCE_ROW_COUNT;"
    "ONLY_OUTPUT_INDEX_MINUS_ONE_IS_ELIGIBLE;LATEST_VALUE_MUST_BE_FINITE;"
    "NEVER_SCAN_BACKWARD_TO_AN_OLDER_FINITE_VALUE;NEVER_ZERO_FILL_OR_CARRY_FORWARD"
)

CURRENT_TIMEFRAME_COMPACT_TA_FIELDS: Final = (
    "RSI",
    "MACD",
    "MACD_signal",
    "MACD_hist",
    "ATR",
    "EMA_12",
    "EMA_26",
    "bollinger_upper",
    "bollinger_middle",
    "bollinger_lower",
    "bollinger_width_pct",
)

CURRENT_TIMEFRAME_NATIVE_CORE_FIELDS: Final = (
    "ret_pct",
    "log_return",
    "range_pct",
    "body_pct",
    "true_range_pct",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_width_pct",
    "htf_ret_pct",
    "htf_rsi_14",
)

CURRENT_TIMEFRAME_TA_FULL_FIELDS: Final = (
    "taf_atr_14",
    "taf_bb_width_pct",
    "taf_ema_12",
    "taf_ema_20",
    "taf_ema_21",
    "taf_ema_26",
    "taf_ema_50",
    "taf_ema_9",
    "taf_macd",
    "taf_macd_hist",
    "taf_macd_signal",
    "taf_rsi_14",
    "taf_sma_12",
    "taf_sma_20",
    "taf_sma_21",
    "taf_sma_26",
    "taf_sma_50",
    "taf_sma_9",
    "taf_ta_ad",
    "taf_ta_adosc",
    "taf_ta_adx",
    "taf_ta_adxr",
    "taf_ta_apo",
    "taf_ta_aroonosc",
    "taf_ta_aroon_aroondown",
    "taf_ta_aroon_aroonup",
    "taf_ta_avgprice",
    "taf_ta_bbands_20_lower",
    "taf_ta_bbands_20_upper",
    "taf_ta_bbands_lowerband",
    "taf_ta_bbands_middleband",
    "taf_ta_bbands_upperband",
    "taf_ta_beta",
    "taf_ta_bop",
    "taf_ta_cci",
    "taf_ta_cdl2crows_integer",
    "taf_ta_cdl3blackcrows_integer",
    "taf_ta_cdl3inside_integer",
    "taf_ta_cdl3linestrike_integer",
    "taf_ta_cdl3outside_integer",
    "taf_ta_cdl3starsinsouth_integer",
    "taf_ta_cdl3whitesoldiers_integer",
    "taf_ta_cdlabandonedbaby_integer",
    "taf_ta_cdladvanceblock_integer",
    "taf_ta_cdlbelthold_integer",
    "taf_ta_cdlbreakaway_integer",
    "taf_ta_cdlclosingmarubozu_integer",
    "taf_ta_cdlconcealbabyswall_integer",
    "taf_ta_cdlcounterattack_integer",
    "taf_ta_cdldarkcloudcover_integer",
    "taf_ta_cdldojistar_integer",
    "taf_ta_cdldoji_integer",
    "taf_ta_cdldragonflydoji_integer",
    "taf_ta_cdlengulfing_integer",
    "taf_ta_cdleveningdojistar_integer",
    "taf_ta_cdleveningstar_integer",
    "taf_ta_cdlgapsidesidewhite_integer",
    "taf_ta_cdlhammer_integer",
    "taf_ta_cdlhangingman_integer",
    "taf_ta_cdlharamicross_integer",
    "taf_ta_cdlhighwave_integer",
    "taf_ta_cdlhikkakemod_integer",
    "taf_ta_cdlhikkake_integer",
    "taf_ta_cdlhomingpigeon_integer",
    "taf_ta_cdlidentical3crows_integer",
    "taf_ta_cdlinneck_integer",
    "taf_ta_cdlinvertedhammer_integer",
    "taf_ta_cdlkickingbylength_integer",
    "taf_ta_cdlkicking_integer",
    "taf_ta_cdlladderbottom_integer",
    "taf_ta_cdllongline_integer",
    "taf_ta_cdlmarubozu_integer",
    "taf_ta_cdlmathold_integer",
    "taf_ta_cdlmorningdojistar_integer",
    "taf_ta_cdlmorningstar_integer",
    "taf_ta_cdlonneck_integer",
    "taf_ta_cdlpiercing_integer",
    "taf_ta_cdlrickshawman_integer",
    "taf_ta_cdlrisefall3methods_integer",
    "taf_ta_cdlseparatinglines_integer",
    "taf_ta_cdlshootingstar_integer",
    "taf_ta_cdlshortline_integer",
    "taf_ta_cdlspinningtop_integer",
    "taf_ta_cdlstalledpattern_integer",
    "taf_ta_cdlsticksandwich_integer",
    "taf_ta_cdltakuri_integer",
    "taf_ta_cdltasukigap_integer",
    "taf_ta_cdlthrusting_integer",
    "taf_ta_cdltristar_integer",
    "taf_ta_cdlunique3river_integer",
    "taf_ta_cdlupsidegap2crows_integer",
    "taf_ta_cdlxsidegap3methods_integer",
    "taf_ta_cmo",
    "taf_ta_correl",
    "taf_ta_dema",
    "taf_ta_dx",
    "taf_ta_ema",
    "taf_ta_ht_dcperiod",
    "taf_ta_ht_dcphase",
    "taf_ta_ht_phasor_inphase",
    "taf_ta_ht_phasor_quadrature",
    "taf_ta_ht_sine_leadsine",
    "taf_ta_ht_sine_sine",
    "taf_ta_ht_trendline",
    "taf_ta_ht_trendmode_integer",
    "taf_ta_kama",
    "taf_ta_linearreg",
    "taf_ta_linearreg_angle",
    "taf_ta_linearreg_intercept",
    "taf_ta_linearreg_slope",
    "taf_ta_ma",
    "taf_ta_macdext_macdhist",
    "taf_ta_macdext_macdsignal",
    "taf_ta_macdfix_macd",
    "taf_ta_macdfix_macdhist",
    "taf_ta_macdfix_macdsignal",
    "taf_ta_mama_fama",
    "taf_ta_mama_mama",
    "taf_ta_mavp",
    "taf_ta_medprice",
    "taf_ta_mfi",
    "taf_ta_midpoint",
    "taf_ta_midprice",
    "taf_ta_minus_di",
    "taf_ta_minus_dm",
    "taf_ta_mom",
    "taf_ta_natr",
    "taf_ta_obv",
    "taf_ta_plus_di",
    "taf_ta_plus_dm",
    "taf_ta_ppo",
    "taf_ta_roc",
    "taf_ta_rocp",
    "taf_ta_rocr",
    "taf_ta_rocr100",
    "taf_ta_sar",
    "taf_ta_sarext",
    "taf_ta_stddev",
    "taf_ta_stochf_fastd",
    "taf_ta_stochf_fastk",
    "taf_ta_stochrsi_fastd",
    "taf_ta_stochrsi_fastk",
    "taf_ta_stoch_slowd",
    "taf_ta_t3",
    "taf_ta_tema",
    "taf_ta_trange",
    "taf_ta_trima",
    "taf_ta_trix",
    "taf_ta_tsf",
    "taf_ta_typprice",
    "taf_ta_ultosc",
    "taf_ta_var",
    "taf_ta_wclprice",
    "taf_ta_willr",
    "taf_ta_wma",
)

TRUE_1H_TA_FIELDS: Final = (
    "htf1h_taf_rsi",
    "htf1h_taf_adx",
    "htf1h_taf_macd_hist",
    "htf1h_taf_atr",
    "htf1h_taf_mfi",
    "htf1h_taf_willr",
    "htf1h_taf_natr",
    "htf1h_taf_cci",
)

# TA-Lib's declared lookback plus one source row.  Candlestick functions may
# emit numeric zero before their declared lookback, but that is not treated as
# proof that their dependency history is complete.
_CURRENT_TF_LOOKBACK_GROUPS: Final = (
    (
        1,
        (
            "taf_ta_ad",
            "taf_ta_avgprice",
            "taf_ta_bop",
            "taf_ta_medprice",
            "taf_ta_obv",
            "taf_ta_typprice",
            "taf_ta_wclprice",
        ),
    ),
    (2, ("taf_ta_sar", "taf_ta_sarext", "taf_ta_trange")),
    (3, ("taf_ta_cdlengulfing_integer", "taf_ta_cdlxsidegap3methods_integer")),
    (4, ("taf_ta_cdl3outside_integer",)),
    (
        5,
        (
            "taf_ta_bbands_lowerband",
            "taf_ta_bbands_middleband",
            "taf_ta_bbands_upperband",
            "taf_ta_stddev",
            "taf_ta_var",
        ),
    ),
    (6, ("taf_ta_beta", "taf_ta_cdlhikkake_integer")),
    (7, ("taf_ta_stochf_fastd", "taf_ta_stochf_fastk")),
    (
        8,
        (
            "taf_ta_cdlgapsidesidewhite_integer",
            "taf_ta_cdlsticksandwich_integer",
            "taf_ta_cdltasukigap_integer",
        ),
    ),
    (9, ("taf_ema_9", "taf_sma_9", "taf_ta_cdl3linestrike_integer", "taf_ta_stoch_slowd")),
    (10, ("taf_ta_adosc",)),
    (
        11,
        (
            "taf_ta_cdlbelthold_integer",
            "taf_ta_cdlclosingmarubozu_integer",
            "taf_ta_cdldoji_integer",
            "taf_ta_cdldragonflydoji_integer",
            "taf_ta_cdlhighwave_integer",
            "taf_ta_cdlhikkakemod_integer",
            "taf_ta_cdllongline_integer",
            "taf_ta_cdlmarubozu_integer",
            "taf_ta_cdlrickshawman_integer",
            "taf_ta_cdlshortline_integer",
            "taf_ta_cdlspinningtop_integer",
            "taf_ta_cdltakuri_integer",
            "taf_ta_mom",
            "taf_ta_roc",
            "taf_ta_rocp",
            "taf_ta_rocr",
            "taf_ta_rocr100",
        ),
    ),
    (
        12,
        (
            "taf_ema_12",
            "taf_sma_12",
            "taf_ta_cdlcounterattack_integer",
            "taf_ta_cdldarkcloudcover_integer",
            "taf_ta_cdldojistar_integer",
            "taf_ta_cdlhammer_integer",
            "taf_ta_cdlhangingman_integer",
            "taf_ta_cdlharamicross_integer",
            "taf_ta_cdlhomingpigeon_integer",
            "taf_ta_cdlinneck_integer",
            "taf_ta_cdlinvertedhammer_integer",
            "taf_ta_cdlkickingbylength_integer",
            "taf_ta_cdlkicking_integer",
            "taf_ta_cdlonneck_integer",
            "taf_ta_cdlpiercing_integer",
            "taf_ta_cdlseparatinglines_integer",
            "taf_ta_cdlshootingstar_integer",
            "taf_ta_cdlthrusting_integer",
        ),
    ),
    (
        13,
        (
            "taf_ta_cdl2crows_integer",
            "taf_ta_cdl3inside_integer",
            "taf_ta_cdl3starsinsouth_integer",
            "taf_ta_cdl3whitesoldiers_integer",
            "taf_ta_cdlabandonedbaby_integer",
            "taf_ta_cdladvanceblock_integer",
            "taf_ta_cdleveningdojistar_integer",
            "taf_ta_cdleveningstar_integer",
            "taf_ta_cdlidentical3crows_integer",
            "taf_ta_cdlmorningdojistar_integer",
            "taf_ta_cdlmorningstar_integer",
            "taf_ta_cdlstalledpattern_integer",
            "taf_ta_cdltristar_integer",
            "taf_ta_cdlunique3river_integer",
            "taf_ta_cdlupsidegap2crows_integer",
        ),
    ),
    (
        14,
        (
            "taf_ta_cci",
            "taf_ta_cdl3blackcrows_integer",
            "taf_ta_cdlconcealbabyswall_integer",
            "taf_ta_linearreg",
            "taf_ta_linearreg_angle",
            "taf_ta_linearreg_intercept",
            "taf_ta_linearreg_slope",
            "taf_ta_midpoint",
            "taf_ta_midprice",
            "taf_ta_minus_dm",
            "taf_ta_plus_dm",
            "taf_ta_tsf",
            "taf_ta_willr",
        ),
    ),
    (
        15,
        (
            "taf_atr_14",
            "taf_rsi_14",
            "taf_ta_aroonosc",
            "taf_ta_aroon_aroondown",
            "taf_ta_aroon_aroonup",
            "taf_ta_cdlbreakaway_integer",
            "taf_ta_cdlladderbottom_integer",
            "taf_ta_cdlmathold_integer",
            "taf_ta_cdlrisefall3methods_integer",
            "taf_ta_cmo",
            "taf_ta_dx",
            "taf_ta_mfi",
            "taf_ta_minus_di",
            "taf_ta_natr",
            "taf_ta_plus_di",
        ),
    ),
    (
        20,
        (
            "taf_bb_width_pct",
            "taf_ema_20",
            "taf_sma_20",
            "taf_ta_bbands_20_lower",
            "taf_ta_bbands_20_upper",
        ),
    ),
    (21, ("taf_ema_21", "taf_sma_21", "taf_ta_stochrsi_fastd", "taf_ta_stochrsi_fastk")),
    (25, ("taf_ta_t3",)),
    (26, ("taf_ema_26", "taf_sma_26", "taf_ta_apo", "taf_ta_ppo")),
    (28, ("taf_ta_adx",)),
    (29, ("taf_ta_ultosc",)),
    (
        30,
        (
            "taf_ta_correl",
            "taf_ta_ema",
            "taf_ta_ma",
            "taf_ta_mavp",
            "taf_ta_trima",
            "taf_ta_wma",
        ),
    ),
    (31, ("taf_ta_kama",)),
    (
        33,
        (
            "taf_ta_ht_dcperiod",
            "taf_ta_ht_phasor_inphase",
            "taf_ta_ht_phasor_quadrature",
            "taf_ta_mama_fama",
            "taf_ta_mama_mama",
        ),
    ),
    (
        34,
        (
            "taf_macd",
            "taf_macd_hist",
            "taf_macd_signal",
            "taf_ta_macdext_macdhist",
            "taf_ta_macdext_macdsignal",
            "taf_ta_macdfix_macd",
            "taf_ta_macdfix_macdhist",
            "taf_ta_macdfix_macdsignal",
        ),
    ),
    (41, ("taf_ta_adxr",)),
    (50, ("taf_ema_50", "taf_sma_50")),
    (59, ("taf_ta_dema",)),
    (
        64,
        (
            "taf_ta_ht_dcphase",
            "taf_ta_ht_sine_leadsine",
            "taf_ta_ht_sine_sine",
            "taf_ta_ht_trendline",
            "taf_ta_ht_trendmode_integer",
        ),
    ),
    (88, ("taf_ta_tema",)),
    (89, ("taf_ta_trix",)),
)

_TRUE_1H_LOOKBACKS: Final = (
    ("htf1h_taf_rsi", 15, "RSI(timeperiod=14):real"),
    ("htf1h_taf_adx", 28, "ADX(timeperiod=14):real"),
    ("htf1h_taf_macd_hist", 34, "MACD(fastperiod=12,slowperiod=26,signalperiod=9):macdhist"),
    ("htf1h_taf_atr", 15, "ATR(timeperiod=14):real"),
    ("htf1h_taf_mfi", 15, "MFI(timeperiod=14):real"),
    ("htf1h_taf_willr", 14, "WILLR(timeperiod=14):real"),
    ("htf1h_taf_natr", 15, "NATR(timeperiod=14):real"),
    ("htf1h_taf_cci", 14, "CCI(timeperiod=14):real"),
)

_APPLICABLE_UNSTABLE_FUNCTIONS: Final = (
    "ADX",
    "ADXR",
    "ATR",
    "CMO",
    "DX",
    "EMA",
    "HT_DCPERIOD",
    "HT_DCPHASE",
    "HT_PHASOR",
    "HT_SINE",
    "HT_TRENDLINE",
    "HT_TRENDMODE",
    "KAMA",
    "MAMA",
    "MFI",
    "MINUS_DI",
    "MINUS_DM",
    "NATR",
    "PLUS_DI",
    "PLUS_DM",
    "RSI",
    "STOCHRSI",
    "T3",
)


class ModelTATechnicalDependencyContractError(ValueError):
    """The immutable technical-dependency inventory or environment is invalid."""


@dataclass(frozen=True, slots=True)
class TalibEnvironmentIdentity:
    schema_version: str
    interpreter_environment: str
    python_implementation: str
    python_version: str
    machine: str
    numpy_version: str
    distribution_name: str
    distribution_version: str
    wrapper_version: str
    native_version: str
    native_extension_filename: str
    native_binary_size: int
    native_binary_sha256: str
    function_count: int
    ordered_function_names_sha256: str
    function_catalog_schema_version: str
    function_catalog_sha256: str
    compatibility: int
    unstable_periods: tuple[tuple[str, int], ...]
    global_state_sha256: str


EXPECTED_DEPLOYED_TALIB_ENVIRONMENT: Final = TalibEnvironmentIdentity(
    schema_version=TALIB_ENVIRONMENT_IDENTITY_VERSION,
    interpreter_environment="repository_.venv",
    python_implementation="CPython",
    python_version="3.12.3",
    machine="x86_64",
    numpy_version="2.4.4",
    distribution_name="TA-Lib",
    distribution_version="0.6.8",
    wrapper_version="0.6.8",
    native_version="0.6.4 (Oct 20 2025 20:23:51)",
    native_extension_filename="_ta_lib.cpython-312-x86_64-linux-gnu.so",
    native_binary_size=14_198_209,
    native_binary_sha256="ee9ae58a5d61f670ff4319b62550ff9808c17418b5e570364b0c7341b268fed5",
    function_count=158,
    ordered_function_names_sha256=(
        "717c6ee47aea0c825830f6f8d53027520dc155fc772582ecc5347942fdaa0b76"
    ),
    function_catalog_schema_version=TALIB_FUNCTION_CATALOG_VERSION,
    function_catalog_sha256=("560659c280b4583b8b2f929122a318dafec2b71dc09f4e7abd08aa0eeff1cf99"),
    compatibility=0,
    unstable_periods=tuple((name, 0) for name in _APPLICABLE_UNSTABLE_FUNCTIONS),
    global_state_sha256="909881bf7b73767a9df68fdefeb9b0d529f54cc81975c6c50cf85e779a7e4903",
)


@dataclass(frozen=True, slots=True)
class ModelTAFieldDependency:
    feature_name: str
    dependency_role: str
    declared_lookback: int
    minimum_source_rows: int
    derivation_identity: str
    strict_latest_output_semantics: str = field(
        default=STRICT_LATEST_OUTPUT_SEMANTICS,
        init=False,
    )


@dataclass(frozen=True, slots=True)
class ModelTAABILeaf:
    abi_index: int
    feature_name: str
    dependency_role: str
    feature_spec_source_label: str


@dataclass(frozen=True, slots=True)
class ModelTATechnicalDependencyContract:
    schema_version: str
    multi_timeframe_dependency_version: str
    dependency_classification: str
    dependency_scope: str
    market_selection_threshold: bool
    existing_core_contract_version: str
    existing_core_minimum_source_rows: int
    current_timeframe_minimum_source_rows: int
    true_1h_minimum_source_rows: int
    current_timeframe_ta_full_fields: tuple[str, ...]
    true_1h_ta_fields: tuple[str, ...]
    current_timeframe_dependencies: tuple[ModelTAFieldDependency, ...]
    true_1h_dependencies: tuple[ModelTAFieldDependency, ...]
    ta_ohlcv_abi_leaves: tuple[ModelTAABILeaf, ...]
    model_feature_abi_schema_version: str
    model_feature_abi_sha256: str
    ta_full_feature_map_sha256: str
    ta_full_fields_sha256: str
    ta_ohlcv_abi_leaves_sha256: str
    lookback_manifest_sha256: str
    talib_environment: TalibEnvironmentIdentity
    talib_environment_sha256: str
    strict_latest_output_semantics: str
    contract_material_json: str
    contract_sha256: str
    reads_mutable_ta_payload: bool = field(default=False, init=False)
    grants_market_admission: bool = field(default=False, init=False)
    grants_trainer_admission: bool = field(default=False, init=False)
    grants_feature_publication: bool = field(default=False, init=False)
    grants_live_execution: bool = field(default=False, init=False)
    authorizes_order_submission: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ModelTACoverageAudit:
    current_timeframe_source_rows: int
    true_1h_source_rows: int
    missing_current_timeframe_fields: tuple[str, ...]
    missing_true_1h_fields: tuple[str, ...]
    technical_dependencies_satisfied: bool
    market_selection_threshold: bool = field(default=False, init=False)
    grants_market_admission: bool = field(default=False, init=False)
    grants_trainer_admission: bool = field(default=False, init=False)
    grants_feature_publication: bool = field(default=False, init=False)
    grants_live_execution: bool = field(default=False, init=False)
    authorizes_order_submission: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class StrictLatestOutputAudit:
    status: str
    source_row_count: int
    output_row_count: int | None
    latest_value: float | None
    eligible_output_index: int
    semantics: str = field(default=STRICT_LATEST_OUTPUT_SEMANTICS, init=False)
    grants_trainer_admission: bool = field(default=False, init=False)
    grants_feature_publication: bool = field(default=False, init=False)
    grants_live_execution: bool = field(default=False, init=False)
    authorizes_order_submission: bool = field(default=False, init=False)


def _invalid(reason: str) -> NoReturn:
    raise ModelTATechnicalDependencyContractError(reason) from None


def _canonical_json(material: object) -> str:
    try:
        return json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _invalid("model_ta_contract_material_invalid")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def _plain_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("ascii", errors="strict")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _current_tf_lookback_by_field() -> dict[str, int]:
    result: dict[str, int] = {}
    for minimum_rows, field_names in _CURRENT_TF_LOOKBACK_GROUPS:
        for feature_name in field_names:
            if feature_name in result:
                _invalid("model_ta_current_timeframe_lookback_duplicate")
            result[feature_name] = minimum_rows
    if set(result) != set(CURRENT_TIMEFRAME_TA_FULL_FIELDS):
        _invalid("model_ta_current_timeframe_lookback_inventory_mismatch")
    if max(result.values()) != CURRENT_TIMEFRAME_TA_FULL_MINIMUM_ROWS:
        _invalid("model_ta_current_timeframe_minimum_derivation_mismatch")
    return result


def _current_tf_dependencies() -> tuple[ModelTAFieldDependency, ...]:
    lookbacks = _current_tf_lookback_by_field()
    return tuple(
        ModelTAFieldDependency(
            feature_name=feature_name,
            dependency_role="CURRENT_TIMEFRAME_TA_FULL",
            declared_lookback=lookbacks[feature_name] - 1,
            minimum_source_rows=lookbacks[feature_name],
            derivation_identity=(
                "PINNED_TA_FULL_FEATURE_MAP_ENTRY_AND_TALIB_ABSTRACT_CATALOG_OR_"
                "EXPLICIT_ALIAS_PROFILE"
            ),
        )
        for feature_name in CURRENT_TIMEFRAME_TA_FULL_FIELDS
    )


def _true_1h_dependencies() -> tuple[ModelTAFieldDependency, ...]:
    dependencies = tuple(
        ModelTAFieldDependency(
            feature_name=feature_name,
            dependency_role="TRUE_1H_TA_FULL",
            declared_lookback=minimum_rows - 1,
            minimum_source_rows=minimum_rows,
            derivation_identity=derivation_identity,
        )
        for feature_name, minimum_rows, derivation_identity in _TRUE_1H_LOOKBACKS
    )
    if tuple(item.feature_name for item in dependencies) != TRUE_1H_TA_FIELDS:
        _invalid("model_ta_true_1h_lookback_inventory_mismatch")
    if max(item.minimum_source_rows for item in dependencies) != TRUE_1H_TA_MINIMUM_ROWS:
        _invalid("model_ta_true_1h_minimum_derivation_mismatch")
    return dependencies


def _abi_leaves() -> tuple[ModelTAABILeaf, ...]:
    leaves: list[ModelTAABILeaf] = []
    leaves.extend(
        ModelTAABILeaf(index, name, "CURRENT_TIMEFRAME_COMPACT_TA", "v2:features:ta")
        for index, name in zip(range(57, 68), CURRENT_TIMEFRAME_COMPACT_TA_FIELDS, strict=True)
    )
    leaves.extend(
        ModelTAABILeaf(index, name, "CURRENT_TIMEFRAME_NATIVE_CORE", "v2:features:latest")
        for index, name in zip(range(166, 180), CURRENT_TIMEFRAME_NATIVE_CORE_FIELDS, strict=True)
    )
    full_indices = (234, 241, *range(252, 259), *range(281, 427))
    leaves.extend(
        ModelTAABILeaf(index, name, "CURRENT_TIMEFRAME_TA_FULL", "v2:features:ta_full")
        for index, name in zip(full_indices, CURRENT_TIMEFRAME_TA_FULL_FIELDS, strict=True)
    )
    leaves.extend(
        ModelTAABILeaf(index, name, "TRUE_1H_TA_FULL", "v2:features:ta_full:1h")
        for index, name in zip(range(434, 442), TRUE_1H_TA_FIELDS, strict=True)
    )
    if len(leaves) != 188 or len({item.feature_name for item in leaves}) != 188:
        _invalid("model_ta_abi_leaf_inventory_invalid")
    if tuple(item.abi_index for item in leaves) != tuple(sorted(item.abi_index for item in leaves)):
        _invalid("model_ta_abi_leaf_order_invalid")
    return tuple(leaves)


def _environment_material(identity: TalibEnvironmentIdentity) -> dict[str, object]:
    material = asdict(identity)
    material["unstable_periods"] = [
        {"function_name": name, "unstable_period": period}
        for name, period in identity.unstable_periods
    ]
    return material


def inspect_deployed_talib_environment() -> TalibEnvironmentIdentity:
    """Inspect the active process; imports TA-Lib lazily and performs no writes."""

    try:
        import numpy
        import talib
        import talib._ta_lib as native
        from talib import abstract
    except Exception as exc:  # noqa: BLE001
        _invalid(f"model_ta_talib_environment_import_failed:{type(exc).__name__}")

    repository_root = Path(__file__).absolute().parents[5]
    interpreter_environment = (
        "repository_.venv"
        if Path(sys.prefix).resolve() == (repository_root / ".venv").resolve()
        else "UNAPPROVED_INTERPRETER_ENVIRONMENT"
    )
    talib_runtime: Any = talib
    native_runtime: Any = native
    abstract_runtime: Any = abstract
    function_names = list(talib_runtime.get_functions())
    function_catalog: list[dict[str, object]] = []
    for function_name in function_names:
        function = abstract_runtime.Function(function_name)
        function_catalog.append(
            {
                "name": function_name,
                "input_names": _plain_json_value(function.input_names),
                "parameters": _plain_json_value(function.parameters),
                "output_names": _plain_json_value(function.output_names),
                "lookback": int(function.lookback),
            }
        )
    catalog_material = {
        "schema_version": TALIB_FUNCTION_CATALOG_VERSION,
        "functions": function_catalog,
    }
    ordered_names_json = json.dumps(function_names, separators=(",", ":"))

    unstable_periods: list[tuple[str, int]] = []
    for function_name in function_names:
        try:
            unstable_periods.append(
                (function_name, int(talib_runtime.get_unstable_period(function_name)))
            )
        except (KeyError, TypeError):
            continue
    compatibility = int(talib_runtime.get_compatibility())
    global_state = {
        "compatibility": compatibility,
        "unstable_periods": dict(unstable_periods),
    }
    native_path = Path(native_runtime.__file__)
    native_version_raw = talib_runtime.__ta_version__
    native_version = (
        native_version_raw.decode("ascii", errors="strict")
        if isinstance(native_version_raw, bytes)
        else str(native_version_raw)
    )
    return TalibEnvironmentIdentity(
        schema_version=TALIB_ENVIRONMENT_IDENTITY_VERSION,
        interpreter_environment=interpreter_environment,
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        machine=platform.machine(),
        numpy_version=str(numpy.__version__),
        distribution_name="TA-Lib",
        distribution_version=importlib.metadata.version("TA-Lib"),
        wrapper_version=str(talib_runtime.__version__),
        native_version=native_version,
        native_extension_filename=native_path.name,
        native_binary_size=native_path.stat().st_size,
        native_binary_sha256=hashlib.sha256(native_path.read_bytes()).hexdigest(),
        function_count=len(function_names),
        ordered_function_names_sha256=_sha256_text(ordered_names_json),
        function_catalog_schema_version=TALIB_FUNCTION_CATALOG_VERSION,
        function_catalog_sha256=_sha256_text(_canonical_json(catalog_material)),
        compatibility=compatibility,
        unstable_periods=tuple(sorted(unstable_periods)),
        global_state_sha256=_sha256_text(_canonical_json(global_state)),
    )


def validate_deployed_talib_environment(identity: TalibEnvironmentIdentity) -> None:
    """Fail closed and name every identity field that drifted."""

    expected = asdict(EXPECTED_DEPLOYED_TALIB_ENVIRONMENT)
    observed = asdict(identity)
    mismatches = tuple(name for name in expected if observed.get(name) != expected[name])
    if mismatches:
        _invalid("model_ta_talib_environment_identity_mismatch:" + ",".join(mismatches))


def _leaf_manifest_material(leaves: tuple[ModelTAABILeaf, ...]) -> dict[str, object]:
    return {
        "schema_version": TA_OHLC_ABI_LEAF_MANIFEST_VERSION,
        "model_feature_abi_sha256": MODEL_FEATURE_ABI_SHA256,
        "leaves": [asdict(item) for item in leaves],
    }


def build_model_ta_technical_dependency_contract() -> ModelTATechnicalDependencyContract:
    """Build the audit-only contract after verifying the deployed environment."""

    environment = inspect_deployed_talib_environment()
    validate_deployed_talib_environment(environment)
    current_dependencies = _current_tf_dependencies()
    true_1h_dependencies = _true_1h_dependencies()
    leaves = _abi_leaves()

    fields_material = {
        "schema_version": TA_FULL_FIELD_MANIFEST_VERSION,
        "feature_names": list(CURRENT_TIMEFRAME_TA_FULL_FIELDS),
    }
    fields_sha256 = _sha256_text(_canonical_json(fields_material))
    if fields_sha256 != CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256:
        _invalid("model_ta_full_field_manifest_hash_mismatch")

    leaf_sha256 = _sha256_text(_canonical_json(_leaf_manifest_material(leaves)))
    if leaf_sha256 != TA_OHLC_ABI_LEAVES_SHA256:
        _invalid("model_ta_abi_leaf_manifest_hash_mismatch")

    lookback_material = {
        "schema_version": LOOKBACK_MANIFEST_VERSION,
        "strict_latest_output_semantics": STRICT_LATEST_OUTPUT_SEMANTICS,
        "current_timeframe": [asdict(item) for item in current_dependencies],
        "true_1h": [asdict(item) for item in true_1h_dependencies],
    }
    lookback_sha256 = _sha256_text(_canonical_json(lookback_material))
    if lookback_sha256 != LOOKBACK_MANIFEST_SHA256:
        _invalid("model_ta_lookback_manifest_hash_mismatch")
    environment_sha256 = _sha256_text(_canonical_json(_environment_material(environment)))
    if environment_sha256 != DEPLOYED_TALIB_ENVIRONMENT_SHA256:
        _invalid("model_ta_environment_manifest_hash_mismatch")
    material = {
        "schema_version": MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
        "multi_timeframe_dependency_version": MODEL_TA_MULTI_TIMEFRAME_DEPENDENCY_VERSION,
        "dependency_classification": DEPENDENCY_CLASSIFICATION,
        "dependency_scope": DEPENDENCY_SCOPE,
        "market_selection_threshold": False,
        "technical_dependency_minima": {
            "existing_native_core_contract_version": EXISTING_CORE_CONTRACT_VERSION,
            "existing_native_core_source_rows": EXISTING_CORE_MINIMUM_SOURCE_ROWS,
            "current_timeframe_model_ta_source_rows": CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
            "true_1h_ta_source_rows": TRUE_1H_TA_MINIMUM_ROWS,
        },
        "model_feature_abi_schema_version": MODEL_FEATURE_ABI_SCHEMA_VERSION,
        "model_feature_abi_sha256": MODEL_FEATURE_ABI_SHA256,
        "ta_full_feature_map_sha256": CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256,
        "ta_full_fields_sha256": fields_sha256,
        "ta_ohlcv_abi_leaves_sha256": leaf_sha256,
        "lookback_manifest_sha256": lookback_sha256,
        "talib_environment_sha256": environment_sha256,
        "strict_latest_output_semantics": STRICT_LATEST_OUTPUT_SEMANTICS,
        "authority": {
            "reads_mutable_ta_payload": False,
            "grants_market_admission": False,
            "grants_trainer_admission": False,
            "grants_feature_publication": False,
            "grants_live_execution": False,
            "authorizes_order_submission": False,
        },
    }
    material_json = _canonical_json(material)
    contract_sha256 = _sha256_text(material_json)
    if contract_sha256 != MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256:
        _invalid("model_ta_technical_dependency_contract_hash_mismatch")
    return ModelTATechnicalDependencyContract(
        schema_version=MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
        multi_timeframe_dependency_version=MODEL_TA_MULTI_TIMEFRAME_DEPENDENCY_VERSION,
        dependency_classification=DEPENDENCY_CLASSIFICATION,
        dependency_scope=DEPENDENCY_SCOPE,
        market_selection_threshold=False,
        existing_core_contract_version=EXISTING_CORE_CONTRACT_VERSION,
        existing_core_minimum_source_rows=EXISTING_CORE_MINIMUM_SOURCE_ROWS,
        current_timeframe_minimum_source_rows=CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
        true_1h_minimum_source_rows=TRUE_1H_TA_MINIMUM_ROWS,
        current_timeframe_ta_full_fields=CURRENT_TIMEFRAME_TA_FULL_FIELDS,
        true_1h_ta_fields=TRUE_1H_TA_FIELDS,
        current_timeframe_dependencies=current_dependencies,
        true_1h_dependencies=true_1h_dependencies,
        ta_ohlcv_abi_leaves=leaves,
        model_feature_abi_schema_version=MODEL_FEATURE_ABI_SCHEMA_VERSION,
        model_feature_abi_sha256=MODEL_FEATURE_ABI_SHA256,
        ta_full_feature_map_sha256=CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256,
        ta_full_fields_sha256=fields_sha256,
        ta_ohlcv_abi_leaves_sha256=leaf_sha256,
        lookback_manifest_sha256=lookback_sha256,
        talib_environment=environment,
        talib_environment_sha256=environment_sha256,
        strict_latest_output_semantics=STRICT_LATEST_OUTPUT_SEMANTICS,
        contract_material_json=material_json,
        contract_sha256=contract_sha256,
    )


def audit_model_ta_technical_coverage(
    contract: ModelTATechnicalDependencyContract,
    *,
    current_timeframe_source_rows: object,
    true_1h_source_rows: object,
) -> ModelTACoverageAudit:
    """Evaluate only declared lookback coverage; never grant admission."""

    if type(current_timeframe_source_rows) is not int or current_timeframe_source_rows < 0:
        _invalid("model_ta_current_timeframe_source_rows_invalid")
    if type(true_1h_source_rows) is not int or true_1h_source_rows < 0:
        _invalid("model_ta_true_1h_source_rows_invalid")
    current_rows = current_timeframe_source_rows
    one_hour_rows = true_1h_source_rows
    missing_current = tuple(
        item.feature_name
        for item in contract.current_timeframe_dependencies
        if item.minimum_source_rows > current_rows
    )
    missing_1h = tuple(
        item.feature_name
        for item in contract.true_1h_dependencies
        if item.minimum_source_rows > one_hour_rows
    )
    return ModelTACoverageAudit(
        current_timeframe_source_rows=current_rows,
        true_1h_source_rows=one_hour_rows,
        missing_current_timeframe_fields=missing_current,
        missing_true_1h_fields=missing_1h,
        technical_dependencies_satisfied=not missing_current and not missing_1h,
    )


def inspect_strict_latest_output(
    output: object,
    *,
    source_row_count: object,
) -> StrictLatestOutputAudit:
    """Audit exact-final-element eligibility without deriving or substituting data."""

    if type(source_row_count) is not int or source_row_count < 1:
        _invalid("model_ta_strict_latest_source_row_count_invalid")
    if isinstance(output, Mapping | str | bytes | bytearray):
        return StrictLatestOutputAudit(
            status="OUTPUT_NOT_ONE_DIMENSIONAL_SEQUENCE",
            source_row_count=source_row_count,
            output_row_count=None,
            latest_value=None,
            eligible_output_index=-1,
        )
    try:
        output_count = len(output)  # type: ignore[arg-type]
    except TypeError:
        return StrictLatestOutputAudit(
            status="OUTPUT_NOT_ONE_DIMENSIONAL_SEQUENCE",
            source_row_count=source_row_count,
            output_row_count=None,
            latest_value=None,
            eligible_output_index=-1,
        )
    if output_count != source_row_count:
        return StrictLatestOutputAudit(
            status="OUTPUT_LENGTH_MISMATCH",
            source_row_count=source_row_count,
            output_row_count=output_count,
            latest_value=None,
            eligible_output_index=-1,
        )
    try:
        raw_latest = output[-1]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return StrictLatestOutputAudit(
            status="OUTPUT_NOT_ONE_DIMENSIONAL_SEQUENCE",
            source_row_count=source_row_count,
            output_row_count=output_count,
            latest_value=None,
            eligible_output_index=-1,
        )
    if isinstance(raw_latest, bool):
        return StrictLatestOutputAudit(
            status="LATEST_OUTPUT_NOT_NUMERIC",
            source_row_count=source_row_count,
            output_row_count=output_count,
            latest_value=None,
            eligible_output_index=-1,
        )
    try:
        latest = float(raw_latest)
    except (TypeError, ValueError, OverflowError):
        return StrictLatestOutputAudit(
            status="LATEST_OUTPUT_NOT_NUMERIC",
            source_row_count=source_row_count,
            output_row_count=output_count,
            latest_value=None,
            eligible_output_index=-1,
        )
    if not math.isfinite(latest):
        return StrictLatestOutputAudit(
            status="NONFINITE_LATEST_OUTPUT",
            source_row_count=source_row_count,
            output_row_count=output_count,
            latest_value=None,
            eligible_output_index=-1,
        )
    return StrictLatestOutputAudit(
        status="PRESENT_FINITE",
        source_row_count=source_row_count,
        output_row_count=output_count,
        latest_value=latest,
        eligible_output_index=source_row_count - 1,
    )


__all__ = [
    "CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS",
    "CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256",
    "CURRENT_TIMEFRAME_TA_FULL_FIELDS",
    "CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256",
    "EXPECTED_DEPLOYED_TALIB_ENVIRONMENT",
    "DEPLOYED_TALIB_ENVIRONMENT_SHA256",
    "EXISTING_CORE_CONTRACT_VERSION",
    "EXISTING_CORE_MINIMUM_SOURCE_ROWS",
    "MODEL_FEATURE_ABI_SCHEMA_VERSION",
    "MODEL_FEATURE_ABI_SHA256",
    "MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION",
    "MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256",
    "ModelTACoverageAudit",
    "ModelTAFieldDependency",
    "ModelTAABILeaf",
    "ModelTATechnicalDependencyContract",
    "ModelTATechnicalDependencyContractError",
    "STRICT_LATEST_OUTPUT_SEMANTICS",
    "LOOKBACK_MANIFEST_SHA256",
    "StrictLatestOutputAudit",
    "TA_OHLC_ABI_LEAVES_SHA256",
    "TRUE_1H_TA_FIELDS",
    "TRUE_1H_TA_MINIMUM_ROWS",
    "TalibEnvironmentIdentity",
    "audit_model_ta_technical_coverage",
    "build_model_ta_technical_dependency_contract",
    "inspect_deployed_talib_environment",
    "inspect_strict_latest_output",
    "validate_deployed_talib_environment",
]
