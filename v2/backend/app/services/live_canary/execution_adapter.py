"""V2 live-canary operator-gated execution adapter.

Binance exchange transport is WebSocket API primary. REST is not the primary
canary mutation path. The real transport still remains unreachable unless the
existing 14-gate cascade passes at submission time.

- The forgeable caller-supplied ``canary_signed_by_executor_gate_cascade``
  boolean field has been REMOVED from intent payloads. No
  caller-supplied flag of any shape can authorize a real order.
- The old REST signed POST path has been replaced by Binance WebSocket API
  ``order.place``. The signed WebSocket request is built and sent only inside
  ``BinanceFuturesExchangeAdapter.submit_signed_canary_order`` after fresh gate
  revalidation.
- That single function:
  1. rejects non-``GateDecision`` arguments,
  2. rejects ``GateDecision`` whose ``_token`` is forged,
  3. re-reads operator approval file from disk,
  4. re-reads permission probe status file from disk,
  5. re-runs the shared 14-gate cascade against the freshly-read
     state via ``_evaluate_real_order_blockers``,
  6. on ANY blocker, returns blocked WITHOUT calling the WebSocket sender,
  7. only after the cascade clears, builds a signed ``order.place`` request
     and sends it through the configured WebSocket API sender.
- A ``GateDecision`` dataclass carries the parameters needed for
  re-validation. Its ``_token`` field is a defense-in-depth check;
  the real safety guarantee is that the transport reads CURRENT
  disk/Redis state at the moment of submission.

Default state at construction time:

- ``exchange_adapter = FakeExchangeAdapter`` (no network surface)
- ``dry_run = True``
- ``live_enabled = False``
- ``live_gate = "blocked_human_only"`` (reported in payload)
- ``live_symbols = []`` (reported in payload)
- ``direct_call_bypass_remediated = True``
- ``caller_supplied_gate_boolean_accepted = False``
- ``final_submit_rechecks_all_gates = True``

NEVER cancels orders. NEVER modifies orders. NEVER changes
leverage. NEVER changes margin mode. NEVER writes legacy Redis.
NEVER returns or logs raw API key/secret values. The only real exchange
mutation surface anywhere in this module is WebSocket API ``order.place``, and
that surface is gated by independent re-validation of all 14 gates.

Allowed Redis writes (enforced by ``_safe_redis_set``):
- ``v2:live_canary:intents``
- ``v2:live_canary:ledger``
- ``v2:live_canary:heartbeat``
- ``v2:live_canary:status``
- ``v2:live_canary:kill_switch``
"""
from __future__ import annotations

import dataclasses
import json
import secrets as _secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_ws_api_url,
    build_signed_ws_api_request,
    default_ws_api_sender,
    redacted_json,
)
from v2.backend.app.services.execution.binance_order_builder import (
    build_binance_order_plan,
)

V2_REDIS_PREFIX = "v2:"
LIVE_CANARY_NAMESPACE = "v2:live_canary:"
KEY_INTENTS = "v2:live_canary:intents"
KEY_LEDGER = "v2:live_canary:ledger"
KEY_HEARTBEAT = "v2:live_canary:heartbeat"
KEY_STATUS = "v2:live_canary:status"
KEY_KILL_SWITCH = "v2:live_canary:kill_switch"
ALLOWED_REDIS_KEYS = (
    KEY_INTENTS,
    KEY_LEDGER,
    KEY_HEARTBEAT,
    KEY_STATUS,
    KEY_KILL_SWITCH,
)

APPROVAL_FILE_PATH = Path(
    "claude_worklog/approvals/OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md"
)
CODEX_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/codex_review/CODEX_LIVE_CANARY_PASS.marker"
)
CODEX_FINAL_PASS_MARKER_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_execution_adapter_operator_gated/latest/codex_review/CODEX_FINAL_LIVE_CANARY_PASS.marker"
)
PERMISSION_PROBE_STATUS_PATH = Path(
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json"
)
PROBE_GO_READY = "V2_LIVE_CANARY_PERMISSION_PROBE_READY"

DEFAULT_HEARTBEAT_TTL_SECONDS = 300
DEFAULT_LEDGER_TTL_SECONDS = 86400 * 7
DEFAULT_INTENTS_TTL_SECONDS = 600
DEFAULT_STATUS_TTL_SECONDS = 600
DEFAULT_KILL_SWITCH_TTL_SECONDS = 86400
DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS = 600

# Module-private token used as a defense-in-depth check against a
# raw GateDecision dataclass construction with no factory. The real
# security guarantee is the transport's independent re-evaluation
# of the 14 gates from current disk/Redis state at submission time.
_MODULE_GATE_TOKEN = _secrets.token_hex(32)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None) -> bool:
    """Refuse any key not in the explicit allowlist."""
    if redis_client is None:
        return False
    if not isinstance(key, str):
        return False
    if key not in ALLOWED_REDIS_KEYS:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            redis_client.set(key, value, ex=int(ex))
        else:
            redis_client.set(key, value)
        return True
    except Exception:
        return False


def _kill_switch_active(redis_client: Any) -> bool:
    """Return True iff the kill switch is set to a truthy value.
    Fail-closed on missing Redis or read errors."""
    if redis_client is None:
        return True
    try:
        raw = redis_client.get(KEY_KILL_SWITCH)
    except Exception:
        return True
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if text in ("", "false", "0", "off", "disarmed"):
        return False
    return True


@dataclasses.dataclass(frozen=True)
class PermissionProbeFreshness:
    pass_present: bool
    fresh: bool
    age_seconds: float
    go_no_go: str | None

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        max_age_seconds: int = DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
        now_utc: datetime | None = None,
    ) -> "PermissionProbeFreshness":
        if not path.exists():
            return cls(
                pass_present=False, fresh=False, age_seconds=float("inf"), go_no_go=None
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls(
                pass_present=False, fresh=False, age_seconds=float("inf"), go_no_go=None
            )
        go = data.get("go_no_go") if isinstance(data, dict) else None
        gen_utc = data.get("generated_utc") if isinstance(data, dict) else None
        pass_present = go == PROBE_GO_READY
        age = float("inf")
        if isinstance(gen_utc, str):
            try:
                gen = datetime.fromisoformat(gen_utc.replace("Z", "+00:00"))
                if gen.tzinfo is None:
                    gen = gen.replace(tzinfo=timezone.utc)
                ref = now_utc or datetime.now(timezone.utc)
                age = max(0.0, (ref - gen).total_seconds())
            except Exception:
                age = float("inf")
        fresh = age <= max_age_seconds
        return cls(pass_present=pass_present, fresh=fresh, age_seconds=age, go_no_go=go)


@dataclasses.dataclass(frozen=True)
class ApprovalEnvelope:
    approval_file_present: bool
    canary_mode_selected: str
    allowed_symbols: tuple[str, ...]
    max_notional_usdt: float | None
    max_daily_live_trades: int | None
    max_daily_loss_usdt: float | None
    leverage_change_approved: bool
    margin_mode_change_approved: bool
    redis_trim_approved: bool
    legacy_shutdown_approved: bool
    runtime_live_gate_requested: str = "blocked_human_only"
    runtime_live_symbols_requested: tuple[str, ...] = tuple()

    @classmethod
    def closed_default(cls) -> "ApprovalEnvelope":
        return cls(
            approval_file_present=False,
            canary_mode_selected="BLOCKED_UNSELECTED",
            allowed_symbols=tuple(),
            max_notional_usdt=None,
            max_daily_live_trades=None,
            max_daily_loss_usdt=None,
            leverage_change_approved=False,
            margin_mode_change_approved=False,
            redis_trim_approved=False,
            legacy_shutdown_approved=False,
            runtime_live_gate_requested="blocked_human_only",
            runtime_live_symbols_requested=tuple(),
        )


@dataclasses.dataclass(frozen=True)
class IntentCandidate:
    symbol: str
    side: str
    requested_notional_usdt: float
    requested_quantity: float | None = None
    current_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    symbol_filters: Mapping[str, Any] | None = None
    hedge_mode: bool = True
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 4.0
    signal_source: str = "V2_NATIVE_SIGNAL_CANARY"
    expected_move_after_cost_bps: float | None = None
    paper_fill_gate_open: bool = False
    feature_freshness_state: str | None = None
    v2_prediction_present: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "requested_notional_usdt": float(self.requested_notional_usdt),
            "requested_quantity": self.requested_quantity,
            "current_price": self.current_price,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "symbol_filters": dict(self.symbol_filters or {}),
            "hedge_mode": bool(self.hedge_mode),
            "maker_fee_bps": float(self.maker_fee_bps),
            "taker_fee_bps": float(self.taker_fee_bps),
            "signal_source": self.signal_source,
            "expected_move_after_cost_bps": self.expected_move_after_cost_bps,
            "paper_fill_gate_open": self.paper_fill_gate_open,
            "feature_freshness_state": self.feature_freshness_state,
            "v2_prediction_present": self.v2_prediction_present,
        }


@dataclasses.dataclass
class DailyCounters:
    live_trades_today: int = 0
    realized_loss_usdt_today: float = 0.0


@dataclasses.dataclass(frozen=True)
class GateDecision:
    """Carries the parameters the transport re-validates from current
    state at submission time. The ``_token`` field is a
    defense-in-depth marker; the real safety guarantee is that the
    transport re-reads disk/Redis state at submission time and
    re-runs the 14-gate cascade. A forged ``GateDecision`` cannot
    bypass re-validation."""

    candidate: IntentCandidate
    approval_file_path: Path
    codex_final_pass_marker_path: Path
    permission_probe_status_path: Path
    kill_switch_redis_client: Any = None
    daily_counters: DailyCounters = dataclasses.field(default_factory=DailyCounters)
    dry_run: bool = True
    live_enabled: bool = False
    permission_probe_freshness_max_seconds: int = (
        DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS
    )
    _token: str = ""


def _create_gate_decision(
    *,
    candidate: IntentCandidate,
    approval_file_path: Path,
    codex_final_pass_marker_path: Path,
    permission_probe_status_path: Path,
    kill_switch_redis_client: Any,
    daily_counters: DailyCounters,
    dry_run: bool,
    live_enabled: bool,
    permission_probe_freshness_max_seconds: int = DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
) -> GateDecision:
    """Module-private factory that stamps a freshly-generated
    GateDecision with the per-process token. The transport's token
    check is a defense-in-depth marker only; the real safety
    guarantee is the re-validation step that re-reads disk/Redis
    state."""
    return GateDecision(
        candidate=candidate,
        approval_file_path=approval_file_path,
        codex_final_pass_marker_path=codex_final_pass_marker_path,
        permission_probe_status_path=permission_probe_status_path,
        kill_switch_redis_client=kill_switch_redis_client,
        daily_counters=daily_counters,
        dry_run=dry_run,
        live_enabled=live_enabled,
        permission_probe_freshness_max_seconds=permission_probe_freshness_max_seconds,
        _token=_MODULE_GATE_TOKEN,
    )


def _evaluate_real_order_blockers(
    *,
    approval: ApprovalEnvelope,
    candidate: IntentCandidate,
    codex_final_pass_marker_path: Path,
    permission_probe_freshness: PermissionProbeFreshness,
    redis_client: Any,
    daily_counters: DailyCounters,
    dry_run: bool,
    live_enabled: bool,
) -> list[str]:
    """Shared 14-gate evaluator. Called by both
    ``LiveCanaryExecutionAdapter.evaluate_real_order_blockers``
    (during intent building) and by the real transport's
    ``submit_signed_canary_order`` (during submission re-validation).
    Sharing the implementation guarantees the two evaluations cannot
    drift."""
    blockers: list[str] = []
    if not approval.approval_file_present:
        blockers.append("GATE_1_OPERATOR_APPROVAL_FILE_ABSENT")
    if not codex_final_pass_marker_path.exists():
        blockers.append("GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT")
    if not permission_probe_freshness.pass_present:
        blockers.append("GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT")
    elif not permission_probe_freshness.fresh:
        blockers.append(
            f"GATE_3_PERMISSION_PROBE_STALE_AGE_SECONDS_{int(permission_probe_freshness.age_seconds)}"
        )
    if approval.canary_mode_selected not in (
        "V2_NATIVE_SIGNAL_CANARY",
        "LEGACY_SIGNAL_V2_EXECUTION_CANARY",
    ):
        blockers.append("GATE_4_CANARY_MODE_NOT_SELECTED_OR_INVALID")
    if not approval.allowed_symbols:
        blockers.append("GATE_5_APPROVED_SYMBOL_WHITELIST_EMPTY")
    if candidate.symbol not in approval.allowed_symbols:
        blockers.append("GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST")
    max_notional = approval.max_notional_usdt
    if max_notional is None or max_notional <= 0:
        blockers.append("GATE_7_MAX_NOTIONAL_CAP_MISSING_OR_NONPOSITIVE")
    elif candidate.requested_notional_usdt > max_notional:
        blockers.append("GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP")
    max_trades = approval.max_daily_live_trades
    if max_trades is None or daily_counters.live_trades_today >= max_trades:
        blockers.append("GATE_9_DAILY_TRADE_COUNT_AT_OR_ABOVE_LIMIT")
    max_loss = approval.max_daily_loss_usdt
    if max_loss is None or daily_counters.realized_loss_usdt_today >= max_loss:
        blockers.append("GATE_10_DAILY_LOSS_AT_OR_ABOVE_LIMIT")
    if _kill_switch_active(redis_client):
        blockers.append("GATE_11_KILL_SWITCH_ARMED")
    if not live_enabled:
        blockers.append("GATE_12_LIVE_ENABLED_FALSE")
    if dry_run:
        blockers.append("GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER")
    declared = tuple(sorted(approval.runtime_live_symbols_requested))
    approved = tuple(sorted(approval.allowed_symbols))
    if declared != approved:
        blockers.append("GATE_13_RUNTIME_LIVE_SYMBOLS_NOT_EQUAL_APPROVED_SYMBOLS")
    if approval.runtime_live_gate_requested != "live_canary_operator_approved":
        blockers.append("GATE_13_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED")
    if approval.leverage_change_approved:
        blockers.append("GATE_14_LEVERAGE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.margin_mode_change_approved:
        blockers.append("GATE_14_MARGIN_MODE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.redis_trim_approved:
        blockers.append("GATE_14_REDIS_TRIM_APPROVAL_PRESENT_NOT_ALLOWED")
    if approval.legacy_shutdown_approved:
        blockers.append("GATE_14_LEGACY_SHUTDOWN_APPROVAL_PRESENT_NOT_ALLOWED")
    return blockers


def _blocked_response(
    blockers: list[str], status_label: str = "REJECTED_GATE_REVALIDATION_FAILED"
) -> dict[str, Any]:
    return {
        "real_order_submitted": False,
        "real_order_attempted": False,
        "places_real_order": False,
        "writes_exchange_orders": False,
        "writes_legacy_redis": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "exchange_response_status": status_label,
        "fail_blockers": blockers,
    }


class ExchangeAdapter(Protocol):
    """Transport protocol. The ONLY public method is
    ``submit_signed_canary_order``, which receives a ``GateDecision``
    and is responsible for re-validating all 14 gates before any
    network call."""

    def submit_signed_canary_order(
        self, *, gate_decision: GateDecision
    ) -> dict[str, Any]: ...


class FakeExchangeAdapter:
    """Default canary transport used in dry-run / blocked paths.

    Records the ``GateDecision`` in memory and NEVER opens a
    network socket. The fake transport's ``submit_signed_canary_order``
    returns a payload pinned to ``real_order_submitted=False``.
    """

    def __init__(self) -> None:
        self.submit_calls: list[GateDecision] = []
        self.call_count: int = 0

    def submit_signed_canary_order(
        self, *, gate_decision: GateDecision
    ) -> dict[str, Any]:
        self.call_count += 1
        self.submit_calls.append(gate_decision)
        return {
            "kind": "FAKE_DRY_RUN_RECORD",
            "real_order_submitted": False,
            "real_order_attempted": False,
            "places_real_order": False,
            "intent_recorded": True,
            "exchange_response_status": "FAKE_NO_NETWORK_CALL",
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
        }


class BinanceFuturesExchangeAdapter:
    """Real Binance Futures WebSocket API transport.

    The ONLY public method is ``submit_signed_canary_order``. That
    method INDEPENDENTLY re-reads operator approval file, Codex
    final marker, permission probe status file, kill switch Redis
    state, and runtime live gate / live symbols at the moment of
    submission, then re-runs the shared 14-gate cascade. The
    network call is unreachable when any gate fails.

    NEVER cancels orders. NEVER modifies orders. NEVER changes
    leverage. NEVER changes margin mode. NEVER writes legacy Redis.
    """

    ORDER_METHOD = "order.place"
    WS_TIMEOUT_SECONDS = 10.0
    RECV_WINDOW_MS = 5000

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        ws_api_url: str | None = None,
        ws_sender: Callable[..., dict[str, Any]] | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "BINANCE_FUTURES_EXCHANGE_ADAPTER_REQUIRES_CREDENTIALS"
            )
        self._api_key = api_key
        self._api_secret = api_secret
        self._ws_api_url = (ws_api_url or binance_ws_api_url()).rstrip("/")
        self._ws_sender = ws_sender or default_ws_api_sender
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def submit_signed_canary_order(
        self, *, gate_decision: GateDecision
    ) -> dict[str, Any]:
        """The ONLY method on this class that may reach
        WebSocket API sender. The 14-gate revalidation and signed
        ``order.place`` submission are physically in the same function so that
        no callable bypass exists (private or otherwise). Steps in order:

        1. Reject anything that is not a ``GateDecision`` instance.
        2. Reject a ``GateDecision`` whose ``_token`` does not equal
           the module's per-process token (defense-in-depth).
        3. Re-read operator approval file from disk.
        4. Re-read permission probe status file from disk.
        5. Re-run the shared 14-gate cascade against the freshly-read
           state.
        6. On ANY blocker, return a blocked response WITHOUT calling the
           WebSocket sender.
        7. Only after a clean re-validation, build the signed WebSocket API
           request and call the configured WebSocket sender.

        There is no ``_perform_signed_post``. There is no ``_signed_post``,
        ``_post_order``, ``_submit_order_raw``, or ``submit_raw``. The gate
        revalidation and the WebSocket network call cannot be separated.
        """
        # ------------------------------------------------------------------
        # Step 1: type-level rejection.
        # ------------------------------------------------------------------
        if not isinstance(gate_decision, GateDecision):
            return _blocked_response(
                ["REJECTED_NON_GATE_DECISION_OBJECT"],
                status_label="REJECTED_NON_GATE_DECISION_OBJECT",
            )
        # ------------------------------------------------------------------
        # Step 2: token-level rejection (defense-in-depth).
        # ------------------------------------------------------------------
        if getattr(gate_decision, "_token", "") != _MODULE_GATE_TOKEN:
            return _blocked_response(
                ["REJECTED_FORGED_GATE_DECISION_TOKEN"],
                status_label="REJECTED_FORGED_GATE_DECISION_TOKEN",
            )
        # ------------------------------------------------------------------
        # Step 3: re-read operator approval + Codex final marker +
        # permission probe from current disk / Redis state.
        # ------------------------------------------------------------------
        fresh_approval = parse_approval_file(gate_decision.approval_file_path)
        fresh_probe = PermissionProbeFreshness.from_path(
            gate_decision.permission_probe_status_path,
            max_age_seconds=gate_decision.permission_probe_freshness_max_seconds,
        )
        # ------------------------------------------------------------------
        # Step 4: independent 14-gate revalidation. Identical logic to
        # ``LiveCanaryExecutionAdapter.evaluate_real_order_blockers`` so
        # the two evaluations cannot drift.
        # ------------------------------------------------------------------
        blockers = _evaluate_real_order_blockers(
            approval=fresh_approval,
            candidate=gate_decision.candidate,
            codex_final_pass_marker_path=gate_decision.codex_final_pass_marker_path,
            permission_probe_freshness=fresh_probe,
            redis_client=gate_decision.kill_switch_redis_client,
            daily_counters=gate_decision.daily_counters,
            dry_run=gate_decision.dry_run,
            live_enabled=gate_decision.live_enabled,
        )
        if blockers:
            return _blocked_response(
                blockers, status_label="REJECTED_GATE_REVALIDATION_FAILED"
            )
        # ------------------------------------------------------------------
        # Step 5: candidate shape check (cheap defensive read).
        # ------------------------------------------------------------------
        candidate = gate_decision.candidate
        symbol = candidate.symbol
        side = candidate.side
        quantity = candidate.requested_quantity
        if not symbol or not side or quantity is None:
            return _blocked_response(
                ["MALFORMED_INTENT"], status_label="MALFORMED_INTENT"
            )
        # ------------------------------------------------------------------
        # Step 6: build a maker-first LIMIT+GTX WebSocket order in this same
        # function. No REST endpoint is primary for canary order submission,
        # and a live canary entry must fail closed unless it carries enough
        # current book/filter context to prove the post-only order will not
        # cross the spread.
        # ------------------------------------------------------------------
        symbol_filters = dict(candidate.symbol_filters or {})
        if not symbol_filters:
            return _blocked_response(
                ["MAKER_FIRST_SYMBOL_FILTERS_MISSING"],
                status_label="REJECTED_MAKER_FIRST_ORDER_PLAN",
            )
        plan = build_binance_order_plan(
            symbol=str(symbol),
            side=str(side),
            symbol_filters=symbol_filters,
            hedge_mode=bool(candidate.hedge_mode),
            generated_utc=_utc_iso(),
            current_price=candidate.current_price,
            best_bid=candidate.best_bid,
            best_ask=candidate.best_ask,
            quantity=quantity,
            notional_usd=candidate.requested_notional_usdt,
            order_type="LIMIT",
            time_in_force="GTX",
            close_position=False,
            reduce_only=False,
            maker_fee_bps=candidate.maker_fee_bps,
            taker_fee_bps=candidate.taker_fee_bps,
        )
        reject_reasons = list(plan.get("builder_reject_reasons") or [])
        if not plan.get("symbol_filter_pass"):
            reject_reasons.append("SYMBOL_FILTER_PASS_FALSE")
        if not plan.get("maker_first") or plan.get("order_type") != "LIMIT":
            reject_reasons.append("MAKER_FIRST_LIMIT_GTX_REQUIRED")
        if plan.get("timeInForce") != "GTX":
            reject_reasons.append("POST_ONLY_GTX_REQUIRED")
        if plan.get("post_only_cross_spread_risk"):
            reject_reasons.append("POST_ONLY_WOULD_CROSS_OR_BOOK_MISSING")
        params = dict(plan.get("order_params") or {})
        if reject_reasons or not params:
            return _blocked_response(
                sorted(set(reject_reasons or ["MAKER_FIRST_ORDER_PLAN_INVALID"])),
                status_label="REJECTED_MAKER_FIRST_ORDER_PLAN",
            )
        params["recvWindow"] = self.RECV_WINDOW_MS
        request_payload = build_signed_ws_api_request(
            method=self.ORDER_METHOD,
            params=params,
            api_key=self._api_key,
            api_secret=self._api_secret,
            request_id=f"v2_canary_{int(self._clock_ms())}",
            clock_ms=self._clock_ms,
        )
        # ------------------------------------------------------------------
        # Step 7: call the WebSocket API sender. This is the only real exchange
        # network call site on the class.
        # ------------------------------------------------------------------
        try:
            response = self._ws_sender(
                endpoint=self._ws_api_url,
                payload=request_payload,
                timeout=self.WS_TIMEOUT_SECONDS,
            )
            response_payload = (
                response.get("response") if isinstance(response, Mapping) else None
            )
            ws_status = (
                int(response.get("status_code") or 0)
                if isinstance(response, Mapping)
                else 0
            )
            submitted = bool(response.get("ok")) and ws_status == 200 if isinstance(response, Mapping) else False
            return {
                "real_order_submitted": submitted,
                "real_order_attempted": True,
                "places_real_order": submitted,
                "writes_exchange_orders": submitted,
                "exchange_response_status": f"WS_{ws_status}" if ws_status else "WS_ERROR",
                "websocket_api_url": self._ws_api_url,
                "websocket_method": self.ORDER_METHOD,
                "request_redacted": redacted_json(request_payload),
                "response_redacted": redacted_json(response_payload or {}),
                "rest_fallback_used": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
                "writes_legacy_redis": False,
            }
        except Exception as e:
            return {
                "real_order_submitted": False,
                "real_order_attempted": True,
                "places_real_order": False,
                "writes_exchange_orders": False,
                "exchange_response_status": f"WS_ERROR:{type(e).__name__}",
                "websocket_api_url": self._ws_api_url,
                "websocket_method": self.ORDER_METHOD,
                "request_redacted": redacted_json(request_payload),
                "rest_fallback_used": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
                "writes_legacy_redis": False,
            }


class LiveCanaryExecutionAdapter:
    """Operator-gated live-canary execution adapter.

    Default state at construction time:

    - ``exchange_adapter = FakeExchangeAdapter`` (no network surface)
    - ``dry_run = True``
    - ``live_enabled = False``
    - ``live_gate = "blocked_human_only"`` (reported in payload)
    - ``live_symbols = []`` (reported in payload)
    - ``direct_call_bypass_remediated = True``
    - ``caller_supplied_gate_boolean_accepted = False``
    - ``final_submit_rechecks_all_gates = True``

    No caller-supplied boolean field can authorize a real order.
    The transport's ``submit_signed_canary_order`` ALWAYS
    re-validates the 14 gates from current disk/Redis state at the
    moment of submission.
    """

    def __init__(
        self,
        *,
        redis_client: Any = None,
        approval: ApprovalEnvelope | None = None,
        exchange_adapter: Any = None,
        approval_file_path: Path | None = None,
        codex_pass_marker_path: Path | None = None,
        codex_final_pass_marker_path: Path | None = None,
        permission_probe_status_path: Path | None = None,
        permission_probe_freshness_max_seconds: int = DEFAULT_PERMISSION_PROBE_FRESHNESS_MAX_SECONDS,
        dry_run: bool = True,
        live_enabled: bool = False,
        # Backward-compat with the prior packet:
        permission_probe_go_no_go: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._approval = approval or ApprovalEnvelope.closed_default()
        self._exchange_adapter = exchange_adapter or FakeExchangeAdapter()
        self._approval_file_path = approval_file_path or APPROVAL_FILE_PATH
        self._codex_pass_marker_path = (
            codex_pass_marker_path or CODEX_PASS_MARKER_PATH
        )
        self._codex_final_pass_marker_path = (
            codex_final_pass_marker_path or CODEX_FINAL_PASS_MARKER_PATH
        )
        self._permission_probe_status_path = (
            permission_probe_status_path or PERMISSION_PROBE_STATUS_PATH
        )
        self._permission_probe_freshness_max_seconds = (
            permission_probe_freshness_max_seconds
        )
        self._dry_run = bool(dry_run)
        self._live_enabled = bool(live_enabled)
        self._daily = DailyCounters()
        self._probe_go_override = permission_probe_go_no_go

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled

    @property
    def approval(self) -> ApprovalEnvelope:
        return self._approval

    @property
    def exchange_adapter(self) -> Any:
        return self._exchange_adapter

    def _read_permission_probe_freshness(self) -> PermissionProbeFreshness:
        if self._probe_go_override is not None:
            return PermissionProbeFreshness(
                pass_present=self._probe_go_override == PROBE_GO_READY,
                fresh=True,
                age_seconds=0.0,
                go_no_go=self._probe_go_override,
            )
        return PermissionProbeFreshness.from_path(
            self._permission_probe_status_path,
            max_age_seconds=self._permission_probe_freshness_max_seconds,
        )

    def evaluate_real_order_blockers(
        self,
        candidate: IntentCandidate,
        *,
        freshness: PermissionProbeFreshness | None = None,
    ) -> list[str]:
        probe = freshness or self._read_permission_probe_freshness()
        return _evaluate_real_order_blockers(
            approval=self._approval,
            candidate=candidate,
            codex_final_pass_marker_path=self._codex_final_pass_marker_path,
            permission_probe_freshness=probe,
            redis_client=self._redis,
            daily_counters=self._daily,
            dry_run=self._dry_run,
            live_enabled=self._live_enabled,
        )

    def evaluate_pretrade_blockers(
        self,
        *,
        candidate: IntentCandidate,
    ) -> list[str]:
        return self.evaluate_real_order_blockers(candidate)

    def build_intent_record(
        self,
        *,
        candidate: IntentCandidate,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        blockers = self.evaluate_real_order_blockers(candidate)
        probe = self._read_permission_probe_freshness()
        return {
            "schema_version": "v2_live_canary_intent_v3",
            "cycle_id": cycle_id,
            "generated_utc": _utc_iso(),
            "candidate": candidate.as_payload(),
            "signal_source": candidate.signal_source,
            "v2_trainer_parity_claimed": False,
            "approved_envelope": {
                "approval_file_present": self._approval.approval_file_present,
                "canary_mode_selected": self._approval.canary_mode_selected,
                "allowed_symbols": list(self._approval.allowed_symbols),
                "max_notional_usdt": self._approval.max_notional_usdt,
                "max_daily_live_trades": self._approval.max_daily_live_trades,
                "max_daily_loss_usdt": self._approval.max_daily_loss_usdt,
                "leverage_change_approved": self._approval.leverage_change_approved,
                "margin_mode_change_approved": self._approval.margin_mode_change_approved,
                "redis_trim_approved": self._approval.redis_trim_approved,
                "legacy_shutdown_approved": self._approval.legacy_shutdown_approved,
                "runtime_live_gate_requested": self._approval.runtime_live_gate_requested,
                "runtime_live_symbols_requested": list(
                    self._approval.runtime_live_symbols_requested
                ),
            },
            "permission_probe": {
                "pass_present": probe.pass_present,
                "fresh": probe.fresh,
                "age_seconds": probe.age_seconds if probe.age_seconds != float("inf") else None,
                "go_no_go": probe.go_no_go,
            },
            "exchange_adapter_kind": type(self._exchange_adapter).__name__,
            "kill_switch_active": _kill_switch_active(self._redis),
            "dry_run": self._dry_run,
            "live_enabled": self._live_enabled,
            "fail_blockers": list(blockers),
            "would_advance_to_live_submission": (
                not blockers and self._live_enabled and not self._dry_run
            ),
            "real_order_submitted": False,
            "real_order_attempted": False,
            "places_real_order": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "direct_call_bypass_remediated": True,
            "caller_supplied_gate_boolean_accepted": False,
            "final_submit_rechecks_all_gates": True,
        }

    def submit_canary_order(
        self,
        *,
        candidate: IntentCandidate,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the gate cascade, build a GateDecision, and dispatch to
        the configured transport. The default transport is
        ``FakeExchangeAdapter`` (no network). Even when a real
        transport is configured, the transport's
        ``submit_signed_canary_order`` independently re-validates
        the 14 gates from current disk/Redis state before any
        urlopen call."""
        intent = self.build_intent_record(candidate=candidate, cycle_id=cycle_id)
        self.persist_intent(intent)
        blockers = list(intent["fail_blockers"])
        gate_decision = _create_gate_decision(
            candidate=candidate,
            approval_file_path=self._approval_file_path,
            codex_final_pass_marker_path=self._codex_final_pass_marker_path,
            permission_probe_status_path=self._permission_probe_status_path,
            kill_switch_redis_client=self._redis,
            daily_counters=self._daily,
            dry_run=self._dry_run,
            live_enabled=self._live_enabled,
            permission_probe_freshness_max_seconds=self._permission_probe_freshness_max_seconds,
        )
        if blockers:
            # On blocked path use a fresh fake transport so the
            # configured (possibly real) transport is NEVER reached
            # when any gate fails.
            fake = FakeExchangeAdapter()
            response = fake.submit_signed_canary_order(gate_decision=gate_decision)
            result = self._build_outcome(
                intent=intent,
                response=response,
                blockers=blockers,
                outcome="BLOCKED_REAL_ORDER_REFUSED",
                live_gate_state="blocked_human_only",
                live_symbols_state=[],
            )
            self.write_ledger_entry(result)
            return result
        # All gates passed at this evaluation. Hand to the configured
        # transport which will ALSO independently re-validate before
        # any network call.
        response = self._exchange_adapter.submit_signed_canary_order(
            gate_decision=gate_decision
        )
        real_submitted = bool(response.get("real_order_submitted"))
        outcome = (
            "OK_REAL_ORDER_SUBMITTED"
            if real_submitted
            else "EXCHANGE_REJECTED_OR_FAKE_ADAPTER"
        )
        result = self._build_outcome(
            intent=intent,
            response=response,
            blockers=list(response.get("fail_blockers", [])),
            outcome=outcome,
            live_gate_state=(
                "live_canary_operator_approved"
                if real_submitted
                else "blocked_human_only"
            ),
            live_symbols_state=(
                list(self._approval.allowed_symbols) if real_submitted else []
            ),
        )
        self.write_ledger_entry(result)
        if real_submitted:
            self._daily.live_trades_today += 1
        return result

    def _build_outcome(
        self,
        *,
        intent: dict[str, Any],
        response: Mapping[str, Any],
        blockers: list[str],
        outcome: str,
        live_gate_state: str,
        live_symbols_state: list[str],
    ) -> dict[str, Any]:
        real_submitted = bool(response.get("real_order_submitted"))
        real_attempted = bool(response.get("real_order_attempted"))
        return {
            "schema_version": "v2_live_canary_execution_outcome_v2",
            "generated_utc": _utc_iso(),
            "go_no_go": outcome,
            "intent": intent,
            "fail_blockers": blockers,
            "exchange_response": dict(response),
            "exchange_adapter_kind": type(self._exchange_adapter).__name__,
            "real_order_submitted": real_submitted,
            "real_order_attempted": real_attempted,
            "places_real_order": real_submitted,
            "writes_exchange_orders": real_submitted,
            "writes_legacy_redis": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "dry_run": self._dry_run,
            "live_enabled": self._live_enabled,
            "live_gate": live_gate_state,
            "live_symbols": live_symbols_state,
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "raw_credential_in_payload": "NEVER",
            "direct_call_bypass_remediated": True,
            "caller_supplied_gate_boolean_accepted": False,
            "final_submit_rechecks_all_gates": True,
        }

    # Backward-compatible alias kept for existing callers/tests.
    def submit_live_canary_order(
        self,
        *,
        candidate: IntentCandidate,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        return self.submit_canary_order(candidate=candidate, cycle_id=cycle_id)

    def persist_intent(self, intent: dict[str, Any]) -> bool:
        if self._redis is None:
            return False
        try:
            raw = self._redis.get(KEY_INTENTS)
            current = json.loads(raw) if raw else []
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        current.append(intent)
        return _safe_redis_set(
            self._redis,
            KEY_INTENTS,
            json.dumps(current[-100:]),
            ex=DEFAULT_INTENTS_TTL_SECONDS,
        )

    def write_heartbeat(self, payload: dict[str, Any]) -> bool:
        return _safe_redis_set(
            self._redis,
            KEY_HEARTBEAT,
            json.dumps(payload),
            ex=DEFAULT_HEARTBEAT_TTL_SECONDS,
        )

    def write_status(self, payload: dict[str, Any]) -> bool:
        return _safe_redis_set(
            self._redis,
            KEY_STATUS,
            json.dumps(payload),
            ex=DEFAULT_STATUS_TTL_SECONDS,
        )

    def write_ledger_entry(self, entry: dict[str, Any]) -> bool:
        if self._redis is None:
            return False
        try:
            raw = self._redis.get(KEY_LEDGER)
            current = json.loads(raw) if raw else []
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        current.append(entry)
        return _safe_redis_set(
            self._redis,
            KEY_LEDGER,
            json.dumps(current[-200:]),
            ex=DEFAULT_LEDGER_TTL_SECONDS,
        )


# Map each canonical field key to a tuple of acceptable key aliases.
# The operator's approval file may use either the strict ``KEY: VALUE``
# convention or the human-prose form documented in the live-canary
# acceptance template (e.g. ``Approved live canary mode: ...``). The
# parser checks every alias before falling back to the closed default.
APPROVAL_FILE_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "canary_mode": (
        "canary_mode",
        "approved canary mode",
        "approved live canary mode",
        "canary mode",
    ),
    "live_symbols": (
        "live_symbols",
        "approved live symbols",
        "approved symbols",
    ),
    "max_notional_usdt": (
        "max_notional_usdt",
        "max notional usdt",
        "max notional usdt per order",
        "max notional per order usdt",
        "max notional per order",
    ),
    "max_daily_live_trades": (
        "max_daily_live_trades",
        "max daily live trades",
        "max daily trades",
    ),
    "max_daily_loss_usdt": (
        "max_daily_loss_usdt",
        "max daily loss usdt",
        "max daily loss",
    ),
    "leverage_change_approved": (
        "leverage_change_approved",
        "leverage change approved",
    ),
    "margin_mode_change_approved": (
        "margin_mode_change_approved",
        "margin mode change approved",
        "margin change approved",
    ),
    "redis_trim_approved": (
        "redis_trim_approved",
        "redis trim approved",
    ),
    "legacy_shutdown_approved": (
        "legacy_shutdown_approved",
        "legacy shutdown approved",
    ),
    "runtime_live_gate": (
        "runtime_live_gate",
        "runtime live gate",
        "live_gate target for canary only",
        "live_gate target",
        "live gate target",
    ),
    "runtime_live_symbols": (
        "runtime_live_symbols",
        "runtime live symbols",
        "live_symbols target for canary only",
        "live_symbols target",
        "live symbols target",
    ),
}

# Sentence-style "is not approved" lines (no colon) used by the operator
# to deny a category. Each tuple maps a canonical field key to a list of
# substrings whose presence anywhere in the file forces the boolean to
# False. This is read-only enforcement — it can never flip a flag to
# True, only confirm a deny.
APPROVAL_FILE_PROSE_DENIES: dict[str, tuple[str, ...]] = {
    "leverage_change_approved": (
        "leverage change is not approved",
        "leverage is not approved",
        "no leverage change",
    ),
    "margin_mode_change_approved": (
        "margin mode change is not approved",
        "margin change is not approved",
        "no margin mode change",
    ),
    "redis_trim_approved": (
        "redis trim is not approved",
        "no redis trim",
    ),
    "legacy_shutdown_approved": (
        "legacy shutdown is not approved",
        "shutdown is not approved",
        "no legacy shutdown",
    ),
}


def parse_approval_file(approval_path: Path | None = None) -> ApprovalEnvelope:
    """Parse the operator approval markdown into a structured envelope.

    Accepts both strict ``KEY: VALUE`` lines and the operator's
    natural-language form (e.g.
    ``Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY``).
    For deny-style sentence lines like ``Leverage change is not
    approved.``, the parser keeps the corresponding boolean field
    pinned at False. No sentence form can flip a deny field to True;
    that still requires an explicit ``KEY: YES`` / ``KEY: TRUE`` /
    ``KEY: 1`` line."""
    path = approval_path or APPROVAL_FILE_PATH
    if not path.exists():
        return ApprovalEnvelope.closed_default()
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ApprovalEnvelope.closed_default()

    text_lower = text.lower()

    def _val(key: str) -> str | None:
        aliases = APPROVAL_FILE_KEY_ALIASES.get(key, (key,))
        alias_lower = tuple(a.lower() for a in aliases)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            if k.strip().lower() in alias_lower:
                return v.strip()
        return None

    def _float(key: str) -> float | None:
        v = _val(key)
        if v is None:
            return None
        try:
            return float(v.replace(",", "").rstrip("uUsSdDtT").strip())
        except ValueError:
            return None

    def _int(key: str) -> int | None:
        v = _val(key)
        if v is None:
            return None
        try:
            return int(float(v.replace(",", "").strip()))
        except ValueError:
            return None

    def _bool_strict(key: str) -> bool:
        # Sentence-style deny lines force the field to False even if a
        # later explicit YES would otherwise flip it. This makes the
        # deny prose binding and prevents accidental drift.
        deny_phrases = APPROVAL_FILE_PROSE_DENIES.get(key, tuple())
        for phrase in deny_phrases:
            if phrase in text_lower:
                return False
        v = _val(key)
        if v is None:
            return False
        return v.strip().upper() in ("YES", "TRUE", "1")

    def _symbols(key: str) -> tuple[str, ...]:
        v = _val(key)
        if not v:
            return tuple()
        cleaned = v.replace("[", "").replace("]", "")
        return tuple(s.strip().upper() for s in cleaned.split(",") if s.strip())

    mode_label = (_val("canary_mode") or "BLOCKED_UNSELECTED").strip()
    if mode_label not in (
        "V2_NATIVE_SIGNAL_CANARY",
        "LEGACY_SIGNAL_V2_EXECUTION_CANARY",
    ):
        mode_label = "BLOCKED_UNSELECTED"

    runtime_gate = (_val("runtime_live_gate") or "blocked_human_only").strip()
    if runtime_gate != "live_canary_operator_approved":
        runtime_gate = "blocked_human_only"

    return ApprovalEnvelope(
        approval_file_present=True,
        canary_mode_selected=mode_label,
        allowed_symbols=_symbols("live_symbols"),
        max_notional_usdt=_float("max_notional_usdt"),
        max_daily_live_trades=_int("max_daily_live_trades"),
        max_daily_loss_usdt=_float("max_daily_loss_usdt"),
        leverage_change_approved=_bool_strict("leverage_change_approved"),
        margin_mode_change_approved=_bool_strict("margin_mode_change_approved"),
        redis_trim_approved=_bool_strict("redis_trim_approved"),
        legacy_shutdown_approved=_bool_strict("legacy_shutdown_approved"),
        runtime_live_gate_requested=runtime_gate,
        runtime_live_symbols_requested=_symbols("runtime_live_symbols"),
    )
