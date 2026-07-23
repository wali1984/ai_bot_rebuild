from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer import (
    profiled_research_finalized_outcome_ledger_v1 as outcome,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.profiled_research_finalized_outcome_ledger_v1 import (  # noqa: E501
    ProfiledResearchFinalizedOutcomeLedgerV1,
    ProfiledResearchFinalizedOutcomeV1IntegrityError,
    ProfiledResearchFinalizedOutcomeV1ValidationError,
    ProfiledResearchFinalizedOutcomeWriterLease,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_commitment_v1 import (  # noqa: E501
    ProfiledResearchShadowHypothesisCommitmentLedgerV1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_research_shadow_hypothesis_commitment_v1 as commitment_support,
)


@pytest.fixture(autouse=True)
def _clear_inference_order_registry():  # noqa: ANN201
    inference = commitment_support.inference_support.inference
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    yield
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001


def _clock(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _committed_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # noqa: ANN202
    store, closure, hypothesis = commitment_support._bundle(  # noqa: SLF001
        tmp_path,
        monkeypatch,
    )
    commitment_ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "commitments.sqlite3"
    )
    committed = commitment_ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    return store, commitment_ledger, committed


def _path_bounds(decision_time: str) -> tuple[int, int]:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = _clock(decision_time) - epoch
    decision_us = (
        delta.days * 86_400 * 1_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    decision_ms = decision_us // 1_000
    target_ms = (decision_us + 900 * 1_000_000 + 999) // 1_000
    start_close_ms = ((decision_ms + 1) // 300_000 + 1) * 300_000 - 1
    end_close_ms = ((target_ms + 300_000) // 300_000) * 300_000 - 1
    return start_close_ms, end_close_ms


def _label_rows(
    committed,  # noqa: ANN001
    *,
    final_close: float = 102.0,
    ingested_at_ms: int | None = None,
) -> list[dict[str, object]]:
    start_close_ms, end_close_ms = _path_bounds(committed.decision_time)
    closes = list(range(start_close_ms, end_close_ms + 1, 300_000))
    rows: list[dict[str, object]] = []
    for index, close_ms in enumerate(closes):
        open_ms = close_ms - 299_999
        close_price = (
            final_close
            if index == len(closes) - 1
            else 100.2 + 0.2 * index
        )
        high = 300.0 if index == 0 else max(103.0, close_price)
        low = min(99.0 + 0.1 * index, close_price)
        received = ingested_at_ms if ingested_at_ms is not None else close_ms + 1
        candle = canonical_from_binance_rest(
            [
                open_ms,
                100.05,
                high,
                low,
                close_price,
                10.0,
                close_ms,
                1000.0,
                10,
                5.0,
                500.0,
            ],
            symbol=committed.symbol,
            timeframe="5m",
            ingested_at=received,
        )
        rows.append(candle.to_dict())
    return rows


def _set_outcome_clocks(
    monkeypatch: pytest.MonkeyPatch,
    start: datetime,
    *,
    count: int = 8,
) -> None:
    values = iter(start + timedelta(microseconds=index) for index in range(count))
    monkeypatch.setattr(outcome, "_utc_now", lambda: next(values))


def _ready_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    final_close: float = 102.0,
    ingested_at_ms: int | None = None,
    observed_at: datetime | None = None,
):  # noqa: ANN202
    store, commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    rows = _label_rows(
        committed,
        final_close=final_close,
        ingested_at_ms=ingested_at_ms,
    )
    append = archive.append_candles(rows)
    start = observed_at or datetime.now(UTC) + timedelta(seconds=5)
    _set_outcome_clocks(monkeypatch, start)
    ledger = ProfiledResearchFinalizedOutcomeLedgerV1(
        tmp_path / "outcomes.sqlite3"
    )
    return store, commitment_ledger, committed, archive, append, rows, ledger


def _mature(ready):  # noqa: ANN001, ANN202
    store, _commitment_ledger, committed, archive, _append, _rows, ledger = ready
    return ledger.mature_hypothesis(
        committed_hypothesis=committed,
        label_archive=archive,
        store=store,
    )


def test_matures_exact_selected_long_outcome_and_remains_non_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, rows, ledger = ready

    matured = _mature(ready)
    economics = matured.economics
    calibration = matured.calibration_row

    entry = 100.05
    raw_return = (float(rows[-1]["close"]) - entry) / entry * 10_000.0
    fee, spread, impact, funding = economics["cost_feature_values"]
    long_cost = 2.0 * fee + spread + 2.0 * impact + funding
    assert economics["raw_market_return_bps"] == pytest.approx(raw_return)
    assert economics["long_total_cost_bps"] == pytest.approx(long_cost)
    assert economics["selected_action"] == "long"
    assert economics["selected_action_net_pnl_bps"] == pytest.approx(
        raw_return - long_cost
    )
    assert economics["selected_action_profitable"] is True
    assert economics["postdecision_excursion_candle_count"] == 3
    assert economics["selected_action_max_favorable_excursion_bps"] < 1_000.0
    assert economics["predecision_overlap_excluded_from_excursion"] is True
    assert calibration["eligible"] is True
    assert calibration["selected_directional_action"] == "long"
    assert calibration["raw_probability"] == 0.72
    assert calibration["observed_strictly_positive_net_pnl"] is True
    assert calibration["raw_brier_contribution"] == pytest.approx((0.72 - 1.0) ** 2)
    assert len(matured.authorization) == 18
    assert set(matured.authorization.values()) == {False}
    assert matured.runtime_wired is False
    assert matured.trainer_admission_authorized is False
    assert matured.calibration_input_authorized is False
    assert matured.paper_trading_authorized is False
    assert matured.live_execution_authorized is False
    assert _clock(matured.actual_label_available_at) <= _clock(
        matured.maturation_observed_at
    ) < _clock(matured.commit_observed_at)
    assert _clock(matured.commit_observed_at) <= _clock(matured.commit_prepared_at)
    assert _clock(matured.commit_observed_at) < _clock(
        matured.postcommit_observed_at
    ) <= _clock(matured.postcommit_readback_at)
    integrity = ledger.verify_integrity(store=store)
    assert integrity.total_finalized_outcomes == 1
    assert integrity.cas_outcomes_verified == 1
    assert integrity.cas_label_candles_verified == 4
    assert integrity.cas_head_anchors_verified == 1
    assert integrity.clock_causality_verified is True


def test_public_maturation_api_accepts_no_caller_clock_price_or_outcome() -> None:
    parameters = inspect.signature(
        ProfiledResearchFinalizedOutcomeLedgerV1.mature_hypothesis
    ).parameters

    assert tuple(parameters) == (
        "self",
        "committed_hypothesis",
        "label_archive",
        "store",
        "writer_lease",
    )
    forbidden = ("clock", "observed", "price", "return", "target", "outcome")
    assert not any(
        fragment in parameter
        for parameter in parameters
        for fragment in forbidden
        if parameter != "self"
    )


@pytest.mark.parametrize(
    ("selected_action", "selected_index", "raw_probability", "final_close"),
    (
        ("long", 1, 0.72, 102.0),
        ("short", 2, 0.64, 98.0),
        ("hold", 0, None, 102.0),
    ),
)
def test_selected_action_economics_preserve_ex_ante_action_and_funding_sign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selected_action: str,
    selected_index: int,
    raw_probability: float | None,
    final_close: float,
) -> None:
    store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    del store
    contract = committed.hypothesis_contract
    raw = dict(contract["raw_inference_payload"])
    raw["selected_action"] = selected_action
    raw["selected_action_index"] = selected_index
    raw["selected_directional_profitability_raw"] = raw_probability
    rows = _label_rows(committed, final_close=final_close)

    economics, calibration = outcome._derive_economics(  # noqa: SLF001
        contract=contract,
        raw=raw,
        label_rows=rows,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256="a" * 64,
        decision_time=committed.decision_time,
    )

    base = (
        2.0 * economics["fee_bps_per_side"]
        + economics["full_round_trip_spread_bps"]
        + 2.0 * economics["expected_slippage_bps_per_side"]
    )
    funding = economics["signed_horizon_funding_bps"]
    assert economics["long_total_cost_bps"] == pytest.approx(base + funding)
    assert economics["short_total_cost_bps"] == pytest.approx(base - funding)
    assert economics["selected_action"] == selected_action
    assert economics["hindsight_action_substituted_for_selected_action"] is False
    if selected_action == "hold":
        assert calibration["eligible"] is False
        assert calibration["raw_probability"] is None
        assert calibration["observed_strictly_positive_net_pnl"] is None
        assert calibration["raw_brier_contribution"] is None
        assert economics["selected_action_max_favorable_excursion_bps"] is None
        assert economics["selected_action_max_adverse_excursion_bps"] is None
    else:
        selected_net = economics[f"counterfactual_{selected_action}_net_pnl_bps"]
        assert economics["selected_action_net_pnl_bps"] == selected_net
        assert calibration["observed_strictly_positive_net_pnl"] is (
            selected_net > 0.0
        )


def test_rejects_maturation_before_earliest_label_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    archive = DurableCanonical5mLabelArchive(tmp_path / "unused-labels.sqlite3")
    ledger = ProfiledResearchFinalizedOutcomeLedgerV1(tmp_path / "early.sqlite3")
    _set_outcome_clocks(
        monkeypatch,
        _clock(committed.label_earliest_available_at) - timedelta(microseconds=1),
    )

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1ValidationError,
        match="PROFILED_OUTCOME_EARLIEST_LABEL_TIME_NOT_REACHED",
    ):
        ledger.mature_hypothesis(
            committed_hypothesis=committed,
            label_archive=archive,
            store=store,
        )


@pytest.mark.parametrize("offset_microseconds", (-1, 0))
def test_exact_actual_availability_boundary_is_microsecond_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offset_microseconds: int,
) -> None:
    future = datetime.now(UTC) + timedelta(seconds=60)
    available_ms = outcome._epoch_microseconds(future) // 1_000  # noqa: SLF001
    observed = outcome._datetime_from_epoch_milliseconds(available_ms) + timedelta(  # noqa: SLF001
        microseconds=offset_microseconds
    )
    ready = _ready_bundle(
        tmp_path,
        monkeypatch,
        ingested_at_ms=available_ms,
        observed_at=observed,
    )

    if offset_microseconds < 0:
        with pytest.raises(
            ProfiledResearchFinalizedOutcomeV1ValidationError,
            match="PROFILED_OUTCOME_LABEL_PATH_NOT_MATURE",
        ):
            _mature(ready)
    else:
        matured = _mature(ready)
        assert matured.actual_label_available_at == outcome._format_microsecond(  # noqa: SLF001
            observed
        )


def test_rejects_archive_receipt_committed_after_internal_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(
        tmp_path,
        monkeypatch,
        observed_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1ValidationError,
        match="PROFILED_OUTCOME_LABEL_PATH_NOT_MATURE",
    ):
        _mature(ready)


@pytest.mark.parametrize(
    "clock_offsets",
    (
        (0, 0, 1),
        (0, 1, 1),
        (0, -1, 1),
        (0, 1, 0),
    ),
)
def test_rejects_raw_internal_clock_ties_instead_of_synthesizing_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock_offsets: tuple[int, int, int],
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    base = datetime.now(UTC) + timedelta(seconds=5)
    clocks = iter(base + timedelta(microseconds=value) for value in clock_offsets)
    monkeypatch.setattr(outcome, "_utc_now", lambda: next(clocks))

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1ValidationError,
        match="PROFILED_OUTCOME_(COMMIT|POSTCOMMIT)_CLOCK_NOT_AFTER",
    ):
        _mature(ready)


def test_exact_microsecond_horizon_uses_four_finalized_candles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matured = _mature(_ready_bundle(tmp_path, monkeypatch))
    proof = matured.outcome_contract["label_path_proof_at_maturation"]
    start, end = _path_bounds(matured.decision_time)

    assert proof["start_close_time_ms"] == start
    assert proof["end_close_time_ms"] == end
    assert proof["expected_rows"] == 4
    assert proof["loaded_rows"] == 4
    assert proof["strictly_after_decision_verified"] is True
    assert proof["horizon_endpoint_verified"] is True


def test_decision_one_microsecond_after_open_excludes_overlap_without_float_rounding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    contract = committed.hypothesis_contract
    raw = contract["raw_inference_payload"]
    rows = _label_rows(committed)
    first_open_ms = int(rows[0]["candle_open_time"])
    exact_decision = outcome._format_microsecond(  # noqa: SLF001
        outcome._datetime_from_epoch_milliseconds(first_open_ms)  # noqa: SLF001
        + timedelta(microseconds=1)
    )

    economics, _calibration = outcome._derive_economics(  # noqa: SLF001
        contract=contract,
        raw=raw,
        label_rows=rows,
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256="f" * 64,
        decision_time=exact_decision,
    )

    assert outcome._epoch_microseconds(_clock(exact_decision)) % 1_000 == 1  # noqa: SLF001
    assert economics["postdecision_excursion_candle_count"] == len(rows) - 1
    assert economics["selected_action_max_favorable_excursion_bps"] < 1_000.0


def test_missing_canonical_path_row_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    archive = DurableCanonical5mLabelArchive(tmp_path / "gapped-labels.sqlite3")
    rows = _label_rows(committed)
    archive.append_candles(rows[:1] + rows[2:])
    _set_outcome_clocks(monkeypatch, datetime.now(UTC) + timedelta(seconds=5))
    ledger = ProfiledResearchFinalizedOutcomeLedgerV1(tmp_path / "gapped.sqlite3")

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1ValidationError,
        match="PROFILED_OUTCOME_LABEL_PATH_NOT_MATURE",
    ):
        ledger.mature_hypothesis(
            committed_hypothesis=committed,
            label_archive=archive,
            store=store,
        )


def test_identical_maturation_retry_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    first = _mature(ready)
    second = _mature(ready)

    assert second.transaction_id == first.transaction_id
    assert second.outcome_artifact_sha256 == first.outcome_artifact_sha256
    assert second.append_receipt_sha256 == first.append_receipt_sha256
    assert second.postcommit_readback_receipt_sha256 == (
        first.postcommit_readback_receipt_sha256
    )


def test_reopen_remains_bound_to_scoped_labels_after_archive_tail_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, committed, archive, _append, rows, ledger = ready
    matured = _mature(ready)
    prior_artifact = matured.outcome_artifact_sha256
    prior_proof = matured.outcome_contract["label_path_proof_at_maturation"]
    last_close_ms = int(rows[-1]["candle_close_time"])
    next_open_ms = last_close_ms + 1
    next_close_ms = last_close_ms + 300_000
    tail = canonical_from_binance_rest(
        [
            next_open_ms,
            102.0,
            103.0,
            101.0,
            102.5,
            10.0,
            next_close_ms,
            1000.0,
            10,
            5.0,
            500.0,
        ],
        symbol=committed.symbol,
        timeframe="5m",
        ingested_at=next_close_ms + 1,
    )
    archive.append_candles([tail.to_dict()])

    reopened = ledger.open_matured_outcome(
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        committed_hypothesis=committed,
        label_archive=archive,
        store=store,
    )
    assert reopened.outcome_artifact_sha256 == prior_artifact
    assert reopened.outcome_contract["label_path_proof_at_maturation"] == prior_proof


def test_recovers_append_commit_before_postcommit_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    original = ledger._write_postcommit  # noqa: SLF001

    def injected_crash(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("INJECTED_AFTER_APPEND_COMMIT")

    monkeypatch.setattr(ledger, "_write_postcommit", injected_crash)
    with pytest.raises(RuntimeError, match="INJECTED_AFTER_APPEND_COMMIT"):
        _mature(ready)
    connection = sqlite3.connect(ledger.path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_finalized_outcomes"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_finalized_outcome_postcommit_receipts"
        ).fetchone()[0] == 0
    finally:
        connection.close()

    monkeypatch.setattr(ledger, "_write_postcommit", original)
    _set_outcome_clocks(monkeypatch, datetime.now(UTC) + timedelta(seconds=20))
    recovered = ledger.recover_pending_postcommit_readbacks(store=store)
    assert recovered["pending_transactions"] == 1
    assert recovered["recovered_transactions"] == 1
    assert ledger.verify_integrity(store=store).postcommit_receipts_verified == 1


def test_recovers_database_head_before_external_catalog_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    original = ledger._publish_head_catalog  # noqa: SLF001

    def injected_crash(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("INJECTED_BEFORE_EXTERNAL_HEAD_PUBLICATION")

    monkeypatch.setattr(ledger, "_publish_head_catalog", injected_crash)
    with pytest.raises(RuntimeError, match="INJECTED_BEFORE_EXTERNAL_HEAD_PUBLICATION"):
        _mature(ready)
    monkeypatch.setattr(ledger, "_publish_head_catalog", original)

    recovered = ledger.recover_pending_postcommit_readbacks(store=store)
    assert recovered["pending_transactions"] == 0
    assert ledger.verify_integrity(store=store).cas_head_anchors_verified == 1


def test_fresh_process_reopens_committed_hypothesis_and_finalized_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, commitment_ledger, committed, archive, _append, _rows, ledger = ready
    matured = _mature(ready)
    repo = Path(__file__).resolve().parents[6]
    script = """
import json
import sys
from pathlib import Path
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer import (
    durable_canonical_5m_label_archive as labels,
    profiled_research_finalized_outcome_ledger_v1 as outcomes,
    profiled_research_shadow_hypothesis_commitment_v1 as commitments,
)
store = ImmutableSourcePayloadStore(Path(sys.argv[1]))
committed = commitments.ProfiledResearchShadowHypothesisCommitmentLedgerV1(
    Path(sys.argv[2])
).open_committed_hypothesis(
    hypothesis_artifact_sha256=sys.argv[5],
    store=store,
)
opened = outcomes.ProfiledResearchFinalizedOutcomeLedgerV1(
    Path(sys.argv[3])
).open_matured_outcome(
    hypothesis_artifact_sha256=sys.argv[5],
    committed_hypothesis=committed,
    label_archive=labels.DurableCanonical5mLabelArchive(Path(sys.argv[4])),
    store=store,
)
print(json.dumps({
    "artifact": opened.outcome_artifact_sha256,
    "runtime": opened.runtime_wired,
}, sort_keys=True))
"""

    restarted = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            script,
            str(store.root_path),
            str(commitment_ledger.path),
            str(ledger.path),
            str(archive.path),
            committed.hypothesis_artifact_sha256,
        ],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(restarted.stdout) == {
        "artifact": matured.outcome_artifact_sha256,
        "runtime": False,
    }


@pytest.mark.parametrize("missing_kind", ("outcome", "candle"))
def test_missing_cas_evidence_fails_without_self_healing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_kind: str,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, committed, archive, _append, _rows, ledger = ready
    matured = _mature(ready)
    if missing_kind == "outcome":
        missing_sha = matured.outcome_artifact_sha256
    else:
        missing_sha = matured.outcome_contract["label_candle_inventory"][0][
            "candle_cas_address"
        ]["payload_sha256"]
    missing_path = store.path_for(missing_sha)
    missing_path.unlink()

    with pytest.raises(ProfiledResearchFinalizedOutcomeV1IntegrityError):
        ledger.open_matured_outcome(
            hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
            committed_hypothesis=committed,
            label_archive=archive,
            store=store,
        )
    assert not missing_path.exists()


def test_factory_result_seal_rejects_public_field_forgery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matured = _mature(_ready_bundle(tmp_path, monkeypatch))
    forged = replace(matured, selected_action="short")

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1IntegrityError,
        match="PROFILED_OUTCOME_RESULT_FACTORY_SEAL_INVALID",
    ):
        _ = forged.authorization


@pytest.mark.parametrize("lease_mode", ("constructor", "per_call"))
def test_result_validation_reuses_active_external_writer_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lease_mode: str,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, committed, archive, _append, _rows, original = ready
    path = original.path
    lease = ProfiledResearchFinalizedOutcomeWriterLease.acquire(path)
    try:
        ledger = ProfiledResearchFinalizedOutcomeLedgerV1(
            path,
            writer_lease=lease if lease_mode == "constructor" else None,
        )
        matured = ledger.mature_hypothesis(
            committed_hypothesis=committed,
            label_archive=archive,
            store=store,
            writer_lease=lease if lease_mode == "per_call" else None,
        )
        assert matured.authorization == outcome._AUTHORIZATION  # noqa: SLF001
    finally:
        lease.release()


def test_independent_reader_fails_closed_while_writer_lease_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    _mature(ready)
    lease = ProfiledResearchFinalizedOutcomeWriterLease.acquire(ledger.path)
    try:
        independent = ProfiledResearchFinalizedOutcomeLedgerV1(ledger.path)
        with pytest.raises(
            ProfiledResearchFinalizedOutcomeV1IntegrityError,
            match="PROFILED_OUTCOME_READER_LEASE_WRITER_ACTIVE",
        ):
            independent.verify_integrity(store=store)
    finally:
        lease.release()


def test_forged_committed_result_is_rejected_before_label_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, committed, archive, _append, _rows, ledger = ready
    forged = replace(committed, hypothesis_artifact_sha256="0" * 64)

    with pytest.raises(ProfiledResearchFinalizedOutcomeV1IntegrityError):
        ledger.mature_hypothesis(
            committed_hypothesis=forged,
            label_archive=archive,
            store=store,
        )


@pytest.mark.parametrize(
    "semantic_mutation",
    ("economics", "proof", "label_digest", "range_digest", "unknown"),
)
def test_source_free_artifact_validation_rejects_self_consistent_contradictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    semantic_mutation: str,
) -> None:
    matured = _mature(_ready_bundle(tmp_path, monkeypatch))
    artifact = json.loads(json.dumps(matured.outcome_contract))
    if semantic_mutation == "economics":
        artifact["economics"]["selected_action_net_pnl_bps"] += 1.0
        artifact["calibration_row"]["selected_action_net_pnl_bps"] += 1.0
    elif semantic_mutation == "proof":
        artifact["label_path_proof_at_maturation"]["pit_available_at_verified"] = False
    elif semantic_mutation == "label_digest":
        artifact["label_path_proof_at_maturation"]["label_path_sha256"] = "d" * 64
    elif semantic_mutation == "range_digest":
        artifact["label_path_proof_at_maturation"]["range_proof"][
            "range_sha256"
        ] = "e" * 64
    else:
        artifact["future_label"] = 1.0
    material = {
        key: value for key, value in artifact.items() if key != "outcome_material_sha256"
    }
    artifact["outcome_material_sha256"] = outcome._sha256(material)  # noqa: SLF001

    with pytest.raises(ProfiledResearchFinalizedOutcomeV1IntegrityError):
        outcome._validate_artifact_structure(artifact)  # noqa: SLF001


def test_schema_trigger_tamper_fails_integrity_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    _mature(ready)
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("DROP INDEX profiled_finalized_outcome_decision_time")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1IntegrityError,
        match="PROFILED_OUTCOME_SCHEMA_INVALID",
    ):
        ledger.verify_integrity(store=store)


def test_suffix_truncation_is_exposed_by_external_head_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    _mature(ready)
    tables = (
        "profiled_finalized_outcome_head_anchors",
        "profiled_finalized_outcome_postcommit_receipts",
        "profiled_finalized_outcome_append_receipts",
        "profiled_finalized_outcomes",
    )
    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            connection.execute(f"DROP TRIGGER {table}_no_delete")  # noqa: S608
            connection.execute(f"DELETE FROM {table}")  # noqa: S608
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ProfiledResearchFinalizedOutcomeV1IntegrityError):
        ledger.verify_integrity(store=store)


def test_database_size_resource_bound_is_checked_before_sqlite_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    store, _commitment_ledger, _committed, _archive, _append, _rows, ledger = ready
    _mature(ready)
    monkeypatch.setattr(outcome, "_MAX_LEDGER_DATABASE_BYTES", 1)

    with pytest.raises(ProfiledResearchFinalizedOutcomeV1IntegrityError):
        ledger.verify_integrity(store=store)


def test_head_catalog_rejects_nonhex_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    _mature(ready)
    ledger = ready[-1]
    sha_root = outcome._head_catalog_root(ledger.path) / "sha256"  # noqa: SLF001
    (sha_root / "ZZ").mkdir()

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1IntegrityError,
        match="PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID",
    ):
        ledger._observed_head_catalog_digests()  # noqa: SLF001


def test_head_catalog_rejects_broken_sha_root_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    _mature(ready)
    ledger = ready[-1]
    sha_root = outcome._head_catalog_root(ledger.path) / "sha256"  # noqa: SLF001
    sha_root.rename(sha_root.with_name("sha256-retained-for-test"))
    sha_root.symlink_to(tmp_path / "missing-sha-root", target_is_directory=True)

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1IntegrityError,
        match="PROFILED_OUTCOME_HEAD_CATALOG_LAYOUT_INVALID",
    ):
        ledger._observed_head_catalog_digests()  # noqa: SLF001


def test_head_catalog_file_traversal_stops_at_record_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_bundle(tmp_path, monkeypatch)
    _mature(ready)
    ledger = ready[-1]
    sha_root = outcome._head_catalog_root(ledger.path) / "sha256"  # noqa: SLF001
    dummy_sha = "0" * 64
    dummy_shard = sha_root / dummy_sha[:2]
    dummy_shard.mkdir(exist_ok=True)
    (dummy_shard / dummy_sha).write_bytes(b"{}")
    monkeypatch.setattr(outcome, "_MAX_LEDGER_RECORDS", 1)

    with pytest.raises(
        ProfiledResearchFinalizedOutcomeV1IntegrityError,
        match="PROFILED_OUTCOME_HEAD_CATALOG_RESOURCE_BOUND_EXCEEDED",
    ):
        ledger._observed_head_catalog_digests()  # noqa: SLF001


def test_exact_zero_net_is_not_profitable_and_never_changes_selected_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    contract = committed.hypothesis_contract
    raw = dict(contract["raw_inference_payload"])
    entry = contract["decision_reference_binding"]["mid"]
    fee, spread, impact, funding = contract["cost_evidence_binding"][
        "ordered_values"
    ]
    long_cost = 2.0 * fee + spread + 2.0 * impact + funding
    exact_zero_close = entry * (1.0 + long_cost / 10_000.0)

    economics, calibration = outcome._derive_economics(  # noqa: SLF001
        contract=contract,
        raw=raw,
        label_rows=_label_rows(committed, final_close=exact_zero_close),
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256="b" * 64,
        decision_time=committed.decision_time,
    )

    assert economics["selected_action"] == "long"
    assert economics["selected_action_net_pnl_bps"] == pytest.approx(0.0, abs=1e-12)
    assert economics["selected_action_profitable"] is False
    assert economics["diagnostic_best_after_cost_action"] == "hold"
    assert calibration["observed_strictly_positive_net_pnl"] is False
    assert economics["static_market_threshold_used"] is False


@pytest.mark.parametrize("signed_funding", (-2.5, 3.0))
def test_signed_funding_is_applied_oppositely_to_long_and_short_costs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signed_funding: float,
) -> None:
    _store, _commitment_ledger, committed = _committed_bundle(tmp_path, monkeypatch)
    contract = json.loads(json.dumps(committed.hypothesis_contract))
    contract["cost_evidence_binding"]["ordered_values"][-1] = signed_funding
    raw = contract["raw_inference_payload"]

    economics, _calibration = outcome._derive_economics(  # noqa: SLF001
        contract=contract,
        raw=raw,
        label_rows=_label_rows(committed),
        hypothesis_identity_sha256=committed.hypothesis_identity_sha256,
        hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
        label_source_binding_sha256="c" * 64,
        decision_time=committed.decision_time,
    )

    assert economics["long_total_cost_bps"] - economics[
        "base_execution_cost_bps"
    ] == pytest.approx(signed_funding)
    assert economics["short_total_cost_bps"] - economics[
        "base_execution_cost_bps"
    ] == pytest.approx(-signed_funding)


@pytest.mark.parametrize("final_close", (102.0, 99.0))
def test_directional_calibration_records_both_binary_classes_with_raw_brier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_close: float,
) -> None:
    matured = _mature(
        _ready_bundle(tmp_path, monkeypatch, final_close=final_close)
    )
    row = matured.calibration_row
    observed = matured.economics["selected_action_net_pnl_bps"] > 0.0

    assert row["observed_strictly_positive_net_pnl"] is observed
    assert row["raw_brier_contribution"] == pytest.approx(
        (row["raw_probability"] - (1.0 if observed else 0.0)) ** 2
    )
    assert row["fit_partition"] == "UNASSIGNED_REQUIRES_PURGED_TRAIN_ONLY_ADMISSION"
    assert row["calibration_input_authorized"] is False
