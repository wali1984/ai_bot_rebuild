from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_economic_cohort_binding_republisher as worker


class Pipeline:
    def __init__(self, client):
        self.client = client
        self.pending = []

    def multi(self):
        return self

    def set(self, key, value):
        self.pending.append((key, value))
        return self

    def execute(self):
        for key, value in self.pending:
            self.client.values[key] = value
        return [True for _ in self.pending]


class FakeRedis:
    def __init__(self, active, legacy=None):
        self.values = {worker.ACTIVE_KEY: json.dumps(active)}
        if legacy is not None:
            self.values[worker.LEGACY_COHORT_KEY] = json.dumps(legacy)

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True

    def pipeline(self):
        return Pipeline(self)


def _document():
    cohort = "paper_serving_abi_v2:test"
    bundle_hash = "b" * 64
    abi_hash = "a" * 64
    economic = {
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_bundle_sha256": bundle_hash,
        "feature_abi_sha256": abi_hash,
        "cohort_id": cohort,
        "window_type": "CHECKPOINT_GENERATION_NATURAL_DIRECTIONAL_CLOSES",
        "minimum_natural_directional_closes": 5,
        "paper_only": True,
        "live_eligible": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    legacy = {
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "paper_strategy_cohort_id": cohort,
        "paper_only": True,
        "live_eligible": False,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {
        "activation_receipt": {
            "registry_generation": 3,
            "checkpoint_id": "checkpoint-3",
            "checkpoint_bundle_sha256": bundle_hash,
        },
        "economic_cohort": economic,
        "legacy_serving_cohort": legacy,
    }


def _active():
    return {
        "registry_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_bundle": {
            "content_sha256": "b" * 64,
            "feature_abi_sha256": "a" * 64,
        },
    }


def test_republish_restores_only_receipt_bound_cohort(tmp_path) -> None:
    document = _document()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(document))
    client = FakeRedis(_active(), legacy=document["legacy_serving_cohort"])

    status = worker.republish(client, receipt_path=receipt)

    assert status["result"] == "PASS_RESTORED_FROM_DURABLE_ACTIVATION_RECEIPT"
    restored = json.loads(client.values[worker.ECONOMIC_COHORT_KEY])
    assert restored == document["economic_cohort"]
    assert status["places_real_order"] is False


def test_republish_fails_closed_on_active_registry_mismatch(tmp_path) -> None:
    document = _document()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(document))
    active = _active()
    active["registry_generation"] = 4

    with pytest.raises(ValueError, match="COHORT_BINDING_VALIDATION_FAILED"):
        worker.republish(FakeRedis(active), receipt_path=receipt)


def test_republish_fails_closed_on_existing_cohort_conflict(tmp_path) -> None:
    document = _document()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(document))
    client = FakeRedis(_active(), legacy=document["legacy_serving_cohort"])
    client.values[worker.ECONOMIC_COHORT_KEY] = json.dumps({"cohort_id": "other"})

    with pytest.raises(ValueError, match="ECONOMIC_COHORT_CONFLICT"):
        worker.republish(client, receipt_path=receipt)
