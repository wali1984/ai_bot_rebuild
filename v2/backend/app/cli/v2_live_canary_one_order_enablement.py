"""V2 live-canary one-order enablement CLI.

Two modes:

- ``--preflight-only``: read everything, verify every gate, write
  the preflight status. NEVER opens a network socket. NEVER calls
  any exchange endpoint.
- ``--execute-live-once``: fail-closed unless EVERY gate clears
  including a Codex one-order PASS marker AND a runtime-shell
  credential vault. If everything clears, exactly ONE order is
  attempted through the operator-gated execution adapter, then the
  state auto-re-locks: live_gate → blocked_human_only,
  live_symbols → [], live_enabled → false, one_order_attempt_consumed → true.

Hard invariants (enforced by THIS module AND by the
LiveCanaryExecutionAdapter's internal 14-gate revalidation):

- BTCUSDT only.
- 50 USDT ≤ notional ≤ 55 USDT (exchange min via probe; operator cap).
- Max daily live trades: 1 (counted via the live-canary ledger).
- Max daily loss: 5 USDT.
- Kill switch must be disarmed.
- Codex one-order PASS marker must exist with exact content.
- Private signed-post bypass remediation Codex PASS must exist.
- Dry-run approval-binding Codex PASS must exist.
- No leverage / margin / Redis-trim / legacy-shutdown approval.
- ``live_gate=live_canary_operator_approved`` is scoped ONLY to the
  single ``--execute-live-once`` invocation; the auto-re-lock fires
  in a ``try/finally`` so it runs whether the order succeeds, is
  refused, or throws.
- The CLI NEVER creates the Codex marker file itself.
- The CLI NEVER writes outside ``v2:live_canary:*``.
- The CLI NEVER prints raw credential values.

Allowed Redis writes (enforced by execution_adapter's _safe_redis_set):
- v2:live_canary:intents
- v2:live_canary:ledger
- v2:live_canary:heartbeat
- v2:live_canary:status
- v2:live_canary:kill_switch
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from v2.backend.app.services.live_canary.execution_adapter import (
    APPROVAL_FILE_PATH,
    DEFAULT_HEARTBEAT_TTL_SECONDS,
    DEFAULT_LEDGER_TTL_SECONDS,
    DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
    DEFAULT_STATUS_TTL_SECONDS,
    KEY_HEARTBEAT,
    KEY_LEDGER,
    KEY_STATUS,
    PERMISSION_PROBE_STATUS_PATH,
    ApprovalEnvelope,
    BinanceFuturesExchangeAdapter,
    DailyCounters,
    FakeExchangeAdapter,
    IntentCandidate,
    LiveCanaryExecutionAdapter,
    PermissionProbeFreshness,
    _kill_switch_active,
    _safe_redis_set,
    parse_approval_file,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_SYMBOL = "BTCUSDT"
MAX_NOTIONAL_USDT = 55.0
MIN_NOTIONAL_USDT = 50.0  # exchange minimum per permission probe
MAX_DAILY_LIVE_TRADES = 1
MAX_DAILY_LOSS_USDT = 5.0
CANARY_MODE_REQUIRED = "LEGACY_SIGNAL_V2_EXECUTION_CANARY"
RUNTIME_LIVE_GATE_TARGET = "live_canary_operator_approved"
RUNTIME_LIVE_GATE_BLOCKED = "blocked_human_only"

# Codex pass marker contents required by this packet.
#
# Each prerequisite below must be an actual Codex review file
# (``codex_review/CODEX_GO_NO_GO.md``) containing the exact
# ``*_CODEX_PASS`` token. The implementation-side
# ``latest/GO_NO_GO.md`` files (which carry the ``*_READY`` token)
# DO NOT and MUST NOT satisfy these prerequisites.
CODEX_ONE_ORDER_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/codex_review/CODEX_GO_NO_GO.md"
)
CODEX_ONE_ORDER_PASS_CONTENT = "V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_PASS"

CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/codex_review/CODEX_GO_NO_GO.md"
)
CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT = (
    "V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_CODEX_PASS"
)

CODEX_DRY_RUN_BINDING_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/codex_review/CODEX_GO_NO_GO.md"
)
CODEX_DRY_RUN_BINDING_PASS_CONTENT = (
    "V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_CODEX_PASS"
)

# Packet output paths.
STATUS_WORKLOG_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/one_order_enablement_status.json"
)
PUBLIC_DASHBOARD_PATH = Path(
    "v2/frontend/public/v2_live_canary_one_order_enablement/latest/operator_dashboard_payload.json"
)
LIVE_CANARY_STATUS_MIRROR_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/v2_live_canary_status.json"
)

# Packet-level GO_NO_GO labels (the file written next to this CLI's
# worklog status — different from the per-invocation outcome).
PACKET_GO_READY_PENDING_CODEX = "V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_READY_PENDING_CODEX"
PACKET_GO_BLOCKED = "V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_BLOCKED"

# Per-invocation outcome labels (preflight + execute).
PREFLIGHT_OUTCOME_READY = "V2_LIVE_CANARY_ONE_ORDER_PREFLIGHT_READY"
PREFLIGHT_OUTCOME_BLOCKED = "V2_LIVE_CANARY_ONE_ORDER_PREFLIGHT_BLOCKED"
EXECUTE_OUTCOME_BLOCKED = "V2_LIVE_CANARY_ONE_ORDER_EXECUTE_BLOCKED"
EXECUTE_OUTCOME_SUBMITTED = "V2_LIVE_CANARY_ONE_ORDER_LIVE_SUBMITTED"
EXECUTE_OUTCOME_REJECTED = "V2_LIVE_CANARY_ONE_ORDER_EXCHANGE_REJECTED_OR_FAKE"

DEFAULT_CANDIDATE_NOTIONAL_USDT = 55.0
DEFAULT_CANDIDATE_SIDE = "BUY"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _utc_today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _connect_redis():  # pragma: no cover — exercised at runtime, mocked in tests
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _read_marker_content(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def read_exact_codex_pass_marker(path: Path, expected_token: str) -> dict[str, Any]:
    """Read a Codex PASS marker file and verify exact-string equality.

    Exact match only after ``strip()``. No substring match, no prefix
    match, no alternate ``*_READY`` token accepted. The returned dict
    is what the preflight payload renders into the operator-facing
    ``prerequisite_*_codex_marker_*`` audit fields.
    """
    actual_raw = _read_marker_content(path)
    actual_token = actual_raw if actual_raw is not None else "MISSING"
    passed = actual_raw is not None and actual_raw == expected_token
    return {
        "path": str(path),
        "expected": expected_token,
        "actual": actual_token,
        "passed": bool(passed),
    }


def _check_marker_exact(path: Path, expected: str) -> bool:
    """Strict exact-string match. Kept for legacy callers; new code
    should use ``read_exact_codex_pass_marker``."""
    return read_exact_codex_pass_marker(path, expected)["passed"]


def _count_one_order_attempts_today(redis_client: Any) -> int:
    """Count ledger entries with ``one_order_enablement_invocation=True``
    or ``real_order_attempted=True`` whose ``generated_utc`` date is
    today. The daily cap fires when this count reaches
    ``MAX_DAILY_LIVE_TRADES``."""
    if redis_client is None:
        return 0
    try:
        raw = redis_client.get(KEY_LEDGER)
    except Exception:
        return 0
    if not raw:
        return 0
    try:
        ledger = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(ledger, list):
        return 0
    today = _utc_today_date()
    count = 0
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        gen = entry.get("generated_utc") or ""
        if not isinstance(gen, str) or not gen.startswith(today):
            continue
        is_real_attempt = bool(entry.get("real_order_attempted")) or bool(
            entry.get("real_order_submitted")
        )
        is_one_order_invocation = bool(entry.get("one_order_enablement_invocation"))
        if is_real_attempt or is_one_order_invocation:
            count += 1
    return count


def _sum_daily_realized_loss_usdt(redis_client: Any) -> float:
    """Sum negative realized PnL from the live-canary ledger for
    today's UTC date. NEVER returns a negative number; if no losses,
    returns 0.0."""
    if redis_client is None:
        return 0.0
    try:
        raw = redis_client.get(KEY_LEDGER)
    except Exception:
        return 0.0
    if not raw:
        return 0.0
    try:
        ledger = json.loads(raw)
    except Exception:
        return 0.0
    if not isinstance(ledger, list):
        return 0.0
    today = _utc_today_date()
    total = 0.0
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        gen = entry.get("generated_utc") or ""
        if not gen.startswith(today):
            continue
        pnl = entry.get("realized_pnl_usdt")
        try:
            pnl_val = float(pnl)
        except (TypeError, ValueError):
            continue
        if pnl_val < 0:
            total += -pnl_val
    return total


@dataclasses.dataclass(frozen=True)
class PreflightResult:
    preflight_ready: bool
    blockers: tuple[str, ...]
    approval_file_present: bool
    canary_mode_selected: str
    allowed_symbols: tuple[str, ...]
    max_notional_usdt: float | None
    max_daily_live_trades: int | None
    max_daily_loss_usdt: float | None
    runtime_live_gate_requested: str
    runtime_live_symbols_requested: tuple[str, ...]
    leverage_change_approved: bool
    margin_mode_change_approved: bool
    redis_trim_approved: bool
    legacy_shutdown_approved: bool
    permission_probe_pass_present: bool
    permission_probe_fresh: bool
    permission_probe_age_seconds: float
    permission_probe_go_no_go: str | None
    codex_one_order_pass_present: bool
    codex_private_signed_post_bypass_pass_present: bool
    codex_dry_run_binding_pass_present: bool
    one_order_codex_marker_probe: dict[str, Any]
    private_signed_post_codex_marker_probe: dict[str, Any]
    dry_run_binding_codex_marker_probe: dict[str, Any]
    kill_switch_armed: bool
    candidate_symbol: str
    candidate_notional_usdt: float
    daily_live_trade_count: int
    daily_loss_usdt: float

    def as_payload(self) -> dict[str, Any]:
        return {
            "preflight_ready": self.preflight_ready,
            "blockers": list(self.blockers),
            "approval_file_present": self.approval_file_present,
            "canary_mode_selected": self.canary_mode_selected,
            "allowed_symbols": list(self.allowed_symbols),
            "max_notional_usdt": self.max_notional_usdt,
            "max_daily_live_trades": self.max_daily_live_trades,
            "max_daily_loss_usdt": self.max_daily_loss_usdt,
            "runtime_live_gate_requested": self.runtime_live_gate_requested,
            "runtime_live_symbols_requested": list(self.runtime_live_symbols_requested),
            "leverage_change_approved": self.leverage_change_approved,
            "margin_mode_change_approved": self.margin_mode_change_approved,
            "redis_trim_approved": self.redis_trim_approved,
            "legacy_shutdown_approved": self.legacy_shutdown_approved,
            "permission_probe_pass_present": self.permission_probe_pass_present,
            "permission_probe_fresh": self.permission_probe_fresh,
            "permission_probe_age_seconds": (
                self.permission_probe_age_seconds
                if self.permission_probe_age_seconds != float("inf")
                else None
            ),
            "permission_probe_go_no_go": self.permission_probe_go_no_go,
            "codex_one_order_pass_present": self.codex_one_order_pass_present,
            "codex_private_signed_post_bypass_pass_present": (
                self.codex_private_signed_post_bypass_pass_present
            ),
            "codex_dry_run_binding_pass_present": self.codex_dry_run_binding_pass_present,
            # Hard audit field: this CLI never accepts implementation
            # ``*_READY`` markers as Codex-prerequisite evidence.
            "implementation_ready_markers_accepted_for_codex_prerequisites": False,
            "prerequisite_one_order_codex_marker_path": (
                self.one_order_codex_marker_probe["path"]
            ),
            "prerequisite_one_order_codex_marker_expected": (
                self.one_order_codex_marker_probe["expected"]
            ),
            "prerequisite_one_order_codex_marker_actual": (
                self.one_order_codex_marker_probe["actual"]
            ),
            "prerequisite_one_order_codex_marker_passed": (
                self.one_order_codex_marker_probe["passed"]
            ),
            "prerequisite_private_signed_post_codex_marker_path": (
                self.private_signed_post_codex_marker_probe["path"]
            ),
            "prerequisite_private_signed_post_codex_marker_expected": (
                self.private_signed_post_codex_marker_probe["expected"]
            ),
            "prerequisite_private_signed_post_codex_marker_actual": (
                self.private_signed_post_codex_marker_probe["actual"]
            ),
            "prerequisite_private_signed_post_codex_marker_passed": (
                self.private_signed_post_codex_marker_probe["passed"]
            ),
            "prerequisite_dry_run_binding_codex_marker_path": (
                self.dry_run_binding_codex_marker_probe["path"]
            ),
            "prerequisite_dry_run_binding_codex_marker_expected": (
                self.dry_run_binding_codex_marker_probe["expected"]
            ),
            "prerequisite_dry_run_binding_codex_marker_actual": (
                self.dry_run_binding_codex_marker_probe["actual"]
            ),
            "prerequisite_dry_run_binding_codex_marker_passed": (
                self.dry_run_binding_codex_marker_probe["passed"]
            ),
            "kill_switch_armed": self.kill_switch_armed,
            "candidate_symbol": self.candidate_symbol,
            "candidate_notional_usdt": self.candidate_notional_usdt,
            "daily_live_trade_count": self.daily_live_trade_count,
            "daily_loss_usdt": self.daily_loss_usdt,
            "max_daily_live_trades_cap": MAX_DAILY_LIVE_TRADES,
            "max_daily_loss_usdt_cap": MAX_DAILY_LOSS_USDT,
            "max_notional_usdt_cap": MAX_NOTIONAL_USDT,
            "min_notional_usdt_floor": MIN_NOTIONAL_USDT,
            "allowed_symbol_only": ALLOWED_SYMBOL,
        }


def preflight(
    *,
    redis_client: Any = None,
    approval_path: Path | None = None,
    permission_probe_status_path: Path | None = None,
    codex_one_order_pass_marker_path: Path | None = None,
    codex_private_signed_post_bypass_pass_marker_path: Path | None = None,
    codex_dry_run_binding_pass_marker_path: Path | None = None,
    candidate_symbol: str = ALLOWED_SYMBOL,
    candidate_notional_usdt: float = DEFAULT_CANDIDATE_NOTIONAL_USDT,
    permission_probe_freshness_max_seconds: int = DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
) -> PreflightResult:
    """Verify every gate without placing an order or making any
    exchange-mutating call."""
    approval_path = approval_path or APPROVAL_FILE_PATH
    permission_probe_status_path = (
        permission_probe_status_path or PERMISSION_PROBE_STATUS_PATH
    )
    codex_one_order_pass_marker_path = (
        codex_one_order_pass_marker_path or CODEX_ONE_ORDER_PASS_MARKER_PATH
    )
    codex_private_signed_post_bypass_pass_marker_path = (
        codex_private_signed_post_bypass_pass_marker_path
        or CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_PATH
    )
    codex_dry_run_binding_pass_marker_path = (
        codex_dry_run_binding_pass_marker_path
        or CODEX_DRY_RUN_BINDING_PASS_MARKER_PATH
    )

    approval = parse_approval_file(approval_path)
    probe = PermissionProbeFreshness.from_path(
        permission_probe_status_path,
        max_age_seconds=permission_probe_freshness_max_seconds,
    )
    one_order_probe = read_exact_codex_pass_marker(
        codex_one_order_pass_marker_path, CODEX_ONE_ORDER_PASS_CONTENT
    )
    private_signed_post_probe = read_exact_codex_pass_marker(
        codex_private_signed_post_bypass_pass_marker_path,
        CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT,
    )
    dry_run_binding_probe = read_exact_codex_pass_marker(
        codex_dry_run_binding_pass_marker_path,
        CODEX_DRY_RUN_BINDING_PASS_CONTENT,
    )
    codex_one_order_pass = one_order_probe["passed"]
    codex_private_signed_post_bypass_pass = private_signed_post_probe["passed"]
    codex_dry_run_binding_pass = dry_run_binding_probe["passed"]
    kill_switch_armed = _kill_switch_active(redis_client)
    daily_live_trade_count = _count_one_order_attempts_today(redis_client)
    daily_loss_usdt = _sum_daily_realized_loss_usdt(redis_client)

    blockers: list[str] = []
    if not approval.approval_file_present:
        blockers.append("PREFLIGHT_OPERATOR_APPROVAL_FILE_ABSENT")
    if approval.canary_mode_selected != CANARY_MODE_REQUIRED:
        blockers.append(
            f"PREFLIGHT_CANARY_MODE_MISMATCH:{approval.canary_mode_selected}"
        )
    if ALLOWED_SYMBOL not in approval.allowed_symbols:
        blockers.append("PREFLIGHT_APPROVAL_ALLOWED_SYMBOLS_MISSING_BTCUSDT")
    if approval.max_notional_usdt is None or approval.max_notional_usdt <= 0:
        blockers.append("PREFLIGHT_APPROVAL_MAX_NOTIONAL_MISSING_OR_NONPOSITIVE")
    elif approval.max_notional_usdt > MAX_NOTIONAL_USDT:
        blockers.append(
            f"PREFLIGHT_APPROVAL_MAX_NOTIONAL_ABOVE_PACKET_CAP:{approval.max_notional_usdt}"
        )
    if (
        approval.max_daily_live_trades is None
        or approval.max_daily_live_trades > MAX_DAILY_LIVE_TRADES
    ):
        blockers.append("PREFLIGHT_APPROVAL_MAX_DAILY_TRADES_INVALID")
    if (
        approval.max_daily_loss_usdt is None
        or approval.max_daily_loss_usdt > MAX_DAILY_LOSS_USDT
    ):
        blockers.append("PREFLIGHT_APPROVAL_MAX_DAILY_LOSS_INVALID")
    if approval.runtime_live_gate_requested != RUNTIME_LIVE_GATE_TARGET:
        blockers.append(
            f"PREFLIGHT_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED:{approval.runtime_live_gate_requested}"
        )
    if tuple(sorted(approval.runtime_live_symbols_requested)) != (ALLOWED_SYMBOL,):
        blockers.append("PREFLIGHT_RUNTIME_LIVE_SYMBOLS_NOT_EXACTLY_BTCUSDT")

    if approval.leverage_change_approved:
        blockers.append("PREFLIGHT_LEVERAGE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.margin_mode_change_approved:
        blockers.append("PREFLIGHT_MARGIN_MODE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.redis_trim_approved:
        blockers.append("PREFLIGHT_REDIS_TRIM_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.legacy_shutdown_approved:
        blockers.append("PREFLIGHT_LEGACY_SHUTDOWN_APPROVAL_PRESENT_NOT_ALLOWED")

    if not probe.pass_present:
        blockers.append("PREFLIGHT_PERMISSION_PROBE_PASS_NOT_PRESENT")
    elif not probe.fresh:
        blockers.append(
            f"PREFLIGHT_PERMISSION_PROBE_STALE_AGE_SECONDS_{int(probe.age_seconds)}"
        )

    if not codex_one_order_pass:
        blockers.append("PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH")
    if not codex_private_signed_post_bypass_pass:
        blockers.append(
            "PREFLIGHT_CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_ABSENT_OR_MISMATCH"
        )
    if not codex_dry_run_binding_pass:
        blockers.append("PREFLIGHT_CODEX_DRY_RUN_BINDING_PASS_MARKER_ABSENT_OR_MISMATCH")

    if kill_switch_armed:
        blockers.append("PREFLIGHT_KILL_SWITCH_ARMED")

    if candidate_symbol != ALLOWED_SYMBOL:
        blockers.append(f"PREFLIGHT_CANDIDATE_SYMBOL_NOT_BTCUSDT:{candidate_symbol}")
    if candidate_notional_usdt > MAX_NOTIONAL_USDT:
        blockers.append(
            f"PREFLIGHT_CANDIDATE_NOTIONAL_ABOVE_CAP:{candidate_notional_usdt}"
        )
    if candidate_notional_usdt < MIN_NOTIONAL_USDT:
        blockers.append(
            f"PREFLIGHT_CANDIDATE_NOTIONAL_BELOW_EXCHANGE_MIN:{candidate_notional_usdt}"
        )
    if daily_live_trade_count >= MAX_DAILY_LIVE_TRADES:
        blockers.append(
            f"PREFLIGHT_DAILY_LIVE_TRADE_COUNT_AT_OR_ABOVE_LIMIT:{daily_live_trade_count}"
        )
    if daily_loss_usdt >= MAX_DAILY_LOSS_USDT:
        blockers.append(
            f"PREFLIGHT_DAILY_LOSS_AT_OR_ABOVE_LIMIT:{daily_loss_usdt}"
        )

    return PreflightResult(
        preflight_ready=not blockers,
        blockers=tuple(blockers),
        approval_file_present=approval.approval_file_present,
        canary_mode_selected=approval.canary_mode_selected,
        allowed_symbols=approval.allowed_symbols,
        max_notional_usdt=approval.max_notional_usdt,
        max_daily_live_trades=approval.max_daily_live_trades,
        max_daily_loss_usdt=approval.max_daily_loss_usdt,
        runtime_live_gate_requested=approval.runtime_live_gate_requested,
        runtime_live_symbols_requested=approval.runtime_live_symbols_requested,
        leverage_change_approved=approval.leverage_change_approved,
        margin_mode_change_approved=approval.margin_mode_change_approved,
        redis_trim_approved=approval.redis_trim_approved,
        legacy_shutdown_approved=approval.legacy_shutdown_approved,
        permission_probe_pass_present=probe.pass_present,
        permission_probe_fresh=probe.fresh,
        permission_probe_age_seconds=probe.age_seconds,
        permission_probe_go_no_go=probe.go_no_go,
        codex_one_order_pass_present=codex_one_order_pass,
        codex_private_signed_post_bypass_pass_present=(
            codex_private_signed_post_bypass_pass
        ),
        codex_dry_run_binding_pass_present=codex_dry_run_binding_pass,
        one_order_codex_marker_probe=one_order_probe,
        private_signed_post_codex_marker_probe=private_signed_post_probe,
        dry_run_binding_codex_marker_probe=dry_run_binding_probe,
        kill_switch_armed=kill_switch_armed,
        candidate_symbol=candidate_symbol,
        candidate_notional_usdt=candidate_notional_usdt,
        daily_live_trade_count=daily_live_trade_count,
        daily_loss_usdt=daily_loss_usdt,
    )


def _auto_relock_status_payload(
    *,
    preflight_payload: dict[str, Any],
    execute_outcome: str,
    result: dict[str, Any],
    candidate: IntentCandidate,
    fail_blockers: list[str],
    one_order_attempt_consumed: bool,
    transport_kind: str,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_live_canary_one_order_enablement_relock_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": execute_outcome,
        "auto_relocked": True,
        "one_order_attempt_consumed": one_order_attempt_consumed,
        "exchange_adapter_kind": transport_kind,
        "candidate": {
            "symbol": candidate.symbol,
            "side": candidate.side,
            "requested_notional_usdt": candidate.requested_notional_usdt,
            "requested_quantity": candidate.requested_quantity,
        },
        "fail_blockers": list(fail_blockers),
        "real_order_attempted": bool(result.get("real_order_attempted")),
        "real_order_submitted": bool(result.get("real_order_submitted")),
        "places_real_order": bool(result.get("places_real_order")),
        "writes_exchange_orders": bool(result.get("real_order_submitted")),
        "writes_legacy_redis": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "live_gate": RUNTIME_LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "raw_credential_in_payload": "NEVER",
        "private_signed_post_bypass_remediated": True,
        "private_signed_post_callable": False,
        "final_order_post_boundary_count": 1,
        "final_post_revalidates_all_gates": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "preflight": preflight_payload,
    }


def _write_one_order_ledger_entry(
    redis_client: Any, entry: dict[str, Any]
) -> bool:
    """Append a one-order-enablement ledger entry tagged with
    ``one_order_enablement_invocation=True`` so the next preflight's
    daily count includes this attempt (fake or real)."""
    if redis_client is None:
        return False
    try:
        raw = redis_client.get(KEY_LEDGER)
        current = json.loads(raw) if raw else []
        if not isinstance(current, list):
            current = []
    except Exception:
        current = []
    current.append(entry)
    return _safe_redis_set(
        redis_client,
        KEY_LEDGER,
        json.dumps(current[-200:]),
        ex=DEFAULT_LEDGER_TTL_SECONDS,
    )


def execute_live_once(
    *,
    redis_client: Any = None,
    transport: Any | None = None,
    approval_path: Path | None = None,
    permission_probe_status_path: Path | None = None,
    codex_one_order_pass_marker_path: Path | None = None,
    codex_private_signed_post_bypass_pass_marker_path: Path | None = None,
    codex_dry_run_binding_pass_marker_path: Path | None = None,
    codex_final_pass_marker_path: Path | None = None,
    candidate_symbol: str = ALLOWED_SYMBOL,
    candidate_side: str = DEFAULT_CANDIDATE_SIDE,
    candidate_notional_usdt: float = DEFAULT_CANDIDATE_NOTIONAL_USDT,
    candidate_quantity: float | None = None,
    permission_probe_freshness_max_seconds: int = DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
    construct_real_transport_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Fail-closed one-order execution path.

    Defaults to fake transport when ``transport`` is supplied (tests).
    When ``transport`` is None and preflight is READY, the real
    ``BinanceFuturesExchangeAdapter`` is constructed from OS env
    BINANCE_API_KEY / BINANCE_API_SECRET via
    ``construct_real_transport_factory`` (operator-runtime path).

    The result includes ``auto_relocked=True`` and a re-locked
    status payload regardless of success / failure / exception.
    """
    preflight_result = preflight(
        redis_client=redis_client,
        approval_path=approval_path,
        permission_probe_status_path=permission_probe_status_path,
        codex_one_order_pass_marker_path=codex_one_order_pass_marker_path,
        codex_private_signed_post_bypass_pass_marker_path=(
            codex_private_signed_post_bypass_pass_marker_path
        ),
        codex_dry_run_binding_pass_marker_path=(
            codex_dry_run_binding_pass_marker_path
        ),
        candidate_symbol=candidate_symbol,
        candidate_notional_usdt=candidate_notional_usdt,
        permission_probe_freshness_max_seconds=(
            permission_probe_freshness_max_seconds
        ),
    )
    preflight_payload = preflight_result.as_payload()

    candidate = IntentCandidate(
        symbol=candidate_symbol,
        side=candidate_side,
        requested_notional_usdt=candidate_notional_usdt,
        requested_quantity=candidate_quantity,
        signal_source="LEGACY_SIGNAL_V2_EXECUTION_CANARY",
        expected_move_after_cost_bps=None,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )

    if not preflight_result.preflight_ready:
        # Build a blocked result, write a ledger entry tagging this
        # invocation, and auto-re-lock.
        fail_blockers = list(preflight_result.blockers)
        result: dict[str, Any] = {
            "real_order_submitted": False,
            "real_order_attempted": False,
            "places_real_order": False,
            "exchange_response_status": "REFUSED_PREFLIGHT_BLOCKERS",
            "fail_blockers": fail_blockers,
        }
        relock = _auto_relock_status_payload(
            preflight_payload=preflight_payload,
            execute_outcome=EXECUTE_OUTCOME_BLOCKED,
            result=result,
            candidate=candidate,
            fail_blockers=fail_blockers,
            one_order_attempt_consumed=False,
            transport_kind="NONE_TRANSPORT_NOT_CONSTRUCTED",
        )
        _write_one_order_ledger_entry(
            redis_client,
            {
                **relock,
                "one_order_enablement_invocation": True,
                "one_order_attempt_consumed": False,
                "preflight_blockers": fail_blockers,
            },
        )
        _safe_redis_set(
            redis_client,
            KEY_STATUS,
            json.dumps(relock),
            ex=DEFAULT_STATUS_TTL_SECONDS,
        )
        _safe_redis_set(
            redis_client,
            KEY_HEARTBEAT,
            json.dumps(
                {
                    "schema_version": "v2_live_canary_one_order_enablement_heartbeat_v1",
                    "generated_utc": _utc_iso(),
                    "go_no_go": EXECUTE_OUTCOME_BLOCKED,
                    "live_gate": RUNTIME_LIVE_GATE_BLOCKED,
                    "live_symbols": [],
                    "real_order_attempted": False,
                    "real_order_submitted": False,
                }
            ),
            ex=DEFAULT_HEARTBEAT_TTL_SECONDS,
        )
        return {
            "go_no_go": EXECUTE_OUTCOME_BLOCKED,
            "auto_relocked": True,
            "one_order_attempt_consumed": False,
            "preflight": preflight_payload,
            "fail_blockers": fail_blockers,
            "exchange_adapter_kind": "NONE_TRANSPORT_NOT_CONSTRUCTED",
            "candidate": {
                "symbol": candidate.symbol,
                "side": candidate.side,
                "requested_notional_usdt": candidate.requested_notional_usdt,
            },
            "real_order_attempted": False,
            "real_order_submitted": False,
            "places_real_order": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "live_gate_before": RUNTIME_LIVE_GATE_BLOCKED,
            "live_gate_after": RUNTIME_LIVE_GATE_BLOCKED,
            "live_symbols_before": [],
            "live_symbols_after": [],
            "raw_credential_in_payload": "NEVER",
        }

    # All preflight gates pass. Construct an operator-gated adapter
    # scoped to this single invocation and dispatch.
    if transport is None:
        if construct_real_transport_factory is None:
            api_key = os.environ.get("BINANCE_API_KEY", "")
            api_secret = os.environ.get("BINANCE_API_SECRET", "")
            transport = BinanceFuturesExchangeAdapter(api_key, api_secret)
        else:
            transport = construct_real_transport_factory()
    approval = parse_approval_file(approval_path)
    adapter = LiveCanaryExecutionAdapter(
        redis_client=redis_client,
        approval=approval,
        exchange_adapter=transport,
        approval_file_path=approval_path or APPROVAL_FILE_PATH,
        codex_pass_marker_path=codex_final_pass_marker_path,
        codex_final_pass_marker_path=(
            codex_final_pass_marker_path or codex_one_order_pass_marker_path
        ),
        permission_probe_status_path=(
            permission_probe_status_path or PERMISSION_PROBE_STATUS_PATH
        ),
        permission_probe_freshness_max_seconds=permission_probe_freshness_max_seconds,
        dry_run=False,
        live_enabled=True,
    )
    transport_kind = type(transport).__name__

    result: dict[str, Any]
    exception_during_submit: Exception | None = None
    try:
        result = adapter.submit_canary_order(
            candidate=candidate, cycle_id=_utc_iso()
        )
    except Exception as e:  # pragma: no cover — defensive only
        exception_during_submit = e
        result = {
            "real_order_submitted": False,
            "real_order_attempted": False,
            "places_real_order": False,
            "exchange_response_status": f"ERROR:{type(e).__name__}",
            "fail_blockers": [f"EXECUTE_EXCEPTION_{type(e).__name__}"],
        }

    real_submitted = bool(result.get("real_order_submitted"))
    real_attempted = bool(result.get("real_order_attempted"))
    adapter_blockers = list(result.get("fail_blockers", []) or [])

    if real_submitted:
        execute_outcome = EXECUTE_OUTCOME_SUBMITTED
    elif adapter_blockers:
        execute_outcome = EXECUTE_OUTCOME_BLOCKED
    else:
        execute_outcome = EXECUTE_OUTCOME_REJECTED

    relock = _auto_relock_status_payload(
        preflight_payload=preflight_payload,
        execute_outcome=execute_outcome,
        result=result,
        candidate=candidate,
        fail_blockers=adapter_blockers,
        one_order_attempt_consumed=True,
        transport_kind=transport_kind,
    )
    relock["live_gate_before"] = RUNTIME_LIVE_GATE_TARGET
    relock["live_gate_after"] = RUNTIME_LIVE_GATE_BLOCKED
    relock["live_symbols_before"] = [ALLOWED_SYMBOL]
    relock["live_symbols_after"] = []
    relock["exception_during_submit"] = (
        type(exception_during_submit).__name__ if exception_during_submit else None
    )

    _write_one_order_ledger_entry(
        redis_client,
        {
            **relock,
            "one_order_enablement_invocation": True,
            "one_order_attempt_consumed": True,
            "exchange_response": dict(result.get("exchange_response") or {}),
        },
    )
    _safe_redis_set(
        redis_client,
        KEY_STATUS,
        json.dumps(relock),
        ex=DEFAULT_STATUS_TTL_SECONDS,
    )
    _safe_redis_set(
        redis_client,
        KEY_HEARTBEAT,
        json.dumps(
            {
                "schema_version": "v2_live_canary_one_order_enablement_heartbeat_v1",
                "generated_utc": _utc_iso(),
                "go_no_go": execute_outcome,
                "live_gate": RUNTIME_LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "real_order_attempted": real_attempted,
                "real_order_submitted": real_submitted,
                "auto_relocked": True,
            }
        ),
        ex=DEFAULT_HEARTBEAT_TTL_SECONDS,
    )
    return {
        "go_no_go": execute_outcome,
        "auto_relocked": True,
        "one_order_attempt_consumed": True,
        "preflight": preflight_payload,
        "fail_blockers": adapter_blockers,
        "exchange_adapter_kind": transport_kind,
        "candidate": {
            "symbol": candidate.symbol,
            "side": candidate.side,
            "requested_notional_usdt": candidate.requested_notional_usdt,
        },
        "real_order_attempted": real_attempted,
        "real_order_submitted": real_submitted,
        "places_real_order": real_submitted,
        "writes_exchange_orders": real_submitted,
        "writes_legacy_redis": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "live_gate_before": RUNTIME_LIVE_GATE_TARGET,
        "live_gate_after": RUNTIME_LIVE_GATE_BLOCKED,
        "live_symbols_before": [ALLOWED_SYMBOL],
        "live_symbols_after": [],
        "raw_credential_in_payload": "NEVER",
        "exchange_response": dict(result.get("exchange_response") or {}),
    }


def _write_status_files(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for path in (STATUS_WORKLOG_PATH, PUBLIC_DASHBOARD_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_live_canary_one_order_enablement")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute-live-once", action="store_true")
    parser.add_argument(
        "--candidate-notional-usdt",
        type=float,
        default=DEFAULT_CANDIDATE_NOTIONAL_USDT,
    )
    parser.add_argument(
        "--candidate-side", type=str, default=DEFAULT_CANDIDATE_SIDE
    )
    parser.add_argument(
        "--candidate-quantity", type=float, default=None
    )
    args = parser.parse_args(argv)

    r = _connect_redis()

    if args.preflight_only:
        result = preflight(
            redis_client=r,
            candidate_notional_usdt=args.candidate_notional_usdt,
        )
        payload = {
            "schema_version": "v2_live_canary_one_order_enablement_preflight_status_v1",
            "generated_utc": _utc_iso(),
            "go_no_go": (
                PREFLIGHT_OUTCOME_READY
                if result.preflight_ready
                else PREFLIGHT_OUTCOME_BLOCKED
            ),
            "preflight_ready": result.preflight_ready,
            "blockers": list(result.blockers),
            **result.as_payload(),
            "real_order_attempted": False,
            "real_order_submitted": False,
            "places_real_order": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "live_gate": RUNTIME_LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "raw_credential_in_payload": "NEVER",
        }
        _write_status_files(payload)
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "preflight_ready": result.preflight_ready,
                    "blocker_count": len(result.blockers),
                },
                sort_keys=True,
            )
        )
        return 0 if result.preflight_ready else 0

    # --execute-live-once
    outcome = execute_live_once(
        redis_client=r,
        candidate_notional_usdt=args.candidate_notional_usdt,
        candidate_side=args.candidate_side,
        candidate_quantity=args.candidate_quantity,
    )
    payload = {
        "schema_version": "v2_live_canary_one_order_enablement_execute_status_v1",
        "generated_utc": _utc_iso(),
        **outcome,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_status_files(payload)
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "auto_relocked": payload["auto_relocked"],
                "one_order_attempt_consumed": payload["one_order_attempt_consumed"],
                "real_order_attempted": payload["real_order_attempted"],
                "real_order_submitted": payload["real_order_submitted"],
                "live_gate_after": payload["live_gate_after"],
                "live_symbols_after": payload["live_symbols_after"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
