from __future__ import annotations

import fnmatch
import json

import pytest

from v2.backend.app.services.altdata.provider_consumption_status import (
    build_provider_consumption_status,
)


class _FakeRedis:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self._data = dict(data or {})

    def scan_iter(self, match: str = "*", count: int = 500):  # noqa: ARG002
        for key in sorted(self._data):
            if fnmatch.fnmatch(key, match):
                yield key

    def get(self, key: str):
        value = self._data.get(key)
        return None if value is None else json.dumps(value)


def test_matrix_consumption_requires_real_tensor_altdata_feature_value() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [
                        {
                            "preemptive_decision_time": "2026-07-12T00:02:00Z",
                            "altdata_confluence_present": False,
                            "altdata_hedge_required_score": 0.0,
                            "altdata_hedge_required": False,
                            "altdata_feature_cutoff": None,
                        }
                    ]
                }
            }
        )
    )

    decision = status["decision_altdata_consumption"]
    assert status["matrix_rows_with_altdata"] == 0
    assert decision["rows_scanned"] == 1
    assert decision["rows_with_any_altdata_feature"] == 0
    assert decision["rows_with_metadata_only_altdata"] == 1


def test_decision_altdata_reports_non_null_rates_and_time_safety() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [
                        {
                            "preemptive_decision_time": "2026-07-12T00:02:00Z",
                            "altdata_feature_cutoff": "2026-07-12T00:01:00Z",
                            "altdata_trade_block_score": 0.25,
                            "provider_features_used": [
                                "coinglass",
                                "moralis",
                                "altdata_trade_block_score",
                            ],
                        },
                        {
                            "preemptive_decision_time": "2026-07-12T00:02:00Z",
                            "altdata_feature_cutoff": "2026-07-12T00:03:00Z",
                            "altdata_trade_block_score": None,
                            "provider_features_missing": ["moralis"],
                        },
                    ]
                }
            }
        )
    )

    decision = status["decision_altdata_consumption"]
    trade_block = decision["feature_stats"]["altdata_trade_block_score"]

    assert status["matrix_rows_with_altdata"] == 1
    assert trade_block["row_count"] == 2
    assert trade_block["non_null_count"] == 1
    assert trade_block["non_null_rate"] == 0.5
    assert trade_block["decision_time_safe_count"] == 1
    assert trade_block["future_leak_count"] == 1
    assert decision["provider_features_used_counts"]["coinglass"] == 1
    assert "altdata_trade_block_score" not in decision["provider_features_used_counts"]
    assert decision["provider_feature_names_used_counts"]["altdata_trade_block_score"] == 1
    assert decision["provider_features_missing_counts"]["moralis"] == 1
    assert decision["attribution_status"]["status"] == "FEATURE_ATTRIBUTION_NOT_YET_AVAILABLE"


def test_provider_payload_freshness_reports_missing_and_stale_masks() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "PARTIAL_REQUIRED_FEATURES_MISSING",
                    "actual_payload_present": True,
                    "feature_bridge_ready": False,
                    "feature_count": 7,
                    "available_at": "2026-07-12T05:49:43Z",
                    "feature_cutoff": "2026-07-12T05:42:47Z",
                    "missing_mask": {
                        "moralis_exchange_inflow_usd": False,
                        "moralis_holder_count": True,
                    },
                    "stale_mask": {
                        "moralis_exchange_inflow_usd": False,
                    },
                },
                "v2:provider:coinglass:feature_bridge_status": {
                    "status": "READY",
                    "actual_payload_present": True,
                    "feature_bridge_ready": True,
                    "feature_count": 12,
                    "stale_mask": {"coinglass_oi_delayed_data_window": True},
                },
            }
        )
    )

    moralis = status["provider_payload_freshness"]["moralis"]
    coinglass = status["provider_payload_freshness"]["coinglass"]

    assert moralis["missing_feature_count"] == 1
    assert moralis["missing_mask_true"] is True
    assert moralis["feature_bridge_ready"] is False
    assert coinglass["stale_feature_count"] == 1
    assert coinglass["stale_mask_true"] is True


def test_provider_consumption_flags_do_not_bleed_between_providers() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:coinglass:feature_bridge_status": {
                    "status": "READY",
                    "feature_count": 12,
                    "actual_payload_present": True,
                },
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "ISOLATED_BY_POLICY",
                    "feature_count": 0,
                    "actual_payload_present": False,
                },
                "v2:altdata:confluence:BTCUSDT:1m": {
                    "features": {"altdata_trade_block_score": 0.25},
                },
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [
                        {
                            "preemptive_decision_time": "2026-07-12T00:02:00Z",
                            "altdata_feature_cutoff": "2026-07-12T00:01:00Z",
                            "altdata_trade_block_score": 0.25,
                            "provider_features_used": ["coinglass"],
                        }
                    ]
                },
            }
        )
    )

    coinglass = status["providers"]["coinglass"]
    moralis = status["providers"]["moralis"]
    assert coinglass["trainer_consumption"] is True
    assert coinglass["risk_direct_consumption"] is True
    assert moralis["trainer_consumption"] is False
    assert moralis["provider_tensor_consumption"] is False
    assert moralis["ppo_consumption"] is False
    assert moralis["masa_consumption"] is False
    assert moralis["risk_direct_consumption"] is False
    assert moralis["allocator_direct_consumption"] is False
    assert moralis["paper_lineage"] is False
    assert status["trainer_consumption"] is True


@pytest.mark.parametrize("invalid_feature_count", [True, "8", -1, "not-a-number"])
def test_provider_consumption_rejects_non_exact_feature_counts(
    invalid_feature_count: object,
) -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "ISOLATED_BY_POLICY",
                    "feature_count": invalid_feature_count,
                    "actual_payload_present": False,
                }
            }
        )
    )

    moralis = status["providers"]["moralis"]
    assert moralis["feature_count"] == 0
    assert moralis["trainer_consumption"] is False
    assert moralis["provider_tensor_consumption"] is False
    assert status["provider_payload_freshness"]["moralis"]["feature_count"] == 0


def test_provider_presence_does_not_claim_decision_consumption() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "PAYLOADS_PENDING",
                    "feature_count": 0,
                },
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [{"altdata_providers_present": ["moralis"]}]
                },
            }
        )
    )

    decision = status["decision_altdata_consumption"]
    moralis = status["providers"]["moralis"]
    assert decision["provider_presence_counts"] == {"moralis": 1}
    assert decision["provider_features_used_counts"] == {}
    assert moralis["risk_direct_consumption"] is False
    assert moralis["paper_lineage"] is False


def test_provider_feature_name_credits_its_provider() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "READY",
                    "feature_count": 1,
                },
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [{"provider_features_used": ["moralis_holder_count"]}]
                },
            }
        )
    )

    decision = status["decision_altdata_consumption"]
    moralis = status["providers"]["moralis"]
    assert decision["provider_features_used_counts"]["moralis"] == 1
    assert decision["provider_feature_names_used_counts"]["moralis_holder_count"] == 1
    assert moralis["trainer_consumption"] is True
    assert moralis["risk_direct_consumption"] is True


def test_moralis_isolation_overrides_inconsistent_count_and_usage_claims() -> None:
    status = build_provider_consumption_status(
        _FakeRedis(
            {
                "v2:provider:moralis:feature_bridge_status": {
                    "status": "ISOLATED_BY_POLICY",
                    "trainer_isolation_active": True,
                    "feature_count": 8,
                },
                "v2:paper:preemptive_candidate_decision_matrix": {
                    "rows": [{"provider_features_used": ["moralis_holder_count"]}]
                },
            }
        )
    )

    moralis = status["providers"]["moralis"]
    assert moralis["feature_count"] == 0
    for field in (
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_direct_consumption",
        "orchestrator_direct_consumption",
        "allocator_direct_consumption",
        "paper_lineage",
        "dry_run_lineage",
        "feedback_attribution",
    ):
        assert moralis[field] is False
