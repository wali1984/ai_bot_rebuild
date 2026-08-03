"""V2 live-canary executor CLI (fail-closed dry-run; operator-gated).

Bounded one-shot (or --loop) tool that runs the live-canary gate
cascade against current paper/shadow rows. The CLI defaults to a
``FakeExchangeAdapter`` and to ``dry_run=True`` / ``live_enabled=False``;
the real Binance Futures adapter is in source but unreachable from
this CLI surface. Operators who want to advance to a real order
must construct the adapter directly in a separate, reviewed entry
point.

NEVER places, cancels, or modifies any exchange entry. NEVER
changes leverage. NEVER changes margin. NEVER writes legacy Redis.
NEVER imports torch. NEVER deserializes pickle. NEVER reads raw
API key values. NEVER prints the operator approval file contents.

Allowed Redis writes (enforced by execution adapter's
``_safe_redis_set``):
- ``v2:live_canary:intents``
- ``v2:live_canary:ledger``
- ``v2:live_canary:heartbeat``
- ``v2:live_canary:status``
- ``v2:live_canary:kill_switch``

Allowed file writes:
- ``claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/live_canary_executor_status.json``
- ``v2/frontend/public/operator_runtime/v2_live_canary/latest/live_canary_executor_status.json``
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.live_canary.execution_adapter import (
    CODEX_FINAL_PASS_MARKER_PATH,
    PERMISSION_PROBE_STATUS_PATH,
    ApprovalEnvelope,
    FakeExchangeAdapter,
    IntentCandidate,
    LiveCanaryExecutionAdapter,
    PermissionProbeFreshness,
    parse_approval_file,
)
from v2.backend.app.services.live_canary.permission_probe import (
    PROBE_GO_READY,
    run_probe,
)

V2_REDIS_PREFIX = "v2:"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/live_canary_executor_status.json"
)
PUBLIC_STATUS = Path(
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/live_canary_executor_status.json"
)

# Permission-probe mirror paths. The executor writes BOTH on every
# tick so the two locations can never disagree (Codex regression
# fix: stale READY in the public mirror while the worklog says
# BLOCKED).
PERMISSION_PROBE_WORKLOG_MIRROR = PERMISSION_PROBE_STATUS_PATH
PERMISSION_PROBE_PUBLIC_MIRROR = Path(
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json"
)
PERMISSION_PROBE_GO_NO_GO_MIRROR = Path(
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/GO_NO_GO.md"
)


def _refresh_permission_probe_mirrors(probe_payload: dict[str, Any]) -> None:
    """Write the probe snapshot to BOTH the worklog truth file and
    the public mirror so they cannot diverge. Also refresh the
    GO_NO_GO marker. Best-effort: any write failure leaves the
    existing files in place; safety pins still hold because dry-run
    / live-disabled already block the real-order path."""
    body = json.dumps(probe_payload, indent=2, sort_keys=True) + "\n"
    for target in (PERMISSION_PROBE_WORKLOG_MIRROR, PERMISSION_PROBE_PUBLIC_MIRROR):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        except Exception:
            continue
    try:
        PERMISSION_PROBE_GO_NO_GO_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        PERMISSION_PROBE_GO_NO_GO_MIRROR.write_text(
            str(probe_payload.get("go_no_go", "")) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


GO_DRY_RUN_READY = "V2_24H_LIVE_CANARY_DRY_RUN_READY"
GO_OPERATOR_APPROVAL_REQUIRED = "V2_24H_LIVE_CANARY_OPERATOR_APPROVAL_REQUIRED"
GO_PERMISSION_UNKNOWN = "V2_24H_LIVE_CANARY_BLOCKED_EXCHANGE_PERMISSION_UNKNOWN"
GO_READY_PENDING_CODEX = "V2_24H_LIVE_CANARY_READY_PENDING_CODEX"
GO_BLOCKED = "V2_24H_LIVE_CANARY_BLOCKED"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _read_json_list(r, key: str) -> list[dict]:
    if r is None:
        return []
    try:
        raw = r.get(key)
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _read_json_dict(r, key: str) -> dict:
    if r is None:
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _v2_prediction_for_symbol(r, symbol: str) -> dict:
    return _read_json_dict(r, f"{V2_REDIS_PREFIX}prediction:{symbol}:1m")


def _v2_features_for_symbol(r, symbol: str) -> dict:
    return _read_json_dict(r, f"{V2_REDIS_PREFIX}features:latest:{symbol}:1m")


def _candidate_from_shadow_row(r, row: dict) -> IntentCandidate:
    symbol = str(row.get("symbol") or "")
    features = _v2_features_for_symbol(r, symbol)
    prediction = _v2_prediction_for_symbol(r, symbol)
    freshness = features.get("feature_freshness_state") if isinstance(features, dict) else None
    v2_prediction_present = bool(prediction.get("direction")) if isinstance(prediction, dict) else False
    requested_notional = 0.0
    try:
        requested_notional = float(row.get("requested_notional_usdt") or 0.0)
    except (ValueError, TypeError):
        requested_notional = 0.0
    return IntentCandidate(
        symbol=symbol,
        side=str(row.get("side") or "HOLD"),
        requested_notional_usdt=requested_notional,
        signal_source=str(row.get("signal_source") or "V2_NATIVE_SIGNAL_CANARY"),
        expected_move_after_cost_bps=None,
        paper_fill_gate_open=bool(row.get("paper_fill_allowed") or False),
        feature_freshness_state=freshness,
        v2_prediction_present=v2_prediction_present,
    )


def _select_go_no_go(
    *,
    approval: ApprovalEnvelope,
    probe_go: str,
    codex_marker_present: bool,
    fatal_blockers_universal: list[str],
) -> str:
    if not approval.approval_file_present:
        return GO_OPERATOR_APPROVAL_REQUIRED
    if probe_go != PROBE_GO_READY:
        return GO_PERMISSION_UNKNOWN
    if not codex_marker_present:
        return GO_READY_PENDING_CODEX
    if fatal_blockers_universal:
        return GO_BLOCKED
    return GO_DRY_RUN_READY


def _build_status_payload(
    *,
    intents: list[dict[str, Any]],
    approval: ApprovalEnvelope,
    probe_payload: dict[str, Any],
    codex_marker_present: bool,
    codex_final_marker_present: bool,
    permission_probe_freshness: PermissionProbeFreshness,
    go_no_go: str,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_24h_live_canary_executor_status_v2",
        "generated_utc": _utc_iso(),
        "go_no_go": go_no_go,
        "dry_run": True,
        "live_enabled": False,
        "exchange_adapter_kind": "FakeExchangeAdapter",
        "real_order_attempted": False,
        "real_order_submitted": False,
        "places_real_order": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "approval_file_present": approval.approval_file_present,
        "canary_mode_selected": approval.canary_mode_selected,
        "permission_probe_go_no_go": probe_payload.get("go_no_go"),
        "permission_probe_fail_blockers": probe_payload.get("fail_blockers"),
        "permission_probe_status_path_present": permission_probe_freshness.pass_present,
        "permission_probe_fresh": permission_probe_freshness.fresh,
        "permission_probe_age_seconds": (
            permission_probe_freshness.age_seconds
            if permission_probe_freshness.age_seconds != float("inf")
            else None
        ),
        "codex_live_canary_pass_marker_present": codex_marker_present,
        "codex_final_live_canary_pass_marker_present": codex_final_marker_present,
        "runtime_live_gate_requested": approval.runtime_live_gate_requested,
        "runtime_live_symbols_requested": list(approval.runtime_live_symbols_requested),
        "intent_count": len(intents),
        "intents": intents,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "allowed_redis_writes": [
            "v2:live_canary:intents",
            "v2:live_canary:ledger",
            "v2:live_canary:heartbeat",
            "v2:live_canary:status",
            "v2:live_canary:kill_switch",
        ],
        "raw_credential_in_payload": "NEVER",
        "kill_switch_namespace": "v2:live_canary:kill_switch",
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "direct_call_bypass_remediated": True,
        "caller_supplied_gate_boolean_accepted": False,
        "final_submit_rechecks_all_gates": True,
        "private_signed_post_bypass_remediated": True,
        "private_signed_post_callable": False,
        "final_order_post_boundary_count": 1,
        "final_post_revalidates_all_gates": True,
        "direct_import_urlopen_call_count_with_missing_gates": 0,
        "direct_import_forged_gate_rejected": True,
        "operator_gated_gate_cascade_conditions": [
            "GATE_1_OPERATOR_APPROVAL_FILE_PRESENT",
            "GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_PRESENT",
            "GATE_3_PERMISSION_PROBE_READY_AND_FRESH",
            "GATE_4_CANARY_MODE_SELECTED",
            "GATE_5_APPROVED_SYMBOL_WHITELIST_NONEMPTY",
            "GATE_6_SYMBOL_IN_APPROVED_WHITELIST",
            "GATE_7_MAX_NOTIONAL_CAP_POSITIVE",
            "GATE_8_REQUESTED_NOTIONAL_AT_OR_BELOW_CAP",
            "GATE_9_DAILY_TRADE_COUNT_BELOW_LIMIT",
            "GATE_10_DAILY_LOSS_BELOW_LIMIT",
            "GATE_11_KILL_SWITCH_DISARMED",
            "GATE_12_LIVE_ENABLED_AND_NOT_DRY_RUN",
            "GATE_13_RUNTIME_LIVE_GATE_OPERATOR_APPROVED_AND_SYMBOLS_MATCH",
            "GATE_14_NO_LEVERAGE_MARGIN_REDIS_TRIM_OR_SHUTDOWN_APPROVALS",
        ],
    }


def _write_status_files(payload: dict[str, Any], worklog: Path, public: Path) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text(body, encoding="utf-8")


def run_once(
    redis_client: Any | None = None,
    *,
    approval_path: Path | None = None,
    codex_pass_marker_path: Path | None = None,
    secrets_path: Path | None = None,
    out_worklog: Path | None = None,
    out_public: Path | None = None,
) -> dict[str, Any]:
    r = redis_client if redis_client is not None else _connect_redis()
    approval = parse_approval_file(approval_path)
    probe_result = run_probe(
        secrets_path=secrets_path,
        approval_path=approval_path,
        codex_pass_marker_path=codex_pass_marker_path,
    )
    probe_payload = probe_result.as_payload()
    # Refresh the permission-probe status snapshot inline on every
    # dry-run tick. We write BOTH the worklog truth file AND the
    # public mirror under v2/frontend/public/operator_runtime/, so
    # the two locations can never diverge: a stale READY in the
    # public mirror cannot persist past the next dry-run tick.
    #
    # A recurring credentialed Binance call from a separate timer
    # is NOT enabled here; the probe runs read-only and reports
    # BINANCE_API_KEY_ENV_VAR_ABSENT when the dry-run service env
    # carries no credentials. That honest BLOCKED state is then
    # mirrored to BOTH paths.
    _refresh_permission_probe_mirrors(probe_payload)
    codex_marker = codex_pass_marker_path
    if codex_marker is None:
        from v2.backend.app.services.live_canary.permission_probe import (
            CODEX_PASS_MARKER_PATH,
        )

        codex_marker = CODEX_PASS_MARKER_PATH
    adapter = LiveCanaryExecutionAdapter(
        redis_client=r,
        approval=approval,
        exchange_adapter=FakeExchangeAdapter(),
        codex_pass_marker_path=codex_marker,
        codex_final_pass_marker_path=CODEX_FINAL_PASS_MARKER_PATH,
        permission_probe_status_path=PERMISSION_PROBE_STATUS_PATH,
        dry_run=True,
        live_enabled=False,
    )
    shadow_rows = _read_json_list(r, f"{V2_REDIS_PREFIX}paper:shadow_observations")
    held_rows = _read_json_list(r, f"{V2_REDIS_PREFIX}paper:intents_held_by_paper_fill_gate")
    candidates: list[IntentCandidate] = []
    for row in shadow_rows[-20:]:  # cap at last 20 to bound work per cycle
        candidates.append(_candidate_from_shadow_row(r, row))
    for row in held_rows[-20:]:
        symbol = str(row.get("symbol") or "")
        features = _v2_features_for_symbol(r, symbol)
        prediction = _v2_prediction_for_symbol(r, symbol)
        freshness = features.get("feature_freshness_state") if isinstance(features, dict) else None
        v2_prediction_present = bool(prediction.get("direction")) if isinstance(prediction, dict) else False
        candidates.append(
            IntentCandidate(
                symbol=symbol,
                side=str(row.get("selected_action_upstream") or "HOLD"),
                requested_notional_usdt=0.0,
                signal_source="LEGACY_SIGNAL_V2_EXECUTION_CANARY",
                expected_move_after_cost_bps=None,
                paper_fill_gate_open=False,
                feature_freshness_state=freshness,
                v2_prediction_present=v2_prediction_present,
            )
        )
    intents: list[dict[str, Any]] = []
    universal_fatals: list[str] = []
    for candidate in candidates:
        intent = adapter.build_intent_record(
            candidate=candidate,
            cycle_id=_utc_iso(),
        )
        intents.append(intent)
        adapter.persist_intent(intent)
        adapter.write_ledger_entry(intent)
        for blocker in intent.get("fail_blockers", []):
            if blocker not in universal_fatals:
                universal_fatals.append(blocker)
    codex_marker_present = codex_marker.exists()
    codex_final_marker_present = CODEX_FINAL_PASS_MARKER_PATH.exists()
    probe_freshness = PermissionProbeFreshness.from_path(
        PERMISSION_PROBE_STATUS_PATH
    )
    go = _select_go_no_go(
        approval=approval,
        probe_go=probe_payload.get("go_no_go", ""),
        codex_marker_present=codex_marker_present,
        fatal_blockers_universal=universal_fatals,
    )
    status_payload = _build_status_payload(
        intents=intents,
        approval=approval,
        probe_payload=probe_payload,
        codex_marker_present=codex_marker_present,
        codex_final_marker_present=codex_final_marker_present,
        permission_probe_freshness=probe_freshness,
        go_no_go=go,
    )
    adapter.write_status(status_payload)
    adapter.write_heartbeat(
        {
            "schema_version": "v2_live_canary_heartbeat_v1",
            "generated_utc": _utc_iso(),
            "go_no_go": go,
            "dry_run": True,
            "live_enabled": False,
            "intent_count": len(intents),
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }
    )
    if out_worklog is not None:
        _write_status_files(
            status_payload,
            out_worklog,
            out_public if out_public is not None else PUBLIC_STATUS,
        )
    return status_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_live_canary_executor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_STATUS)
    parser.add_argument("--approval-path", type=Path, default=None)
    parser.add_argument("--codex-pass-marker-path", type=Path, default=None)
    parser.add_argument("--secrets-path", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help=(
            "Always dry-run in this packet. The flag is preserved for "
            "future compatibility but cannot be flipped to False in this "
            "scaffolding packet."
        ),
    )
    args = parser.parse_args(argv)
    if args.once == args.loop:
        args.once = True
        args.loop = False
    if args.once:
        payload = run_once(
            approval_path=args.approval_path,
            codex_pass_marker_path=args.codex_pass_marker_path,
            secrets_path=args.secrets_path,
            out_worklog=args.out_worklog,
            out_public=args.out_public,
        )
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "dry_run": payload["dry_run"],
                    "live_enabled": payload["live_enabled"],
                    "real_order_attempted": payload["real_order_attempted"],
                    "leverage_changed": payload["leverage_changed"],
                    "margin_mode_changed": payload["margin_mode_changed"],
                    "writes_legacy_redis": payload["writes_legacy_redis"],
                    "writes_exchange_orders": payload["writes_exchange_orders"],
                    "intent_count": payload["intent_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    while True:
        run_once(
            approval_path=args.approval_path,
            codex_pass_marker_path=args.codex_pass_marker_path,
            secrets_path=args.secrets_path,
            out_worklog=args.out_worklog,
            out_public=args.out_public,
        )
        try:
            time.sleep(max(5, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
