"""V2 alt-data Symbol Universe candidate publisher.

Read-only display + Redis publish surface. Reads ONLY:

- ``v2:altdata:symbol_score:{symbol}`` — per-symbol scores produced
  by the scoring CLI (already Codex-passed).
- ``v2:market:prices:{symbol}`` — Binance tradability hint.
- ``v2:features:latest:{symbol}:{timeframe}`` — feature presence.

NEVER reads ``v2:paper:*`` or ``v2:risk:*``. NEVER calls a provider
endpoint. NEVER places, cancels, or modifies any exchange order.
NEVER changes leverage or margin. NEVER writes legacy Redis. NEVER
mutates ``live_symbols``, ``paper_symbols``, or ``training_symbols``
— those sets belong to the existing Symbol Universe governance lane
and require their own gate.

Allowed Redis writes (enforced by ``safe_redis_set``):
- ``v2:symbol_universe:altdata_candidates``
- ``v2:altdata:candidate_publisher:status``

This module produces structured candidate proposals only. Proposed
uses include ``watchlist_candidate``, ``paper_symbol_candidate``,
``training_symbol_candidate``. ``live_symbol_candidate`` is pinned
to ``False`` everywhere; the publisher never proposes a live order.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WATCHLIST_THRESHOLD = 0.10
DEFAULT_PAPER_THRESHOLD = 0.30
DEFAULT_TRAINING_THRESHOLD = 0.50
DEFAULT_MAX_PROVIDER_AGE_SECONDS = 1_800

CANDIDATE_STATE_READY = "CANDIDATE_READY"
CANDIDATE_STATE_MISSING_PROVIDER_DATA = "MISSING_PROVIDER_DATA"
CANDIDATE_STATE_STALE_PROVIDER_DATA = "STALE_PROVIDER_DATA"
CANDIDATE_STATE_BUDGET_LIMITED = "BUDGET_LIMITED"
CANDIDATE_STATE_BELOW_THRESHOLD = "BELOW_THRESHOLD"
CANDIDATE_STATE_SYMBOL_NOT_TRADABLE = "SYMBOL_NOT_TRADABLE_ON_BINANCE"
CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED = "SYMBOL_UNIVERSE_GATE_REQUIRED"

ALL_CANDIDATE_STATES = (
    CANDIDATE_STATE_READY,
    CANDIDATE_STATE_MISSING_PROVIDER_DATA,
    CANDIDATE_STATE_STALE_PROVIDER_DATA,
    CANDIDATE_STATE_BUDGET_LIMITED,
    CANDIDATE_STATE_BELOW_THRESHOLD,
    CANDIDATE_STATE_SYMBOL_NOT_TRADABLE,
    CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED,
)

PROPOSED_USE_WATCHLIST = "watchlist_candidate"
PROPOSED_USE_PAPER = "paper_symbol_candidate"
PROPOSED_USE_TRAINING = "training_symbol_candidate"

# Allowed Redis writes for this lane.
KEY_ALTDATA_CANDIDATES = "v2:symbol_universe:altdata_candidates"
KEY_PUBLISHER_STATUS = "v2:altdata:candidate_publisher:status"
ALLOWED_REDIS_WRITE_KEYS = (KEY_ALTDATA_CANDIDATES, KEY_PUBLISHER_STATUS)

# Forbidden namespaces — explicitly documented for auditor greps.
FORBIDDEN_READ_NAMESPACES = ("v2:paper:*", "v2:risk:*")


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def safe_redis_set(redis_client: Any, key: str, payload: Any) -> bool:
    """Refuse any key not in the publisher's tight allowlist.

    The publisher never writes a key outside its declared output
    namespace. This is the lowest-level boundary so a logic bug
    cannot leak writes into ``v2:paper:*``, ``v2:risk:*``, or any
    legacy namespace.
    """
    if redis_client is None:
        return False
    if not isinstance(key, str):
        return False
    if key not in ALLOWED_REDIS_WRITE_KEYS:
        return False
    if not key.startswith("v2:"):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tradability + budget classification helpers
# ---------------------------------------------------------------------------


def _is_tradable_on_binance(market_prices_payload: Mapping[str, Any] | None) -> bool:
    """Return True iff ``v2:market:prices:{symbol}`` carries a
    ticker_24hr that looks valid. Absence or malformed payload →
    not tradable."""
    if not isinstance(market_prices_payload, Mapping):
        return False
    ticker = market_prices_payload.get("ticker_24hr")
    if not isinstance(ticker, Mapping):
        return False
    last = ticker.get("lastPrice")
    return bool(last)


def _has_missing_provider_data(symbol_score: Mapping[str, Any]) -> bool:
    if not isinstance(symbol_score, Mapping):
        return True
    if symbol_score.get("altdata_symbol_score") is None:
        return True
    consulted = symbol_score.get("providers_consulted") or []
    if not isinstance(consulted, list) or len(consulted) == 0:
        return True
    missing = symbol_score.get("missing_provider_flags") or []
    if isinstance(missing, list) and missing and not consulted:
        return True
    if bool(symbol_score.get("missing_signal")) and not consulted:
        return True
    return False


def _has_stale_provider_data(symbol_score: Mapping[str, Any]) -> bool:
    if not isinstance(symbol_score, Mapping):
        return False
    stale = symbol_score.get("stale_provider_flags") or []
    if isinstance(stale, list) and stale:
        return True
    if bool(symbol_score.get("stale_signal")):
        return True
    return False


# ---------------------------------------------------------------------------
# Candidate construction
# ---------------------------------------------------------------------------


def classify_candidate_state(
    *,
    symbol_score: Mapping[str, Any] | None,
    market_prices_payload: Mapping[str, Any] | None,
    watchlist_threshold: float = DEFAULT_WATCHLIST_THRESHOLD,
    paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
) -> str:
    """Return exactly one candidate state.

    Priority order (highest first):
    1. SYMBOL_NOT_TRADABLE_ON_BINANCE
    2. MISSING_PROVIDER_DATA  (per-symbol score absent / null)
    3. STALE_PROVIDER_DATA
    4. BELOW_THRESHOLD  (score < watchlist threshold)
    5. SYMBOL_UNIVERSE_GATE_REQUIRED  (score >= paper threshold;
       adoption to paper/training requires the existing governance
       gate)
    6. CANDIDATE_READY  (score >= watchlist threshold but below
       paper threshold; watchlist-only proposal needs no gate)

    ``BUDGET_LIMITED`` remains a valid schema state but is no longer
    produced here: the only providers with budget-limited status
    payloads were removed (operator directive 2026-07-16).
    """
    if not _is_tradable_on_binance(market_prices_payload):
        return CANDIDATE_STATE_SYMBOL_NOT_TRADABLE
    if not isinstance(symbol_score, Mapping) or _has_missing_provider_data(symbol_score):
        return CANDIDATE_STATE_MISSING_PROVIDER_DATA
    if _has_stale_provider_data(symbol_score):
        return CANDIDATE_STATE_STALE_PROVIDER_DATA
    score = symbol_score.get("altdata_symbol_score")
    try:
        score_val = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_val = None
    if score_val is None or score_val < watchlist_threshold:
        return CANDIDATE_STATE_BELOW_THRESHOLD
    if score_val >= paper_threshold:
        return CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED
    return CANDIDATE_STATE_READY


def derive_proposed_uses(
    *,
    candidate_state: str,
    score: float | None,
    watchlist_threshold: float = DEFAULT_WATCHLIST_THRESHOLD,
    paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
    training_threshold: float = DEFAULT_TRAINING_THRESHOLD,
) -> list[str]:
    """List the proposed_use entries for a candidate. Never includes
    a live use; live adoption is out of scope for this publisher."""
    uses: list[str] = []
    if candidate_state in (CANDIDATE_STATE_READY, CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED):
        if score is not None and score >= watchlist_threshold:
            uses.append(PROPOSED_USE_WATCHLIST)
        if score is not None and score >= paper_threshold:
            uses.append(PROPOSED_USE_PAPER)
        if score is not None and score >= training_threshold:
            uses.append(PROPOSED_USE_TRAINING)
    return uses


def build_candidate_reason(
    *,
    candidate_state: str,
    symbol_score: Mapping[str, Any] | None,
) -> str:
    """Operator-readable, deterministic reason string."""
    if candidate_state == CANDIDATE_STATE_SYMBOL_NOT_TRADABLE:
        return "Binance market prices payload absent or has no ticker_24hr.lastPrice."
    if candidate_state == CANDIDATE_STATE_BUDGET_LIMITED:
        return "Provider budget limited."
    if candidate_state == CANDIDATE_STATE_MISSING_PROVIDER_DATA:
        if not isinstance(symbol_score, Mapping):
            return "v2:altdata:symbol_score:{symbol} absent."
        if symbol_score.get("altdata_symbol_score") is None:
            return "altdata_symbol_score is null; no provider signal aggregated."
        missing = symbol_score.get("missing_provider_flags") or []
        if isinstance(missing, list) and missing:
            return f"missing_provider_flags={','.join(sorted(set(missing)))}"
        return "Provider signal coverage insufficient."
    if candidate_state == CANDIDATE_STATE_STALE_PROVIDER_DATA:
        stale = (
            (symbol_score or {}).get("stale_provider_flags") or []
            if isinstance(symbol_score, Mapping)
            else []
        )
        return f"stale_provider_flags={','.join(sorted(set(stale))) or 'unspecified'}"
    if candidate_state == CANDIDATE_STATE_BELOW_THRESHOLD:
        score = (symbol_score or {}).get("altdata_symbol_score")
        return (
            f"altdata_symbol_score={score} below watchlist threshold "
            f"{DEFAULT_WATCHLIST_THRESHOLD}."
        )
    if candidate_state == CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED:
        score = (symbol_score or {}).get("altdata_symbol_score")
        return (
            f"altdata_symbol_score={score} above paper-symbol threshold "
            f"{DEFAULT_PAPER_THRESHOLD}; adoption to paper/training requires "
            "existing Symbol Universe governance gate."
        )
    if candidate_state == CANDIDATE_STATE_READY:
        score = (symbol_score or {}).get("altdata_symbol_score")
        return (
            f"altdata_symbol_score={score} at-or-above watchlist threshold "
            f"{DEFAULT_WATCHLIST_THRESHOLD}; watchlist proposal only."
        )
    return f"Unrecognised candidate state: {candidate_state}."


@dataclasses.dataclass(frozen=True)
class CandidateInputs:
    symbol_score: Mapping[str, Any] | None
    market_prices_payload: Mapping[str, Any] | None
    feature_payload: Mapping[str, Any] | None


def build_candidate(
    symbol: str,
    inputs: CandidateInputs,
    *,
    watchlist_threshold: float = DEFAULT_WATCHLIST_THRESHOLD,
    paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
    training_threshold: float = DEFAULT_TRAINING_THRESHOLD,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    now = generated_utc or utc_iso()
    score = inputs.symbol_score if isinstance(inputs.symbol_score, Mapping) else None
    state = classify_candidate_state(
        symbol_score=score,
        market_prices_payload=inputs.market_prices_payload,
        watchlist_threshold=watchlist_threshold,
        paper_threshold=paper_threshold,
    )
    raw_score = (score or {}).get("altdata_symbol_score") if score else None
    try:
        score_val = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        score_val = None
    proposed_uses = derive_proposed_uses(
        candidate_state=state,
        score=score_val,
        watchlist_threshold=watchlist_threshold,
        paper_threshold=paper_threshold,
        training_threshold=training_threshold,
    )
    reason = build_candidate_reason(
        candidate_state=state,
        symbol_score=score,
    )
    return {
        "schema_version": "v2_alt_data_symbol_candidate_v1",
        "generated_utc": now,
        "symbol": symbol,
        "candidate_state": state,
        "candidate_reason": reason,
        "altdata_symbol_score": score_val,
        "altdata_symbol_rank": (score or {}).get("altdata_symbol_rank") if score else None,
        "provider_availability_score": (
            (score or {}).get("provider_availability_score") if score else None
        ),
        "altdata_freshness_score": (
            (score or {}).get("altdata_freshness_score") if score else None
        ),
        "missing_provider_flags": list(
            (score or {}).get("missing_provider_flags") or [] if score else []
        ),
        "stale_provider_flags": list(
            (score or {}).get("stale_provider_flags") or [] if score else []
        ),
        "providers_consulted": list(
            (score or {}).get("providers_consulted") or [] if score else []
        ),
        "symbol_tradable_on_binance": _is_tradable_on_binance(
            inputs.market_prices_payload
        ),
        "feature_payload_present": isinstance(inputs.feature_payload, Mapping),
        "proposed_use": proposed_uses,
        "watchlist_candidate": PROPOSED_USE_WATCHLIST in proposed_uses,
        "paper_symbol_candidate": PROPOSED_USE_PAPER in proposed_uses,
        "training_symbol_candidate": PROPOSED_USE_TRAINING in proposed_uses,
        "live_symbol_candidate": False,
        # Safety invariants (immutable per candidate).
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "may_not_place_orders": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "raw_credential_in_payload": "NEVER",
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "candidate_only_not_adopted": True,
    }


def build_candidate_list(
    symbols: Iterable[str],
    inputs_by_symbol: Mapping[str, CandidateInputs],
    *,
    watchlist_threshold: float = DEFAULT_WATCHLIST_THRESHOLD,
    paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
    training_threshold: float = DEFAULT_TRAINING_THRESHOLD,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    """Build the full candidate publish payload.

    Candidates are sorted by ``altdata_symbol_score`` descending
    (None scores sort last). Rank is assigned by sort order.
    """
    now = generated_utc or utc_iso()
    normalized_symbols = sorted({s.upper() for s in symbols if isinstance(s, str) and s})
    candidates: list[dict[str, Any]] = []
    for symbol in normalized_symbols:
        inputs = inputs_by_symbol.get(symbol) or CandidateInputs(
            symbol_score=None,
            market_prices_payload=None,
            feature_payload=None,
        )
        candidates.append(
            build_candidate(
                symbol,
                inputs,
                watchlist_threshold=watchlist_threshold,
                paper_threshold=paper_threshold,
                training_threshold=training_threshold,
                generated_utc=now,
            )
        )
    candidates.sort(
        key=lambda c: (
            c["altdata_symbol_score"] is None,
            -(c["altdata_symbol_score"] or 0.0),
            c["symbol"],
        )
    )
    for idx, c in enumerate(candidates, start=1):
        c["candidate_publisher_rank"] = idx
    by_state: dict[str, int] = {state: 0 for state in ALL_CANDIDATE_STATES}
    for c in candidates:
        by_state[c["candidate_state"]] = by_state.get(c["candidate_state"], 0) + 1
    return {
        "schema_version": "v2_alt_data_symbol_candidate_publisher_payload_v1",
        "generated_utc": now,
        "go_no_go": "V2_ALT_DATA_SYMBOL_UNIVERSE_CANDIDATE_PUBLISHER_READY",
        "watchlist_threshold": watchlist_threshold,
        "paper_threshold": paper_threshold,
        "training_threshold": training_threshold,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "candidate_states_legend": {
            CANDIDATE_STATE_READY: "score within watchlist band; watchlist-only proposal.",
            CANDIDATE_STATE_MISSING_PROVIDER_DATA: "altdata_symbol_score null or required providers absent.",
            CANDIDATE_STATE_STALE_PROVIDER_DATA: "provider payload older than freshness window.",
            CANDIDATE_STATE_BUDGET_LIMITED: "Provider daily budget / rate limit hit (retained schema state; no current provider produces it).",
            CANDIDATE_STATE_BELOW_THRESHOLD: "score < watchlist threshold.",
            CANDIDATE_STATE_SYMBOL_NOT_TRADABLE: "no v2:market:prices:{symbol} ticker_24hr.lastPrice.",
            CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED: "score above paper/training threshold; adoption requires existing Symbol Universe governance gate.",
        },
        "candidate_state_counts": by_state,
        "allowed_inputs": [
            "v2:altdata:symbol_score:{symbol}",
            "v2:market:prices:{symbol}",
            "v2:features:latest:{symbol}:{timeframe}",
        ],
        "forbidden_input_namespaces": list(FORBIDDEN_READ_NAMESPACES),
        "allowed_writes": list(ALLOWED_REDIS_WRITE_KEYS),
        # Safety invariants on the publisher itself.
        "candidate_only_not_adopted": True,
        "paper_symbols_expanded": False,
        "training_symbols_expanded": False,
        "live_symbols_expanded": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "raw_credential_in_payload": "NEVER",
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "writes_legacy_redis": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "real_order_attempted": False,
        "real_order_submitted": False,
        "places_real_order": False,
        "provider_network_calls_attempted": False,
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "may_not_place_orders": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
    }
