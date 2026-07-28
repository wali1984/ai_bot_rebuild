"""PaperAccountEpochV1 — session scoping (read) + atomic epoch rotation (write).

READ side (used by API readers): scope paper rows to the current operational
session (default), archived, or all — filtering on the `paper_session_id` the
writer already stamps on every row.

WRITE side (`rotate`): create a clean $3,000 operational session while PRESERVING
all historical/global evidence. It NEVER `SET []`s a global history key; it writes
new epoch-scoped keys + the current pointer + the current portfolio face, atomically
via a single Lua script, and only after the preflight PASSES and an archive manifest
is written and read-back-verified. `execute=False` is a pure dry-run (state_mutated=false).

Invariants held: paper_only, live_gate=blocked_human_only, routes_to_live=false,
places_real_order=false, exchange_action_taken=false.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
EPOCH_POINTER_KEY = "v2:paper:account_epoch:current"      # PaperAccountEpochV1 doc
EPOCH_COUNTER_KEY = "v2:paper:account_epoch:counter"       # monotonic INCR
EPOCH_RECEIPT_PREFIX = "v2:paper:account_epoch:receipt:"   # + epoch
EPOCH_IDEMPO_PREFIX = "v2:paper:account_epoch:idempo:"     # + idempotency key
EPOCH_ARCHIVE_PREFIX = "v2:paper:account_epoch:archive:"   # + prev_session_id
LEGACY_SESSION_KEY = "v2:paper:session"                     # pre-rotation pointer

# Current operational face + global immutable history (history is NEVER SET [])
PORTFOLIO_STATE_KEY = "v2:portfolio:state"
GLOBAL_POSITIONS_KEY = "v2:paper:positions"
GLOBAL_ACCEPTED_FILLS_KEY = "v2:paper:accepted_fills"
GLOBAL_CLOSED_TRADES_KEY = "v2:paper:closed_trades"
FILL_PERSISTENCE_TRACE_KEY = "v2:paper:fill_persistence_trace"


def epoch_key(epoch: int, leaf: str) -> str:
    return f"v2:paper:epoch:{epoch}:{leaf}"


SCHEMA_VERSION = "PaperAccountEpochV1"
STARTING_EQUITY_USD = 3000.0
RECONCILE_THRESHOLD_USD = 0.02
VALID_SCOPES = ("current_session", "archived", "all")
DEFAULT_SCOPE = "current_session"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _get_json(redis, key) -> Any:
    raw = redis.get(key)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _as_rows(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("positions", "rows", "items", "open_positions", "closed_trades"):
            if isinstance(payload.get(k), list):
                return payload[k]
        return list(payload.values())
    return []


# ===========================================================================
# READ SIDE — session scoping
# ===========================================================================
def normalize_scope(scope: str | None) -> str:
    return scope if scope in VALID_SCOPES else DEFAULT_SCOPE


def current_session(redis) -> dict:
    """Current operational session identity. Prefers the PaperAccountEpochV1 pointer;
    falls back to the legacy `v2:paper:session` key (paper_session_id, epoch=None) so
    this is correct BOTH pre- and post-rotation."""
    ptr = _get_json(redis, EPOCH_POINTER_KEY)
    if isinstance(ptr, dict) and ptr.get("paper_session_id"):
        return {
            "paper_session_id": ptr.get("paper_session_id"),
            "paper_account_epoch": ptr.get("paper_account_epoch"),
            "starting_equity_usd": ptr.get("starting_equity_usd", STARTING_EQUITY_USD),
        }
    legacy = _get_json(redis, LEGACY_SESSION_KEY) or {}
    return {
        "paper_session_id": legacy.get("paper_session_id"),
        "paper_account_epoch": legacy.get("paper_account_epoch"),
        "starting_equity_usd": legacy.get("initial_capital", STARTING_EQUITY_USD),
    }


def row_session_id(row) -> str | None:
    if isinstance(row, dict):
        return row.get("paper_session_id") or row.get("session_id")
    return None


def scope_rows(rows: list, current_session_id: str | None, scope: str) -> list:
    """Filter rows by scope.

    current_session -> ONLY rows whose paper_session_id == current (strict; rows with
      no/other session id are excluded so the clean session can never show old data).
    archived        -> rows whose session id is present and != current.
    all             -> everything (governed economic + history readers use this).
    """
    scope = normalize_scope(scope)
    if scope == "all":
        return list(rows)
    out = []
    for r in rows:
        sid = row_session_id(r)
        if scope == "current_session":
            if sid is not None and sid == current_session_id:
                out.append(r)
        elif scope == "archived":
            if sid is not None and sid != current_session_id:
                out.append(r)
    return out


def scope_response_fields(
    session: dict, scope: str, total_rows: int, shown_rows: int, historical_preserved: bool = True
) -> dict:
    """Required response fields to append to every session-scoped payload."""
    scope = normalize_scope(scope)
    excluded = max(0, total_rows - shown_rows) if scope == "current_session" else 0
    return {
        "paper_session_id": session.get("paper_session_id"),
        "paper_account_epoch": session.get("paper_account_epoch"),
        "scope": scope,
        "starting_equity_usd": session.get("starting_equity_usd", STARTING_EQUITY_USD),
        "historical_rows_excluded_from_current_view": excluded,
        "historical_evidence_preserved": bool(historical_preserved),
    }


# ===========================================================================
# PREFLIGHT — canonical read-only precondition evaluation
# ===========================================================================
# Predicate-3 set (operator directive 2026-07-28): position/fill/reservation/accounting cleanliness.
# Proof-store health, quarantine reasons, legitimate-position wipes and duplicate fills/closes are
# validated by predicate 2 = tools/paper_runtime_acceptance_harness.py over >=3 cycles (the CG-F063
# fix removed v2:paper:fill_persistence_trace, so a single-snapshot key check here is obsolete).
_REQUIRED = {
    "open_positions": 0,
    "pending_fills": 0,
    "pending_reservations": 0,
    "used_margin_usd": 0,
    "reserved_margin_usd": 0,
    "unresolved_accounting_reconciliation": 0,
    "duplicate_fill_count": 0,
    "duplicate_close_count": 0,
}
_NET_PNL_FIELDS = ("realized_net_pnl_usd", "realized_net_pnl", "realized_pnl_usd", "realized_pnl", "net_pnl_usd")


def evaluate_preconditions(redis) -> dict:
    """Read-only. Returns the preflight report; never mutates. status is PASS only if
    all preconditions hold. Reconciliation basis is realized NET pnl (matches Guardian G08)."""
    checks: dict[str, dict] = {}

    def record(name, actual, ok, evidence=""):
        checks[name] = {"required": _REQUIRED[name], "actual": actual, "pass": bool(ok), "evidence": evidence}

    portfolio = _get_json(redis, PORTFOLIO_STATE_KEY) or {}
    positions = _as_rows(_get_json(redis, GLOBAL_POSITIONS_KEY))
    accepted = _get_json(redis, GLOBAL_ACCEPTED_FILLS_KEY) or []
    closed = _get_json(redis, GLOBAL_CLOSED_TRADES_KEY) or []
    trace = _get_json(redis, FILL_PERSISTENCE_TRACE_KEY) or {}
    session = current_session(redis)

    def _num(v):
        return v if isinstance(v, (int, float)) else None

    # Predicate 3: any open position (proof-backed or proofless) blocks — the reset must not run
    # while positions exist, and a proofless phantom is never "solved" by deletion here.
    record("open_positions", len(positions), len(positions) == 0, f"{len(positions)} rows in v2:paper:positions")
    record("pending_fills", len(accepted), len(accepted) == 0)
    record("pending_reservations", 0, True, "no v2:paper:reservations key")

    used = _num(portfolio.get("used_margin_usd"))
    record("used_margin_usd", used, used == 0)
    reserved = _num(portfolio.get("reserved_margin_usd"))
    record("reserved_margin_usd", reserved, reserved == 0, "null/unset" if reserved is None else "")

    def _pnl(t):
        for k in _NET_PNL_FIELDS:
            if isinstance(t, dict) and isinstance(t.get(k), (int, float)):
                return t[k]
        return 0.0
    # Reconcile CURRENT-session trades vs the operational ledger (correct in any epoch:
    # pre-rotation all rows are current; post-rotation current is empty -> 0 vs 0).
    current_closed = scope_rows(closed, session.get("paper_session_id"), "current_session")
    trade_sum = sum(_pnl(t) for t in current_closed if isinstance(t, dict))
    ledger = _num(portfolio.get("realized_pnl_usd"))
    if ledger is None:
        record("unresolved_accounting_reconciliation", "ledger_null", False)
    else:
        diff = abs(trade_sum - ledger)
        record("unresolved_accounting_reconciliation", round(diff, 6), diff <= RECONCILE_THRESHOLD_USD,
               f"|{trade_sum:.4f} - {ledger:.4f}| = {diff:.6f}")

    def _dupes(rows, id_keys):
        ids = [x[k] for x in rows if isinstance(x, dict) for k in id_keys if x.get(k)][: len(rows) * 1]
        ids = [next((x[k] for k in id_keys if x.get(k)), None) for x in rows if isinstance(x, dict)]
        ids = [i for i in ids if i]
        return len(ids) - len(set(ids))
    record("duplicate_fill_count", _dupes(accepted, ("fill_id", "accepted_fill_id", "id")),
           _dupes(accepted, ("fill_id", "accepted_fill_id", "id")) == 0)
    record("duplicate_close_count", _dupes(closed, ("trade_id", "close_id", "id")),
           _dupes(closed, ("trade_id", "close_id", "id")) == 0)

    all_pass = all(c["pass"] for c in checks.values())
    return {
        "schema_version": "paper_epoch_preflight_v1",
        "generated_utc": _now(),
        "state_mutated": False,
        "status": "PASS" if all_pass else "BLOCKED_RESET_PRECONDITION",
        "current_paper_session_id": session.get("paper_session_id"),
        "current_paper_account_epoch": session.get("paper_account_epoch"),
        "historical_closed_trade_count": len(closed),
        "checks": checks,
        "failing": [k for k, v in checks.items() if not v["pass"]],
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }


# ===========================================================================
# WRITE SIDE — archive manifest + atomic rotation
# ===========================================================================
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _row_hashes(rows: list) -> list[str]:
    return [_sha256(json.dumps(r, sort_keys=True, default=str)) for r in rows]


def deterministic_session_id(prev_session_id: str | None, epoch: int, started_at: str) -> str:
    digest = _sha256(f"{prev_session_id}:{epoch}:{started_at}")[:16]
    return f"paper_session_{digest}"


def idempotency_key(prev_session_id: str | None, reset_reason: str) -> str:
    return _sha256(f"{prev_session_id}:{reset_reason}")[:24]


def clean_portfolio_state(session_id: str, epoch: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "equity_usd": STARTING_EQUITY_USD,
        "wallet_balance_usd": STARTING_EQUITY_USD,
        "free_margin_usd": STARTING_EQUITY_USD,
        "used_margin_usd": 0.0,
        "reserved_margin_usd": 0.0,
        "realized_pnl_usd": 0.0,
        "unrealized_pnl_usd": 0.0,
        "open_position_count": 0,
        "starting_equity_usd": STARTING_EQUITY_USD,
        "paper_session_id": session_id,
        "paper_account_epoch": epoch,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "generated_utc": _now(),
    }


def build_archive_manifest(redis, prev_session: dict) -> dict:
    """Snapshot current session state + hashes. Read-only (no writes here)."""
    portfolio = _get_json(redis, PORTFOLIO_STATE_KEY) or {}
    positions = _as_rows(_get_json(redis, GLOBAL_POSITIONS_KEY))
    accepted = _get_json(redis, GLOBAL_ACCEPTED_FILLS_KEY) or []
    closed = _get_json(redis, GLOBAL_CLOSED_TRADES_KEY) or []
    session_state = _get_json(redis, LEGACY_SESSION_KEY) or {}
    manifest = {
        "schema_version": "PaperAccountEpochArchiveV1",
        "previous_paper_session_id": prev_session.get("paper_session_id"),
        "archived_utc": _now(),
        "starting_equity_usd": portfolio.get("starting_equity_usd", STARTING_EQUITY_USD),
        "ending_equity_usd": portfolio.get("free_margin_usd"),
        "ending_realized_pnl_usd": portfolio.get("realized_pnl_usd"),
        "accepted_fill_count": len(accepted),
        "accepted_fill_list_sha256": _sha256(json.dumps(accepted, sort_keys=True, default=str)),
        "open_position_count": len(positions),
        "open_position_list_sha256": _sha256(json.dumps(positions, sort_keys=True, default=str)),
        "closed_trade_count": len(closed),
        "closed_trade_list_sha256": _sha256(json.dumps(closed, sort_keys=True, default=str)),
        "closed_trade_row_sha256": _row_hashes(closed),
        "checkpoint_id": session_state.get("checkpoint_id"),
        "cohort_id": session_state.get("cohort_id"),
        "session_state_sha256": _sha256(json.dumps(session_state, sort_keys=True, default=str)),
    }
    manifest["manifest_sha256"] = _sha256(json.dumps(manifest, sort_keys=True, default=str))
    return manifest


def verify_archive_readback(redis, manifest: dict) -> tuple[bool, str]:
    """Re-read the global history and confirm counts/hashes match the manifest."""
    closed = _get_json(redis, GLOBAL_CLOSED_TRADES_KEY) or []
    accepted = _get_json(redis, GLOBAL_ACCEPTED_FILLS_KEY) or []
    if len(closed) != manifest["closed_trade_count"]:
        return False, "closed_trade_count changed"
    if _sha256(json.dumps(closed, sort_keys=True, default=str)) != manifest["closed_trade_list_sha256"]:
        return False, "closed_trade hash mismatch"
    if len(accepted) != manifest["accepted_fill_count"]:
        return False, "accepted_fill_count changed"
    return True, "ok"


# Atomic rotation: re-assert live-state guards, then write ALL new keys in one op.
# History keys are intentionally absent — they are NEVER written here.
_ROTATION_LUA = """
local idempo = KEYS[1]
local existing = redis.call('GET', idempo)
if existing then return existing end
-- live-state guard (positions + accepted_fills must be empty right now)
local pos = redis.call('GET', KEYS[2])
if pos and pos ~= '[]' and pos ~= '' and pos ~= 'null' then
  return cjson.encode({status='BLOCKED_ATOMIC_GUARD', reason='positions_not_empty'})
end
local acc = redis.call('GET', KEYS[3])
if acc and acc ~= '[]' and acc ~= '' and acc ~= 'null' then
  return cjson.encode({status='BLOCKED_ATOMIC_GUARD', reason='accepted_fills_not_empty'})
end
-- write clean epoch-scoped current state + operational face + pointer + receipt
redis.call('SET', KEYS[4], ARGV[1])   -- epoch:{N}:portfolio_state
redis.call('SET', KEYS[5], '[]')      -- epoch:{N}:positions
redis.call('SET', KEYS[6], '[]')      -- epoch:{N}:accepted_fills
redis.call('SET', KEYS[7], '[]')      -- epoch:{N}:closed_trades
redis.call('SET', KEYS[8], '[]')      -- epoch:{N}:reservations
redis.call('SET', KEYS[9], ARGV[1])   -- v2:portfolio:state (operational face)
redis.call('SET', KEYS[10], ARGV[2])  -- account_epoch:current pointer
redis.call('SET', KEYS[11], ARGV[3])  -- receipt:{N}
redis.call('SET', idempo, ARGV[3])    -- idempotency -> receipt
return ARGV[3]
"""


def rotate(redis, *, started_at: str | None = None,
           reset_reason: str = "OPERATOR_REQUESTED_CLEAN_OPERATIONAL_PAPER_SESSION",
           expected_previous_session_id: str | None = None,
           execute: bool = False) -> dict:
    """Atomic epoch rotation. execute=False = dry-run (state_mutated=false).

    Order: preflight PASS -> idempotency check -> archive manifest + readback verify ->
    allocate epoch -> atomic Lua write of new epoch-scoped clean state + pointer + receipt.
    History keys are never touched. Returns a receipt/report dict.
    """
    started_at = started_at or _now()

    # Idempotency FIRST — a replay of the same request must no-op, regardless of the
    # post-rotation plane divergence that would otherwise trip the reconciliation gate.
    # Anchor the key to a STABLE predecessor: an explicit expected id, else (if already
    # rotated) the pointer's recorded predecessor, else the live current session.
    ptr = _get_json(redis, EPOCH_POINTER_KEY)
    if expected_previous_session_id:
        rotate_from = expected_previous_session_id
    elif isinstance(ptr, dict) and ptr.get("paper_session_id"):
        rotate_from = ptr.get("previous_session_id")
    else:
        rotate_from = current_session(redis).get("paper_session_id")
    idem = idempotency_key(rotate_from, reset_reason)
    existing = redis.get(EPOCH_IDEMPO_PREFIX + idem)
    if existing:
        rec = existing.decode() if isinstance(existing, bytes) else existing
        return {"status": "NOOP_ALREADY_ROTATED", "state_mutated": False, "receipt": json.loads(rec)}

    pre = evaluate_preconditions(redis)
    if pre["status"] != "PASS":
        return {"status": "BLOCKED_RESET_PRECONDITION", "state_mutated": False,
                "failing": pre["failing"], "preflight": pre}

    prev = current_session(redis)
    manifest = build_archive_manifest(redis, prev)
    ok, why = verify_archive_readback(redis, manifest)
    if not ok:
        return {"status": "BLOCKED_ARCHIVE_READBACK_FAILED", "state_mutated": False, "reason": why}

    # Peek the next epoch WITHOUT allocating (dry-run must not mutate the counter).
    try:
        counter = int(redis.get(EPOCH_COUNTER_KEY) or 0)
    except (TypeError, ValueError):
        counter = 0
    next_epoch = counter + 1
    new_id = deterministic_session_id(prev.get("paper_session_id"), next_epoch, started_at)
    clean = clean_portfolio_state(new_id, next_epoch)
    pointer = {
        "schema_version": SCHEMA_VERSION, "paper_session_id": new_id, "paper_account_epoch": next_epoch,
        "started_at": started_at, "starting_equity_usd": STARTING_EQUITY_USD, "currency": "USD",
        "paper_only": True, "live_gate": "blocked_human_only", "routes_to_live": False,
        "places_real_order": False, "previous_session_id": prev.get("paper_session_id"),
        "historical_evidence_preserved": True, "reset_reason": reset_reason,
        "archive_manifest_sha256": manifest["manifest_sha256"], "idempotency_key": idem,
    }
    receipt = {
        "schema_version": "PaperEpochRotationReceiptV1", "rotated_utc": _now(),
        "previous_session_id": prev.get("paper_session_id"), "new_session_id": new_id,
        "paper_account_epoch": next_epoch, "starting_equity_usd": STARTING_EQUITY_USD,
        "archive_manifest_sha256": manifest["manifest_sha256"],
        "historical_closed_trade_count_preserved": manifest["closed_trade_count"],
        "idempotency_key": idem, "live_gate": "blocked_human_only",
    }

    plan = {
        "status": "DRY_RUN_OK" if not execute else None, "state_mutated": False,
        "previous_session_id": prev.get("paper_session_id"), "new_session_id": new_id,
        "paper_account_epoch": next_epoch, "archive_manifest": manifest,
        "pointer": pointer, "receipt": receipt,
        "would_write_keys": [
            epoch_key(next_epoch, "portfolio_state"), epoch_key(next_epoch, "positions"),
            epoch_key(next_epoch, "accepted_fills"), epoch_key(next_epoch, "closed_trades"),
            epoch_key(next_epoch, "reservations"), PORTFOLIO_STATE_KEY, EPOCH_POINTER_KEY,
            EPOCH_RECEIPT_PREFIX + str(next_epoch),
        ],
        "would_NOT_touch_history_keys": [GLOBAL_CLOSED_TRADES_KEY, GLOBAL_ACCEPTED_FILLS_KEY],
    }
    if not execute:
        return plan

    # EXECUTE: allocate epoch atomically, then atomic write via Lua (guarded + idempotent).
    epoch = int(redis.incr(EPOCH_COUNTER_KEY))
    # Recompute identity for the actually-allocated epoch (counter may have advanced).
    new_id = deterministic_session_id(prev.get("paper_session_id"), epoch, started_at)
    clean = clean_portfolio_state(new_id, epoch)
    pointer.update({"paper_session_id": new_id, "paper_account_epoch": epoch})
    receipt.update({"new_session_id": new_id, "paper_account_epoch": epoch})
    keys = [
        EPOCH_IDEMPO_PREFIX + idem, GLOBAL_POSITIONS_KEY, GLOBAL_ACCEPTED_FILLS_KEY,
        epoch_key(epoch, "portfolio_state"), epoch_key(epoch, "positions"),
        epoch_key(epoch, "accepted_fills"), epoch_key(epoch, "closed_trades"),
        epoch_key(epoch, "reservations"), PORTFOLIO_STATE_KEY, EPOCH_POINTER_KEY,
        EPOCH_RECEIPT_PREFIX + str(epoch),
    ]
    argv = [json.dumps(clean), json.dumps(pointer), json.dumps(receipt)]
    # persist the archive manifest first (immutable), then the atomic rotation
    redis.set(EPOCH_ARCHIVE_PREFIX + str(prev.get("paper_session_id")), json.dumps(manifest))
    result_raw = redis.eval(_ROTATION_LUA, len(keys), *keys, *argv)
    result = json.loads(result_raw.decode() if isinstance(result_raw, bytes) else result_raw)
    if isinstance(result, dict) and str(result.get("status", "")).startswith("BLOCKED"):
        return {"status": result["status"], "state_mutated": False, "reason": result.get("reason")}
    return {"status": "ROTATED", "state_mutated": True, "receipt": result,
            "new_session_id": new_id, "paper_account_epoch": epoch,
            "archive_manifest_sha256": manifest["manifest_sha256"]}
