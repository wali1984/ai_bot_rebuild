"""V2 signal lineage worker — standalone CLI worker.

Subscribes to the seven per-stage records emitted by the V2 paper
runtime bundle
(market data -> feature snapshot -> model output -> trainer prediction
-> orchestrator decision -> risk gateway decision -> paper execution
result) and emits a unified ``signal_lineage`` record. Each stage
carries an explainability block whose claims are backed by evidence
citations pointing at concrete source fields. When evidence is missing
the worker writes ``EVIDENCE_MISSING_LABEL`` instead of fabricating a
claim.

Hard rules (asserted by tests):
  - Fail-closed if any stage record is missing or staler than the
    configured stale threshold.
  - Explainability citation invariant: every emitted explanation either
    cites every required evidence field or is replaced with
    ``EVIDENCE_MISSING_LABEL``.
  - signal_publisher.py contains no scaffold remnant.
  - Live gate is permanently ``blocked_human_only``.
  - No exchange-mutation method names, no Binance/ccxt/Redis imports.
  - Symbol Universe contract: scope is read via the V2 Symbol Universe
    service; the 25-symbol legacy active subset is surfaced as
    ``legacy_active_symbols`` and is not the universe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from v2.backend.app.services.signal_publisher import (
    EVIDENCE_MISSING_LABEL,
    SIGNAL_SERVICE_ID,
    build_signal_record,
    cite_evidence,
    evidence_present,
    explain_or_missing,
    required_signal_record_fields,
    signal_publisher_self_check,
)
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


WORKER_ID = "v2_signal_lineage_worker"
SOURCE_RUNTIME_ID = "paper_online"
LIVE_GATE_STATUS = "blocked_human_only"
EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_SIGNAL_LINEAGE_WORKER"
SYMBOL_UNIVERSE_CONTRACT = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
SYMBOL_UNIVERSE_SERVICE_PATH = "v2/backend/app/services/symbol_universe/service.py"

STAGE_ORDER: Tuple[str, ...] = (
    "market_data",
    "feature_snapshot",
    "model_output",
    "trainer_prediction",
    "orchestrator_decision",
    "risk_gateway_decision",
    "paper_execution_result",
)

DEFAULT_WARN_THRESHOLD_SECONDS = 120
DEFAULT_STALE_THRESHOLD_SECONDS = 600

SIGNAL_PUBLISHER_REL_PATH = "v2/backend/app/services/signal_publisher.py"
SIGNAL_PUBLISHER_REMNANT_PATTERNS: Tuple[str, ...] = (
    "placeholder",
    "todo",
    "fixme",
    "scaffold",
    "no behavior",
    "not implemented",
    "stub",
)

LEGACY_SOURCE_PATHS: List[str] = [
    "legacy_reference/rl/orchestrator_worker.py",
    "legacy_reference/rl/hybrid_trainer.py",
    "legacy_reference/rl/signal_state_manager.py",
    "legacy_reference/trading/signal_router.py",
    "legacy_reference/monitor_trainer_signals.py",
    "legacy_reference/scripts/trace_symbol_e2e.py",
    "legacy_reference/scripts/signal_accuracy_v2.py",
    "legacy_reference/scripts/signal_accuracy_48h.py",
    "legacy_reference/scripts/why_hedged_timeline.py",
]

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = (
    V2_ROOT / "frontend" / "public" / "operator_runtime" / WORKER_ID / "latest"
)
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / WORKER_ID / "latest"
WORKER_STATUS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)

PUBLIC_STATUS_FILE = PUBLIC_RUNTIME_DIR / f"{WORKER_ID}_status.json"
LOCAL_STATUS_FILE = LOCAL_RUNTIME_DIR / f"{WORKER_ID}_status.json"
WORKER_STATUS_FILE = WORKER_STATUS_DIR / f"{WORKER_ID}_status.json"

BUNDLE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / SOURCE_RUNTIME_ID
    / "latest"
    / "paper_runtime_status.json",
    V2_ROOT / "runtime" / SOURCE_RUNTIME_ID / "latest" / "paper_runtime_status.json",
]
SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES: List[Path] = [
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
    V2_ROOT
    / "frontend"
    / "public"
    / "symbol_universe"
    / "latest"
    / "symbol_universe_status.json",
]

SIGNAL_PUBLISHER_ABS_PATH = REPO_ROOT / SIGNAL_PUBLISHER_REL_PATH

REQUIRED_PUBLIC_PAYLOAD_FIELDS: Tuple[str, ...] = (
    "worker_id",
    "last_run_ts",
    "live_gate",
    "current_gate_state",
    "current_gate_state_must_equal_blocked_human_only",
    "gate_always_blocked_invariant",
    "exchange_call_invariant",
    "exchange_action_taken",
    "fail_closed",
    "fail_closed_reason",
    "missing_runtime_evidence",
    "runtime_evidence_status",
    "freshness_seconds",
    "source_payload_path",
    "source_runtime_id",
    "legacy_source_paths",
    "live_blocked",
    "stages",
    "stage_names",
    "stage_order",
    "chain_complete",
    "chain_consistent",
    "chain_inconsistencies",
    "lineage_ids",
    "signal_record",
    "signal_lineage_record",
    "explainability_invariant_violated",
    "evidence_missing_label",
    "placeholder_remnant_check",
    "signal_publisher_self_check",
    "stale_threshold_seconds",
    "warn_threshold_seconds",
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "symbol_universe_public_payload_status",
    "legacy_active_symbols",
    "legacy_active_symbol_source",
    "discovered_symbols",
    "dynamic_discovered_symbols",
    "dynamic_symbol_sources",
    "observed_symbols",
    "training_symbols",
    "paper_symbols",
    "live_symbols",
    "live_blocked_symbols",
    "live_symbol_policy",
    "passive_monitor_all_discovered_symbols",
    "train_all_discovered_symbols",
    "trade_all_discovered_symbols",
    "binance_usdm_confirmed_symbols",
    "symbol_selection_score_factors",
)


# ---------------------------------------------------------------------------
# time / IO helpers
# ---------------------------------------------------------------------------


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_iso_to_ms(ts: Optional[str]) -> Optional[int]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        parsed = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            parsed = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return int(parsed.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def freshness_state(
    age_seconds: Optional[int],
    *,
    warn: int,
    stale: int,
) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= warn:
        return "CURRENT"
    if age_seconds <= stale:
        return "WARN"
    return "STALE"


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _ledger_rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# symbol universe
# ---------------------------------------------------------------------------


def _as_symbol_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        items: List[Any] = [value]
    elif isinstance(value, list):
        items = list(value)
    else:
        return []
    out: List[str] = []
    for raw in items:
        if isinstance(raw, dict):
            raw = (
                raw.get("canonical_symbol_id")
                or raw.get("symbol")
                or raw.get("legacy_symbol")
            )
        text = str(raw or "").strip().upper()
        if text:
            out.append(text)
    return sorted(set(out))


def _load_symbol_universe_public_payload() -> Tuple[Dict[str, Any], Optional[str]]:
    for candidate in SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            try:
                rel = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(candidate)
            return (data if isinstance(data, dict) else {}), rel
    return {}, None


def build_symbol_scope(
    *,
    observed_symbols: List[str],
) -> Dict[str, Any]:
    public_payload, public_path = _load_symbol_universe_public_payload()
    legacy_seed = _as_symbol_list(
        public_payload.get("legacy_active_symbols") or LEGACY_ACTIVE_SYMBOLS_25
    )
    service = SymbolUniverseService(legacy_active_symbols=legacy_seed)
    discovered = _as_symbol_list(
        public_payload.get("discovered_symbols")
        or public_payload.get("symbols_discovered")
    )
    if not discovered:
        discovered = sorted(
            {
                identity.canonical_symbol_id.upper()
                for identity in service.all_discovered_symbols()
                if getattr(identity, "canonical_symbol_id", None)
            }
        )
    dynamic_discovered = _as_symbol_list(
        public_payload.get("dynamic_discovered_symbols") or discovered
    )
    if not discovered and dynamic_discovered:
        discovered = list(dynamic_discovered)
    training_symbols = _as_symbol_list(public_payload.get("training_symbols"))
    paper_symbols = _as_symbol_list(public_payload.get("paper_symbols"))
    binance_confirmed = _as_symbol_list(
        public_payload.get("binance_usdm_confirmed_symbols")
        or public_payload.get("binance_usdm_tradable_symbols")
    )
    live_blocked = _as_symbol_list(public_payload.get("live_blocked_symbols"))
    if not live_blocked:
        live_blocked = sorted(
            set(
                dynamic_discovered
                or discovered
                or observed_symbols
                or service.legacy_active_symbols()
            )
        )
    return {
        "symbol_universe_contract": SYMBOL_UNIVERSE_CONTRACT,
        "symbol_universe_source_path": public_path or SYMBOL_UNIVERSE_SERVICE_PATH,
        "symbol_universe_public_payload_status": (
            "PRESENT" if public_path else "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
        ),
        "legacy_active_symbols": service.legacy_active_symbols(),
        "legacy_active_symbol_source": "legacy_config.py_SYMBOLS_current_25",
        "discovered_symbols": discovered,
        "dynamic_discovered_symbols": dynamic_discovered,
        "dynamic_symbol_sources": list(DYNAMIC_SYMBOL_SOURCES),
        "observed_symbols": _as_symbol_list(observed_symbols),
        "training_symbols": training_symbols,
        "paper_symbols": paper_symbols,
        "live_symbols": [],
        "live_blocked_symbols": live_blocked,
        "binance_usdm_confirmed_symbols": binance_confirmed,
        "coinank_symbols_tradability": (
            "market_intelligence_only_until_binance_usdm_confirmed"
        ),
        "symbol_scope_policy": (
            "do_not_train_or_trade_all_discovered_symbols_automatically"
        ),
        "passive_monitor_all_discovered_symbols": True,
        "train_all_discovered_symbols": False,
        "trade_all_discovered_symbols": False,
        "live_symbol_policy": "none_live_blocked_human_only",
        "symbol_selection_score_factors": list(SYMBOL_SELECTION_SCORE_FACTORS),
    }


# ---------------------------------------------------------------------------
# bundle loading
# ---------------------------------------------------------------------------


def load_bundle(
    args: argparse.Namespace,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Return (bundle_or_None, source_payload_path, status).

    status in {"present", "missing", "load_failed"}.
    """
    if args.source_file:
        path = Path(args.source_file)
        if not path.exists():
            return None, str(path), "missing"
        data = _read_json(path)
        if not isinstance(data, dict):
            return None, str(path), "load_failed"
        return data, str(path), "present"
    for candidate in BUNDLE_PUBLIC_PAYLOAD_CANDIDATES:
        if candidate.exists():
            data = _read_json(candidate)
            if not isinstance(data, dict):
                continue
            try:
                rel = str(candidate.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(candidate)
            return data, rel, "present"
    return None, "", "missing"


# ---------------------------------------------------------------------------
# placeholder remnant check
# ---------------------------------------------------------------------------


def check_signal_publisher_remnants() -> Dict[str, Any]:
    """Scan ``signal_publisher.py`` for scaffold remnants.

    The lineage worker refuses to certify a green payload if the
    publisher module still ships with words that indicate an
    unfinished placeholder body. The patterns are case-insensitive.
    """
    patterns = list(SIGNAL_PUBLISHER_REMNANT_PATTERNS)
    try:
        source_text = SIGNAL_PUBLISHER_ABS_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "signal_publisher_path": SIGNAL_PUBLISHER_REL_PATH,
            "readable": False,
            "read_error": f"{exc.__class__.__name__}: {exc}",
            "remnants_found": True,
            "patterns_checked": patterns,
            "remnants_matched": patterns,
        }
    lowered = source_text.lower()
    matched = [pattern for pattern in patterns if pattern in lowered]
    return {
        "signal_publisher_path": SIGNAL_PUBLISHER_REL_PATH,
        "readable": True,
        "read_error": "",
        "remnants_found": bool(matched),
        "patterns_checked": patterns,
        "remnants_matched": matched,
    }


# ---------------------------------------------------------------------------
# stage extraction + explainability
# ---------------------------------------------------------------------------


def _stage_block(
    *,
    name: str,
    record: Optional[Mapping[str, Any]],
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
    citations: List[Mapping[str, Any]],
    explanation: str,
    record_ts: Optional[str] = None,
    extra_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    present = record is not None
    age_seconds = bundle_age_seconds if present else None
    fs = freshness_state(age_seconds, warn=warn, stale=stale) if present else "MISSING"
    rendered_explanation = (
        explain_or_missing(explanation=explanation, citations=citations)
        if present
        else EVIDENCE_MISSING_LABEL
    )
    block = {
        "stage_name": name,
        "present": bool(present),
        "source_path": source_path,
        "record_ts": record_ts or "",
        "age_seconds": age_seconds,
        "freshness_state": fs,
        "evidence_citations": [dict(c) for c in citations] if present else [],
        "explanation": rendered_explanation,
        "evidence_missing_label_used": rendered_explanation == EVIDENCE_MISSING_LABEL,
    }
    if extra_fields:
        block.update({k: v for k, v in extra_fields.items()})
    return block


def _build_market_data_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    market = bundle.get("market_feed")
    record: Optional[Dict[str, Any]] = market if isinstance(market, dict) else None
    if record is None:
        block = _stage_block(
            name="market_data",
            record=None,
            source_path=source_path,
            bundle_age_seconds=bundle_age_seconds,
            warn=warn,
            stale=stale,
            citations=[],
            explanation="",
        )
        return block, None
    citations = [
        cite_evidence(
            field_name="symbol",
            source="market_feed.symbol",
            value=record.get("symbol"),
        ),
        cite_evidence(
            field_name="price",
            source="market_feed.price",
            value=record.get("price"),
        ),
        cite_evidence(
            field_name="freshness_state",
            source="market_feed.freshness_state",
            value=record.get("freshness_state"),
        ),
        cite_evidence(
            field_name="age_seconds",
            source="market_feed.age_seconds",
            value=record.get("age_seconds"),
        ),
        cite_evidence(
            field_name="source_type",
            source="market_feed.source_type",
            value=record.get("source_type"),
        ),
    ]
    explanation = (
        f"Read-only market feed observed price={record.get('price')!r} for "
        f"symbol={record.get('symbol')!r} from source_type="
        f"{record.get('source_type')!r}; freshness="
        f"{record.get('freshness_state')!r} age_seconds="
        f"{record.get('age_seconds')!r}."
    )
    block = _stage_block(
        name="market_data",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("last_event_at") or record.get("generated_at") or ""),
    )
    return block, record


def _build_feature_snapshot_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    record = bundle.get("feature_snapshot")
    record = record if isinstance(record, dict) else None
    if record is None:
        return (
            _stage_block(
                name="feature_snapshot",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    features = record.get("features") if isinstance(record.get("features"), dict) else {}
    citations = [
        cite_evidence(
            field_name="feature_snapshot_id",
            source="feature_snapshot.feature_snapshot_id",
            value=record.get("feature_snapshot_id"),
        ),
        cite_evidence(
            field_name="freshness_state",
            source="feature_snapshot.freshness_state",
            value=record.get("freshness_state"),
        ),
        cite_evidence(
            field_name="market_age_seconds",
            source="feature_snapshot.market_age_seconds",
            value=record.get("market_age_seconds"),
        ),
        cite_evidence(
            field_name="return_5m",
            source="feature_snapshot.features.return_5m",
            value=features.get("return_5m"),
        ),
        cite_evidence(
            field_name="return_15m",
            source="feature_snapshot.features.return_15m",
            value=features.get("return_15m"),
        ),
        cite_evidence(
            field_name="volume_last",
            source="feature_snapshot.features.volume_last",
            value=features.get("volume_last"),
        ),
    ]
    explanation = (
        f"Feature snapshot {record.get('feature_snapshot_id')!r} captured "
        f"return_5m={features.get('return_5m')!r} return_15m="
        f"{features.get('return_15m')!r} volume_last="
        f"{features.get('volume_last')!r} with freshness="
        f"{record.get('freshness_state')!r}."
    )
    block = _stage_block(
        name="feature_snapshot",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("generated_at") or ""),
    )
    return block, record


def _build_model_output_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    prediction = bundle.get("trainer_prediction")
    prediction = prediction if isinstance(prediction, dict) else None
    raw_output = (
        prediction.get("raw_output")
        if prediction and isinstance(prediction.get("raw_output"), dict)
        else None
    )
    if raw_output is None:
        return (
            _stage_block(
                name="model_output",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    citations = [
        cite_evidence(
            field_name="side",
            source="trainer_prediction.raw_output.side",
            value=raw_output.get("side"),
        ),
        cite_evidence(
            field_name="momentum_score",
            source="trainer_prediction.raw_output.momentum_score",
            value=raw_output.get("momentum_score"),
        ),
        cite_evidence(
            field_name="model_checkpoint",
            source="trainer_prediction.model_checkpoint",
            value=prediction.get("model_checkpoint") if prediction else None,
        ),
    ]
    explanation = (
        f"Model raw output side={raw_output.get('side')!r} momentum_score="
        f"{raw_output.get('momentum_score')!r} from checkpoint="
        f"{prediction.get('model_checkpoint')!r}."
    )
    block = _stage_block(
        name="model_output",
        record=raw_output,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(prediction.get("generated_at") or "") if prediction else "",
    )
    return block, raw_output


def _build_trainer_prediction_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    record = bundle.get("trainer_prediction")
    record = record if isinstance(record, dict) else None
    if record is None:
        return (
            _stage_block(
                name="trainer_prediction",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    citations = [
        cite_evidence(
            field_name="prediction_id",
            source="trainer_prediction.prediction_id",
            value=record.get("prediction_id"),
        ),
        cite_evidence(
            field_name="feature_snapshot_id",
            source="trainer_prediction.feature_snapshot_id",
            value=record.get("feature_snapshot_id"),
        ),
        cite_evidence(
            field_name="confidence_calibrated",
            source="trainer_prediction.confidence_calibrated",
            value=record.get("confidence_calibrated"),
        ),
        cite_evidence(
            field_name="trainer_state",
            source="trainer_prediction.trainer_state",
            value=record.get("trainer_state"),
        ),
        cite_evidence(
            field_name="model_checkpoint",
            source="trainer_prediction.model_checkpoint",
            value=record.get("model_checkpoint"),
        ),
    ]
    explanation = (
        f"Trainer prediction {record.get('prediction_id')!r} for feature "
        f"snapshot {record.get('feature_snapshot_id')!r} produced calibrated "
        f"confidence {record.get('confidence_calibrated')!r} from trainer state "
        f"{record.get('trainer_state')!r} checkpoint "
        f"{record.get('model_checkpoint')!r}."
    )
    block = _stage_block(
        name="trainer_prediction",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("generated_at") or ""),
    )
    return block, record


def _build_orchestrator_decision_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    lineage = bundle.get("current_signal_lineage")
    lineage = lineage if isinstance(lineage, dict) else None
    record = lineage.get("orchestrator_decision") if lineage else None
    record = record if isinstance(record, dict) else None
    if record is None:
        return (
            _stage_block(
                name="orchestrator_decision",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    citations = [
        cite_evidence(
            field_name="orchestrator_decision_id",
            source="current_signal_lineage.orchestrator_decision.orchestrator_decision_id",
            value=record.get("orchestrator_decision_id"),
        ),
        cite_evidence(
            field_name="decision_action",
            source="current_signal_lineage.orchestrator_decision.decision_action",
            value=record.get("decision_action"),
        ),
        cite_evidence(
            field_name="decision_reason",
            source="current_signal_lineage.orchestrator_decision.decision_reason",
            value=record.get("decision_reason"),
        ),
        cite_evidence(
            field_name="risk_gateway_required",
            source="current_signal_lineage.orchestrator_decision.risk_gateway_required",
            value=record.get("risk_gateway_required"),
        ),
    ]
    explanation = (
        f"Orchestrator decision {record.get('orchestrator_decision_id')!r} "
        f"selected action {record.get('decision_action')!r} with reason "
        f"{record.get('decision_reason')!r}; risk_gateway_required="
        f"{record.get('risk_gateway_required')!r}."
    )
    block = _stage_block(
        name="orchestrator_decision",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("generated_at") or ""),
    )
    return block, record


def _build_risk_decision_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    lineage = bundle.get("current_signal_lineage")
    lineage = lineage if isinstance(lineage, dict) else None
    record = lineage.get("risk_decision") if lineage else None
    record = record if isinstance(record, dict) else None
    if record is None:
        return (
            _stage_block(
                name="risk_gateway_decision",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    citations = [
        cite_evidence(
            field_name="risk_decision_id",
            source="current_signal_lineage.risk_decision.risk_decision_id",
            value=record.get("risk_decision_id"),
        ),
        cite_evidence(
            field_name="risk_action",
            source="current_signal_lineage.risk_decision.risk_action",
            value=record.get("risk_action"),
        ),
        cite_evidence(
            field_name="risk_reason_code",
            source="current_signal_lineage.risk_decision.risk_reason_code",
            value=record.get("risk_reason_code"),
        ),
        cite_evidence(
            field_name="risk_result",
            source="current_signal_lineage.risk_decision.risk_result",
            value=record.get("risk_result"),
        ),
        cite_evidence(
            field_name="live_blocked",
            source="current_signal_lineage.risk_decision.live_blocked",
            value=record.get("live_blocked"),
        ),
    ]
    explanation = (
        f"Risk gateway decision {record.get('risk_decision_id')!r} returned "
        f"action {record.get('risk_action')!r} with reason "
        f"{record.get('risk_reason_code')!r}; result={record.get('risk_result')!r}; "
        f"live_blocked={record.get('live_blocked')!r}."
    )
    block = _stage_block(
        name="risk_gateway_decision",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("generated_at") or ""),
    )
    return block, record


def _build_paper_execution_stage(
    bundle: Mapping[str, Any],
    *,
    source_path: str,
    bundle_age_seconds: Optional[int],
    warn: int,
    stale: int,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    tail = bundle.get("paper_ledger_tail")
    record = None
    if isinstance(tail, list) and tail and isinstance(tail[0], dict):
        record = tail[0]
    if record is None:
        return (
            _stage_block(
                name="paper_execution_result",
                record=None,
                source_path=source_path,
                bundle_age_seconds=bundle_age_seconds,
                warn=warn,
                stale=stale,
                citations=[],
                explanation="",
            ),
            None,
        )
    citations = [
        cite_evidence(
            field_name="paper_ledger_entry_id",
            source="paper_ledger_tail[0].paper_ledger_entry_id",
            value=record.get("paper_ledger_entry_id"),
        ),
        cite_evidence(
            field_name="execution_intent_id",
            source="paper_ledger_tail[0].execution_intent_id",
            value=record.get("execution_intent_id"),
        ),
        cite_evidence(
            field_name="ledger_action",
            source="paper_ledger_tail[0].ledger_action",
            value=record.get("ledger_action"),
        ),
        cite_evidence(
            field_name="paper_result",
            source="paper_ledger_tail[0].paper_result",
            value=record.get("paper_result"),
        ),
        cite_evidence(
            field_name="live_order",
            source="paper_ledger_tail[0].live_order",
            value=record.get("live_order"),
        ),
    ]
    explanation = (
        f"Paper execution ledger entry {record.get('paper_ledger_entry_id')!r} "
        f"recorded ledger_action={record.get('ledger_action')!r} with "
        f"paper_result={record.get('paper_result')!r}; live_order="
        f"{record.get('live_order')!r}."
    )
    block = _stage_block(
        name="paper_execution_result",
        record=record,
        source_path=source_path,
        bundle_age_seconds=bundle_age_seconds,
        warn=warn,
        stale=stale,
        citations=citations,
        explanation=explanation,
        record_ts=str(record.get("generated_at") or ""),
    )
    return block, record


# ---------------------------------------------------------------------------
# unified lineage record + status payload
# ---------------------------------------------------------------------------


def _bundle_age_seconds(bundle: Mapping[str, Any]) -> Optional[int]:
    ts_ms_raw = bundle.get("generated_at_ms")
    ts_ms: Optional[int]
    if isinstance(ts_ms_raw, (int, float)):
        ts_ms = int(ts_ms_raw)
    else:
        ts_ms = parse_iso_to_ms(bundle.get("generated_at"))
    if ts_ms is None:
        return None
    return max(0, int((now_ms() - ts_ms) / 1000))


def _collect_lineage_ids(
    *,
    feature_snapshot: Optional[Mapping[str, Any]],
    trainer_prediction: Optional[Mapping[str, Any]],
    orchestrator_decision: Optional[Mapping[str, Any]],
    risk_decision: Optional[Mapping[str, Any]],
    paper_execution: Optional[Mapping[str, Any]],
    signal_record: Mapping[str, Any],
) -> Dict[str, Any]:
    def _g(d: Optional[Mapping[str, Any]], k: str) -> Optional[str]:
        if not d:
            return None
        v = d.get(k)
        return str(v) if v is not None else None

    signal_id_sources = {
        "signal_record.signal_id": str(signal_record.get("signal_id") or ""),
        "orchestrator_decision.signal_id": _g(orchestrator_decision, "signal_id"),
        "risk_decision.signal_id": _g(risk_decision, "signal_id"),
        "paper_execution.signal_id": _g(paper_execution, "signal_id"),
    }
    return {
        "feature_snapshot_id": _g(feature_snapshot, "feature_snapshot_id"),
        "prediction_id": _g(trainer_prediction, "prediction_id"),
        "signal_id": str(signal_record.get("signal_id") or ""),
        "orchestrator_decision_id": _g(orchestrator_decision, "orchestrator_decision_id"),
        "risk_decision_id": _g(risk_decision, "risk_decision_id"),
        "execution_intent_id": _g(paper_execution, "execution_intent_id"),
        "paper_ledger_entry_id": _g(paper_execution, "paper_ledger_entry_id"),
        "signal_id_sources": signal_id_sources,
    }


def _check_chain_consistency(ids: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    inconsistencies: List[str] = []
    for key, value in ids.items():
        if isinstance(value, dict):
            continue
        if value in (None, ""):
            inconsistencies.append(f"missing_lineage_id:{key}")
    signal_sources = ids.get("signal_id_sources")
    if isinstance(signal_sources, Mapping):
        present_sources = {
            str(source): str(value)
            for source, value in signal_sources.items()
            if value not in (None, "")
        }
        distinct = sorted(set(present_sources.values()))
        if len(distinct) > 1:
            details = ",".join(
                f"{source}={value}" for source, value in sorted(present_sources.items())
            )
            inconsistencies.append(f"signal_id_mismatch:{details}")
    return (len(inconsistencies) == 0), inconsistencies


def build_signal_lineage_record(
    *,
    bundle: Mapping[str, Any],
    stages: Mapping[str, Mapping[str, Any]],
    signal_record: Mapping[str, Any],
    lineage_ids: Mapping[str, Any],
    run_ts: str,
) -> Dict[str, Any]:
    return {
        "schema": "v2_signal_lineage_record_v1",
        "generated_at": run_ts,
        "classification": "REALTIME_RUNTIME_EVIDENCE",
        "source_runtime_id": SOURCE_RUNTIME_ID,
        "stage_order": list(STAGE_ORDER),
        "stages": {name: dict(stages[name]) for name in STAGE_ORDER},
        "signal_record": dict(signal_record),
        "lineage_ids": dict(lineage_ids),
        "live_gate": LIVE_GATE_STATUS,
        "exchange_action_taken": False,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "bundle_generated_at": str(bundle.get("generated_at") or ""),
    }


def build_status_payload(
    *,
    run_ts: str,
    source_payload_path: str,
    bundle: Optional[Mapping[str, Any]],
    stages: Mapping[str, Mapping[str, Any]],
    chain_complete: bool,
    chain_consistent: bool,
    chain_inconsistencies: List[str],
    lineage_ids: Mapping[str, Any],
    signal_record: Mapping[str, Any],
    signal_lineage_record: Optional[Mapping[str, Any]],
    fail_closed: bool,
    fail_closed_reason: str,
    missing_runtime_evidence: bool,
    runtime_evidence_status: str,
    freshness_seconds: Optional[int],
    warn_threshold: int,
    stale_threshold: int,
    symbol_scope: Mapping[str, Any],
    explainability_violation: bool,
    placeholder_check: Mapping[str, Any],
    publisher_self_check: Mapping[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "worker_id": WORKER_ID,
        "last_run_ts": run_ts,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "exchange_call_invariant": EXCHANGE_CALL_INVARIANT,
        "exchange_action_taken": False,
        "fail_closed": bool(fail_closed),
        "fail_closed_reason": fail_closed_reason,
        "missing_runtime_evidence": bool(missing_runtime_evidence),
        "runtime_evidence_status": runtime_evidence_status,
        "freshness_seconds": freshness_seconds,
        "source_payload_path": source_payload_path,
        "source_runtime_id": SOURCE_RUNTIME_ID,
        "legacy_source_paths": list(LEGACY_SOURCE_PATHS),
        "live_blocked": True,
        "stages": {name: dict(stages[name]) for name in STAGE_ORDER},
        "stage_names": list(STAGE_ORDER),
        "stage_order": list(STAGE_ORDER),
        "chain_complete": bool(chain_complete),
        "chain_consistent": bool(chain_consistent),
        "chain_inconsistencies": list(chain_inconsistencies),
        "lineage_ids": dict(lineage_ids),
        "signal_record": dict(signal_record),
        "signal_lineage_record": (
            dict(signal_lineage_record) if signal_lineage_record else {}
        ),
        "explainability_invariant_violated": bool(explainability_violation),
        "evidence_missing_label": EVIDENCE_MISSING_LABEL,
        "placeholder_remnant_check": dict(placeholder_check),
        "signal_publisher_self_check": dict(publisher_self_check),
        "stale_threshold_seconds": int(stale_threshold),
        "warn_threshold_seconds": int(warn_threshold),
    }
    payload.update(symbol_scope)
    return payload


def write_status(status: Mapping[str, Any]) -> None:
    PUBLIC_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    WORKER_STATUS_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(status, indent=2, sort_keys=True, default=str)
    PUBLIC_STATUS_FILE.write_text(body)
    LOCAL_STATUS_FILE.write_text(body)
    WORKER_STATUS_FILE.write_text(body)


# ---------------------------------------------------------------------------
# main run loop
# ---------------------------------------------------------------------------


def _empty_stage(name: str, source_path: str) -> Dict[str, Any]:
    return _stage_block(
        name=name,
        record=None,
        source_path=source_path,
        bundle_age_seconds=None,
        warn=DEFAULT_WARN_THRESHOLD_SECONDS,
        stale=DEFAULT_STALE_THRESHOLD_SECONDS,
        citations=[],
        explanation="",
    )


def _empty_signal_record(run_ts: str) -> Dict[str, Any]:
    return {
        "signal_id": "",
        "service_id": SIGNAL_SERVICE_ID,
        "generated_at": run_ts,
        "symbol": "",
        "prediction_id": "",
        "feature_snapshot_id": "",
        "proposed_action": "hold",
        "side": None,
        "confidence_calibrated": None,
        "confidence_floor": 0.0,
        "actionable": False,
        "actionable_reason_code": "no_evidence",
        "source_freshness": None,
        "market_age_seconds": None,
        "evidence_citations": [],
        "explanation": EVIDENCE_MISSING_LABEL,
        "live_gate": LIVE_GATE_STATUS,
        "exchange_call_invariant": "NO_REAL_EXCHANGE_CALL_FROM_SIGNAL_PUBLISHER",
        "exchange_action_taken": False,
    }


def run_once(args: argparse.Namespace) -> Dict[str, Any]:
    run_ts = iso_now()
    warn_threshold = max(1, int(getattr(args, "warn_threshold_seconds", DEFAULT_WARN_THRESHOLD_SECONDS)))
    stale_threshold = max(warn_threshold + 1, int(getattr(args, "stale_threshold_seconds", DEFAULT_STALE_THRESHOLD_SECONDS)))
    placeholder_check = check_signal_publisher_remnants()
    publisher_self_check = signal_publisher_self_check()

    bundle, source_path, load_status = load_bundle(args)
    observed: List[str] = []
    if isinstance(bundle, dict):
        sym = bundle.get("market_feed", {}).get("symbol") if isinstance(bundle.get("market_feed"), dict) else None
        if isinstance(sym, str) and sym:
            observed = [sym]
    symbol_scope = build_symbol_scope(observed_symbols=observed)

    empty_stages: Dict[str, Dict[str, Any]] = {
        name: _empty_stage(name, source_path) for name in STAGE_ORDER
    }

    if load_status == "missing":
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            bundle=None,
            stages=empty_stages,
            chain_complete=False,
            chain_consistent=False,
            chain_inconsistencies=["bundle_source_missing"],
            lineage_ids={
                "feature_snapshot_id": None,
                "prediction_id": None,
                "signal_id": "",
                "orchestrator_decision_id": None,
                "risk_decision_id": None,
                "execution_intent_id": None,
                "paper_ledger_entry_id": None,
            },
            signal_record=_empty_signal_record(run_ts),
            signal_lineage_record=None,
            fail_closed=True,
            fail_closed_reason="no_paper_runtime_source_found",
            missing_runtime_evidence=True,
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            freshness_seconds=None,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            symbol_scope=symbol_scope,
            explainability_violation=False,
            placeholder_check=placeholder_check,
            publisher_self_check=publisher_self_check,
        )
        write_status(status)
        return status

    if load_status == "load_failed":
        status = build_status_payload(
            run_ts=run_ts,
            source_payload_path=source_path,
            bundle=None,
            stages=empty_stages,
            chain_complete=False,
            chain_consistent=False,
            chain_inconsistencies=["bundle_invalid_json"],
            lineage_ids={
                "feature_snapshot_id": None,
                "prediction_id": None,
                "signal_id": "",
                "orchestrator_decision_id": None,
                "risk_decision_id": None,
                "execution_intent_id": None,
                "paper_ledger_entry_id": None,
            },
            signal_record=_empty_signal_record(run_ts),
            signal_lineage_record=None,
            fail_closed=True,
            fail_closed_reason="paper_runtime_source_invalid_json",
            missing_runtime_evidence=True,
            runtime_evidence_status="INVALID_PAYLOAD",
            freshness_seconds=None,
            warn_threshold=warn_threshold,
            stale_threshold=stale_threshold,
            symbol_scope=symbol_scope,
            explainability_violation=False,
            placeholder_check=placeholder_check,
            publisher_self_check=publisher_self_check,
        )
        write_status(status)
        return status

    assert isinstance(bundle, dict)
    bundle_age = _bundle_age_seconds(bundle)
    bundle_fresh_state = freshness_state(bundle_age, warn=warn_threshold, stale=stale_threshold)

    # build all 7 stage blocks
    market_block, market_record = _build_market_data_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    feature_block, feature_record = _build_feature_snapshot_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    model_block, model_record = _build_model_output_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    pred_block, pred_record = _build_trainer_prediction_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    orch_block, orch_record = _build_orchestrator_decision_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    risk_block, risk_record = _build_risk_decision_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    paper_block, paper_record = _build_paper_execution_stage(
        bundle, source_path=source_path, bundle_age_seconds=bundle_age,
        warn=warn_threshold, stale=stale_threshold,
    )
    stages: Dict[str, Dict[str, Any]] = {
        "market_data": market_block,
        "feature_snapshot": feature_block,
        "model_output": model_block,
        "trainer_prediction": pred_block,
        "orchestrator_decision": orch_block,
        "risk_gateway_decision": risk_block,
        "paper_execution_result": paper_block,
    }

    missing_stages = [name for name in STAGE_ORDER if not stages[name]["present"]]

    # Build signal record via the publisher service.
    if pred_record and feature_record and market_record:
        signal_record = build_signal_record(
            prediction=pred_record,
            feature_snapshot=feature_record,
            market_freshness_state=str(market_record.get("freshness_state") or ""),
            market_age_seconds=market_record.get("age_seconds"),
            run_ts=run_ts,
        )
        upstream_signal_id = ""
        for candidate in (orch_record, risk_record, paper_record):
            if candidate and candidate.get("signal_id"):
                upstream_signal_id = str(candidate.get("signal_id"))
                break
        if upstream_signal_id:
            signal_record = dict(signal_record)
            signal_record["signal_id"] = upstream_signal_id
    else:
        signal_record = _empty_signal_record(run_ts)

    lineage_ids = _collect_lineage_ids(
        feature_snapshot=feature_record,
        trainer_prediction=pred_record,
        orchestrator_decision=orch_record,
        risk_decision=risk_record,
        paper_execution=paper_record,
        signal_record=signal_record,
    )
    chain_consistent, chain_inconsistencies = _check_chain_consistency(lineage_ids)

    fail_closed = False
    fail_closed_reason = ""
    runtime_evidence_status = "PRESENT"
    missing_runtime_evidence = False
    if placeholder_check["remnants_found"]:
        fail_closed = True
        fail_closed_reason = (
            "signal_publisher_scaffold_remnants_present:"
            + ",".join(placeholder_check.get("remnants_matched") or [])
        )
        runtime_evidence_status = "PUBLISHER_REMNANT_DETECTED"
    elif missing_stages:
        fail_closed = True
        fail_closed_reason = "chain_record_missing:" + ",".join(missing_stages)
        runtime_evidence_status = "MISSING_CHAIN_RECORDS"
        missing_runtime_evidence = True
    elif bundle_fresh_state == "STALE" or bundle_fresh_state == "MISSING":
        fail_closed = True
        fail_closed_reason = (
            f"paper_runtime_source_stale: age_seconds={bundle_age} "
            f"stale_threshold={stale_threshold}"
        )
        runtime_evidence_status = "STALE_RUNTIME_EVIDENCE"
        missing_runtime_evidence = True
    elif not chain_consistent:
        fail_closed = True
        fail_closed_reason = (
            "chain_id_inconsistencies:" + ",".join(chain_inconsistencies)
        )
        runtime_evidence_status = "CHAIN_INCONSISTENT"

    chain_complete = (
        not missing_stages
        and bundle_fresh_state in ("CURRENT", "WARN")
    )

    # Explainability invariant: every present stage's explanation must be
    # either a cited claim or the missing-evidence label. We never invent
    # a claim. The invariant is "violated" only when a present stage emits
    # an explanation that is neither cited nor the missing label.
    invariant_violation = False
    for name in STAGE_ORDER:
        block = stages[name]
        if not block["present"]:
            continue
        explanation = str(block.get("explanation") or "")
        if explanation == EVIDENCE_MISSING_LABEL:
            continue
        if not block.get("evidence_citations"):
            invariant_violation = True
            break
        if not any(evidence_present(c) for c in block["evidence_citations"]):
            invariant_violation = True
            break

    lineage_record = (
        build_signal_lineage_record(
            bundle=bundle,
            stages=stages,
            signal_record=signal_record,
            lineage_ids=lineage_ids,
            run_ts=run_ts,
        )
        if chain_complete and not fail_closed
        else None
    )

    status = build_status_payload(
        run_ts=run_ts,
        source_payload_path=source_path,
        bundle=bundle,
        stages=stages,
        chain_complete=chain_complete,
        chain_consistent=chain_consistent,
        chain_inconsistencies=chain_inconsistencies,
        lineage_ids=lineage_ids,
        signal_record=signal_record,
        signal_lineage_record=lineage_record,
        fail_closed=fail_closed,
        fail_closed_reason=fail_closed_reason,
        missing_runtime_evidence=missing_runtime_evidence,
        runtime_evidence_status=runtime_evidence_status,
        freshness_seconds=bundle_age,
        warn_threshold=warn_threshold,
        stale_threshold=stale_threshold,
        symbol_scope=symbol_scope,
        explainability_violation=invariant_violation,
        placeholder_check=placeholder_check,
        publisher_self_check=publisher_self_check,
    )
    write_status(status)
    return status


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument(
        "--source-file",
        default=None,
        help=(
            "Path to a paper_online runtime bundle JSON file. If omitted, "
            "the worker reads the paper_online public payload."
        ),
    )
    parser.add_argument(
        "--warn-threshold-seconds",
        type=int,
        default=DEFAULT_WARN_THRESHOLD_SECONDS,
        help="freshness WARN threshold in seconds",
    )
    parser.add_argument(
        "--stale-threshold-seconds",
        type=int,
        default=DEFAULT_STALE_THRESHOLD_SECONDS,
        help="freshness STALE threshold in seconds (fail-closed boundary)",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--interval", type=int, default=30, help="seconds between loop iterations"
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="dry-run; do not write the public payload",
    )
    args = parser.parse_args(argv)
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.no_write:
        global write_status

        def _skip(_status: Mapping[str, Any]) -> None:
            return None

        write_status = _skip  # type: ignore[assignment]
    if args.once:
        status = run_once(args)
        return 0 if not status.get("fail_closed") else 2
    while True:
        try:
            run_once(args)
        except KeyboardInterrupt:
            return 0
        except Exception:  # noqa: BLE001 - the loop must not crash
            pass
        time.sleep(max(1, args.interval))


if __name__ == "__main__":
    sys.exit(main())
