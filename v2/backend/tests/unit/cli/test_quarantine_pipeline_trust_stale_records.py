from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

import pytest

from app.cli.quarantine_pipeline_trust_stale_records import quarantine_pipeline_trust_stale_records


class FakeRedis:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.writes: list[tuple[str, str]] = []

    def scan_iter(self, match: str, count: int = 250):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key

    def type(self, key: str) -> str:
        value = self.data[key]
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict) and value.get("__redis_type") == "hash":
            return "hash"
        return "string"

    def get(self, key: str) -> str:
        return json.dumps(self.data[key])

    def set(self, key: str, value: str) -> None:
        self.writes.append(("set", key))
        self.data[key] = json.loads(value)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return [json.dumps(value) for value in self.data[key][start : end + 1]]

    def lset(self, key: str, index: int, value: str) -> None:
        self.writes.append(("lset", key))
        self.data[key][index] = json.loads(value)

    def hgetall(self, key: str) -> dict[str, str]:
        value = dict(self.data[key])
        value.pop("__redis_type", None)
        return {field: json.dumps(payload) for field, payload in value.items()}

    def hset(self, key: str, field: str, value: str) -> None:
        self.writes.append(("hset", key))
        self.data[key][field] = json.loads(value)


def stale_active_risk() -> dict[str, Any]:
    return {
        "risk_decision_id": "rd-old",
        "decision_id": "dec-old",
        "prediction_id": "pred-old",
        "symbol": "BTCUSDT",
        "risk_action": "allow",
        "pre_trade_allowed": True,
        "feature_cutoff": 1_700_000_000_000,
        "available_at": 1_700_000_000_000,
    }


def stale_inactive_prediction() -> dict[str, Any]:
    return {
        "prediction_id": "pred-old",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "paper_fill_allowed": False,
        "routes_to_orchestrator": False,
    }


def review_file(tmp_path: Path, rows: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> Path:
    path = tmp_path / "review.targets.json"
    path.write_text(json.dumps({"summary": summary or {}, "targets": rows}), encoding="utf-8")
    return path


def review_row(key: str, group: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "key": key,
        "review_group": group,
        "safe_to_apply": group == "SAFE_TO_QUARANTINE",
        "trust_schema_version": "missing",
        "active_state": False,
    }
    row.update(overrides)
    return row


def test_quarantine_dry_run_mutates_nothing(tmp_path: Path) -> None:
    client = FakeRedis({"v2:risk:decisions": stale_active_risk()})

    report = quarantine_pipeline_trust_stale_records(client=client, output_root=tmp_path, apply=False)

    assert report["dry_run"] is True
    assert report["records_targeted"] == 1
    assert client.writes == []
    assert client.data["v2:risk:decisions"]["pre_trade_allowed"] is True
    assert Path(report["backup_path"]).exists()


def test_quarantine_apply_backs_up_before_marking_stale_records(tmp_path: Path) -> None:
    client = FakeRedis({"v2:risk:decisions": stale_active_risk()})

    report = quarantine_pipeline_trust_stale_records(
        client=client,
        output_root=tmp_path,
        apply=True,
        require_backup=True,
    )

    assert report["dry_run"] is False
    assert client.writes == [("set", "v2:risk:decisions")]
    marked = client.data["v2:risk:decisions"]
    assert marked["quarantined"] is True
    assert marked["pre_trade_allowed"] is False
    assert marked["risk_action"] == "deny"
    backup_text = Path(report["backup_path"]).read_text(encoding="utf-8")
    assert '"pre_trade_allowed": true' in backup_text


def test_quarantine_marks_old_coinapi_microfeature_ineligible(tmp_path: Path) -> None:
    client = FakeRedis(
        {
            "v2:features:microfeat:BTCUSDT:1m": {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "features": {"imbalance_5": 0.1},
            }
        }
    )

    report = quarantine_pipeline_trust_stale_records(
        client=client,
        output_root=tmp_path,
        apply=True,
        require_backup=True,
    )

    assert report["records_targeted"] == 1
    marked = client.data["v2:features:microfeat:BTCUSDT:1m"]
    assert marked["feature_eligible"] is False
    assert marked["trainer_consumable"] is False
    assert marked["prediction_eligible"] is False
    assert "COINAPI_MICROFEATURE_MISSING_TRUST_TIMESTAMPS" in marked["quarantine_reasons"]


def test_only_review_group_safe_selects_only_safe_records(tmp_path: Path) -> None:
    safe_key = "v2:prediction:SAFEUSDT:1m"
    manual_key = "v2:prediction:MANUALUSDT:1m"
    dnt_key = "v2:prediction:DNTUSDT:1m"
    client = FakeRedis(
        {
            safe_key: stale_inactive_prediction(),
            manual_key: stale_inactive_prediction(),
            dnt_key: stale_inactive_prediction(),
        }
    )
    review = review_file(
        tmp_path,
        [
            review_row(safe_key, "SAFE_TO_QUARANTINE"),
            review_row(manual_key, "REQUIRES_MANUAL_REVIEW"),
            review_row(dnt_key, "DO_NOT_TOUCH"),
        ],
    )

    report = quarantine_pipeline_trust_stale_records(
        client=client,
        output_root=tmp_path,
        review_file=review,
        only_review_groups=("SAFE_TO_QUARANTINE",),
        exclude_review_groups=("REQUIRES_MANUAL_REVIEW", "DO_NOT_TOUCH"),
        expect_targets=1,
        max_targets=1,
        require_review_file=True,
        fail_if_manual_review_targeted=True,
        fail_if_do_not_touch_targeted=True,
        apply=False,
    )

    assert report["records_targeted"] == 1
    assert report["plan"][0]["redis_key"] == safe_key
    assert report["excluded_counts"]["review_group"] == 2
    assert client.writes == []


def test_unmatched_review_record_fails_closed(tmp_path: Path) -> None:
    client = FakeRedis({"v2:prediction:UNMATCHEDUSDT:1m": stale_inactive_prediction()})
    review = review_file(tmp_path, [review_row("v2:prediction:OTHERUSDT:1m", "SAFE_TO_QUARANTINE")])

    with pytest.raises(SystemExit, match="target not matched"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            require_review_file=True,
            apply=False,
        )


def test_review_fingerprint_mismatch_fails_closed(tmp_path: Path) -> None:
    key = "v2:prediction:SAFEUSDT:1m"
    client = FakeRedis({key: stale_inactive_prediction()})
    review = review_file(
        tmp_path,
        [review_row(key, "SAFE_TO_QUARANTINE")],
        summary={"target_keys_fingerprint": "not-the-current-target-fingerprint"},
    )

    with pytest.raises(SystemExit, match="review fingerprint mismatch"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            require_review_file=True,
            apply=False,
        )


def test_expect_targets_mismatch_fails(tmp_path: Path) -> None:
    key = "v2:prediction:SAFEUSDT:1m"
    client = FakeRedis({key: stale_inactive_prediction()})
    review = review_file(tmp_path, [review_row(key, "SAFE_TO_QUARANTINE")])

    with pytest.raises(SystemExit, match="does not match"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            expect_targets=2,
            apply=False,
        )


def test_max_targets_exceeded_fails(tmp_path: Path) -> None:
    key1 = "v2:prediction:SAFE1USDT:1m"
    key2 = "v2:prediction:SAFE2USDT:1m"
    client = FakeRedis({key1: stale_inactive_prediction(), key2: stale_inactive_prediction()})
    review = review_file(
        tmp_path,
        [review_row(key1, "SAFE_TO_QUARANTINE"), review_row(key2, "SAFE_TO_QUARANTINE")],
    )

    with pytest.raises(SystemExit, match="exceeds"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            max_targets=1,
            apply=False,
        )


def test_pipeline_trust_v3_selected_target_fails(tmp_path: Path) -> None:
    key = "v2:prediction:V3USDT:1m"
    row = stale_inactive_prediction()
    row.update({"trust_schema_version": "pipeline_trust_v3", "paper_fill_allowed": True})
    client = FakeRedis({key: row})
    review = review_file(tmp_path, [review_row(key, "SAFE_TO_QUARANTINE", trust_schema_version="pipeline_trust_v3")])

    with pytest.raises(SystemExit, match="pipeline_trust_v3"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            fail_if_v3_targeted=True,
            apply=False,
        )


def test_live_order_selected_target_fails(tmp_path: Path) -> None:
    key = "v2:live_order_transport:stale"
    client = FakeRedis({key: {"pre_trade_allowed": True, "prediction_id": "p1"}})
    review = review_file(tmp_path, [review_row(key, "SAFE_TO_QUARANTINE")])

    with pytest.raises(SystemExit, match="live/exchange order"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            patterns=(key,),
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            fail_if_live_order_targeted=True,
            apply=False,
        )


def test_apply_requires_backup_flag(tmp_path: Path) -> None:
    key = "v2:prediction:SAFEUSDT:1m"
    client = FakeRedis({key: stale_inactive_prediction()})
    review = review_file(tmp_path, [review_row(key, "SAFE_TO_QUARANTINE")])

    with pytest.raises(SystemExit, match="requires --require-backup"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            review_file=review,
            only_review_groups=("SAFE_TO_QUARANTINE",),
            apply=True,
        )


def test_scoped_apply_requires_review_file(tmp_path: Path) -> None:
    client = FakeRedis({"v2:prediction:SAFEUSDT:1m": stale_inactive_prediction()})

    with pytest.raises(SystemExit, match="requires --review-file"):
        quarantine_pipeline_trust_stale_records(
            client=client,
            output_root=tmp_path,
            apply=True,
            require_review_file=True,
            require_backup=True,
        )


def test_scoped_dry_run_report_includes_selected_and_excluded_counts(tmp_path: Path) -> None:
    safe_key = "v2:prediction:SAFEUSDT:1m"
    manual_key = "v2:prediction:MANUALUSDT:1m"
    client = FakeRedis({safe_key: stale_inactive_prediction(), manual_key: stale_inactive_prediction()})
    review = review_file(
        tmp_path,
        [review_row(safe_key, "SAFE_TO_QUARANTINE"), review_row(manual_key, "REQUIRES_MANUAL_REVIEW")],
    )

    report = quarantine_pipeline_trust_stale_records(
        client=client,
        output_root=tmp_path,
        review_file=review,
        only_review_groups=("SAFE_TO_QUARANTINE",),
        exclude_review_groups=("REQUIRES_MANUAL_REVIEW",),
        apply=False,
    )

    assert report["records_targeted"] == 1
    assert report["excluded_counts"]["review_group"] == 1
    assert report["selected_counts"]["by_review_group"] == {"SAFE_TO_QUARANTINE": 1}
    assert report["selected_counts"]["pipeline_trust_v3"] == 0
    assert report["selected_counts"]["live_or_exchange_order"] == 0
