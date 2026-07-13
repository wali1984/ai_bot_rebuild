"""TA feature expansion: wire the full TA-Lib payload (v2:features:ta_full) into the
model_vector via taf_* features + TA_FULL_FEATURE_MAP.

The talib loop already computes 216 indicators; only ~11 were wired. These lock in
that the taf_* features resolve from the ta_full payload's indicator dict, missing
indicators stay honestly masked, and the model_vector grew to the new width.
"""
from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    TA_FULL_FEATURE_MAP,
    V2UnifiedFeatureTensorBuilder,
)

_NAMES = [n for n, _ in FEATURE_SPEC]


def test_feature_spec_grew_and_has_no_duplicates() -> None:
    assert len(FEATURE_SPEC) == 458
    assert len(_NAMES) == len(set(_NAMES)), "FEATURE_SPEC must have no duplicate names"
    taf = [n for n in _NAMES if n.startswith("taf_")]
    assert len(taf) == 155
    # every taf_ feature has a source of the full TA payload + a map entry.
    for name, source in FEATURE_SPEC:
        if name.startswith("taf_"):
            assert source == "v2:features:ta_full"
            assert name in TA_FULL_FEATURE_MAP


def test_taf_features_resolve_from_ta_full_indicators() -> None:
    b = V2UnifiedFeatureTensorBuilder()
    payloads = {
        "features_ta_full": {
            "indicators": {"ta_ADX": 27.5, "ta_CCI": -80.0, "rsi_14": 61.0, "atr_14": 12.3},
        }
    }
    rec = b.build(symbol="BTCUSDT", timeframe="1m", payloads=payloads)
    assert len(rec.model_vector) == len(FEATURE_SPEC) * 4 == 1832
    assert rec.model_vector[_NAMES.index("taf_ta_adx")] == 27.5
    assert rec.model_vector[_NAMES.index("taf_rsi_14")] == 61.0
    assert rec.model_vector[_NAMES.index("taf_atr_14")] == 12.3
    # A taf_ feature with no indicator value stays missing (honest mask).
    assert rec.missing_mask[_NAMES.index("taf_ta_mfi")] == 1


def test_no_ta_full_payload_leaves_taf_missing_not_crashing() -> None:
    b = V2UnifiedFeatureTensorBuilder()
    rec = b.build(symbol="BTCUSDT", timeframe="1m", payloads={})
    assert len(rec.model_vector) == 1832
    taf_missing = sum(1 for n in _NAMES if n.startswith("taf_") and rec.missing_mask[_NAMES.index(n)] == 1)
    assert taf_missing == 155  # all taf_ honestly missing when no ta_full payload
