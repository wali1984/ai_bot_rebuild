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
PAPER_LEDGER_KEY = "v2:paper:ledger"
PROOF_STORE_KEY = "v2:paper:open_position_fill_proofs"
PROOF_MANIFEST_KEY = "v2:paper:open_position_fill_proofs:manifest"

# Additional single-key durable historical stores (Commit A gap-fill) — bound under the
# operator's read-only census in goal_state/PAPER_ACCOUNT_EPOCH_RESET/proposed_archive_manifest.json
# (mutability_class HISTORICAL_IMMUTABLE) that were not yet in the archive-evidence set.
ACCEPTED_FILLS_QUARANTINE_KEY = "v2:paper:accepted_fills:quarantine"
CLOSED_TRADES_UNPROVED_QUARANTINE_KEY = "v2:paper:closed_trades:unproved_fill_quarantine"
QUARANTINE_INVALID_CLOSED_TRADES_KEY = "v2:paper:quarantine:invalid_closed_trades"
OUTCOME_LABELS_KEY = "v2:paper:outcome_labels"
ECONOMIC_EVALUATION_COHORT_KEY = "v2:paper:economic_evaluation_cohort"
PROVISIONAL_COHORT_ACTIVATION_KEY = "v2:paper:provisional_cohort_activation"

# Exact operational/economic evidence families frozen into the archive manifest.
# These values are read and hashed; rotation never writes or deletes them.
ARCHIVE_EVIDENCE_KEYS: tuple[str, ...] = (
    PORTFOLIO_STATE_KEY,
    LEGACY_SESSION_KEY,
    GLOBAL_POSITIONS_KEY,
    GLOBAL_ACCEPTED_FILLS_KEY,
    GLOBAL_CLOSED_TRADES_KEY,
    PAPER_LEDGER_KEY,
    FILL_PERSISTENCE_TRACE_KEY,
    PROOF_STORE_KEY,
    PROOF_MANIFEST_KEY,
    "v2:paper:account_margin_status",
    "v2:paper:position_fill_reconciliation:status",
    "v2:adaptive_system:candidate_outcomes:status",
    "v2:adaptive_system:candidate_calibration:v2",
    "v2:model_registry:paper:active",
    "v2:guardian:pit_prediction_observations",
    "v2:paper:performance_circuit_breaker_status",
    ACCEPTED_FILLS_QUARANTINE_KEY,
    CLOSED_TRADES_UNPROVED_QUARANTINE_KEY,
    QUARANTINE_INVALID_CLOSED_TRADES_KEY,
    OUTCOME_LABELS_KEY,
    ECONOMIC_EVALUATION_COHORT_KEY,
    PROVISIONAL_COHORT_ACTIVATION_KEY,
)

# Durable historical evidence stored as a KEY FAMILY (glob) rather than one key — bounded
# SCAN over a narrow, known prefix (never a generic keyspace scan; see
# claude_worklog memory "Realtime WS + Redis SCAN trap" on unbounded glob cost). Each family
# hashes to exactly one evidence source (sorted {key: content_sha256} mapping), so the whole
# family is one tamper-evident anchor.
ARCHIVE_GLOB_EVIDENCE_PATTERNS: tuple[str, ...] = (
    "v2:paper:outcome_memory:*",
    "v2:paper:position_fill_reconciliation:receipts:*",
)

# The remaining durable stores in the operator's 22-store census
# (goal_state/PAPER_ACCOUNT_EPOCH_RESET/proposed_archive_manifest.json) are filesystem-backed
# (fs:model_registry/paper/candidates/*.pt + 10 goal_state/**/GUARDIAN/*.json|jsonl files).
# rotate() performs ONLY Redis writes (the atomic Lua below) and never touches the filesystem,
# so those stores are preserved structurally by construction; this Redis-only engine does not
# hash them (no false claim of coverage — see CLAUDE.md Evidence Integrity Rule). Independent
# filesystem verification is the operator's proposed_archive_manifest.json census.
ARCHIVE_FILESYSTEM_STORES_NOTE = (
    "11 filesystem-backed durable stores (fs:model_registry/paper/candidates/*.pt + 10 "
    "goal_state/**/GUARDIAN/*.json|jsonl files) are structurally preserved because rotate() "
    "performs only Redis writes and never touches the filesystem. They are NOT hashed into "
    "this manifest; verify independently via the operator's proposed_archive_manifest.json census."
)


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
    portfolio = _get_json(redis, PORTFOLIO_STATE_KEY) or {}
    return {
        "paper_session_id": legacy.get("paper_session_id") or portfolio.get("paper_session_id"),
        "paper_account_epoch": legacy.get("paper_account_epoch") or portfolio.get("paper_account_epoch"),
        "starting_equity_usd": (
            legacy.get("initial_capital")
            or legacy.get("starting_equity_usd")
            or portfolio.get("starting_equity_usd")
            or portfolio.get("initial_capital")
            or STARTING_EQUITY_USD
        ),
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


def scope_payload(redis, payload: dict, list_fields: tuple[str, ...], scope: str = DEFAULT_SCOPE) -> dict:
    """Turn an API payload session-aware in one call: filter the named row-list fields to the
    requested scope (default current_session) and merge in the required response fields
    (paper_session_id, paper_account_epoch, scope, starting_equity_usd,
    historical_rows_excluded_from_current_view, historical_evidence_preserved). Returns a new dict;
    does not mutate the input. Pre-rotation this is a no-op (all rows are current-session)."""
    session = current_session(redis)
    sid = session.get("paper_session_id")
    scope = normalize_scope(scope)
    out = dict(payload)
    total = shown = 0
    for field in list_fields:
        rows = payload.get(field)
        if isinstance(rows, list):
            total += len(rows)
            scoped = scope_rows(rows, sid, scope)
            out[field] = scoped
            shown += len(scoped)
    out.update(scope_response_fields(session, scope, total, shown))
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
    "unproved_positions": 0,
    "proof_store_initialized": True,
    "proof_store_backfill_complete": True,
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
    ledger = _get_json(redis, PAPER_LEDGER_KEY) or {}
    proofs = _get_json(redis, PROOF_STORE_KEY)
    proof_manifest = _get_json(redis, PROOF_MANIFEST_KEY)
    session = current_session(redis)

    def _num(v):
        return v if isinstance(v, (int, float)) else None

    # Predicate 3: any open position (proof-backed or proofless) blocks — the reset must not run
    # while positions exist, and a proofless phantom is never "solved" by deletion here.
    record("open_positions", len(positions), len(positions) == 0, f"{len(positions)} rows in v2:paper:positions")
    record("pending_fills", len(accepted), len(accepted) == 0)
    reservation = ledger.get("paper_margin_reservation_status")
    reservation = reservation if isinstance(reservation, dict) else {}
    reservation_rows = reservation.get("reservation_rows")
    pending_reservations = len(reservation_rows) if isinstance(reservation_rows, list) else None
    record(
        "pending_reservations",
        pending_reservations,
        pending_reservations == 0,
        "v2:paper:ledger.paper_margin_reservation_status.reservation_rows",
    )

    used = _num(portfolio.get("used_margin_usd"))
    record("used_margin_usd", used, used == 0)
    reserved = _num(portfolio.get("reserved_margin_usd"))
    if reserved is None:
        reserved = _num(
            reservation.get("reserved_margin_usd")
            if reservation
            else None
        )
    record("reserved_margin_usd", reserved, reserved == 0, "null/unset" if reserved is None else "")

    proof_rows = proofs if isinstance(proofs, list) else []
    manifest_material = (
        {key: value for key, value in proof_manifest.items() if key != "manifest_sha256"}
        if isinstance(proof_manifest, dict)
        else None
    )
    manifest_hash_valid = bool(
        manifest_material is not None
        and proof_manifest.get("manifest_sha256") == _canonical_sha256(manifest_material)
    )
    proof_hash_valid = bool(
        isinstance(proofs, list)
        and isinstance(proof_manifest, dict)
        and proof_manifest.get("proof_count") == len(proof_rows)
        and proof_manifest.get("proofs_sha256") == _canonical_sha256(proof_rows)
    )
    proof_initialized = bool(
        manifest_hash_valid
        and proof_hash_valid
        and proof_manifest.get("initialization_state")
        in {"EMPTY_INITIALIZED_PROOF_SET", "INITIALIZED_OR_BACKFILLED_PROOF_SET"}
    )
    proof_backfill_complete = bool(
        proof_initialized
        and proof_manifest.get("completed") is True
        and proof_manifest.get("unresolved_position_count") == 0
    )
    record(
        "unproved_positions",
        max(0, len(positions) - len(proof_rows)),
        len(positions) == 0 or len(proof_rows) == len(positions),
        PROOF_STORE_KEY,
    )
    record(
        "proof_store_initialized",
        proof_initialized,
        proof_initialized,
        PROOF_MANIFEST_KEY,
    )
    record(
        "proof_store_backfill_complete",
        proof_backfill_complete,
        proof_backfill_complete,
        PROOF_MANIFEST_KEY,
    )

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
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "exchange_action_taken": False,
    }


# ===========================================================================
# WRITE SIDE — archive manifest + atomic rotation
# ===========================================================================
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    )


def _evidence_summary(redis, key: str) -> dict[str, Any]:
    try:
        redis_type = redis.type(key)
        if isinstance(redis_type, bytes):
            redis_type = redis_type.decode("ascii")
    except (AttributeError, TypeError):
        redis_type = "string"
    if redis_type == "none":
        return {
            "key": key,
            "redis_type": "none",
            "present": False,
            "byte_count": 0,
            "content_sha256": None,
            "row_count": None,
            "high_watermarks": {},
        }
    if redis_type != "string":
        dumped = redis.dump(key)
        if isinstance(dumped, str):
            dumped = dumped.encode("utf-8")
        dumped = dumped or b""
        count_method = {
            "list": "llen",
            "hash": "hlen",
            "set": "scard",
            "zset": "zcard",
            "stream": "xlen",
        }.get(str(redis_type))
        row_count = (
            int(getattr(redis, count_method)(key)) if count_method else None
        )
        return {
            "key": key,
            "redis_type": redis_type,
            "present": True,
            "byte_count": len(dumped),
            "content_sha256": hashlib.sha256(dumped).hexdigest(),
            "row_count": row_count,
            "high_watermarks": {},
        }
    raw = redis.get(key)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    present = isinstance(raw, str)
    try:
        parsed = json.loads(raw) if present else None
    except (TypeError, ValueError):
        parsed = None
    row_count = len(parsed) if isinstance(parsed, list) else None
    high_watermarks: dict[str, Any] = {}
    if isinstance(parsed, dict):
        for field in (
            "generated_utc",
            "generated_at",
            "cycle_id",
            "row_count",
            "candidate_count",
            "matured_revision_count",
            "terminal_chain_sha256",
            "canonical_label_archive_chain_sha256",
            "registry_generation",
            "checkpoint_id",
            "cohort_id",
            "receipt_id",
            "receipt_sha256",
        ):
            value = parsed.get(field)
            if value not in (None, ""):
                high_watermarks[field] = value
        archive = parsed.get("archive")
        if isinstance(archive, dict):
            for field in (
                "row_count",
                "candidate_count",
                "matured_revision_count",
                "terminal_chain_sha256",
            ):
                value = archive.get(field)
                if value not in (None, ""):
                    high_watermarks[f"archive.{field}"] = value
        maturation = parsed.get("maturation")
        if isinstance(maturation, dict):
            label_chain = maturation.get("canonical_label_archive_chain_sha256")
            if label_chain not in (None, ""):
                high_watermarks["maturation.canonical_label_archive_chain_sha256"] = label_chain
    return {
        "key": key,
        "redis_type": "string",
        "present": present,
        "byte_count": len(raw.encode("utf-8")) if present else 0,
        "content_sha256": _sha256(raw) if present else None,
        "row_count": row_count,
        "high_watermarks": high_watermarks,
    }


def _row_hashes(rows: list) -> list[str]:
    return [_sha256(json.dumps(r, sort_keys=True, default=str)) for r in rows]


def _glob_evidence_summary(redis, pattern: str) -> dict[str, Any]:
    """Bounded SCAN over a narrow, known key-family prefix (never a generic keyspace
    scan) producing one tamper-evident evidence source for the whole family: the sorted
    {key: content_sha256} mapping, canonically hashed. Missing/empty family -> present=False."""
    try:
        keys = sorted(
            k.decode() if isinstance(k, bytes) else k
            for k in redis.scan_iter(match=pattern, count=500)
        )
    except (AttributeError, TypeError):
        keys = []
    member_hashes: dict[str, Any] = {k: _evidence_summary(redis, k).get("content_sha256") for k in keys}
    return {
        "key": pattern,
        "redis_type": "glob_family",
        "present": bool(keys),
        "byte_count": None,
        "content_sha256": _canonical_sha256(member_hashes) if keys else None,
        "row_count": len(keys),
        "high_watermarks": {},
    }


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
    evidence_sources = [
        _evidence_summary(redis, key) for key in ARCHIVE_EVIDENCE_KEYS
    ] + [
        _glob_evidence_summary(redis, pattern) for pattern in ARCHIVE_GLOB_EVIDENCE_PATTERNS
    ]
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
        "evidence_source_count": len(evidence_sources),
        "evidence_sources": evidence_sources,
        "filesystem_stores_note": ARCHIVE_FILESYSTEM_STORES_NOTE,
        "historical_evidence_preserved": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def verify_archive_readback(redis, manifest: dict) -> tuple[bool, str]:
    """Re-read the global history and confirm counts/hashes match the manifest.

    Checks the two explicit fields first (backward compatible with the original
    contract), then re-verifies every evidence source recorded in the manifest —
    the 22-durable-store single-key + glob-family coverage added for Commit A —
    so a mismatch anywhere in that set aborts the rotation before any write."""
    closed = _get_json(redis, GLOBAL_CLOSED_TRADES_KEY) or []
    accepted = _get_json(redis, GLOBAL_ACCEPTED_FILLS_KEY) or []
    if len(closed) != manifest["closed_trade_count"]:
        return False, "closed_trade_count changed"
    if _sha256(json.dumps(closed, sort_keys=True, default=str)) != manifest["closed_trade_list_sha256"]:
        return False, "closed_trade hash mismatch"
    if len(accepted) != manifest["accepted_fill_count"]:
        return False, "accepted_fill_count changed"
    if _sha256(json.dumps(accepted, sort_keys=True, default=str)) != manifest["accepted_fill_list_sha256"]:
        return False, "accepted_fill hash mismatch"

    for recorded in manifest.get("evidence_sources", []):
        key = recorded.get("key")
        if not key:
            continue
        fresh = (
            _glob_evidence_summary(redis, key)
            if key in ARCHIVE_GLOB_EVIDENCE_PATTERNS
            else _evidence_summary(redis, key)
        )
        if fresh.get("content_sha256") != recorded.get("content_sha256"):
            return False, f"evidence mismatch: {key}"
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
redis.call('SET', KEYS[12], ARGV[4])  -- v2:paper:session writer source
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
    pointer["content_sha256"] = _canonical_sha256(pointer)
    session_state = {
        "schema_version": "v2_paper_account_epoch_session_v1",
        "account_scope": "PAPER_SIM_ACCOUNT",
        "paper_or_live": "paper",
        "paper_session_id": new_id,
        "reset_session_id": new_id,
        "paper_account_epoch": next_epoch,
        "started_at": started_at,
        "initial_capital": STARTING_EQUITY_USD,
        "starting_equity_usd": STARTING_EQUITY_USD,
        "session_state": "active",
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "historical_evidence_preserved": True,
    }
    session_state["content_sha256"] = _canonical_sha256(session_state)
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
            LEGACY_SESSION_KEY,
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
    pointer.pop("content_sha256", None)
    pointer["content_sha256"] = _canonical_sha256(pointer)
    session_state.update({"paper_session_id": new_id, "reset_session_id": new_id,
                          "paper_account_epoch": epoch})
    session_state.pop("content_sha256", None)
    session_state["content_sha256"] = _canonical_sha256(session_state)
    receipt.update({"new_session_id": new_id, "paper_account_epoch": epoch})
    keys = [
        EPOCH_IDEMPO_PREFIX + idem, GLOBAL_POSITIONS_KEY, GLOBAL_ACCEPTED_FILLS_KEY,
        epoch_key(epoch, "portfolio_state"), epoch_key(epoch, "positions"),
        epoch_key(epoch, "accepted_fills"), epoch_key(epoch, "closed_trades"),
        epoch_key(epoch, "reservations"), PORTFOLIO_STATE_KEY, EPOCH_POINTER_KEY,
        EPOCH_RECEIPT_PREFIX + str(epoch),
        LEGACY_SESSION_KEY,
    ]
    argv = [json.dumps(clean), json.dumps(pointer), json.dumps(receipt), json.dumps(session_state)]
    # Persist the archive manifest once, then verify the exact immutable value
    # before the atomic session-pointer rotation.
    archive_key = EPOCH_ARCHIVE_PREFIX + str(prev.get("paper_session_id"))
    archive_value = json.dumps(manifest, sort_keys=True)
    archive_created = redis.set(archive_key, archive_value, nx=True)
    existing_archive = redis.get(archive_key)
    if isinstance(existing_archive, bytes):
        existing_archive = existing_archive.decode("utf-8")
    if not archive_created and existing_archive != archive_value:
        return {"status": "BLOCKED_ARCHIVE_IMMUTABILITY_CONFLICT",
                "state_mutated": False, "archive_key": archive_key}
    if existing_archive != archive_value:
        return {"status": "BLOCKED_ARCHIVE_READBACK_FAILED",
                "state_mutated": False, "reason": "archive manifest readback mismatch"}
    result_raw = redis.eval(_ROTATION_LUA, len(keys), *keys, *argv)
    result = json.loads(result_raw.decode() if isinstance(result_raw, bytes) else result_raw)
    if isinstance(result, dict) and str(result.get("status", "")).startswith("BLOCKED"):
        return {"status": result["status"], "state_mutated": False, "reason": result.get("reason")}
    return {"status": "ROTATED", "state_mutated": True, "receipt": result,
            "new_session_id": new_id, "paper_account_epoch": epoch,
            "archive_manifest_sha256": manifest["manifest_sha256"]}
