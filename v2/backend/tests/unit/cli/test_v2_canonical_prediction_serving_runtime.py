from __future__ import annotations

from types import SimpleNamespace

from v2.backend.app.cli import v2_canonical_prediction_serving_runtime as serving


class _IO:
    def __init__(self, client=None) -> None:
        self.client = client
        self.status = None

    def set_json_expiring(self, _key, value, *, ex) -> None:
        assert ex > 0
        self.status = value


def test_run_cycle_reports_real_evidence_validity_counts(monkeypatch) -> None:
    observations = iter(
        [
            {
                "status": "MICROSTRUCTURE_BLOCKED",
                "cost_evidence_valid": True,
                "microstructure_evidence_valid": True,
            },
            {
                "status": "PUBLISHED",
                "prediction_id": "prediction-1",
                "directional": True,
                "cost_evidence_valid": True,
                "microstructure_evidence_valid": True,
            },
        ]
    )
    monkeypatch.setattr(serving, "V2OnlyJsonIO", _IO)
    monkeypatch.setattr(serving, "V2HybridPredictionPublisher", lambda **_kwargs: object())
    monkeypatch.setattr(serving, "read_active_cohort", lambda _client: {})
    monkeypatch.setattr(serving, "publish_one", lambda **_kwargs: next(observations))
    active = SimpleNamespace(
        ckpt=SimpleNamespace(
            checkpoint_id="checkpoint-1",
            feature_abi_sha256=serving.feature_abi_sha256(),
            feature_builder_sha256=serving.feature_builder_sha256(),
            serving_feature_abi_v2=True,
        ),
        generation=2,
        classification="PAPER_ONLY",
    )

    status = serving.run_cycle(
        object(),
        active,
        symbols=["BTCUSDT"],
        timeframes=["1m", "5m"],
        status_path=None,
        reload_count=0,
        rollback_count=0,
    )

    assert status["records_published"] == 1
    assert status["directional_records"] == 1
    assert status["cost_evidence_valid_count"] == 2
    assert status["microstructure_evidence_valid_count"] == 2
