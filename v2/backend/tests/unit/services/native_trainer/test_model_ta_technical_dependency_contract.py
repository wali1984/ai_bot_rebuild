from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    CORE_TA_MINIMUM_COVERAGE_CONTRACT_VERSION,
    CORE_TA_MINIMUM_SOURCE_ROWS,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    TA_FULL_FEATURE_MAP,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
    CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256,
    CURRENT_TIMEFRAME_TA_FULL_FIELDS,
    CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256,
    DEPLOYED_TALIB_ENVIRONMENT_SHA256,
    EXISTING_CORE_CONTRACT_VERSION,
    EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    EXPECTED_DEPLOYED_TALIB_ENVIRONMENT,
    LOOKBACK_MANIFEST_SHA256,
    MODEL_FEATURE_ABI_SHA256,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    STRICT_LATEST_OUTPUT_SEMANTICS,
    TA_OHLC_ABI_LEAVES_SHA256,
    TRUE_1H_TA_FIELDS,
    TRUE_1H_TA_MINIMUM_ROWS,
    ModelTATechnicalDependencyContract,
    ModelTATechnicalDependencyContractError,
    audit_model_ta_technical_coverage,
    build_model_ta_technical_dependency_contract,
    inspect_deployed_talib_environment,
    inspect_strict_latest_output,
    validate_deployed_talib_environment,
)


def _canonical_sha256(material: object) -> str:
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.fixture(scope="module")
def contract() -> ModelTATechnicalDependencyContract:
    return build_model_ta_technical_dependency_contract()


def test_deployed_venv_talib_identity_is_exact_and_drift_fails_closed() -> None:
    observed = inspect_deployed_talib_environment()

    assert observed == EXPECTED_DEPLOYED_TALIB_ENVIRONMENT
    assert observed.distribution_version == observed.wrapper_version == "0.6.8"
    assert observed.native_version == "0.6.4 (Oct 20 2025 20:23:51)"
    assert observed.native_binary_sha256 == (
        "ee9ae58a5d61f670ff4319b62550ff9808c17418b5e570364b0c7341b268fed5"
    )
    assert observed.function_catalog_sha256 == (
        "560659c280b4583b8b2f929122a318dafec2b71dc09f4e7abd08aa0eeff1cf99"
    )
    assert observed.compatibility == 0
    assert set(dict(observed.unstable_periods).values()) == {0}
    validate_deployed_talib_environment(observed)

    drifted = replace(observed, wrapper_version="0.6.7")
    with pytest.raises(
        ModelTATechnicalDependencyContractError,
        match="environment_identity_mismatch:wrapper_version",
    ):
        validate_deployed_talib_environment(drifted)


def test_contract_pins_exact_feature_map_fields_and_188_global_abi_leaves(
    contract: ModelTATechnicalDependencyContract,
) -> None:
    mapping_material = {
        "schema_version": "trainer_ta_full_feature_map_v1",
        "entries": [
            {"feature_name": feature_name, "indicator_name": indicator_name}
            for feature_name, indicator_name in TA_FULL_FEATURE_MAP.items()
        ],
    }
    field_material = {
        "schema_version": "trainer_current_timeframe_ta_full_fields_v1",
        "feature_names": list(CURRENT_TIMEFRAME_TA_FULL_FIELDS),
    }

    assert len(CURRENT_TIMEFRAME_TA_FULL_FIELDS) == len(TA_FULL_FEATURE_MAP) == 155
    assert CURRENT_TIMEFRAME_TA_FULL_FIELDS == tuple(TA_FULL_FEATURE_MAP)
    assert _canonical_sha256(mapping_material) == contract.ta_full_feature_map_sha256
    assert contract.ta_full_feature_map_sha256 == CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256
    assert _canonical_sha256(field_material) == contract.ta_full_fields_sha256
    assert contract.ta_full_fields_sha256 == CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256
    assert len(TRUE_1H_TA_FIELDS) == 8
    assert len(contract.ta_ohlcv_abi_leaves) == 188
    assert contract.ta_ohlcv_abi_leaves_sha256 == TA_OHLC_ABI_LEAVES_SHA256
    assert tuple(leaf.abi_index for leaf in contract.ta_ohlcv_abi_leaves) == tuple(
        sorted(leaf.abi_index for leaf in contract.ta_ohlcv_abi_leaves)
    )
    for leaf in contract.ta_ohlcv_abi_leaves:
        assert FEATURE_SPEC[leaf.abi_index] == (
            leaf.feature_name,
            leaf.feature_spec_source_label,
        )
    assert contract.model_feature_abi_sha256 == MODEL_FEATURE_ABI_SHA256


def test_contract_hashes_minima_and_authority_are_exact(
    contract: ModelTATechnicalDependencyContract,
) -> None:
    assert CORE_TA_MINIMUM_COVERAGE_CONTRACT_VERSION == EXISTING_CORE_CONTRACT_VERSION
    assert CORE_TA_MINIMUM_SOURCE_ROWS == EXISTING_CORE_MINIMUM_SOURCE_ROWS == 71
    assert contract.current_timeframe_minimum_source_rows == 89
    assert CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS == 89
    assert contract.true_1h_minimum_source_rows == TRUE_1H_TA_MINIMUM_ROWS == 34
    assert contract.lookback_manifest_sha256 == LOOKBACK_MANIFEST_SHA256
    assert contract.talib_environment_sha256 == DEPLOYED_TALIB_ENVIRONMENT_SHA256
    assert contract.contract_sha256 == MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256
    assert (
        contract.contract_sha256
        == hashlib.sha256(contract.contract_material_json.encode("utf-8")).hexdigest()
    )
    assert contract.market_selection_threshold is False
    assert contract.reads_mutable_ta_payload is False
    assert contract.grants_market_admission is False
    assert contract.grants_trainer_admission is False
    assert contract.grants_feature_publication is False
    assert contract.grants_live_execution is False
    assert contract.authorizes_order_submission is False


@pytest.mark.parametrize(
    ("current_rows", "expected_missing"),
    [
        (71, ("taf_ta_tema", "taf_ta_trix")),
        (88, ("taf_ta_trix",)),
        (89, ()),
    ],
)
def test_current_timeframe_71_88_89_boundaries_come_from_lookback_manifest(
    contract: ModelTATechnicalDependencyContract,
    current_rows: int,
    expected_missing: tuple[str, ...],
) -> None:
    audit = audit_model_ta_technical_coverage(
        contract,
        current_timeframe_source_rows=current_rows,
        true_1h_source_rows=34,
    )

    assert audit.missing_current_timeframe_fields == expected_missing
    assert audit.missing_true_1h_fields == ()
    assert audit.technical_dependencies_satisfied is (not expected_missing)
    assert audit.grants_trainer_admission is False
    assert audit.grants_feature_publication is False
    assert audit.grants_live_execution is False


@pytest.mark.parametrize(
    ("one_hour_rows", "expected_missing"),
    [
        (33, ("htf1h_taf_macd_hist",)),
        (34, ()),
    ],
)
def test_true_1h_33_34_boundary_comes_from_lookback_manifest(
    contract: ModelTATechnicalDependencyContract,
    one_hour_rows: int,
    expected_missing: tuple[str, ...],
) -> None:
    audit = audit_model_ta_technical_coverage(
        contract,
        current_timeframe_source_rows=89,
        true_1h_source_rows=one_hour_rows,
    )

    assert audit.missing_current_timeframe_fields == ()
    assert audit.missing_true_1h_fields == expected_missing
    assert audit.technical_dependencies_satisfied is (not expected_missing)
    assert audit.grants_market_admission is False
    assert audit.authorizes_order_submission is False


def test_strict_latest_output_never_scans_backward_or_grants_authority() -> None:
    stale_finite_then_nan = inspect_strict_latest_output(
        [1.0, 2.0, float("nan")],
        source_row_count=3,
    )
    exact_latest = inspect_strict_latest_output([1.0, 2.0, 3.0], source_row_count=3)
    wrong_length = inspect_strict_latest_output([1.0, 2.0], source_row_count=3)
    keyed_mapping = inspect_strict_latest_output(
        {0: 1.0, 1: 2.0, -1: 3.0},
        source_row_count=3,
    )

    assert stale_finite_then_nan.status == "NONFINITE_LATEST_OUTPUT"
    assert stale_finite_then_nan.latest_value is None
    assert stale_finite_then_nan.eligible_output_index == -1
    assert exact_latest.status == "PRESENT_FINITE"
    assert exact_latest.latest_value == 3.0
    assert exact_latest.eligible_output_index == 2
    assert wrong_length.status == "OUTPUT_LENGTH_MISMATCH"
    assert keyed_mapping.status == "OUTPUT_NOT_ONE_DIMENSIONAL_SEQUENCE"
    assert keyed_mapping.latest_value is None
    assert stale_finite_then_nan.semantics == STRICT_LATEST_OUTPUT_SEMANTICS
    assert stale_finite_then_nan.grants_trainer_admission is False
    assert stale_finite_then_nan.grants_feature_publication is False
    assert stale_finite_then_nan.grants_live_execution is False
    assert stale_finite_then_nan.authorizes_order_submission is False
