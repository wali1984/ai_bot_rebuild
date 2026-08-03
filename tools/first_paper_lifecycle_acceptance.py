#!/usr/bin/env python3
"""Fail-closed current-epoch natural paper lifecycle acceptance controller.

The controller has no trading or exchange authority.  It waits for a naturally
persisted, proof-backed and protected current-session paper position, freezes the
lineage/accounting evidence, restarts canonical serving and then the paper loop,
proves reconstruction on a completed paper cycle, observes the ordinary
reduce-only close, reconciles accounting, and observes two additional cycles.

It never writes a fill, position, close, reservation, model, threshold or Redis
record.  Its only runtime mutations are the two explicitly authorized user-unit
restarts and atomic evidence/status files.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import redis

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop

POINTER_KEY = "v2:paper:account_epoch:current"
LEGACY_SESSION_KEY = "v2:paper:session"
PORTFOLIO_KEY = "v2:portfolio:state"
PAPER_STATUS_KEY = "v2:paper:trade_management:status"
PROOFS_KEY = "v2:paper:open_position_fill_proofs"
PROOF_MANIFEST_KEY = "v2:paper:open_position_fill_proofs:manifest"
PAPER_UNIT = "ai-bot-v2-trade-management-paper-loop.service"
SERVING_UNIT = "ai-bot-v2-canonical-prediction-serving.service"
LIVE_GATE = "blocked_human_only"


class AcceptanceBoundary(RuntimeError):
    """A hard prerequisite failed; no service restart is permitted."""


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_value(client: redis.Redis, key: str) -> Any:
    raw = client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AcceptanceBoundary(f"{key}:malformed_json") from exc


def _objects(value: object) -> list[dict[str, Any]]:
    return [dict(row) for row in value] if isinstance(value, list) and all(
        isinstance(row, Mapping) for row in value
    ) else []


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first(row: Mapping[str, Any], *fields: str) -> Any:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def _identity(row: Mapping[str, Any], fields: tuple[str, ...]) -> str | None:
    value = _first(row, *fields)
    return str(value) if value not in (None, "") else None


def _duplicate_count(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> int:
    identities = [_identity(row, fields) for row in rows]
    present = [value for value in identities if value]
    return len(present) - len(set(present))


def _epoch_key(epoch: int, leaf: str) -> str:
    return f"v2:paper:epoch:{epoch}:{leaf}"


def _safe_context(client: redis.Redis) -> dict[str, Any]:
    pointer = _json_value(client, POINTER_KEY)
    if not isinstance(pointer, Mapping) or pointer.get("schema_version") != "PaperAccountEpochV1":
        raise AcceptanceBoundary("paper_epoch_pointer:missing_or_invalid")
    session_id = pointer.get("paper_session_id")
    epoch = pointer.get("paper_account_epoch")
    if not isinstance(session_id, str) or not session_id:
        raise AcceptanceBoundary("paper_epoch_pointer:session_id_invalid")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        raise AcceptanceBoundary("paper_epoch_pointer:epoch_invalid")
    safety = {
        "paper_only": pointer.get("paper_only") is True,
        "live_gate": pointer.get("live_gate") == LIVE_GATE,
        "routes_to_live": pointer.get("routes_to_live") is False,
        "places_real_order": pointer.get("places_real_order") is False,
    }
    legacy_session = _json_value(client, LEGACY_SESSION_KEY)
    safety["exchange_action_taken"] = (
        pointer.get("exchange_action_taken") is False
        or (
            pointer.get("exchange_action_taken") is None
            and isinstance(legacy_session, Mapping)
            and legacy_session.get("exchange_action_taken") is False
        )
    )
    if not all(safety.values()):
        raise AcceptanceBoundary(f"paper_safety_boundary:{safety}")

    status = _json_value(client, PAPER_STATUS_KEY)
    if not isinstance(status, Mapping):
        raise AcceptanceBoundary("paper_status:missing_or_invalid")
    if status.get("paper_session_id") != session_id or status.get("paper_account_epoch") != epoch:
        raise AcceptanceBoundary("paper_status:epoch_identity_mismatch")
    for field, required in (
        ("paper_only", True),
        ("live_gate", LIVE_GATE),
        ("routes_to_live", False),
        ("places_real_order", False),
        ("exchange_action_taken", False),
    ):
        if status.get(field) != required:
            raise AcceptanceBoundary(f"paper_status:{field}_unsafe")

    manifest = _json_value(client, PROOF_MANIFEST_KEY)
    proofs = _objects(_json_value(client, PROOFS_KEY))
    if not isinstance(manifest, Mapping) or manifest.get("completed") is not True:
        raise AcceptanceBoundary("proof_store:backfill_incomplete")
    if manifest.get("initialization_state") not in {
        "EMPTY_INITIALIZED_PROOF_SET",
        "INITIALIZED_WITH_PROOFS",
        # Production paper loop writes this literal state once at least one
        # proof exists (v2_trade_management_paper_loop initialization
        # vocabulary); the acceptance tool must recognize the producer's
        # actual state names, not a never-written alias.
        "INITIALIZED_OR_BACKFILLED_PROOF_SET",
    }:
        raise AcceptanceBoundary("proof_store:uninitialized")
    if manifest.get("proof_count") != len(proofs):
        raise AcceptanceBoundary("proof_store:manifest_count_mismatch")

    positions = _objects(_json_value(client, _epoch_key(epoch, "positions")))
    fills = _objects(_json_value(client, _epoch_key(epoch, "accepted_fills")))
    closes = _objects(_json_value(client, _epoch_key(epoch, "closed_trades")))
    reservations = _objects(_json_value(client, _epoch_key(epoch, "reservations")))
    epoch_portfolio = _json_value(client, _epoch_key(epoch, "portfolio_state"))
    live_portfolio = _json_value(client, PORTFOLIO_KEY)
    portfolio = live_portfolio if isinstance(live_portfolio, Mapping) else epoch_portfolio
    if not isinstance(portfolio, Mapping):
        raise AcceptanceBoundary("portfolio:missing_or_invalid")
    if portfolio.get("paper_session_id") != session_id or portfolio.get("paper_account_epoch") != epoch:
        raise AcceptanceBoundary("portfolio:epoch_identity_mismatch")

    return {
        "pointer": dict(pointer),
        "session_id": session_id,
        "epoch": epoch,
        "status": dict(status),
        "manifest": dict(manifest),
        "proofs": proofs,
        "positions": positions,
        "fills": fills,
        "closes": closes,
        "reservations": reservations,
        "portfolio": dict(portfolio),
        "safety": safety,
    }


def _position_projection(position: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: position.get(field)
        for field in (
            "position_id",
            "position_generation_id",
            "prediction_id",
            "signal_id",
            "intent_id",
            "orchestrator_decision_id",
            "risk_decision_id",
            "allocation_id",
            "adaptive_policy_action_id",
            "entry_fill_id",
            "source_fill_ids",
            "symbol",
            "timeframe",
            "side",
            "net_quantity",
            "avg_entry_price",
            "gross_notional_usd",
            "effective_leverage",
            "allocated_margin_usd",
            "mandatory_stop_price",
            "stop_price",
            "time_exit_at",
            "checkpoint_generation",
            "checkpoint_id",
            "cohort_id",
            "paper_session_id",
            "paper_account_epoch",
        )
    }


def _find_binding(context: Mapping[str, Any], position: Mapping[str, Any]) -> tuple[dict, dict]:
    position_id = _identity(position, ("position_id",))
    if not position_id:
        raise AcceptanceBoundary("position:position_id_missing")
    proofs = [row for row in context["proofs"] if str(row.get("position_id") or "") == position_id]
    if len(proofs) != 1:
        raise AcceptanceBoundary(f"position:{position_id}:proof_count={len(proofs)}")
    proof = proofs[0]
    proof_reasons = paper_loop._paper_open_position_fill_proof_reasons(proof)  # noqa: SLF001
    binding_reasons = paper_loop._paper_position_proof_binding_reasons(  # noqa: SLF001
        position,
        proof,
    )
    if proof_reasons or binding_reasons:
        raise AcceptanceBoundary(
            f"position:{position_id}:proof_invalid:{sorted(set(proof_reasons + binding_reasons))}"
        )
    fill_id = str(proof.get("fill_id") or "")
    fills = [
        row
        for row in context["fills"]
        if _identity(row, ("fill_id", "accepted_fill_id", "entry_fill_id")) == fill_id
    ]
    if len(fills) != 1:
        raise AcceptanceBoundary(f"position:{position_id}:accepted_fill_count={len(fills)}")
    fill = fills[0]
    if fill.get("paper_session_id") != context["session_id"]:
        raise AcceptanceBoundary(f"position:{position_id}:fill_session_mismatch")
    if fill.get("paper_account_epoch") != context["epoch"]:
        raise AcceptanceBoundary(f"position:{position_id}:fill_epoch_mismatch")
    if fill.get("paper_only") is not True or any(
        fill.get(field) is True
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken")
    ):
        raise AcceptanceBoundary(f"position:{position_id}:fill_authority_unsafe")
    return proof, fill


def _protected(position: Mapping[str, Any]) -> bool:
    stop_price = _finite(_first(position, "mandatory_stop_price", "stop_price", "protective_stop_price"))
    stop_distance = _finite(
        _first(position, "mandatory_stop_distance_bps", "stop_distance_bps", "atr_stop_bps")
    )
    return bool((stop_price is not None and stop_price > 0.0) or (
        stop_distance is not None and stop_distance > 0.0
    ))


def _accounting_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    portfolio = context["portfolio"]
    return {
        "wallet_balance_usd": _finite(_first(portfolio, "wallet_balance_usd", "wallet_balance")),
        "equity_usd": _finite(_first(portfolio, "equity_usd", "equity")),
        "free_margin_usd": _finite(_first(portfolio, "free_margin_usd", "free_margin")),
        "used_margin_usd": _finite(_first(portfolio, "used_margin_usd", "used_margin")),
        "reserved_margin_usd": _finite(portfolio.get("reserved_margin_usd")),
        "realized_pnl_usd": _finite(portfolio.get("realized_pnl_usd")),
        "unrealized_pnl_usd": _finite(portfolio.get("unrealized_pnl_usd")),
    }


def _freeze(context: Mapping[str, Any], position: Mapping[str, Any]) -> dict[str, Any]:
    if context["status"].get("cycle_state") != "COMPLETED_CYCLE":
        raise AcceptanceBoundary("paper_cycle:not_completed_at_freeze")
    if not _protected(position):
        raise AcceptanceBoundary("position:mandatory_protection_missing")
    if position.get("paper_session_id") != context["session_id"]:
        raise AcceptanceBoundary("position:session_mismatch")
    if position.get("paper_account_epoch") != context["epoch"]:
        raise AcceptanceBoundary("position:epoch_mismatch")
    proof, fill = _find_binding(context, position)
    lineage_fields = (
        "prediction_id",
        "orchestrator_decision_id",
        "risk_decision_id",
        "signal_id",
        "intent_id",
        "allocation_id",
        "adaptive_policy_action_id",
        "checkpoint_generation",
        "checkpoint_id",
        "cohort_id",
    )
    # ``paper_strategy_cohort_id`` is the canonical cohort identity stamped by
    # the production loop on positions/fills; the bare ``cohort_id`` alias is
    # only present on some historical rows.  Accept either spelling without
    # weakening the non-empty requirement.
    lineage_aliases: dict[str, tuple[str, ...]] = {
        field: (field,) for field in lineage_fields
    }
    lineage_aliases["cohort_id"] = ("cohort_id", "paper_strategy_cohort_id")
    lineage = {
        field: _first(position, *aliases)
        or _first(fill, *aliases)
        or _first(proof, *aliases)
        for field, aliases in lineage_aliases.items()
    }
    missing = [field for field, value in lineage.items() if value in (None, "")]
    if missing:
        raise AcceptanceBoundary(f"lineage:missing:{','.join(missing)}")
    return {
        "frozen_at": _utc_now(),
        "paper_session_id": context["session_id"],
        "paper_account_epoch": context["epoch"],
        "cycle_generated_utc": context["status"].get("generated_utc"),
        "position": _position_projection(position),
        "position_sha256": _sha256(_position_projection(position)),
        "fill": fill,
        "fill_sha256": _sha256(fill),
        "proof": proof,
        "proof_sha256": _sha256(proof),
        "proof_manifest_sha256": context["manifest"].get("manifest_sha256"),
        "lineage": lineage,
        "accounting": _accounting_projection(context),
        "accepted_fills_sha256": _sha256(context["fills"]),
        "proofs_sha256": _sha256(context["proofs"]),
        "safety": context["safety"],
    }


def _service_state(unit: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "-p",
            "NRestarts",
            "-p",
            "ExecMainStatus",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    values["unit"] = unit
    return values


def _restart(unit: str, *, timeout_seconds: float = 60.0) -> dict[str, Any]:
    before = _service_state(unit)
    subprocess.run(["systemctl", "--user", "restart", unit], check=True, timeout=60)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        after = _service_state(unit)
        if after.get("ActiveState") == "active" and int(after.get("MainPID") or 0) > 0:
            return {"before": before, "after": after, "restarted_at": _utc_now()}
        time.sleep(1.0)
    raise AcceptanceBoundary(f"service:{unit}:restart_not_active")


def _wait_new_cycle(
    client: redis.Redis,
    baseline_cycle: object,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        context = _safe_context(client)
        cycle = context["status"].get("generated_utc")
        if cycle and cycle != baseline_cycle and context["status"].get("cycle_state") == "COMPLETED_CYCLE":
            return context
        time.sleep(poll_seconds)
    raise AcceptanceBoundary("paper_cycle:post_restart_timeout")


def _reconstruction_checks(
    frozen: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    position_id = str(frozen["position"].get("position_id") or "")
    positions = [row for row in context["positions"] if str(row.get("position_id") or "") == position_id]
    if len(positions) != 1:
        raise AcceptanceBoundary(f"reconstruction:position_count={len(positions)}")
    position = positions[0]
    proof, fill = _find_binding(context, position)
    accounting = _accounting_projection(context)
    before_accounting = frozen["accounting"]
    stable_accounting_fields = ("wallet_balance_usd", "used_margin_usd", "reserved_margin_usd")
    accounting_match = all(
        accounting.get(field) is not None
        and before_accounting.get(field) is not None
        and math.isclose(accounting[field], before_accounting[field], rel_tol=0.0, abs_tol=0.01)
        for field in stable_accounting_fields
    )
    checks = {
        "position_identity_match": _sha256(_position_projection(position)) == frozen["position_sha256"],
        "fill_identity_match": _sha256(fill) == frozen["fill_sha256"],
        "proof_identity_match": _sha256(proof) == frozen["proof_sha256"],
        "accepted_fills_match": _sha256(context["fills"]) == frozen["accepted_fills_sha256"],
        "proofs_match": _sha256(context["proofs"]) == frozen["proofs_sha256"],
        "accounting_match": accounting_match,
        "duplicate_fill_count": _duplicate_count(context["fills"], ("fill_id", "accepted_fill_id")),
        "duplicate_close_count": _duplicate_count(context["closes"], ("close_id", "trade_id")),
        "reservation_leak_count": len(context["reservations"]),
    }
    checks["restart_reconstruction_match"] = (
        all(checks[field] is True for field in (
            "position_identity_match",
            "fill_identity_match",
            "proof_identity_match",
            "accepted_fills_match",
            "proofs_match",
            "accounting_match",
        ))
        and checks["duplicate_fill_count"] == 0
        and checks["duplicate_close_count"] == 0
        and checks["reservation_leak_count"] == 0
    )
    if not checks["restart_reconstruction_match"]:
        raise AcceptanceBoundary(f"reconstruction:mismatch:{checks}")
    return checks


def _matching_close(context: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any] | None:
    identifiers = {
        str(value)
        for value in (
            frozen["position"].get("position_id"),
            frozen["lineage"].get("prediction_id"),
            frozen["fill"].get("fill_id"),
        )
        if value not in (None, "")
    }
    matches = []
    for row in context["closes"]:
        row_ids = {
            str(value)
            for value in (
                row.get("position_id"),
                row.get("prediction_id"),
                row.get("entry_fill_id"),
                row.get("source_fill_id"),
            )
            if value not in (None, "")
        }
        if identifiers.intersection(row_ids):
            matches.append(row)
    if len(matches) > 1:
        raise AcceptanceBoundary("close:duplicate_matching_close")
    return matches[0] if matches else None


def _close_checks(context: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
    close = _matching_close(context, frozen)
    if close is None:
        raise AcceptanceBoundary("close:not_found")
    remaining = _finite(close.get("remaining_quantity_after_close"))
    close_valid = (
        close.get("reduce_only") is True
        and close.get("close_position") is True
        and remaining is not None
        and math.isclose(remaining, 0.0, abs_tol=1e-12)
        and close.get("margin_release_required") is True
    )
    if not close_valid:
        raise AcceptanceBoundary("close:reduce_only_contract_invalid")
    if context["positions"]:
        raise AcceptanceBoundary("close:position_not_flat")
    accounting = _accounting_projection(context)
    starting = _finite(context["pointer"].get("starting_equity_usd"))
    realized = sum(
        _finite(_first(row, "realized_net_pnl_usd", "realized_pnl_usd", "net_realized_pnl_usd")) or 0.0
        for row in context["closes"]
    )
    wallet = accounting["wallet_balance_usd"]
    equity = accounting["equity_usd"]
    accounting_reconciled = (
        starting is not None
        and wallet is not None
        and equity is not None
        and math.isclose(wallet, starting + realized, rel_tol=0.0, abs_tol=0.02)
        and math.isclose(equity, wallet, rel_tol=0.0, abs_tol=0.02)
        and math.isclose(accounting["used_margin_usd"] or 0.0, 0.0, abs_tol=0.005)
        and math.isclose(accounting["reserved_margin_usd"] or 0.0, 0.0, abs_tol=0.005)
        and not context["reservations"]
    )
    if not accounting_reconciled:
        raise AcceptanceBoundary("close:accounting_not_reconciled")
    return {
        "close": close,
        "close_sha256": _sha256(close),
        "accounting": accounting,
        "current_session_realized_pnl_sum_usd": realized,
        "accounting_reconciled": True,
        "duplicate_fill_count": _duplicate_count(context["fills"], ("fill_id", "accepted_fill_id")),
        "duplicate_close_count": _duplicate_count(context["closes"], ("close_id", "trade_id")),
        "reservation_leak_count": len(context["reservations"]),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "first_paper_lifecycle_acceptance_state_v1", "completed": []}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceBoundary("observer_state:malformed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("completed"), list):
        raise AcceptanceBoundary("observer_state:invalid")
    return value


def watch(args: argparse.Namespace) -> int:
    state_root = args.state_root.resolve()
    evidence_root = args.evidence_root.resolve()
    state_path = state_root / "state.json"
    status_path = evidence_root / "first_paper_lifecycle_acceptance_status.json"
    lock_path = args.lock_path.resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_handle = lock_path.open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("FIRST_PAPER_LIFECYCLE_ACCEPTANCE_ALREADY_RUNNING", file=sys.stderr)
        return 3
    client = redis.Redis.from_url(args.redis_url, decode_responses=True, socket_timeout=5)
    client.ping()
    state = _load_state(state_path)
    completed_ids = {
        str(row.get("fill_id"))
        for row in state["completed"]
        if isinstance(row, Mapping) and row.get("fill_id")
    }
    while True:
        try:
            context = _safe_context(client)
            candidates = []
            for position in context["positions"]:
                proof, _fill = _find_binding(context, position)
                if str(proof.get("fill_id") or "") not in completed_ids:
                    candidates.append((position, proof))
            status = {
                "schema_version": "first_paper_lifecycle_acceptance_status_v1",
                "generated_utc": _utc_now(),
                "classification": "WAITING_FOR_NATURAL_CURRENT_EPOCH_POSITION",
                "paper_session_id": context["session_id"],
                "paper_account_epoch": context["epoch"],
                "open_positions": len(context["positions"]),
                "eligible_unprocessed_positions": len(candidates),
                "completed_natural_lifecycles": len(state["completed"]),
                "paper_only": True,
                "live_gate": LIVE_GATE,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            }
            _atomic_json(status_path, status)
            if not candidates:
                time.sleep(args.poll_seconds)
                continue
            if len(candidates) != 1:
                raise AcceptanceBoundary(f"observer:simultaneous_unprocessed_positions={len(candidates)}")
            position, proof = candidates[0]
            frozen = _freeze(context, position)
            fill_id = str(proof["fill_id"])
            artifact_path = evidence_root / f"natural_lifecycle_{fill_id}.json"
            artifact: dict[str, Any] = {
                "schema_version": "first_paper_lifecycle_acceptance_v1",
                "classification": "LINEAGE_FROZEN_RESTART_PENDING",
                "frozen": frozen,
                "paper_only": True,
                "live_gate": LIVE_GATE,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            }
            _atomic_json(artifact_path, artifact)

            artifact["canonical_serving_restart"] = _restart(SERVING_UNIT)
            serving_context = _safe_context(client)
            if _sha256(serving_context["fills"]) != frozen["accepted_fills_sha256"]:
                raise AcceptanceBoundary("serving_restart:accepted_fills_changed")
            if _sha256(serving_context["proofs"]) != frozen["proofs_sha256"]:
                raise AcceptanceBoundary("serving_restart:proofs_changed")
            baseline_cycle = serving_context["status"].get("generated_utc")
            artifact["paper_loop_restart"] = _restart(PAPER_UNIT)
            reconstructed = _wait_new_cycle(
                client,
                baseline_cycle,
                timeout_seconds=args.cycle_timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
            artifact["restart_reconstruction"] = _reconstruction_checks(
                frozen,
                reconstructed,
            )
            artifact["classification"] = "RESTART_RECONSTRUCTED_WAITING_FOR_ORDINARY_CLOSE"
            _atomic_json(artifact_path, artifact)

            deadline = time.monotonic() + args.close_timeout_seconds
            close_context = reconstructed
            while time.monotonic() < deadline:
                close_context = _safe_context(client)
                if _matching_close(close_context, frozen) is not None:
                    break
                time.sleep(args.poll_seconds)
            artifact["close_acceptance"] = _close_checks(close_context, frozen)
            artifact["classification"] = "CLOSE_RECONCILED_WAITING_FOR_TWO_CYCLES"
            _atomic_json(artifact_path, artifact)

            cycles = []
            baseline_cycle = close_context["status"].get("generated_utc")
            for _index in range(2):
                post = _wait_new_cycle(
                    client,
                    baseline_cycle,
                    timeout_seconds=args.cycle_timeout_seconds,
                    poll_seconds=args.poll_seconds,
                )
                baseline_cycle = post["status"].get("generated_utc")
                cycles.append(
                    {
                        "generated_utc": baseline_cycle,
                        "open_positions": len(post["positions"]),
                        "duplicate_fill_count": _duplicate_count(
                            post["fills"], ("fill_id", "accepted_fill_id")
                        ),
                        "duplicate_close_count": _duplicate_count(
                            post["closes"], ("close_id", "trade_id")
                        ),
                        "reservation_leak_count": len(post["reservations"]),
                    }
                )
            if any(
                row["duplicate_fill_count"]
                or row["duplicate_close_count"]
                or row["reservation_leak_count"]
                or row["open_positions"]
                for row in cycles
            ):
                raise AcceptanceBoundary("post_close_cycles:invariant_failure")
            artifact["two_additional_cycles"] = cycles
            artifact["classification"] = "NATURAL_LIFECYCLE_ACCEPTED"
            artifact["accepted_at"] = _utc_now()
            material = dict(artifact)
            artifact["content_sha256"] = _sha256(material)
            _atomic_json(artifact_path, artifact)
            state["completed"].append(
                {
                    "fill_id": fill_id,
                    "artifact": str(artifact_path),
                    "artifact_sha256": _sha256(artifact),
                    "accepted_at": artifact["accepted_at"],
                }
            )
            state["generated_utc"] = _utc_now()
            _atomic_json(state_path, state)
            completed_ids.add(fill_id)
        except AcceptanceBoundary as exc:
            failure = {
                "schema_version": "first_paper_lifecycle_acceptance_status_v1",
                "generated_utc": _utc_now(),
                "classification": "FAIL_CLOSED",
                "exact_blocker": str(exc),
                "paper_only": True,
                "live_gate": LIVE_GATE,
                "routes_to_live": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            }
            _atomic_json(status_path, failure)
            print(json.dumps(failure, sort_keys=True), file=sys.stderr)
            return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("watch",))
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path("/home/wali/ai_bot_local_data/permanent_system_recovery/first_lifecycle"),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("goal_state/PERMANENT_SYSTEM_RECOVERY/natural_lifecycles"),
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=Path(f"/run/user/{os.getuid()}/ai-bot-v2-first-paper-lifecycle-acceptance.lock"),
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--cycle-timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--close-timeout-seconds", type=float, default=21_600.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return watch(args)


if __name__ == "__main__":
    raise SystemExit(main())
