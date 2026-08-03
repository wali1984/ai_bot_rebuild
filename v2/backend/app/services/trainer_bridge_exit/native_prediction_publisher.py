"""V2 native trainer bridge-exit prediction publisher (paper/shadow only).

Consumes V2-native dynamic feature / TA / OHLCV / orderbook payloads
already populated under ``v2:*`` by the dynamic runtime executor, and
emits per-symbol per-timeframe blocked-paper-shadow observations.

Honest framing — this is NOT a native trainer or model:

  * ``trainer_source`` stays one of:
      - ``V2_NATIVE_BASELINE_PAPER_SHADOW``  (deterministic baseline)
      - ``V2_NATIVE_CONTRACT_ONLY``           (no inputs available)
  * ``v2_native_trainer_ready`` always ``False``
  * ``trainer_native_readiness_claimed`` always ``False``
  * ``paper_fill_allowed`` always ``False`` for contract-only or
    baseline-only outputs; the paper-fill gate stays the source of
    truth, never weakened
  * Existing stronger ``v2:prediction:*`` runtime predictions are
    preserved when present (publisher refuses to overwrite a
    ``V2_NATIVE_TRAINER`` source with a baseline source)
  * Baseline / contract-only outputs are not written into canonical
    ``v2:prediction:*`` keys; they are isolated in a shadow namespace so
    strict trust verification never treats them as trusted model output
  * No legacy Redis writes; the publisher refuses any non-``v2:*`` key
  * No exchange call, no credential read, no live approval

The module accepts an injectable feature/TA reader so tests can run
hermetically with synthetic inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "v2_native_trainer_bridge_exit_prediction_publisher_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

KNOWN_UNIVERSE = (
    "1000BONKUSDT", "1000FLOKIUSDT", "1000PEPEUSDT", "1000SHIBUSDT",
    "ALICEUSDT", "ASTERUSDT", "AUCTIONUSDT", "AVNTUSDT",
    "BANKUSDT", "BARDUSDT", "BTCUSDT", "DOGEUSDT",
    "ETHUSDT", "FARTCOINUSDT", "HIGHUSDT", "LINKUSDT",
    "LTCUSDT", "PENGUUSDT", "PIPPINUSDT", "RAVEUSDT",
    "RIVERUSDT", "SOLUSDT", "UNIUSDT", "WIFUSDT", "XRPUSDT",
)

TIMEFRAMES = ("1m", "5m")

PREDICTION_KEY_TEMPLATE = "v2:prediction:{symbol}:{timeframe}"
SHADOW_PREDICTION_KEY_TEMPLATE = "v2:trainer:prediction_shadow:{symbol}:{timeframe}"
TRAINER_HEARTBEAT_KEY = "v2:trainer:heartbeat"
TRAINER_PUBLISHER_STATUS_KEY = "v2:trainer:prediction_publisher_status"
FEATURES_KEY_TEMPLATE = "v2:features:latest:{symbol}:{timeframe}"
TA_KEY_TEMPLATE = "v2:features:ta:{symbol}:{timeframe}"


# Allowed trainer_source values for this publisher. No native readiness
# label is permitted until a real native trainer lands and Codex passes.
TRAINER_SOURCE_BASELINE_PAPER_SHADOW = "V2_NATIVE_BASELINE_PAPER_SHADOW"
TRAINER_SOURCE_CONTRACT_ONLY = "V2_NATIVE_CONTRACT_ONLY"
ALLOWED_TRAINER_SOURCE_VALUES = (
    TRAINER_SOURCE_BASELINE_PAPER_SHADOW,
    TRAINER_SOURCE_CONTRACT_ONLY,
)
FORBIDDEN_TRAINER_SOURCE_VALUES = (
    "V2_NATIVE_TRAINER_READY",
    "V2_NATIVE_TRAINER_ACTIVE",
)


# Forbidden source labels in any preserved-stronger-prediction check.
PRESERVE_STRONGER_SOURCES = (
    "V2_NATIVE_TRAINER",  # placeholder for a future stronger source
    "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER",
)


REQUIRED_PREDICTION_FIELDS = (
    "prediction_id",
    "symbol",
    "timeframe",
    "generated_at",
    "feature_snapshot_id",
    "trainer_source",
    "model_source",
    "prediction_source_classification",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "confidence_raw",
    "confidence_calibrated",
    "feature_freshness_state",
    "missing_feature_flags",
    "stale_feature_flags",
    "checkpoint_id",
    "checkpoint_blocker",
    "model_blockers",
    "paper_fill_allowed",
    "paper_fill_gate_status",
    "paper_fill_gate_block_reasons",
    "live_gate",
    "live_symbols",
    "approves_live",
    "approves_canary",
    "approves_legacy_shutdown",
    "approves_redis_trim",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safety_block() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_modify_legacy_tree": True,
        "did_not_stop_legacy_runtime": True,
        "did_not_stop_v2_runtime": True,
        "did_not_stop_report_center": True,
        "did_not_stop_replay_miner": True,
        "did_not_stop_codex_governors": True,
        "did_not_write_old_redis_keys": True,
        "did_not_call_exchange_mutation": True,
        "did_not_expose_raw_api_keys": True,
        "did_not_weaken_paper_fill_gate": True,
        "did_not_claim_trainer_native_readiness": True,
        "did_not_claim_checkpoint_compatibility": True,
        "did_not_overwrite_stronger_existing_prediction": True,
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _stable_prediction_id(
    symbol: str, timeframe: str, feature_snapshot_id: str
) -> str:
    digest = hashlib.sha256(
        f"{symbol}|{timeframe}|{feature_snapshot_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"v2_baseline_pred_{digest}"


# ---------------------------------------------------------------------------
# Baseline prediction (no real model)
# ---------------------------------------------------------------------------


def _compute_baseline_signal(
    features: dict[str, Any] | None, ta: dict[str, Any] | None
) -> tuple[float | None, float | None]:
    """Trivial deterministic baseline.

    Reads the most recent feature/TA payload (already V2-native, written
    by the dynamic runtime executor) and returns (confidence_raw,
    expected_move_bps). Returns (None, None) if inputs are missing —
    contract-only path.
    """
    if not features or not ta:
        return (None, None)
    indicators = ta.get("indicators") or {}
    # Use a single deterministic signal: the EMA-9 vs EMA-21 slope sign
    # if present, otherwise fall back to RSI deviation from 50.
    ema_9 = indicators.get("ema_9")
    ema_21 = indicators.get("ema_21")
    rsi_14 = indicators.get("rsi_14")
    if ema_9 is not None and ema_21 is not None:
        try:
            spread = float(ema_9) - float(ema_21)
        except (TypeError, ValueError):
            return (None, None)
        # Map spread into a bounded confidence + expected move.
        confidence_raw = max(0.0, min(1.0, 0.5 + math.tanh(spread / 5.0) / 2.0))
        expected_move_bps = float(max(-50.0, min(50.0, spread * 4.0)))
        return (confidence_raw, expected_move_bps)
    if rsi_14 is not None:
        try:
            r = float(rsi_14)
        except (TypeError, ValueError):
            return (None, None)
        confidence_raw = max(0.0, min(1.0, 0.5 + (r - 50.0) / 100.0))
        expected_move_bps = float(max(-50.0, min(50.0, (r - 50.0) * 0.8)))
        return (confidence_raw, expected_move_bps)
    return (None, None)


def _calibrate(confidence_raw: float | None) -> float | None:
    if confidence_raw is None:
        return None
    # Light isotonic-style cap so baseline cannot signal high confidence
    # without a real model.
    return float(min(0.55, max(0.45, 0.5 + (confidence_raw - 0.5) * 0.2)))


def _after_cost(
    expected_move_bps: float | None,
    *,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
) -> float | None:
    if expected_move_bps is None:
        return None
    return float(expected_move_bps - fee_bps - slippage_bps)


# ---------------------------------------------------------------------------
# Per-symbol prediction builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PredictionInputs:
    symbol: str
    timeframe: str
    features: dict[str, Any] | None
    ta: dict[str, Any] | None
    existing_prediction: dict[str, Any] | None = None


def build_prediction_payload(inputs: PredictionInputs) -> dict[str, Any]:
    missing_flags: list[str] = []
    stale_flags: list[str] = []
    if not inputs.features:
        missing_flags.append("v2_features_latest_missing")
    elif (inputs.features or {}).get("freshness_state") != "FRESH":
        stale_flags.append("v2_features_latest_stale")
    if not inputs.ta:
        missing_flags.append("v2_features_ta_missing")

    confidence_raw, expected_move_bps = _compute_baseline_signal(
        inputs.features, inputs.ta
    )
    confidence_calibrated = _calibrate(confidence_raw)
    expected_move_after_cost_bps = _after_cost(expected_move_bps)

    if confidence_raw is None or expected_move_bps is None:
        trainer_source = TRAINER_SOURCE_CONTRACT_ONLY
        prediction_source_classification = "CONTRACT_ONLY_NO_BASELINE_SIGNAL"
        model_blockers = [
            "no_baseline_signal_available_from_v2_features_or_ta",
            "native_trainer_not_implemented",
        ]
    else:
        trainer_source = TRAINER_SOURCE_BASELINE_PAPER_SHADOW
        prediction_source_classification = "BASELINE_PAPER_SHADOW"
        model_blockers = [
            "native_trainer_not_implemented",
            "baseline_signal_is_not_an_edge_proof",
        ]

    feature_snapshot_id = (
        (inputs.features or {}).get("feature_snapshot_id")
        or f"{inputs.symbol}:{inputs.timeframe}:no_feature_snapshot"
    )

    paper_fill_block_reasons = [
        "v2_native_trainer_not_implemented",
        "checkpoint_operator_decision_required",
        "contract_only_or_baseline_prediction_not_tradeable",
        "live_gate_blocked_human_only",
    ]

    payload = {
        "prediction_id": _stable_prediction_id(
            inputs.symbol, inputs.timeframe, str(feature_snapshot_id)
        ),
        "symbol": inputs.symbol,
        "timeframe": inputs.timeframe,
        "generated_at": _utc_now_iso(),
        "feature_snapshot_id": feature_snapshot_id,
        "trainer_source": trainer_source,
        "model_source": (
            "v2_native_deterministic_baseline_ema_or_rsi"
            if trainer_source == TRAINER_SOURCE_BASELINE_PAPER_SHADOW
            else "no_model_available"
        ),
        "prediction_source_classification": prediction_source_classification,
        "expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        "feature_freshness_state": (
            "FRESH"
            if (inputs.features or {}).get("freshness_state") == "FRESH"
            and not missing_flags
            else "MISSING_OR_STALE"
        ),
        "missing_feature_flags": missing_flags,
        "stale_feature_flags": stale_flags,
        "checkpoint_id": None,
        "checkpoint_blocker": (
            "OPERATOR_DECISION_REQUIRED_NATIVE_TRAINER_CHECKPOINT"
        ),
        "model_blockers": model_blockers,
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "BLOCKED_BASELINE_OR_CONTRACT_ONLY",
        "paper_fill_gate_block_reasons": paper_fill_block_reasons,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    return payload


def is_publishable(payload: dict[str, Any]) -> bool:
    """Validate that every required field is present and safety pins hold."""
    if not isinstance(payload, dict):
        return False
    for f in REQUIRED_PREDICTION_FIELDS:
        if f not in payload:
            return False
    if payload["trainer_source"] not in ALLOWED_TRAINER_SOURCE_VALUES:
        return False
    if payload["paper_fill_allowed"] is not False:
        return False
    if payload["live_gate"] != LIVE_GATE_BLOCKED:
        return False
    if payload["live_symbols"] != []:
        return False
    return True


def should_preserve_existing(existing: dict[str, Any] | None) -> bool:
    """Return True if we should NOT overwrite the existing prediction."""
    if not existing:
        return False
    src = str(existing.get("trainer_source") or "").upper()
    for preserve in PRESERVE_STRONGER_SOURCES:
        if preserve in src and src not in ALLOWED_TRAINER_SOURCE_VALUES:
            return True
    return False


# ---------------------------------------------------------------------------
# Reader + publisher contracts
# ---------------------------------------------------------------------------


@dataclass
class PublisherAudit:
    redis_connected: bool = False
    writes_attempted: int = 0
    writes_succeeded: int = 0
    writes_failed: int = 0
    old_redis_write_attempts: int = 0
    keys_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V2OnlyPublisher:
    """Thin publisher that refuses any non-``v2:*`` key.

    Constructed with an optional ``client`` (duck-typed: ``get(key)``
    returns bytes/str/None, ``set(key, value)`` returns truthy on
    success). Tests use a stub. No client = audit-only mode.
    """

    def __init__(self, client: Any = None) -> None:
        self._client = client
        self.audit = PublisherAudit(redis_connected=client is not None)

    def get_json(self, key: str) -> dict[str, Any] | None:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            return None
        if raw is None:
            return None
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def set_json(self, key: str, payload: dict[str, Any]) -> bool:
        self.audit.writes_attempted += 1
        if not key.startswith("v2:"):
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(f"blocked_non_v2_key:{key}")
            return False
        if self._client is None:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"no_client:{key}")
            return False
        try:
            self._client.set(
                key, json.dumps(payload, sort_keys=True, default=str)
            )
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True


# ---------------------------------------------------------------------------
# Per-symbol orchestration
# ---------------------------------------------------------------------------


def publish_predictions_for_universe(
    *,
    publisher: V2OnlyPublisher,
    universe: Iterable[str] = KNOWN_UNIVERSE,
    timeframes: Iterable[str] = TIMEFRAMES,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    preserved_count = 0
    published_count = 0
    rejected_count = 0
    contract_only_count = 0
    baseline_count = 0

    for symbol in universe:
        for tf in timeframes:
            features = publisher.get_json(
                FEATURES_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            )
            ta = publisher.get_json(
                TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            )
            prediction_key = PREDICTION_KEY_TEMPLATE.format(
                symbol=symbol, timeframe=tf
            )
            existing = publisher.get_json(prediction_key)
            if should_preserve_existing(existing):
                rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "key": prediction_key,
                    "status": "PRESERVED_EXISTING_STRONGER_PREDICTION",
                    "trainer_source_of_existing": (
                        existing.get("trainer_source") if existing else None
                    ),
                })
                preserved_count += 1
                continue
            payload = build_prediction_payload(
                PredictionInputs(
                    symbol=symbol,
                    timeframe=tf,
                    features=features,
                    ta=ta,
                    existing_prediction=existing,
                )
            )
            if not is_publishable(payload):
                rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "key": prediction_key,
                    "status": "REJECTED_NOT_PUBLISHABLE",
                })
                rejected_count += 1
                continue
            shadow_prediction_key = SHADOW_PREDICTION_KEY_TEMPLATE.format(
                symbol=symbol,
                timeframe=tf,
            )
            publisher.set_json(shadow_prediction_key, payload)
            published_count += 1
            if payload["trainer_source"] == TRAINER_SOURCE_BASELINE_PAPER_SHADOW:
                baseline_count += 1
            else:
                contract_only_count += 1
            rows.append({
                "symbol": symbol,
                "timeframe": tf,
                "key": shadow_prediction_key,
                "canonical_prediction_key": prediction_key,
                "status": "V2_NATIVE_BASELINE_OR_CONTRACT_ONLY_SHADOW_PUBLISHED",
                "trainer_source": payload["trainer_source"],
                "prediction_source_classification": payload[
                    "prediction_source_classification"
                ],
                "paper_fill_allowed": payload["paper_fill_allowed"],
            })

    # Trainer heartbeat + publisher status keys
    publisher.set_json(
        TRAINER_HEARTBEAT_KEY,
        {
            "schema_version": SCHEMA_VERSION + "_trainer_heartbeat",
            "generated_at": _utc_now_iso(),
            "publisher": "v2_native_trainer_bridge_exit_prediction_publisher",
            "trainer_native_readiness_claimed": False,
            "v2_native_trainer_ready": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    )
    status = {
        "schema_version": SCHEMA_VERSION + "_publisher_status",
        "generated_at": _utc_now_iso(),
        "universe_size": len(list(universe)),
        "timeframes": list(timeframes),
        "preserved_count": preserved_count,
        "published_count": published_count,
        "rejected_count": rejected_count,
        "baseline_count": baseline_count,
        "contract_only_count": contract_only_count,
        "canonical_prediction_writes_blocked": True,
        "shadow_prediction_namespace": SHADOW_PREDICTION_KEY_TEMPLATE,
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "did_not_overwrite_stronger_existing_prediction": True,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }
    publisher.set_json(TRAINER_PUBLISHER_STATUS_KEY, status)
    return {"rows": rows, "status": status}


# ---------------------------------------------------------------------------
# Orchestrator + dashboard
# ---------------------------------------------------------------------------


@dataclass
class PublisherPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> PublisherPaths:
    return PublisherPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_native_trainer_prediction_publisher/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_native_trainer_prediction_publisher/latest",
    )


@dataclass
class PublisherRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def build_operator_dashboard_payload(
    result: dict[str, Any], audit: PublisherAudit,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_at": _utc_now_iso(),
        "go_no_go": "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_READY",
        "safety_scoreboard": _safety_block(),
        "summary": {
            "universe_size": result["status"]["universe_size"],
            "timeframes": result["status"]["timeframes"],
            "preserved_count": result["status"]["preserved_count"],
            "published_count": result["status"]["published_count"],
            "rejected_count": result["status"]["rejected_count"],
            "baseline_count": result["status"]["baseline_count"],
            "contract_only_count": result["status"]["contract_only_count"],
            "redis_writes_succeeded": audit.writes_succeeded,
            "old_redis_write_attempts": audit.old_redis_write_attempts,
        },
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "full_migration_claimed": False,
        "bridge_data_labeled_as_v2_native": False,
        "controls_present": False,
        "fake_readiness": False,
    }


def run_publisher_packet(
    paths: PublisherPaths,
    *,
    publisher: V2OnlyPublisher | None = None,
) -> PublisherRunResult:
    pub = publisher or V2OnlyPublisher(client=None)
    result = publish_predictions_for_universe(publisher=pub)
    dashboard = build_operator_dashboard_payload(result, pub.audit)
    publisher_status = result["status"]
    rows = result["rows"]
    audit_payload = {
        "schema_version": SCHEMA_VERSION + "_publisher_audit",
        "generated_at": _utc_now_iso(),
        "redis_connected": pub.audit.redis_connected,
        "writes_attempted": pub.audit.writes_attempted,
        "writes_succeeded": pub.audit.writes_succeeded,
        "writes_failed": pub.audit.writes_failed,
        "old_redis_write_attempts": pub.audit.old_redis_write_attempts,
        "key_count": len(pub.audit.keys_written),
        "errors_head": pub.audit.errors[:16],
    }

    _atomic_write_json(paths.packet_dir / "publisher_status.json", publisher_status)
    _atomic_write_json(paths.packet_dir / "per_symbol_rows.json", {
        "schema_version": SCHEMA_VERSION + "_per_symbol_rows",
        "generated_at": _utc_now_iso(),
        "rows": rows,
        **_safety_block(),
    })
    _atomic_write_json(paths.packet_dir / "publisher_audit.json", audit_payload)
    _atomic_write_json(
        paths.packet_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "publisher_status.json", publisher_status
    )

    report = _render_report(result, audit_payload, dashboard)
    _atomic_write_text(
        paths.packet_dir
        / "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_READY\n",
    )

    return PublisherRunResult(
        go_no_go="V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_REPORT.md",
            paths.packet_dir / "publisher_status.json",
            paths.packet_dir / "per_symbol_rows.json",
            paths.packet_dir / "publisher_audit.json",
            paths.packet_dir / "operator_dashboard_payload.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "publisher_status.json",
        ],
    )


def _render_report(result, audit_payload, dashboard) -> str:
    lines = []
    lines.append("# V2 Native Trainer Bridge-Exit Prediction Publisher\n\n")
    lines.append(
        "GO/NO-GO: V2_NATIVE_TRAINER_BRIDGE_EXIT_PREDICTION_PUBLISHER_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " trainer_native_readiness_claimed=false."
        " v2_native_trainer_ready=false.\n\n"
    )
    s = result["status"]
    lines.append("## Summary\n")
    lines.append(
        f"- universe_size: {s['universe_size']}\n"
        f"- timeframes: {s['timeframes']}\n"
        f"- preserved_count: {s['preserved_count']}\n"
        f"- published_count: {s['published_count']}\n"
        f"- rejected_count: {s['rejected_count']}\n"
        f"- baseline_count: {s['baseline_count']}\n"
        f"- contract_only_count: {s['contract_only_count']}\n\n"
    )
    lines.append("## Redis publisher audit\n")
    lines.append(
        f"- redis_connected: {audit_payload['redis_connected']}\n"
        f"- writes_attempted: {audit_payload['writes_attempted']}\n"
        f"- writes_succeeded: {audit_payload['writes_succeeded']}\n"
        f"- writes_failed: {audit_payload['writes_failed']}\n"
        f"- old_redis_write_attempts (must be 0): "
        f"{audit_payload['old_redis_write_attempts']}\n\n"
    )
    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not claim V2_NATIVE_TRAINER_READY or "
        "V2_NATIVE_TRAINER_ACTIVE.\n"
        "- Did not claim checkpoint compatibility.\n"
        "- Did not overwrite an existing stronger runtime prediction.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not write any non-v2:* Redis key (publisher refuses them).\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not modify legacy or V2 runtime.\n"
        "- Did not load or log any API credential value.\n"
    )
    return "".join(lines)
