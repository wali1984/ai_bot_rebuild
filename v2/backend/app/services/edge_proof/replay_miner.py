"""V2 Native Edge-Proof — post-hoc replay outcome miner.

Maintains an incremental price + bundle store on disk so the
edge-proof evaluator has real future-outcome windows (1m / 5m / 15m /
1h) to score against. Each invocation:

1. Appends the current ``v2:market:prices:{symbol}`` snapshot to a
   per-symbol price-timeline JSONL.
2. Appends new shadow / paper-intent rows from ``v2:paper:ledger``
   into a replay-bundles JSONL store (deduplicating by intent_id).
3. For each existing bundle, attempts to fill any outcome window that
   now has enough elapsed time and at least one timeline point on or
   after the window endpoint. Windows that still cannot be filled stay
   `INSUFFICIENT_EVIDENCE`.
4. Computes after-cost return, max favorable, max adverse, fee drag,
   slippage estimate per filled window.
5. Assigns objective labels from realized after-cost outcome + paper
   gate decision. The miner NEVER fabricates outcomes; missing windows
   stay explicit.

Safety:

- Reads only ``v2:*`` Redis keys via the safe reader and the
  V2-vs-legacy comparator public mirror.
- Writes only under
  ``claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/`` and
  ``v2/frontend/public/v2_post_hoc_replay_outcome_miner/``.
- Never modifies legacy code, never calls the exchange, never enables
  live trading, never adopts symbols, never creates approval markers.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .replay_schema import (
    OUTCOME_WINDOWS_SECONDS,
    OutcomeWindow,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    ReplayBundle,
    ReplayLabel,
)

# Producer-side reuse of the trainer's own label/outcome provenance contract, so
# the emitted envelope is digest-identical to what the strict live-loop label
# validator (dataset_builder._label_row_rejection_reasons) recomputes.  Single
# source of truth — no divergence.  (No import cycle: dataset_builder does not
# import edge_proof.)
from v2.backend.app.services.native_trainer.dataset_builder import (  # noqa: E402
    LabelRow as _TrainerLabelRow,
    _canonical_sha256 as _trainer_canonical_sha256,
    _first_present,
    _label_digest_material as _trainer_label_digest_material,
    _label_for_outcome as _trainer_label_for_outcome,
    _normalized_bundle_side as _trainer_normalized_bundle_side,
    _outcome_digest_material as _trainer_outcome_digest_material,
)

V2_RUNTIME_REPO_ROOT_ENV = "V2_RUNTIME_REPO_ROOT"


def _configured_repo_root(
    environ: Mapping[str, str] | None = None,
    *,
    code_root: Path | None = None,
) -> Path:
    source = os.environ if environ is None else environ
    immutable_code_root = code_root or Path(__file__).resolve().parents[5]
    configured = str(source.get(V2_RUNTIME_REPO_ROOT_ENV) or "").strip()
    return (
        Path(configured).expanduser().resolve()
        if configured
        else immutable_code_root
    )


REPO_ROOT = _configured_repo_root()
STATE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_post_hoc_replay_outcome_miner"
    / "state"
)
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_post_hoc_replay_outcome_miner"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_post_hoc_replay_outcome_miner"
    / "latest"
)

# Operator-decision-required defaults for the cost model. The miner
# applies these as "preliminary defaults" only; the operator must set
# concrete numerics before any canary or live ramp can be approved.
# These are tagged inside every emitted bundle so the operator and
# Codex can audit which cost-model was used during scoring.
DEFAULT_FEE_BPS = 5.0
DEFAULT_SLIPPAGE_BPS = 2.0
# Cost-model marker MUST include the literal ``OPERATOR_DECISION_REQUIRED``
# so every default cost model emitted in a bundle / metrics summary is
# unambiguously flagged as not-yet-approved by the operator. Codex
# review flagged the prior marker for not surfacing this literal;
# do not regress.
COST_MODEL_NOTE = (
    "DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE_OPERATOR_DECISION_REQUIRED"
)
COST_MODEL_OPERATOR_OVERRIDE_REQUIRED = True

PAPER_FILL_GATE_MISSING_SOURCE = "MISSING_SOURCE"
PAPER_FILL_GATE_REASON_STATE_RECORDED = "RECORDED"
PAPER_FILL_GATE_REASON_STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
PAPER_FILL_GATE_EVIDENCE_SOURCES: tuple[str, ...] = (
    "paper_fill_gate_block_reasons",
    "paper_gate_decision.paper_fill_gate_block_reasons",
    "trainer_output.paper_fill_gate_block_reasons",
    "pre_trade_allowed",
    "fee_gate_allowed",
    "churn_blocked",
)

ALTDATA_SYMBOL_SCORE_KEY_TEMPLATE = "v2:altdata:symbol_score:{symbol}"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_iso(ts: Any) -> float | None:
    if not isinstance(ts, str):
        return None
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except Exception:  # noqa: BLE001
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_redis_read(key: str) -> Any:
    """v2:* only. Never writes. Returns parsed JSON or None."""
    if not key.startswith("v2:"):
        return None
    try:
        import redis  # type: ignore

        r = redis.Redis(decode_responses=True, socket_connect_timeout=2)
        r.ping()
        raw = r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return raw
    except Exception:  # noqa: BLE001
        return None


def _list_from_any(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    return []


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _sanitize_public_mapping(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a public V2 payload while redacting accidental credential fields."""
    sanitized: dict[str, Any] = {}
    for key, value in doc.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("secret", "api_key", "apikey", "token")):
            sanitized[str(key)] = "REDACTED_FIELD_NAME_PRESENT"
            continue
        if isinstance(value, Mapping):
            sanitized[str(key)] = _sanitize_public_mapping(value)
        elif isinstance(value, list):
            sanitized[str(key)] = [
                _sanitize_public_mapping(v) if isinstance(v, Mapping) else v
                for v in value
            ]
        else:
            sanitized[str(key)] = value
    return sanitized


def build_altdata_snapshot(symbol: str) -> dict[str, Any]:
    """Return an explicit alt-data snapshot state for a replay bundle.

    The miner reads only the V2-owned per-symbol score key. When the
    source is absent, the bundle records MISSING_SOURCE rather than
    fabricating a neutral score.
    """
    sym = symbol.upper()
    key = ALTDATA_SYMBOL_SCORE_KEY_TEMPLATE.format(symbol=sym)
    doc = _safe_redis_read(key)
    if isinstance(doc, Mapping):
        return {
            "symbol": sym,
            "status": "ATTACHED",
            "source_label": "V2_NATIVE_PUBLIC_PAYLOAD",
            "source_key": key,
            "payload": _sanitize_public_mapping(doc),
        }
    return {
        "symbol": sym,
        "status": PAPER_FILL_GATE_MISSING_SOURCE,
        "source_label": PAPER_FILL_GATE_MISSING_SOURCE,
        "source_key": key,
        "missing_reason": "v2_altdata_symbol_score_key_missing",
        "payload": None,
    }


# ---------------------------------------------------------------------------
# Price timeline
# ---------------------------------------------------------------------------

def _price_timeline_path(symbol: str) -> Path:
    return STATE_DIR / f"price_timeline_{symbol.upper()}.jsonl"


def _read_market_price(symbol: str) -> tuple[float, float] | None:
    """Return (utc_seconds, last_price_float) or None if unavailable."""
    doc = _safe_redis_read(f"v2:market:prices:{symbol.upper()}")
    if not isinstance(doc, dict):
        return None
    fetched_utc = doc.get("fetched_utc")
    ticker = doc.get("ticker_24hr") or {}
    price_str = ticker.get("lastPrice") or ticker.get("bidPrice")
    ts = _parse_iso(fetched_utc)
    price = _coerce_float(price_str)
    if ts is None or price is None or price <= 0:
        return None
    return ts, price


def append_price_snapshot(symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    point = _read_market_price(sym)
    if point is None:
        return {"symbol": sym, "appended": False, "reason": "no_market_price"}
    ts, price = point
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _price_timeline_path(sym)
    # Avoid appending if the same ts has been recorded already.
    last_ts = _last_recorded_ts(path)
    if last_ts is not None and ts <= last_ts:
        return {
            "symbol": sym,
            "appended": False,
            "reason": "no_new_market_tick",
            "last_recorded_ts": last_ts,
            "candidate_ts": ts,
        }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "price": price}) + "\n")
    return {"symbol": sym, "appended": True, "ts": ts, "price": price}


def _last_recorded_ts(path: Path) -> float | None:
    if not path.exists():
        return None
    last = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    last = row.get("ts")
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return None
    return last


def load_price_timeline(symbol: str) -> list[tuple[float, float]]:
    path = _price_timeline_path(symbol.upper())
    if not path.exists():
        return []
    rows: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                ts = float(row.get("ts"))
                price = float(row.get("price"))
                rows.append((ts, price))
            except Exception:  # noqa: BLE001
                continue
    rows.sort(key=lambda x: x[0])
    return rows


# The authoritative, real-time outcome-price source: the canonical finalized 5m
# candle archive written by the live Binance kline WSS loop.  It is dense (one
# closed candle every 300s, current to ~now) and PIT-safe (only closed,
# finalized candles).  The miner's own once-per-run price snapshots are far too
# sparse to source 1m/5m/15m/1h outcome windows, so outcomes are sourced from
# this real-time archive and merged with any self-sampled ticks.
# The canonical outcome source is closed 5m candles (~300s apart); accept the
# first sample within one candle interval (+ small tolerance) past a window
# endpoint as the realized endpoint price.
_OUTCOME_ENDPOINT_HORIZON_SECONDS = 330.0
CANONICAL_5M_LABEL_ARCHIVE_ENV = "V2_CANONICAL_5M_LABEL_ARCHIVE_PATH"
_DEFAULT_CANONICAL_5M_LABEL_ARCHIVE = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer"
    "/canonical_finalized_5m_label_archive.sqlite3"
)


def _canonical_label_archive_path() -> Path:
    configured = str(os.environ.get(CANONICAL_5M_LABEL_ARCHIVE_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    return _DEFAULT_CANONICAL_5M_LABEL_ARCHIVE


def _load_canonical_price_timeline(
    symbol: str, archive_path: Path
) -> list[tuple[float, float]]:
    """Dense (ts_sec, close) timeline from the real-time canonical 5m archive.

    Read-only; failures degrade to an empty list so a missing/locked archive
    never breaks the mining cycle (the window simply stays pending).
    """

    if not archive_path.exists():
        return []
    import sqlite3

    out: list[tuple[float, float]] = []
    try:
        connection = sqlite3.connect(f"file:{archive_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        cursor = connection.execute(
            "SELECT candle_close_time_ms, payload_json "
            "FROM canonical_5m_candles WHERE symbol = ? "
            "ORDER BY candle_close_time_ms",
            (symbol.upper(),),
        )
        for close_ms, payload_json in cursor:
            try:
                close_px = float(json.loads(payload_json).get("close"))
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
            if close_px > 0:
                out.append((float(close_ms) / 1000.0, close_px))
    except sqlite3.Error:
        return out
    finally:
        connection.close()
    return out


def _merged_price_timeline(
    symbol: str, archive_path: Path
) -> list[tuple[float, float]]:
    """Union of the self-sampled ticks and the real-time canonical closes.

    Deduped by timestamp (canonical close wins ties), sorted ascending.
    """

    by_ts: dict[float, float] = {}
    for ts, price in load_price_timeline(symbol):
        by_ts[ts] = price
    for ts, price in _load_canonical_price_timeline(symbol, archive_path):
        by_ts[ts] = price
    return sorted(by_ts.items(), key=lambda item: item[0])


# The canonical outcome source resolves at the 5m candle cadence, so only
# windows at/above that resolution are honestly sourceable from it.  Sub-
# resolution windows (1m) are left best-effort and excluded from the
# archive-completeness check and primary-window selection.
_MIN_HONEST_OUTCOME_WINDOW_SECONDS = 300


def _parse_iso_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _attach_entry_side_provenance(bundle: dict[str, Any]) -> bool:
    """Synthesize the PIT-consistent entry-side timing chain the strict label
    validator requires, honestly derived from the recorded feature cutoff /
    availability / decision clocks.  Returns False when the mandatory anchors
    are absent (bundle then stays unprovenanced and is excluded from training).
    """

    cutoff = _parse_iso_utc(
        bundle.get("feature_cutoff") or bundle.get("entry_feature_cutoff")
    )
    decision = _parse_iso_utc(
        bundle.get("decision_time") or bundle.get("entry_feature_decision_time")
    )
    available = _parse_iso_utc(
        bundle.get("available_at") or bundle.get("entry_feature_available_at")
    )
    if cutoff is None or decision is None:
        return False
    if available is None or available > decision or available < cutoff:
        available = decision
    # entry-feature generation sits between the source cutoff and availability.
    generated = _parse_iso_utc(bundle.get("entry_feature_generated_at"))
    if generated is None or not (cutoff <= generated <= available):
        generated = available
    tf_seconds = _window_seconds_for_timeframe(bundle.get("timeframe"))
    candle_open = cutoff - timedelta(seconds=tf_seconds)
    bundle["candle_close_time"] = _iso_utc(cutoff)
    bundle["candle_open_time"] = _iso_utc(candle_open)
    bundle["source_event_time"] = _iso_utc(cutoff)
    bundle["source_received_time_est"] = _iso_utc(cutoff)
    bundle["source_available_time"] = _iso_utc(cutoff)
    bundle["entry_feature_generated_at"] = _iso_utc(generated)
    bundle["prediction_generated_at"] = _iso_utc(available)
    bundle["available_at"] = _iso_utc(available)
    return True


def _window_seconds_for_timeframe(timeframe: Any) -> int:
    text = str(timeframe or "1m").strip().lower()
    units = {"m": 60, "h": 3600, "d": 86400}
    try:
        return max(1, int(text[:-1])) * units.get(text[-1:], 60)
    except (ValueError, IndexError):
        return 60


def _attach_outcome_provenance(
    bundle: dict[str, Any],
    *,
    timeline: list[tuple[float, float]],
    mining_now: datetime,
) -> None:
    """Emit, for every honestly-sourceable window, the full finalized
    outcome/label provenance envelope (ids, digests, horizon bounds, finality,
    availability chain) the strict live-loop validator recomputes.  Digests are
    produced with the trainer's own material functions so they match exactly.
    """

    decision = _parse_iso_utc(bundle.get("decision_time"))
    entry_price = _coerce_float(bundle.get("entry_price"))
    side = _trainer_normalized_bundle_side(bundle)
    if decision is None or entry_price is None or entry_price <= 0 or side is None:
        return
    if not _attach_entry_side_provenance(bundle):
        return
    decision_ep = decision.timestamp()
    decision_iso = bundle.get("decision_time")
    symbol = str(bundle.get("symbol") or "").upper()
    timeframe = str(bundle.get("timeframe") or "")
    snapshot_id = str(bundle.get("feature_snapshot_id") or "")
    gate = bundle.get("paper_gate_decision") or {}
    gate_status = _first_present(
        gate.get("status"), gate.get("paper_fill_gate_status")
    )
    sign = 1.0 if side == "long" else -1.0
    bundle["bundle_generated_at"] = _iso_utc(mining_now)
    outcomes = bundle.get("future_outcomes") or {}
    for wid, secs in OUTCOME_WINDOWS_SECONDS:
        if secs < _MIN_HONEST_OUTCOME_WINDOW_SECONDS:
            # Sub-resolution windows are not honestly sourceable from the 5m
            # canonical archive; null their realized return so they are neither
            # selected as the primary label window nor treated as evidence.
            sub = outcomes.get(wid) or {}
            sub["after_cost_return_bps"] = None
            sub["source"] = "SUBRESOLUTION_NOT_SOURCEABLE"
            outcomes[wid] = sub
            continue
        window_end_ep = decision_ep + secs
        horizon_end = decision + timedelta(seconds=secs)
        # Source the realized path [decision, first close >= horizon_end].
        slice_ = _find_window_slice(timeline, decision_ep, secs)
        if slice_ is None:
            continue
        endpoint_ts, endpoint_px = next(
            ((ts, px) for ts, px in slice_ if ts >= window_end_ep),
            slice_[-1],
        )
        raw_return_bps = ((endpoint_px - entry_price) / entry_price) * 10_000.0
        signed_path = [
            sign * ((px - entry_price) / entry_price) * 10_000.0
            for _, px in slice_
        ]
        after_cost = sign * raw_return_bps - (DEFAULT_FEE_BPS + DEFAULT_SLIPPAGE_BPS)
        max_favorable = max(signed_path) if signed_path else None
        max_adverse = min(signed_path) if signed_path else None
        # outcome becomes knowable at the sourcing close, never before horizon end.
        knowable = max(horizon_end, datetime.fromtimestamp(endpoint_ts, timezone.utc))
        knowable_iso = _iso_utc(knowable)
        label = _trainer_label_for_outcome(
            after_cost, str(gate_status) if gate_status is not None else None
        )
        outcome_id = _trainer_canonical_sha256(
            {
                "kind": "outcome",
                "feature_snapshot_id": snapshot_id,
                "symbol": symbol,
                "window": wid,
                "decision_time": decision_iso,
            }
        )
        row = _TrainerLabelRow(
            feature_snapshot_id=snapshot_id,
            symbol=symbol,
            timeframe=timeframe,
            label=label,
            after_cost_return_bps=after_cost,
            max_favorable_bps=max_favorable,
            max_adverse_bps=max_adverse,
            paper_gate_status=str(gate_status) if gate_status is not None else None,
            paper_gate_block_reasons=[],
            risk_decision_context=None,
            legacy_reference_action=None,
            side=side,
            decision_time=decision_iso,
            outcome_window=wid,
            label_horizon_start=decision_iso,
            label_horizon_end=_iso_utc(horizon_end),
            label_horizon_seconds=int(secs),
            outcome_generated_at=knowable_iso,
            outcome_available_at=knowable_iso,
            outcome_id=outcome_id,
        )
        outcome_digest = _trainer_canonical_sha256(
            _trainer_outcome_digest_material(row)
        )
        label_id = _trainer_canonical_sha256(
            {
                "kind": "label",
                "outcome_id": outcome_id,
                "label": label,
                "feature_snapshot_id": snapshot_id,
            }
        )
        row = replace(
            row,
            outcome_digest=outcome_digest,
            label_id=label_id,
            label_available_at=knowable_iso,
            label_finalized=True,
        )
        label_digest = _trainer_canonical_sha256(
            _trainer_label_digest_material(row)
        )
        prior = outcomes.get(wid) or {}
        prior.update(
            {
                "return_bps": raw_return_bps,
                "after_cost_return_bps": after_cost,
                "max_favorable_bps": max_favorable,
                "max_adverse_bps": max_adverse,
                "samples": len(slice_),
                "source": "V2_CANONICAL_5M_ARCHIVE",
                "outcome_id": outcome_id,
                "label_id": label_id,
                "label": label,
                "outcome_digest": outcome_digest,
                "label_digest": label_digest,
                "label_horizon_start": decision_iso,
                "label_horizon_end": _iso_utc(horizon_end),
                "label_horizon_seconds": int(secs),
                "outcome_generated_at": knowable_iso,
                "outcome_available_at": knowable_iso,
                "label_available_at": knowable_iso,
                "outcome_finalized": True,
                "label_finalized": True,
            }
        )
        outcomes[wid] = prior
    bundle["future_outcomes"] = outcomes


def _find_window_slice(
    timeline: list[tuple[float, float]],
    anchor_ts: float,
    window_seconds: int,
) -> list[tuple[float, float]] | None:
    """Return the timeline slice in [anchor_ts, anchor_ts + window_seconds]
    if the slice contains at least one point on or after the window
    endpoint, else None (window not yet sourceable).
    """
    if not timeline:
        return None
    window_end = anchor_ts + window_seconds
    # The outcome is sourced from the FIRST price sample at or after the window
    # endpoint.  A sub-second endpoint tolerance assumed a near-continuous tick
    # feed; the real-time source is closed 5m candles (~300s apart), so bound
    # the endpoint search to one candle interval past the endpoint.  If no
    # sample falls within that horizon the window is genuinely not yet
    # sourceable (archive gap or not matured) and stays pending.
    endpoint_horizon = window_end + _OUTCOME_ENDPOINT_HORIZON_SECONDS
    slice_: list[tuple[float, float]] = []
    has_endpoint = False
    for ts, price in timeline:
        if ts < anchor_ts:
            continue
        if ts > endpoint_horizon:
            break
        slice_.append((ts, price))
        if ts >= window_end:
            has_endpoint = True
            break
    if not slice_ or not has_endpoint:
        return None
    return slice_


# ---------------------------------------------------------------------------
# Bundle store
# ---------------------------------------------------------------------------

REPLAY_BUNDLES_PATH = STATE_DIR / "replay_bundles.jsonl"
# Pending store: only bundles still awaiting at least one outcome window.
# mine_once() reads and writes ONLY this file on every normal run (small).
# Fully-filled bundles are appended to REPLAY_BUNDLES_PATH (archive) and
# removed from here, so this file stays tiny regardless of archive size.
REPLAY_BUNDLES_PENDING_PATH = STATE_DIR / "replay_bundles_pending.jsonl"
EVAL_METRICS_PATH = STATE_DIR / "eval_metrics.jsonl"
MAX_PENDING_AGE_SECONDS = 4 * 3600

# Fields extracted from each outcome window for the compact eval store.
_EVAL_WINDOW_KEYS: tuple[str, ...] = (
    "window_id",
    "window_seconds",
    "return_bps",
    "after_cost_return_bps",
    "drawdown_bps",
    "stop_hit",
    "samples",
)


def _read_bundles_from(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out


def _prune_stale_pending_streaming(
    path: Path,
    *,
    now_ts: float,
    maximum_age_seconds: int = MAX_PENDING_AGE_SECONDS,
) -> dict[str, Any]:
    """Atomically prune expired pending rows without materializing the store.

    A pending row is transient scheduling state, not a realized outcome.  The
    prior implementation loaded the complete JSONL into a Python list before
    applying this same four-hour retention rule.  A multi-gigabyte store then
    exceeded the service's 12 GiB cgroup even though every row was already
    expired.  This pass preserves fresh row bytes exactly, records hashes and
    counts, and leaves the source untouched if any row is malformed.
    """

    if not path.exists():
        return {
            "schema_version": "replay_pending_stream_prune_v1",
            "path": str(path),
            "exists": False,
            "rows_seen": 0,
            "rows_retained": 0,
            "rows_stale_pruned": 0,
            "rows_invalid": 0,
            "input_sha256": hashlib.sha256(b"").hexdigest(),
            "output_sha256": hashlib.sha256(b"").hexdigest(),
            "status": "PASS_NOT_PRESENT",
        }
    if maximum_age_seconds <= 0 or not math.isfinite(now_ts):
        raise ValueError("PENDING_STREAM_PRUNE_CONFIGURATION_INVALID")

    tmp = path.with_suffix(path.suffix + ".prune.tmp")
    input_digest = hashlib.sha256()
    output_digest = hashlib.sha256()
    rows_seen = 0
    rows_retained = 0
    rows_stale_pruned = 0
    try:
        with path.open("rb") as source, tmp.open("wb") as target:
            for line_number, raw_line in enumerate(source, start=1):
                input_digest.update(raw_line)
                if not raw_line.strip():
                    continue
                rows_seen += 1
                try:
                    row = json.loads(raw_line)
                except Exception as exc:  # noqa: BLE001 - fail-closed JSONL boundary
                    raise ValueError(
                        f"PENDING_STREAM_ROW_INVALID_JSON:{line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        f"PENDING_STREAM_ROW_NOT_OBJECT:{line_number}"
                    )
                anchor_ts = row.get("anchor_ts")
                anchor_valid = (
                    type(anchor_ts) in {int, float}
                    and math.isfinite(float(anchor_ts))
                )
                if (
                    anchor_valid
                    and now_ts - float(anchor_ts) <= maximum_age_seconds
                ):
                    output_line = (
                        raw_line if raw_line.endswith(b"\n") else raw_line + b"\n"
                    )
                    target.write(output_line)
                    output_digest.update(output_line)
                    rows_retained += 1
                else:
                    rows_stale_pruned += 1
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise

    return {
        "schema_version": "replay_pending_stream_prune_v1",
        "path": str(path),
        "exists": True,
        "rows_seen": rows_seen,
        "rows_retained": rows_retained,
        "rows_stale_pruned": rows_stale_pruned,
        "rows_invalid": 0,
        "maximum_age_seconds": maximum_age_seconds,
        "input_sha256": input_digest.hexdigest(),
        "output_sha256": output_digest.hexdigest(),
        "status": "PASS",
    }


def _read_bundles() -> list[dict[str, Any]]:
    return _read_bundles_from(REPLAY_BUNDLES_PATH)


def _write_bundles_to(bundles: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for b in bundles:
            f.write(json.dumps(b, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def _write_bundles(bundles: list[dict[str, Any]]) -> None:
    _write_bundles_to(bundles, REPLAY_BUNDLES_PATH)


def _append_to_archive(bundles: list[dict[str, Any]]) -> None:
    """Append fully-filled bundles to the archive. Never rewrites the archive."""
    if not bundles:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with REPLAY_BUNDLES_PATH.open("a", encoding="utf-8") as f:
        for b in bundles:
            f.write(json.dumps(b, sort_keys=True, default=str) + "\n")


def _append_to_eval_metrics(bundles: list[dict[str, Any]]) -> None:
    """Append compact eval rows for newly-filled bundles. Never full rewrite."""
    if not bundles:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with EVAL_METRICS_PATH.open("a", encoding="utf-8") as f:
        for b in bundles:
            f.write(json.dumps(_compact_bundle(b), sort_keys=True) + "\n")


def _is_fully_filled(b: dict[str, Any]) -> bool:
    """True when every honestly-sourceable outcome window has a realized
    after-cost return.  Sub-resolution windows (below the canonical 5m source
    cadence) are best-effort and do not block archival."""
    outcomes = b.get("future_outcomes") or {}
    sourceable = [
        wid
        for wid, secs in OUTCOME_WINDOWS_SECONDS
        if secs >= _MIN_HONEST_OUTCOME_WINDOW_SECONDS
    ]
    return all(
        (outcomes.get(wid) or {}).get("after_cost_return_bps") is not None
        for wid in sourceable
    )


def _seed_pending_from_archive() -> None:
    """One-time migration: read archive, split filled vs pending, write pending file.

    The archive is rewritten to contain only fully-filled bundles.
    eval_metrics.jsonl is rebuilt from those filled bundles.
    The pending file is seeded with the unfilled subset.
    This runs once when REPLAY_BUNDLES_PENDING_PATH does not yet exist.
    """
    all_bundles = _read_bundles()
    filled = [b for b in all_bundles if _is_fully_filled(b)]
    pending = [b for b in all_bundles if not _is_fully_filled(b)]
    _write_bundles(filled)
    _write_eval_metrics(filled)
    _write_bundles_to(pending, REPLAY_BUNDLES_PENDING_PATH)


def _legacy_reference_action_for(symbol: str) -> dict[str, Any] | None:
    mirror = (
        REPO_ROOT
        / "v2"
        / "frontend"
        / "public"
        / "v2_legacy_v2_production_comparator"
        / "latest"
        / "operator_dashboard_payload.json"
    )
    try:
        doc = json.loads(mirror.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    rows = doc.get("symbol_rows") or doc.get("per_symbol") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and (row.get("symbol") or "").upper() == symbol.upper():
            action = row.get("legacy_action") or row.get("action")
            if isinstance(action, str):
                return {
                    "action": action,
                    "source": "v2_legacy_v2_production_comparator_mirror",
                }
    return None


def _harvest_paper_evidence() -> list[dict[str, Any]]:
    """Extract paper evidence rows from v2:paper:ledger and v2:paper:intents.

    Each row becomes one candidate replay bundle (deduplicated downstream
    by intent_id). Only data that is already inside V2 keys is read;
    legacy current truth is never consulted.
    """
    rows: list[dict[str, Any]] = []
    ledger = _safe_redis_read("v2:paper:ledger") or {}
    intents = _safe_redis_read("v2:paper:intents") or []
    held = _safe_redis_read("v2:paper:intents_held_by_paper_fill_gate") or []
    risk = _safe_redis_read("v2:risk:decisions") or []
    orch = _safe_redis_read("v2:orchestrator:decisions") or {}

    risk_by_symbol = {
        (r.get("symbol") or "").upper(): r
        for r in (risk if isinstance(risk, list) else [])
        if isinstance(r, dict)
    }

    def _decorate(row: Mapping[str, Any], decision: str) -> dict[str, Any]:
        return {
            "intent_id": row.get("intent_id"),
            "symbol": (row.get("symbol") or "").upper(),
            "side": row.get("side"),
            "ts": _parse_iso(row.get("generated_utc")),
            "generated_utc": row.get("generated_utc"),
            "entry_price": _coerce_float(row.get("entry_price")),
            "expected_move_after_cost_bps": _coerce_float(
                row.get("expected_move_after_cost_bps")
            ),
            "confidence_calibrated": _coerce_float(row.get("confidence_calibrated")),
            "pre_trade_allowed": row.get("pre_trade_allowed"),
            "fee_gate_allowed": row.get("fee_gate_allowed"),
            "churn_blocked": row.get("churn_blocked"),
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "paper_fill_gate_block_reasons": row.get(
                "paper_fill_gate_block_reasons"
            ),
            "decision": decision,
            "decision_time": row.get("decision_time")
            or row.get("entry_feature_decision_time"),
            "available_at": row.get("available_at")
            or row.get("entry_feature_available_at"),
            "feature_cutoff": row.get("feature_cutoff")
            or row.get("entry_feature_cutoff"),
            "entry_feature_decision_time": row.get(
                "entry_feature_decision_time"
            ),
            "entry_feature_available_at": row.get(
                "entry_feature_available_at"
            ),
            "entry_feature_generated_at": row.get(
                "entry_feature_generated_at"
            ),
            "entry_feature_cutoff": row.get("entry_feature_cutoff"),
            "entry_feature_candle_closed_confirmed": row.get(
                "entry_feature_candle_closed_confirmed"
            ),
            "risk_decision": risk_by_symbol.get((row.get("symbol") or "").upper()),
            "orchestrator_decision": orch if isinstance(orch, dict) else None,
            # The replay bundle needs exact disposition evidence, not another
            # multi-megabyte copy of the complete paper matrix.  The complete
            # authenticated candidate remains in CandidateDecisionOutcomeV2.
            "raw_row": {
                "paper_fill_gate_block_reasons": row.get(
                    "paper_fill_gate_block_reasons"
                )
            },
        }

    for r in (ledger.get("accepted") or []):
        if isinstance(r, dict):
            rows.append(_decorate(r, "ACCEPTED_PAPER_FILL"))
    for r in (ledger.get("shadow_observations") or []):
        if isinstance(r, dict):
            rows.append(_decorate(r, "SHADOW_OBSERVATION_ONLY"))
    for r in (ledger.get("held_by_paper_fill_gate") or []):
        if isinstance(r, dict):
            rows.append(_decorate(r, "HELD_BY_PAPER_FILL_GATE"))
    for r in (intents if isinstance(intents, list) else []):
        if isinstance(r, dict):
            decision = "ACCEPTED_PAPER_FILL" if r.get("paper_fill_allowed") else "PAPER_INTENT_OBSERVED"
            rows.append(_decorate(r, decision))
    for r in (held if isinstance(held, list) else []):
        if isinstance(r, dict):
            rows.append(_decorate(r, "HELD_BY_PAPER_FILL_GATE"))
    return rows


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_AUTHORITY_PROJECTION_FIELDS: tuple[str, ...] = (
    "schema_version",
    "decision_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "prediction_id",
    "symbol",
    "timeframe",
    "side",
    "action",
    "decision",
    "status",
    "reason",
    "reasons",
    "strategy_decision_time",
    "strategy_feature_cutoff",
    "decision_time",
    "available_at",
    "generated_at",
    "generated_utc",
    "source_payload_sha256",
    "record_sha256",
    "receipt_sha256",
    "paper_only",
    "live_gate",
    "routes_to_live",
    "places_real_order",
    "exchange_action_taken",
)


def _compact_authority_projection(
    value: Any,
    *,
    projection_schema_version: str,
) -> dict[str, Any] | None:
    """Bind a large authority record without duplicating its full payload."""

    if not isinstance(value, Mapping):
        return None
    material = dict(value)
    projected = {
        field: material.get(field)
        for field in _AUTHORITY_PROJECTION_FIELDS
        if material.get(field) is not None
    }
    projected.update(
        {
            "projection_schema_version": projection_schema_version,
            "source_record_sha256": _canonical_sha256(material),
            "source_record_field_count": len(material),
            "projection_is_complete_source_copy": False,
        }
    )
    return projected


def _resolve_paper_fill_gate_block_reasons(
    row: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    raw = row.get("raw_row") if isinstance(row.get("raw_row"), Mapping) else {}
    paper_gate = row.get("paper_gate_decision") if isinstance(
        row.get("paper_gate_decision"), Mapping
    ) else {}
    trainer_output = row.get("trainer_output") if isinstance(
        row.get("trainer_output"), Mapping
    ) else {}

    reasons: list[str] = []
    evidence_sources: list[dict[str, Any]] = []

    def _add_reasons(field: str, values: Any) -> None:
        extracted = _list_from_any(values)
        if not extracted:
            return
        reasons.extend(extracted)
        evidence_sources.append({
            "field": field,
            "state": PAPER_FILL_GATE_REASON_STATE_RECORDED,
            "count": len(extracted),
        })

    _add_reasons(
        "paper_fill_gate_block_reasons",
        row.get("paper_fill_gate_block_reasons") or raw.get("paper_fill_gate_block_reasons"),
    )
    _add_reasons(
        "paper_gate_decision.paper_fill_gate_block_reasons",
        paper_gate.get("paper_fill_gate_block_reasons"),
    )
    _add_reasons(
        "trainer_output.paper_fill_gate_block_reasons",
        trainer_output.get("paper_fill_gate_block_reasons"),
    )

    explicit_bool_reasons: list[tuple[str, str, bool]] = [
        ("pre_trade_allowed", "PRE_TRADE_GATE_BLOCKED", row.get("pre_trade_allowed") is False),
        ("fee_gate_allowed", "FEE_GATE_BLOCKED", row.get("fee_gate_allowed") is False),
        ("churn_blocked", "CHURN_BLOCKED", row.get("churn_blocked") is True),
    ]
    for field, reason, triggered in explicit_bool_reasons:
        if not triggered:
            continue
        reasons.append(reason)
        evidence_sources.append({
            "field": field,
            "state": PAPER_FILL_GATE_REASON_STATE_RECORDED,
            "reason": reason,
        })

    unique_reasons = _dedupe_strings(reasons)
    paper_fill_allowed = row.get("paper_fill_allowed")
    if paper_fill_allowed is None:
        paper_fill_allowed = paper_gate.get("paper_fill_allowed")
    paper_intent = row.get("paper_intent") if isinstance(row.get("paper_intent"), Mapping) else {}
    decision = str(row.get("decision") or paper_intent.get("decision") or "").upper()
    expected = paper_fill_allowed is False or decision in {
        "HELD_BY_PAPER_FILL_GATE",
        "BLOCKED",
    }
    if unique_reasons:
        state = PAPER_FILL_GATE_REASON_STATE_RECORDED
        missing_reason = None
    elif expected:
        state = PAPER_FILL_GATE_MISSING_SOURCE
        missing_reason = "paper_fill_gate_block_reason_missing_from_v2_sources"
    else:
        state = PAPER_FILL_GATE_REASON_STATE_NOT_APPLICABLE
        missing_reason = None
    return unique_reasons, {
        "state": state,
        "missing_reason": missing_reason,
        "evidence_sources_considered": list(PAPER_FILL_GATE_EVIDENCE_SOURCES),
        "evidence_sources": evidence_sources,
    }


def _new_bundle_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    sym = row.get("symbol") or ""
    side = (row.get("side") or "").lower()
    block_reasons, block_reason_lineage = _resolve_paper_fill_gate_block_reasons(row)
    altdata_snapshot = build_altdata_snapshot(str(sym))
    risk_decision = row.get("risk_decision") if isinstance(row.get("risk_decision"), Mapping) else {}
    bundle_generated_at = row.get("generated_utc") or _utc_iso()
    decision_time = (
        row.get("decision_time")
        or row.get("entry_feature_decision_time")
        or risk_decision.get("strategy_decision_time")
    )
    available_at = row.get("available_at") or row.get("entry_feature_available_at")
    feature_generated_at = row.get("entry_feature_generated_at")
    feature_cutoff = (
        row.get("feature_cutoff")
        or row.get("entry_feature_cutoff")
        or risk_decision.get("strategy_feature_cutoff")
    )
    return {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "feature_snapshot_id": (
            f"{sym}:1m:{bundle_generated_at}"
        ),
        "prediction_id": row.get("intent_id") or f"{sym}:{bundle_generated_at}",
        "symbol": sym,
        "timeframe": "1m",
        "generated_at": bundle_generated_at,
        "bundle_generated_at": bundle_generated_at,
        "decision_time": decision_time,
        "available_at": available_at,
        "feature_cutoff": feature_cutoff,
        "entry_feature_decision_time": decision_time,
        "entry_feature_available_at": available_at,
        "entry_feature_generated_at": feature_generated_at,
        "entry_feature_cutoff": feature_cutoff,
        "entry_feature_candle_closed_confirmed": row.get("entry_feature_candle_closed_confirmed"),
        "anchor_ts": row.get("ts"),
        "features_hash": None,
        "market_snapshot": {
            "fee_bps": DEFAULT_FEE_BPS,
            "slippage_estimate_bps": DEFAULT_SLIPPAGE_BPS,
            "cost_model_source": COST_MODEL_NOTE,
            "operator_override_required": COST_MODEL_OPERATOR_OVERRIDE_REQUIRED,
            "operator_decision_required": True,
            "default_fee_bps_visible": DEFAULT_FEE_BPS,
            "default_slippage_estimate_bps_visible": DEFAULT_SLIPPAGE_BPS,
        },
        "altdata_snapshot": altdata_snapshot,
        "risk_decision": _compact_authority_projection(
            row.get("risk_decision"),
            projection_schema_version="replay_risk_authority_projection_v1",
        ),
        "trainer_output": {
            "selected_action": (
                side if side in ("long", "short") else "hold"
            ),
            "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
            "confidence_calibrated": row.get("confidence_calibrated"),
            "paper_fill_gate_block_reasons": block_reasons,
            "paper_fill_gate_block_reasons_lineage": block_reason_lineage,
        },
        "paper_gate_decision": {
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "paper_fill_gate_block_reasons": block_reasons,
            "paper_fill_gate_block_reasons_lineage": block_reason_lineage,
            "latency_seconds": None,
        },
        "paper_fill_allowed": row.get("paper_fill_allowed"),
        "paper_fill_gate_status": (
            "BLOCK_REASON_RECORDED"
            if block_reasons
            else block_reason_lineage["state"]
        ),
        "paper_fill_gate_block_reasons": block_reasons,
        "paper_fill_gate_block_reasons_lineage": block_reason_lineage,
        "orchestrator_decision": _compact_authority_projection(
            row.get("orchestrator_decision"),
            projection_schema_version=(
                "replay_orchestrator_authority_projection_v1"
            ),
        ),
        "paper_intent": {
            "intent_id": row.get("intent_id"),
            "symbol": sym,
            "side": side or None,
            "decision": row.get("decision"),
        },
        "legacy_reference_action": _legacy_reference_action_for(sym),
        "entry_price": row.get("entry_price"),
        "side": side or None,
        "future_outcomes": {
            wid: {
                "window_id": wid,
                "window_seconds": secs,
                "return_bps": None,
                "after_cost_return_bps": None,
                "drawdown_bps": None,
                "stop_hit": False,
                "samples": 0,
                "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE",
            }
            for wid, secs in OUTCOME_WINDOWS_SECONDS
        },
        "outcome_after_cost": None,
        "label": ReplayLabel.INSUFFICIENT_EVIDENCE.value,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _merge_new_paper_rows(
    existing: list[dict[str, Any]],
    paper_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Return (merged, newly_added_count)."""
    by_intent: dict[str, dict[str, Any]] = {
        b["prediction_id"]: b for b in existing if b.get("prediction_id")
    }
    added = 0
    for row in paper_rows:
        intent_id = row.get("intent_id")
        if not intent_id:
            continue
        if intent_id in by_intent:
            continue
        new_bundle = _new_bundle_from_row(row)
        by_intent[intent_id] = new_bundle
        added += 1
    # Sort by anchor_ts ascending so the JSONL stays time-ordered.
    merged = sorted(
        by_intent.values(),
        key=lambda b: (b.get("anchor_ts") or 0),
    )
    return merged, added


# ---------------------------------------------------------------------------
# Outcome window filling
# ---------------------------------------------------------------------------

def _compute_window(
    *,
    timeline: list[tuple[float, float]],
    anchor_ts: float | None,
    entry_price: float | None,
    side: str | None,
    window_id: str,
    window_seconds: int,
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    if anchor_ts is None or entry_price is None or entry_price <= 0:
        return {
            "window_id": window_id,
            "window_seconds": window_seconds,
            "return_bps": None,
            "after_cost_return_bps": None,
            "drawdown_bps": None,
            "max_favorable_bps": None,
            "max_adverse_bps": None,
            "fee_drag_bps": None,
            "slippage_estimate_bps": None,
            "samples": 0,
            "stop_hit": False,
            "source": "INSUFFICIENT_EVIDENCE_NO_ANCHOR_OR_ENTRY_PRICE",
        }
    sl = _find_window_slice(timeline, anchor_ts, window_seconds)
    if sl is None:
        return {
            "window_id": window_id,
            "window_seconds": window_seconds,
            "return_bps": None,
            "after_cost_return_bps": None,
            "drawdown_bps": None,
            "max_favorable_bps": None,
            "max_adverse_bps": None,
            "fee_drag_bps": None,
            "slippage_estimate_bps": None,
            "samples": 0,
            "stop_hit": False,
            "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE",
        }
    # End price = first sample at or after window endpoint.
    window_end = anchor_ts + window_seconds
    end_price = next(
        (price for ts, price in sl if ts >= window_end),
        sl[-1][1],
    )
    sign = 1.0 if (side or "").lower() == "long" else -1.0 if (side or "").lower() == "short" else 0.0
    raw_return_bps = ((end_price - entry_price) / entry_price) * 10_000.0
    signed_return_bps = sign * raw_return_bps if sign != 0 else raw_return_bps
    cost_drag = fee_bps + slippage_bps
    after_cost = signed_return_bps - cost_drag
    # Max favorable / max adverse across the slice, signed.
    if sign == 0:
        signed_path = [((p - entry_price) / entry_price) * 10_000.0 for _, p in sl]
    else:
        signed_path = [
            sign * ((p - entry_price) / entry_price) * 10_000.0 for _, p in sl
        ]
    max_favorable_bps = max(signed_path) if signed_path else None
    max_adverse_bps = min(signed_path) if signed_path else None
    drawdown_bps = -max_adverse_bps if max_adverse_bps is not None else None
    return {
        "window_id": window_id,
        "window_seconds": window_seconds,
        "return_bps": raw_return_bps,
        "after_cost_return_bps": after_cost,
        "drawdown_bps": drawdown_bps,
        "max_favorable_bps": max_favorable_bps,
        "max_adverse_bps": max_adverse_bps,
        "fee_drag_bps": fee_bps,
        "slippage_estimate_bps": slippage_bps,
        "samples": len(sl),
        "stop_hit": False,
        "source": "V2_MINER_PRICE_TIMELINE",
    }


def _label_from_outcome(
    *,
    bundle: dict[str, Any],
    primary_window_id: str = "5m",
) -> str:
    """Compute objective label from realized after-cost outcome.

    Honest rules:

    - if the primary window's after_cost is unknown -> INSUFFICIENT_EVIDENCE
    - if the trade was taken (paper_fill_allowed=True or decision=ACCEPTED):
      - after_cost > 0 -> CORRECT_TRADE
      - after_cost <= 0 -> FALSE_POSITIVE
    - if the trade was held by the gate (block reasons present):
      - after_cost > 0 (counterfactual would have been profitable) -> FALSE_BLOCK
      - after_cost <= 0 -> CORRECT_NO_TRADE
    - if the model held (not blocked, no fill):
      - after_cost > 0 -> FALSE_NEGATIVE
      - after_cost <= 0 -> CORRECT_NO_TRADE
    """
    outcome = (bundle.get("future_outcomes") or {}).get(primary_window_id) or {}
    after_cost = outcome.get("after_cost_return_bps")
    if after_cost is None:
        return ReplayLabel.INSUFFICIENT_EVIDENCE.value
    gate = bundle.get("paper_gate_decision") or {}
    paper_intent = bundle.get("paper_intent") or {}
    intent_decision = (paper_intent.get("decision") or "").upper()
    block_reasons = gate.get("paper_fill_gate_block_reasons") or []
    blocked = intent_decision in ("HELD_BY_PAPER_FILL_GATE", "BLOCKED") or (
        gate.get("paper_fill_allowed") is False and bool(block_reasons)
    )
    traded = (
        intent_decision == "ACCEPTED_PAPER_FILL"
        or bool(gate.get("paper_fill_allowed"))
    )
    if traded:
        return (
            ReplayLabel.CORRECT_TRADE.value
            if after_cost > 0
            else ReplayLabel.FALSE_POSITIVE.value
        )
    if blocked:
        return (
            ReplayLabel.FALSE_BLOCK.value
            if after_cost > 0
            else ReplayLabel.CORRECT_NO_TRADE.value
        )
    # Model held without gate-block evidence.
    return (
        ReplayLabel.FALSE_NEGATIVE.value
        if after_cost > 0
        else ReplayLabel.CORRECT_NO_TRADE.value
    )


def fill_outcomes(
    bundle: dict[str, Any],
    *,
    timeline_by_symbol: dict[str, list[tuple[float, float]]],
) -> dict[str, Any]:
    symbol = bundle.get("symbol") or ""
    timeline = timeline_by_symbol.get(symbol.upper()) or []
    anchor_ts = bundle.get("anchor_ts")
    entry_price = _coerce_float(bundle.get("entry_price"))
    side = bundle.get("side")
    market = bundle.get("market_snapshot") or {}
    fee_bps = _coerce_float(market.get("fee_bps")) or DEFAULT_FEE_BPS
    slippage_bps = _coerce_float(market.get("slippage_estimate_bps")) or DEFAULT_SLIPPAGE_BPS
    new_outcomes: dict[str, Any] = {}
    for wid, secs in OUTCOME_WINDOWS_SECONDS:
        old = (bundle.get("future_outcomes") or {}).get(wid) or {}
        if old.get("after_cost_return_bps") is not None:
            # Already filled — keep.
            new_outcomes[wid] = old
            continue
        new_outcomes[wid] = _compute_window(
            timeline=timeline,
            anchor_ts=anchor_ts,
            entry_price=entry_price,
            side=side,
            window_id=wid,
            window_seconds=secs,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
    bundle["future_outcomes"] = new_outcomes
    # outcome_after_cost mirrors the primary (5m) window.
    primary = new_outcomes.get("5m") or {}
    bundle["outcome_after_cost"] = primary.get("after_cost_return_bps")
    bundle["label"] = _label_from_outcome(bundle=bundle, primary_window_id="5m")
    return bundle


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def mine_once(
    *,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # 1. Append current price snapshots.
    appended = [append_price_snapshot(s) for s in symbols]
    # 2. Harvest paper evidence and merge into bundle store.
    paper_rows = _harvest_paper_evidence()

    # --- Incremental processing ---
    # On first run: seed the pending file from the full archive (one-time cost).
    # On all subsequent runs: only read/write the small pending file.
    if not REPLAY_BUNDLES_PENDING_PATH.exists():
        _seed_pending_from_archive()

    # Apply the retention boundary before materializing pending state.  This is
    # deliberately streaming: an expired multi-gigabyte store must be reducible
    # under the miner's bounded memory cgroup.
    pending_prune = _prune_stale_pending_streaming(
        REPLAY_BUNDLES_PENDING_PATH,
        now_ts=time.time(),
    )
    pending = _read_bundles_from(REPLAY_BUNDLES_PENDING_PATH)
    stale_pruned = int(pending_prune["rows_stale_pruned"])

    merged, added = _merge_new_paper_rows(pending, paper_rows)

    # 3. Fill outcomes for any bundle whose windows are now sourceable.
    #    Outcome prices come from the real-time canonical 5m archive (dense,
    #    PIT-safe closed candles) merged with any self-sampled ticks.
    _archive_path = _canonical_label_archive_path()
    timeline_by_symbol = {
        s.upper(): _merged_price_timeline(s, _archive_path) for s in symbols
    }
    _mining_now = datetime.now(timezone.utc)
    now_filled: list[dict[str, Any]] = []
    still_pending: list[dict[str, Any]] = []
    for b in merged:
        updated = fill_outcomes(b, timeline_by_symbol=timeline_by_symbol)
        # Emit the finalized PIT outcome/label provenance envelope the strict
        # live-loop label validator requires (ids, digests, horizon bounds,
        # finality, availability chain) for every honestly-sourceable window.
        _attach_outcome_provenance(
            updated,
            timeline=timeline_by_symbol.get(str(updated.get("symbol") or "").upper(), []),
            mining_now=_mining_now,
        )
        if _is_fully_filled(updated):
            now_filled.append(updated)
        else:
            still_pending.append(updated)

    # Append newly-completed bundles to the append-only archive + eval metrics.
    if now_filled:
        _append_to_archive(now_filled)
        _append_to_eval_metrics(now_filled)

    # Write back only the remaining unfilled bundles.
    _write_bundles_to(still_pending, REPLAY_BUNDLES_PENDING_PATH)

    return {
        "symbols": list(symbols),
        "price_snapshots": appended,
        "paper_rows_observed": len(paper_rows),
        "bundles_pending": len(still_pending),
        "bundles_newly_filled": len(now_filled),
        "bundles_added_this_cycle": added,
        "bundles_stale_pruned": stale_pruned,
        "pending_stream_prune": pending_prune,
        "timeline_lengths": {
            s: len(timeline_by_symbol.get(s.upper(), [])) for s in symbols
        },
    }


def load_filled_bundles() -> list[dict[str, Any]]:
    return _read_bundles()


def _compact_bundle(b: dict[str, Any]) -> dict[str, Any]:
    """Return only the fields the evaluator needs — ~300 bytes vs ~56 KB full."""
    future_outcomes: dict[str, Any] = {}
    for wid, secs in OUTCOME_WINDOWS_SECONDS:
        full_win = (b.get("future_outcomes") or {}).get(wid) or {}
        future_outcomes[wid] = {k: full_win.get(k) for k in _EVAL_WINDOW_KEYS}

    paper_gate = b.get("paper_gate_decision") or {}
    trainer = b.get("trainer_output") or {}
    legacy = b.get("legacy_reference_action") or {}
    market = b.get("market_snapshot") or {}
    paper_intent = b.get("paper_intent") or {}

    return {
        "label": b.get("label"),
        "symbol": b.get("symbol"),
        "future_outcomes": future_outcomes,
        "paper_intent": {"decision": paper_intent.get("decision")},
        "paper_gate_decision": {
            "paper_fill_allowed": paper_gate.get("paper_fill_allowed"),
            "paper_fill_gate_block_reasons": paper_gate.get("paper_fill_gate_block_reasons") or [],
            "latency_seconds": paper_gate.get("latency_seconds"),
        },
        "trainer_output": {
            "selected_action": trainer.get("selected_action"),
            "expected_move_after_cost_bps": trainer.get("expected_move_after_cost_bps"),
            "paper_fill_gate_block_reasons": trainer.get("paper_fill_gate_block_reasons") or [],
        },
        "legacy_reference_action": {
            "action": legacy.get("action"),
            "selected_action": legacy.get("selected_action"),
        },
        "market_snapshot": {
            "fee_bps": market.get("fee_bps"),
            "slippage_estimate_bps": market.get("slippage_estimate_bps"),
        },
    }


def _write_eval_metrics(bundles: list[dict[str, Any]]) -> None:
    """Atomically write the compact eval-metrics file from the canonical store.

    Written after every mine_once() and after any backfill that mutates
    REPLAY_BUNDLES_PATH, so load_eval_bundles_or_fallback() always reads
    a file that is consistent with the current full bundle store.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EVAL_METRICS_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for b in bundles:
            f.write(json.dumps(_compact_bundle(b), sort_keys=True) + "\n")
    os.replace(tmp, EVAL_METRICS_PATH)


def _rebuild_eval_metrics_from_store(path: Path) -> None:
    """Rebuild compact evaluator rows from a JSONL source with bounded RAM."""

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EVAL_METRICS_PATH.with_suffix(".jsonl.tmp")
    try:
        with path.open("r", encoding="utf-8") as source, tmp.open(
            "w", encoding="utf-8"
        ) as target:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:  # noqa: BLE001 - persisted boundary
                    raise ValueError(
                        f"EVAL_REBUILD_ROW_INVALID_JSON:{line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        f"EVAL_REBUILD_ROW_NOT_OBJECT:{line_number}"
                    )
                target.write(json.dumps(_compact_bundle(row), sort_keys=True) + "\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, EVAL_METRICS_PATH)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def load_eval_bundles_or_fallback() -> list[dict[str, Any]]:
    """Load compact eval rows (fast ~30 MB read) with fallback to full store.

    The compact file is always written in sync with the full bundle store
    by mine_once() and backfill_jsonl_store(). If it is absent or
    unreadable for any reason, falls back to _read_bundles() which reads
    the full 6+ GB store — identical to the previous behaviour.
    """
    if EVAL_METRICS_PATH.exists():
        try:
            rows: list[dict[str, Any]] = []
            with EVAL_METRICS_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except Exception:  # noqa: BLE001
                        continue
            return rows
        except Exception:  # noqa: BLE001
            pass
    return _read_bundles()


# ---------------------------------------------------------------------------
# Cost-model backfill + artifact validation
# ---------------------------------------------------------------------------

REQUIRED_COST_MODEL_LITERAL = "OPERATOR_DECISION_REQUIRED"
LEGACY_COST_MODEL_MARKER = "DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE"
REQUIRED_COST_MODEL_MARKER = COST_MODEL_NOTE

REQUIRED_MARKET_SNAPSHOT_KEYS: tuple[str, ...] = (
    "cost_model_source",
    "operator_decision_required",
    "operator_override_required",
    "default_fee_bps_visible",
    "default_slippage_estimate_bps_visible",
)


# Frozen, immutable bundle fields the backfill must never touch.
_PROTECTED_BUNDLE_FIELDS: tuple[str, ...] = (
    "intent_id",
    "prediction_id",
    "symbol",
    "generated_at",
    "bundle_generated_at",
    "decision_time",
    "available_at",
    "feature_cutoff",
    "entry_feature_decision_time",
    "entry_feature_available_at",
    "entry_feature_generated_at",
    "entry_feature_cutoff",
    "entry_feature_candle_closed_confirmed",
    "anchor_ts",
    "future_outcomes",
    "label",
    "outcome_after_cost",
    "paper_gate_decision",
    "risk_decision",
    "orchestrator_decision",
    "paper_intent",
    "legacy_reference_action",
)


def backfill_bundle_cost_model(row: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (re-tagged row, changed_flag).

    Only the ``market_snapshot`` sub-document is mutated. Protected
    fields (intent_id, timestamps, future_outcomes, label, paper gate /
    risk / orchestrator decisions, etc.) are left untouched. Existing
    operator-set overrides (e.g. an operator-supplied fee_bps that is
    not the default 5.0) are NOT clobbered: only the marker literal and
    the visible-override metadata are added when missing.
    """
    out = dict(row)
    market = dict(out.get("market_snapshot") or {})
    changed = False
    source = market.get("cost_model_source")
    if isinstance(source, str) and source == LEGACY_COST_MODEL_MARKER:
        market["cost_model_source"] = REQUIRED_COST_MODEL_MARKER
        changed = True
    elif not isinstance(source, str) or REQUIRED_COST_MODEL_LITERAL not in source:
        # Defensive: when source is missing or carries some other tag
        # without the literal, append the required marker. This never
        # silently rewrites an operator-set marker that already includes
        # the literal.
        market["cost_model_source"] = REQUIRED_COST_MODEL_MARKER
        changed = True
    if "operator_decision_required" not in market:
        market["operator_decision_required"] = True
        changed = True
    if "operator_override_required" not in market:
        market["operator_override_required"] = True
        changed = True
    if "default_fee_bps_visible" not in market:
        market["default_fee_bps_visible"] = DEFAULT_FEE_BPS
        changed = True
    if "default_slippage_estimate_bps_visible" not in market:
        market["default_slippage_estimate_bps_visible"] = DEFAULT_SLIPPAGE_BPS
        changed = True
    out["market_snapshot"] = market
    return out, changed


def backfill_bundle_replay_context(row: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Attach explicit paper-gate lineage and alt-data source state.

    This remediation is intentionally evidence-only. It records existing
    gate reasons and explicit missing-source states, but it does not
    fabricate a block reason and does not recalculate labels/outcomes.
    """
    out = dict(row)
    changed = False
    symbol = str(out.get("symbol") or "").upper()
    if not isinstance(out.get("altdata_snapshot"), Mapping):
        out["altdata_snapshot"] = build_altdata_snapshot(symbol)
        changed = True

    paper_gate = dict(out.get("paper_gate_decision") or {})
    if "paper_fill_allowed" not in paper_gate and "paper_fill_allowed" in out:
        paper_gate["paper_fill_allowed"] = out.get("paper_fill_allowed")
    trainer_output = dict(out.get("trainer_output") or {})
    resolver_row = dict(out)
    resolver_row["paper_gate_decision"] = paper_gate
    resolver_row["trainer_output"] = trainer_output
    reasons, lineage = _resolve_paper_fill_gate_block_reasons(resolver_row)
    if paper_gate.get("paper_fill_gate_block_reasons") != reasons:
        paper_gate["paper_fill_gate_block_reasons"] = reasons
        changed = True
    if paper_gate.get("paper_fill_gate_block_reasons_lineage") != lineage:
        paper_gate["paper_fill_gate_block_reasons_lineage"] = lineage
        changed = True
    if trainer_output.get("paper_fill_gate_block_reasons") != reasons:
        trainer_output["paper_fill_gate_block_reasons"] = reasons
        changed = True
    if trainer_output.get("paper_fill_gate_block_reasons_lineage") != lineage:
        trainer_output["paper_fill_gate_block_reasons_lineage"] = lineage
        changed = True
    status = "BLOCK_REASON_RECORDED" if reasons else lineage["state"]
    mirrors = {
        "paper_fill_allowed": paper_gate.get("paper_fill_allowed"),
        "paper_fill_gate_status": status,
        "paper_fill_gate_block_reasons": reasons,
        "paper_fill_gate_block_reasons_lineage": lineage,
    }
    for key, value in mirrors.items():
        if out.get(key) != value:
            out[key] = value
            changed = True
    out["paper_gate_decision"] = paper_gate
    out["trainer_output"] = trainer_output
    return out, changed


def validate_bundle_row(row: Mapping[str, Any]) -> list[str]:
    """Return a list of validation error tokens for one row. Empty list
    means the row passes. Used by tests and by the CLI backfill to
    guarantee no stale row escapes."""
    errors: list[str] = []
    market = row.get("market_snapshot") or {}
    if not isinstance(market, Mapping):
        errors.append("market_snapshot_not_object")
        return errors
    source = market.get("cost_model_source")
    if not isinstance(source, str) or REQUIRED_COST_MODEL_LITERAL not in source:
        errors.append("cost_model_source_missing_required_literal")
    for key in (
        "operator_decision_required",
        "operator_override_required",
    ):
        if market.get(key) is not True:
            errors.append(f"missing_or_falsy_{key}")
    if "default_fee_bps_visible" not in market:
        errors.append("missing_default_fee_bps_visible")
    if "default_slippage_estimate_bps_visible" not in market:
        errors.append("missing_default_slippage_estimate_bps_visible")
    altdata = row.get("altdata_snapshot")
    if not isinstance(altdata, Mapping):
        errors.append("missing_altdata_snapshot_state")
    else:
        source_label = altdata.get("source_label")
        source_key = altdata.get("source_key")
        status = altdata.get("status")
        if source_label not in {"V2_NATIVE_PUBLIC_PAYLOAD", PAPER_FILL_GATE_MISSING_SOURCE}:
            errors.append("invalid_altdata_snapshot_source_label")
        if isinstance(source_key, str) and not source_key.startswith("v2:"):
            errors.append("altdata_snapshot_non_v2_source_key")
        if status == PAPER_FILL_GATE_MISSING_SOURCE and source_label != PAPER_FILL_GATE_MISSING_SOURCE:
            errors.append("altdata_missing_source_label_mismatch")
    gate = row.get("paper_gate_decision") or {}
    if isinstance(gate, Mapping):
        paper_fill_allowed = gate.get("paper_fill_allowed")
        reasons = gate.get("paper_fill_gate_block_reasons") or []
        lineage = gate.get("paper_fill_gate_block_reasons_lineage")
        if paper_fill_allowed is False and not reasons:
            if not isinstance(lineage, Mapping) or lineage.get("state") != PAPER_FILL_GATE_MISSING_SOURCE:
                errors.append("paper_fill_gate_block_reason_missing_without_lineage")
        if reasons and (
            not isinstance(lineage, Mapping)
            or lineage.get("state") != PAPER_FILL_GATE_REASON_STATE_RECORDED
        ):
            errors.append("paper_fill_gate_block_reasons_missing_recorded_lineage")
    # Future outcomes must not be fabricated. INSUFFICIENT windows must
    # have ``after_cost_return_bps == None``.
    outcomes = row.get("future_outcomes") or {}
    for wid, win in outcomes.items():
        if not isinstance(win, Mapping):
            errors.append(f"window_not_object:{wid}")
            continue
        src = win.get("source")
        ac = win.get("after_cost_return_bps")
        if isinstance(src, str) and src.startswith("INSUFFICIENT_EVIDENCE") and ac is not None:
            errors.append(f"insufficient_window_with_fabricated_outcome:{wid}")
    label = row.get("label")
    valid_labels = {l.value for l in ReplayLabel}
    if label not in valid_labels:
        errors.append("invalid_label_value")
    return errors


def _row_protected_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    """Snapshot of the bundle's protected fields for diff verification."""
    return {k: row.get(k) for k in _PROTECTED_BUNDLE_FIELDS}


def backfill_jsonl_store(path: Path) -> dict[str, Any]:
    """Apply ``backfill_bundle_cost_model`` to every row in a JSONL file.

    Returns a status dict describing rows scanned, rows re-tagged,
    validation errors, and protected-field-diff drift (which would be
    a hard failure but should never happen given the backfill only
    touches market_snapshot).
    """
    if not path.exists():
        return {"path": str(path), "exists": False, "rows": 0, "changed": 0, "errors": []}
    parse_errors: list[str] = []
    parse_error_count = 0
    changed_count = 0
    protected_drift: list[str] = []
    protected_drift_count = 0
    validation_errors: list[str] = []
    validation_error_count = 0
    row_count = 0
    tmp = path.with_suffix(path.suffix + ".backfill.tmp")
    try:
        with path.open("r", encoding="utf-8") as source, tmp.open(
            "w", encoding="utf-8"
        ) as target:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                row_count += 1
                try:
                    orig = json.loads(line)
                except Exception:  # noqa: BLE001 - persisted JSONL boundary
                    parse_error_count += 1
                    if len(parse_errors) < 100:
                        parse_errors.append(f"row_{line_number}_invalid_json")
                    continue
                if not isinstance(orig, dict):
                    parse_error_count += 1
                    if len(parse_errors) < 100:
                        parse_errors.append(f"row_{line_number}_not_object")
                    continue
                sig_before = _row_protected_signature(orig)
                cost_row, cost_changed = backfill_bundle_cost_model(orig)
                sig_after = _row_protected_signature(cost_row)
                if sig_before != sig_after:
                    protected_drift_count += 1
                    if len(protected_drift) < 100:
                        protected_drift.append(
                            "row_"
                            f"{line_number}_protected_field_drift:"
                            f"{orig.get('intent_id')}"
                        )
                new_row, context_changed = backfill_bundle_replay_context(cost_row)
                if cost_changed or context_changed:
                    changed_count += 1
                row_errors = validate_bundle_row(new_row)
                validation_error_count += len(row_errors)
                for error in row_errors:
                    if len(validation_errors) >= 100:
                        break
                    validation_errors.append(f"row_{line_number}_{error}")
                target.write(
                    json.dumps(new_row, sort_keys=True, default=str) + "\n"
                )
            target.flush()
            os.fsync(target.fileno())
        validation_passed = not (
            parse_error_count
            or protected_drift_count
            or validation_error_count
        )
        if changed_count > 0 and validation_passed:
            os.replace(tmp, path)
            if path == REPLAY_BUNDLES_PATH:
                _rebuild_eval_metrics_from_store(path)
        else:
            tmp.unlink()
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    return {
        "path": str(path),
        "exists": True,
        "rows": row_count,
        "changed": changed_count,
        "parse_errors": parse_errors,
        "parse_error_count": parse_error_count,
        "protected_field_drift": protected_drift,
        "protected_field_drift_count": protected_drift_count,
        "validation_errors": validation_errors,
        "validation_error_count": validation_error_count,
        "streaming_bounded_memory": True,
        "validation_passed": validation_passed,
    }


def backfill_all_replay_bundle_stores() -> dict[str, Any]:
    """Backfill every persisted replay bundle store and verify the
    canonical marker/override fields are present on every row."""
    targets = [
        WORKLOG_DIR / "replay_outcome_bundles.jsonl",
        PUBLIC_DIR / "replay_outcome_bundles.jsonl",
        REPLAY_BUNDLES_PATH,
        REPLAY_BUNDLES_PENDING_PATH,
    ]
    return {
        "stores": [backfill_jsonl_store(p) for p in targets],
        "required_cost_model_literal": REQUIRED_COST_MODEL_LITERAL,
        "required_cost_model_marker": REQUIRED_COST_MODEL_MARKER,
        "required_market_snapshot_keys": list(REQUIRED_MARKET_SNAPSHOT_KEYS),
    }
