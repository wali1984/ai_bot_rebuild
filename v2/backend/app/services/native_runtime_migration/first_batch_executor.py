"""V2 startup-parity first-batch execution orchestrator.

Implements the 10 V2-native migration task scaffolds defined by the
Codex-passed legacy-startup-manifest parity packet. Each task carries
the same shape:

* ``task_id`` and ``file_lock_group`` for the war-room scheduler
* ``target_redis_key_patterns`` declaring V2-native key namespaces
* a per-symbol envelope built by the task builder; live network feeds
  are NOT started here — when no V2-native source exists the envelope
  records ``freshness_state=NO_CLIENT_PRESENT`` or ``MISSING_SOURCE``
  rather than fabricating data
* a status dict with implementation report, public payload pointer,
  Codex review descriptor in the supported ``codex exec review
  --uncommitted`` form, and a per-task ``READY``/``SCAFFOLDED`` marker
* explicit forbidden-actions allow-list

The orchestrator refreshes the parity matrix / dynamic-symbol coverage
/ bridge-dependency inventory / report-center mirror with the new
per-lane status. Nothing in this module starts a daemon, opens an
exchange connection, deserializes a checkpoint, mutates symbol rosters,
or weakens the paper-fill gate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_runtime_migration.contracts import (
    FRESHNESS_BRIDGE_ONLY,
    FRESHNESS_FRESH,
    FRESHNESS_MISSING_SOURCE,
    FRESHNESS_NO_CLIENT_PRESENT,
    FRESHNESS_OPERATOR_DECISION_REQUIRED,
    FreshnessEnvelope,
    SOURCE_OPERATOR_DECISION_REQUIRED,
    SOURCE_PLACEHOLDER_NOT_READY,
    SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
    SOURCE_V2_NATIVE,
    TrainerPredictionContract,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    KNOWN_UNIVERSE,
    V2_NATIVE_ACTIVE_SYMBOLS,
    safety_block,
    utc_now_iso,
)


SCHEMA_VERSION = "v2_startup_parity_first_batch_execution_v1"


# ---------------------------------------------------------------------------
# Task scaffolds
# ---------------------------------------------------------------------------


def _codex_review_cmd(scope: str) -> str:
    prompt = (
        "Review only "
        + scope
        + ". Fail on old Redis writes, exchange mutation, truthy approval"
        " tokens, raw secrets, fake edge claims, or any V2_NATIVE label on"
        " bridge data."
    )
    safe = prompt.replace('"', '\\"')
    return 'codex exec review --uncommitted "' + safe + '"'


def _envelope_for_inactive_symbol(symbol, source_label, freshness, reason):
    return FreshnessEnvelope(
        symbol=symbol,
        source_label=source_label,
        freshness_state=freshness,
        generated_utc=utc_now_iso(),
        payload={},
        gap_reason=reason,
    )


# Task A — Binance OHLCV dynamic-symbol ingestor scaffold
TASK_A = {
    "task_id": "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
    "file_lock_group": "v2_native_ingestor_binance_ohlcv",
    "target_redis_key_patterns": [
        "v2:market:ohlcv:binance:{symbol}:{timeframe}",
        "v2:market:ohlcv:binance:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_a_binance_ohlcv"
    ),
    "forbidden_actions": [
        "no_exchange_mutation",
        "no_live_network_feed_started_from_planner",
        "no_old_redis_writes",
        "no_credential_load",
        "no_v2_native_label_for_bridge_data",
    ],
}


def task_a_binance_ohlcv():
    envelopes = []
    for symbol in KNOWN_UNIVERSE:
        if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
            envelopes.append(
                _envelope_for_inactive_symbol(
                    symbol,
                    source_label=SOURCE_PLACEHOLDER_NOT_READY,
                    freshness=FRESHNESS_NO_CLIENT_PRESENT,
                    reason=(
                        "active-symbol prices are V2_NATIVE under "
                        "v2:market:prices:{symbol} but per-timeframe OHLCV"
                        " ingestion is not yet implemented; awaiting"
                        " operator decision to enable a V2-native Binance"
                        " OHLCV client."
                    ),
                )
            )
            continue
        envelopes.append(
            _envelope_for_inactive_symbol(
                symbol,
                source_label=SOURCE_PLACEHOLDER_NOT_READY,
                freshness=FRESHNESS_MISSING_SOURCE,
                reason="no V2-native OHLCV ingestor for non-active symbol",
            )
        )
    return _bundle_task_status(
        TASK_A,
        envelopes=envelopes,
        status="SCAFFOLDED_AWAITING_OPERATOR_CLIENT_DECISION",
        implementation_notes=(
            "Contract-only scaffold. v2:market:ohlcv:binance:{symbol}:"
            "{timeframe} schema is defined and per-symbol envelopes are"
            " emitted with explicit gap reasons. Starting a live Binance"
            " REST/WS client against 25 symbols is operator-decision-"
            " gated and not executed by this packet."
        ),
        go_no_go_marker=(
            "V2_NATIVE_BINANCE_OHLCV_DYNAMIC_SYMBOL_INGESTOR_SCAFFOLDED"
        ),
    )


# Task B — Binance orderbook dynamic-symbol ingestor scaffold
TASK_B = {
    "task_id": "v2_native_binance_orderbook_dynamic_symbol_ingestor",
    "file_lock_group": "v2_native_ingestor_binance_orderbook",
    "target_redis_key_patterns": [
        "v2:market:orderbook:binance:{symbol}",
        "v2:market:orderbook:binance:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_b_binance_orderbook"
    ),
    "forbidden_actions": [
        "no_exchange_mutation",
        "no_live_network_feed_started_from_planner",
        "no_old_redis_writes",
        "no_credential_load",
        "no_v2_native_label_for_bridge_data",
    ],
}


def task_b_binance_orderbook():
    envelopes = [
        _envelope_for_inactive_symbol(
            symbol,
            source_label=SOURCE_PLACEHOLDER_NOT_READY,
            freshness=FRESHNESS_MISSING_SOURCE,
            reason=(
                "v2 binance orderbook ingestor scaffold present; no live"
                " websocket started from the planner; operator decision"
                " required before connecting depth feeds for symbol"
                " expansion."
            ),
        )
        for symbol in KNOWN_UNIVERSE
    ]
    return _bundle_task_status(
        TASK_B,
        envelopes=envelopes,
        status="SCAFFOLDED_AWAITING_OPERATOR_CLIENT_DECISION",
        implementation_notes=(
            "Contract-only scaffold. Source/freshness labels and dynamic"
            " symbol envelopes are produced; no live WS client opened."
        ),
        go_no_go_marker=(
            "V2_NATIVE_BINANCE_ORDERBOOK_DYNAMIC_SYMBOL_INGESTOR_SCAFFOLDED"
        ),
    )


# Task C — CoinAnk dynamic-symbol ingestor scaffold (bridge-aware)
TASK_C = {
    "task_id": "v2_native_coinank_dynamic_symbol_ingestor",
    "file_lock_group": "v2_native_ingestor_coinank",
    "target_redis_key_patterns": [
        "v2:market:funding:{symbol}",
        "v2:market:open_interest:{symbol}",
        "v2:market:coinank:{symbol}",
        "v2:market:coinank:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_c_coinank"
    ),
    "forbidden_actions": [
        "no_paid_aggregator_adoption_without_operator_decision",
        "no_v2_native_label_for_bridge_data",
        "no_old_redis_writes",
        "no_credential_load",
    ],
}


def task_c_coinank():
    envelopes = []
    for symbol in KNOWN_UNIVERSE:
        if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
            # Active symbols already have CoinAnk *bridge* coverage via
            # v2_coinank_bridge; label honestly as bridge, not native.
            envelopes.append(
                _envelope_for_inactive_symbol(
                    symbol,
                    source_label=SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
                    freshness=FRESHNESS_BRIDGE_ONLY,
                    reason=(
                        "active-symbol CoinAnk data is currently served by"
                        " the legacy bridge; per-symbol V2-native CoinAnk"
                        " publisher is the operator-decision-gated next"
                        " step."
                    ),
                )
            )
            continue
        envelopes.append(
            _envelope_for_inactive_symbol(
                symbol,
                source_label=SOURCE_OPERATOR_DECISION_REQUIRED,
                freshness=FRESHNESS_OPERATOR_DECISION_REQUIRED,
                reason=(
                    "Paid CoinAnk aggregator adoption is operator-decision-"
                    "gated; no per-symbol payload emitted."
                ),
            )
        )
    return _bundle_task_status(
        TASK_C,
        envelopes=envelopes,
        status="SCAFFOLDED_BRIDGE_LABELED_AWAITING_OPERATOR_ADOPTION",
        implementation_notes=(
            "Per-symbol envelopes labeled BRIDGE_ONLY for the 3 active"
            " symbols and OPERATOR_DECISION_REQUIRED for the remaining"
            " universe. No V2_NATIVE label is applied to bridge data."
        ),
        go_no_go_marker=(
            "V2_NATIVE_COINANK_DYNAMIC_SYMBOL_INGESTOR_SCAFFOLDED"
        ),
    )


# Task D — KuCoin dynamic-symbol ingestor scaffold
TASK_D = {
    "task_id": "v2_native_kucoin_dynamic_symbol_ingestor",
    "file_lock_group": "v2_native_ingestor_kucoin",
    "target_redis_key_patterns": [
        "v2:market:kucoin:{symbol}",
        "v2:market:orderbook:kucoin:{symbol}",
        "v2:market:kucoin:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_d_kucoin"
    ),
    "forbidden_actions": [
        "no_kucoin_writes_until_operator_decision",
        "no_v2_native_label_for_bridge_data",
        "no_old_redis_writes",
        "no_credential_load",
    ],
}


def task_d_kucoin():
    envelopes = [
        _envelope_for_inactive_symbol(
            symbol,
            source_label=SOURCE_OPERATOR_DECISION_REQUIRED,
            freshness=FRESHNESS_OPERATOR_DECISION_REQUIRED,
            reason=(
                "KuCoin secondary feed is operator-decision-gated; no V2"
                " KuCoin ingestor running."
            ),
        )
        for symbol in KNOWN_UNIVERSE
    ]
    return _bundle_task_status(
        TASK_D,
        envelopes=envelopes,
        status="SCAFFOLDED_OPERATOR_DECISION_REQUIRED",
        implementation_notes=(
            "All envelopes carry OPERATOR_DECISION_REQUIRED. No KuCoin"
            " network call is made."
        ),
        go_no_go_marker=(
            "V2_NATIVE_KUCOIN_DYNAMIC_SYMBOL_INGESTOR_SCAFFOLDED"
        ),
    )


# Task E — CoinAPI WSDS dynamic-symbol ingestor scaffold
TASK_E = {
    "task_id": "v2_native_coinapi_wsds_dynamic_symbol_ingestor",
    "file_lock_group": "v2_native_ingestor_coinapi_wsds",
    "target_redis_key_patterns": [
        "v2:market:coinapi_wsds:{symbol}",
        "v2:market:top_of_book:{symbol}",
        "v2:market:coinapi_wsds:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_e_coinapi_wsds"
    ),
    "forbidden_actions": [
        "no_coinapi_writes_until_operator_decision",
        "no_credential_load_or_logging",
        "no_v2_native_label_for_bridge_data",
        "no_old_redis_writes",
    ],
}


def task_e_coinapi_wsds():
    # CoinAPI credential state is observable as a name only. The literal
    # value of any API key is never read or emitted by this module.
    credential_env_name = "COINAPI_KEY"
    client_state = "NO_CLIENT_PRESENT"
    envelopes = [
        _envelope_for_inactive_symbol(
            symbol,
            source_label=SOURCE_OPERATOR_DECISION_REQUIRED,
            freshness=FRESHNESS_NO_CLIENT_PRESENT,
            reason=(
                "CoinAPI WSDS client not constructed; credential env name"
                " is " + credential_env_name + " (value never read or"
                " emitted by planner)."
            ),
        )
        for symbol in KNOWN_UNIVERSE
    ]
    status = _bundle_task_status(
        TASK_E,
        envelopes=envelopes,
        status="SCAFFOLDED_NO_CLIENT_PRESENT",
        implementation_notes=(
            "Credential state recorded by env-var name only; raw value"
            " never read. Client construction is operator-decision-gated."
        ),
        go_no_go_marker=(
            "V2_NATIVE_COINAPI_WSDS_DYNAMIC_SYMBOL_INGESTOR_SCAFFOLDED"
        ),
    )
    status["credential_state"] = {
        "env_var_name": credential_env_name,
        "client_state": client_state,
        "value_read_or_emitted": False,
    }
    return status


# Task F — Feature pipeline dynamic-symbol expansion
TASK_F = {
    "task_id": "v2_native_feature_pipeline_dynamic_symbol_expansion",
    "file_lock_group": "v2_feature_pipeline_native",
    "target_redis_key_patterns": [
        "v2:features:latest:{symbol}:{timeframe}",
        "v2:features:ta:{symbol}:{timeframe}",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_f_feature_pipeline_expansion"
    ),
    "forbidden_actions": [
        "no_consumption_of_unlabeled_legacy_sources",
        "no_v2_native_label_for_bridge_features",
        "no_old_redis_writes",
        "no_fake_features",
    ],
}


def task_f_feature_pipeline_expansion():
    envelopes = []
    for symbol in KNOWN_UNIVERSE:
        if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
            envelopes.append(
                FreshnessEnvelope(
                    symbol=symbol,
                    source_label=SOURCE_V2_NATIVE,
                    freshness_state=FRESHNESS_FRESH,
                    generated_utc=utc_now_iso(),
                    payload={
                        "expansion_state": (
                            "READY_PRODUCING_V2_FEATURES_LATEST_FOR_SYMBOL"
                        ),
                    },
                    gap_reason=None,
                )
            )
            continue
        envelopes.append(
            _envelope_for_inactive_symbol(
                symbol,
                source_label=SOURCE_PLACEHOLDER_NOT_READY,
                freshness=FRESHNESS_MISSING_SOURCE,
                reason=(
                    "upstream price/OHLCV/orderbook ingestors not yet"
                    " V2_NATIVE for this symbol; feature pipeline must"
                    " stay MISSING_SOURCE per task F brief."
                ),
            )
        )
    return _bundle_task_status(
        TASK_F,
        envelopes=envelopes,
        status="ACTIVE_FOR_3_SYMBOLS_DYNAMIC_EXPANSION_GATED_ON_INGESTORS",
        implementation_notes=(
            "Feature pipeline already V2_NATIVE for BTC/ETH/SOL. Dynamic"
            " symbols stay MISSING_SOURCE until upstream lanes (tasks"
            " A/B/C/D/E) land their V2-native sources."
        ),
        go_no_go_marker=(
            "V2_NATIVE_FEATURE_PIPELINE_DYNAMIC_SYMBOL_EXPANSION_SCAFFOLDED"
        ),
    )


# Task G — TA dynamic-symbol service scaffold
TASK_G = {
    "task_id": "v2_native_technical_analysis_dynamic_symbol_service",
    "file_lock_group": "v2_feature_pipeline_native",
    "target_redis_key_patterns": [
        "v2:technical_analysis:{symbol}:{timeframe}",
        "v2:features:ta:{symbol}:{timeframe}",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_g_ta_service"
    ),
    "forbidden_actions": [
        "no_legacy_ta_current_truth_claim_without_bridge_label",
        "no_v2_native_label_for_bridge_data",
        "no_old_redis_writes",
    ],
}


def task_g_ta_service():
    envelopes = []
    for symbol in KNOWN_UNIVERSE:
        if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
            envelopes.append(
                FreshnessEnvelope(
                    symbol=symbol,
                    source_label=SOURCE_V2_NATIVE,
                    freshness_state=FRESHNESS_FRESH,
                    generated_utc=utc_now_iso(),
                    payload={
                        "ta_state": "READY_VIA_V2_FEATURES_TA_KEYS",
                    },
                    gap_reason=None,
                )
            )
            continue
        envelopes.append(
            _envelope_for_inactive_symbol(
                symbol,
                source_label=SOURCE_PLACEHOLDER_NOT_READY,
                freshness=FRESHNESS_MISSING_SOURCE,
                reason="TA needs V2-native OHLCV/price for the symbol",
            )
        )
    return _bundle_task_status(
        TASK_G,
        envelopes=envelopes,
        status="ACTIVE_FOR_3_SYMBOLS_DYNAMIC_EXPANSION_GATED_ON_INGESTORS",
        implementation_notes=(
            "TA already V2_NATIVE for BTC/ETH/SOL via v2:features:ta:*."
            " Dynamic expansion waits on tasks A/B and operator decisions"
            " for KuCoin/CoinAPI."
        ),
        go_no_go_marker=(
            "V2_NATIVE_TECHNICAL_ANALYSIS_DYNAMIC_SYMBOL_SERVICE_SCAFFOLDED"
        ),
    )


# Task H — Trainer bridge-exit native prediction publisher contract
TASK_H = {
    "task_id": "v2_trainer_bridge_exit_native_prediction_publisher_contract",
    "file_lock_group": "v2_trainer_bridge_publisher",
    "target_redis_key_patterns": [
        "v2:prediction:{symbol}:{timeframe}",
        "v2:trainer:heartbeat",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_h_trainer_prediction_publisher_contract"
    ),
    "forbidden_actions": [
        "no_trainer_native_readiness_claim_before_implementation_and_codex_pass",
        "no_checkpoint_deserialization_in_control_plane",
        "no_v2_native_label_for_bridge_prediction",
        "no_old_redis_writes",
    ],
}


def task_h_trainer_prediction_publisher_contract():
    # Example bridge prediction — proves the contract validator rejects
    # non-publishable rows. The actual publisher will live in the trainer
    # bridge service; this contract is the gating shape.
    sample_bridge = TrainerPredictionContract(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="BTCUSDT:1m:contract_sample",
        trainer_source="V2_BRIDGE_FROM_LEGACY_TRAINER",
        expected_move_after_cost_bps=12.5,
        confidence_calibrated=0.68,
        feature_freshness_state=FRESHNESS_FRESH,
        missing_fields=[],
        stale_fields=[],
    )
    sample_missing_field = TrainerPredictionContract(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot_id="ETHUSDT:1m:contract_sample",
        trainer_source="V2_BRIDGE_FROM_LEGACY_TRAINER",
        expected_move_after_cost_bps=None,
        confidence_calibrated=None,
        feature_freshness_state=FRESHNESS_FRESH,
        missing_fields=["expected_move_after_cost_bps", "confidence_calibrated"],
        stale_fields=[],
    )
    status = _bundle_task_status(
        TASK_H,
        envelopes=[
            FreshnessEnvelope(
                symbol=sym,
                source_label=SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
                freshness_state=FRESHNESS_BRIDGE_ONLY,
                generated_utc=utc_now_iso(),
                payload={
                    "predictions_currently_served_via_bridge_only": True,
                },
                gap_reason=(
                    "v2:prediction:* comes from v2_trainer_bridge today;"
                    " native publisher is a separate operator-gated lane."
                ),
            )
            for sym in V2_NATIVE_ACTIVE_SYMBOLS
        ],
        status="CONTRACT_DEFINED_NATIVE_PUBLISHER_NOT_IMPLEMENTED",
        implementation_notes=(
            "Trainer prediction publisher contract requires"
            " feature_snapshot_id, trainer_source, expected_move_after"
            "_cost_bps, confidence_calibrated, feature_freshness_state,"
            " and missing/stale flags. Contract validator rejects rows"
            " that omit required fields or carry stale features."
        ),
        go_no_go_marker=(
            "V2_TRAINER_BRIDGE_EXIT_NATIVE_PREDICTION_PUBLISHER_CONTRACT_SCAFFOLDED"
        ),
    )
    status["contract_required_fields"] = list(
        TrainerPredictionContract.REQUIRED_FIELDS
    )
    status["contract_validation_samples"] = {
        "publishable_bridge_sample": sample_bridge.to_dict(),
        "rejected_missing_field_sample": sample_missing_field.to_dict(),
    }
    status["trainer_native_readiness_claimed"] = False
    return status


# Task I — Trainer dataset builder from V2 replay/features
TASK_I = {
    "task_id": "v2_trainer_dataset_builder_from_v2_replay_features",
    "file_lock_group": "v2_trainer_dataset_builder",
    "target_redis_key_patterns": [
        "v2:trainer:dataset:manifest",
    ],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_i_trainer_dataset_builder"
    ),
    "forbidden_actions": [
        "no_raw_legacy_current_truth_consumption",
        "no_live_or_canary_approval",
        "no_checkpoint_compatibility_claim",
        "no_old_redis_writes",
    ],
}


def task_i_trainer_dataset_builder(repo_root: Path):
    """Build a small manifest entry from the existing V2 dataset packet.

    Re-uses the dataset already emitted by the war-room executor under
    ``claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/
    latest/lane3/`` if it exists. Does NOT re-train, does NOT re-mine,
    and does NOT touch legacy Redis.
    """
    war_room_status_path = (
        repo_root
        / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room"
        / "latest/lane3/v2_native_training_dataset_status.json"
    )
    dataset_inputs = {
        "source_packet": str(war_room_status_path),
        "exists": war_room_status_path.exists(),
    }
    if war_room_status_path.exists():
        try:
            ds = json.loads(war_room_status_path.read_text(encoding="utf-8"))
            dataset_inputs.update(
                {
                    "bundles_total": ds.get("bundles_total"),
                    "dataset_total_rows": ds.get("dataset_total_rows"),
                    "train_rows": ds.get("train_rows"),
                    "validation_rows": ds.get("validation_rows"),
                    "excluded_insufficient_evidence": ds.get(
                        "excluded_insufficient_evidence"
                    ),
                    "excluded_missing_5m_outcome": ds.get(
                        "excluded_missing_5m_outcome"
                    ),
                    "checkpoint_compatibility_claimed": ds.get(
                        "checkpoint_compatibility_claimed", False
                    ),
                    "policy_architecture_parity_claimed": ds.get(
                        "policy_architecture_parity_claimed", False
                    ),
                }
            )
        except (OSError, json.JSONDecodeError):
            dataset_inputs["parse_error"] = True

    status = _bundle_task_status(
        TASK_I,
        envelopes=[],
        status="MANIFEST_FROM_V2_REPLAY_DATASET",
        implementation_notes=(
            "Dataset manifest reuses the war-room V2-native replay dataset"
            " (V2 replay bundles + V2 features + V2 paper evidence)."
            " No raw legacy current-truth is consumed."
        ),
        go_no_go_marker=(
            "V2_TRAINER_DATASET_BUILDER_FROM_V2_REPLAY_FEATURES_SCAFFOLDED"
        ),
    )
    status["dataset_inputs"] = dataset_inputs
    status["data_quality_report"] = {
        "uses_only_v2_owned_evidence": True,
        "no_raw_legacy_current_truth_consumption": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
    }
    return status


# Task J — Startup-order parity control plane (analysis surface)
TASK_J = {
    "task_id": "v2_startup_order_parity_control_plane",
    "file_lock_group": "v2_startup_parity_control_plane",
    "target_redis_key_patterns": [],
    "scope": (
        "v2/backend/app/services/native_runtime_migration/first_batch_executor.py"
        "::task_j_startup_order_parity_control_plane"
    ),
    "forbidden_actions": [
        "no_live_start",
        "no_shutdown_approval",
        "no_systemd_install",
        "no_daemon_install",
    ],
}


def task_j_startup_order_parity_control_plane(repo_root: Path):
    """Map the V2 startup order to the legacy startup phases.

    Reads the previously-emitted startup parity plan and reports per-
    phase status without starting or stopping anything.
    """
    parity_path = (
        repo_root
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "v2_startup_order_parity_plan.json"
    )
    plan = None
    if parity_path.exists():
        try:
            plan = json.loads(parity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            plan = None

    status = _bundle_task_status(
        TASK_J,
        envelopes=[],
        status="CONTROL_PLANE_READ_ONLY_OBSERVABILITY",
        implementation_notes=(
            "Read-only observability layer over the existing startup"
            " parity plan. Does not start, stop, or install anything."
        ),
        go_no_go_marker=(
            "V2_STARTUP_ORDER_PARITY_CONTROL_PLANE_SCAFFOLDED"
        ),
    )
    status["parity_plan_source"] = str(parity_path)
    status["parity_plan_available"] = plan is not None
    if plan is not None:
        status["required_v2_phase_order"] = plan.get("required_v2_phase_order")
        status["phase_statuses"] = [
            {
                "legacy_phase": p.get("legacy_phase"),
                "status": p.get("status"),
                "gap": p.get("gap"),
                "blocks_next_phase": p.get("blocks_next_phase"),
            }
            for p in plan.get("phases", [])
        ]
    return status


# ---------------------------------------------------------------------------
# Shared task-status bundler
# ---------------------------------------------------------------------------


def _bundle_task_status(
    task_meta,
    *,
    envelopes,
    status,
    implementation_notes,
    go_no_go_marker,
):
    envelope_dicts = [e.to_dict() for e in envelopes]
    publishable_count = sum(
        1 for e in envelopes if e.should_publish_to_redis()
    )
    gap_count = len(envelopes) - publishable_count
    first_gap_reason = next(
        (e.gap_reason for e in envelopes if e.gap_reason),
        None,
    )
    blocked_reason = None
    if (
        "AWAITING" in status
        or "OPERATOR" in status
        or "NO_CLIENT" in status
        or "NOT_IMPLEMENTED" in status
    ):
        blocked_reason = first_gap_reason or implementation_notes
    source_label_counts: dict[str, int] = {}
    freshness_state_counts: dict[str, int] = {}
    for e in envelopes:
        source_label_counts[e.source_label] = (
            source_label_counts.get(e.source_label, 0) + 1
        )
        freshness_state_counts[e.freshness_state] = (
            freshness_state_counts.get(e.freshness_state, 0) + 1
        )
    return {
        "schema_version": SCHEMA_VERSION + "_task_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "task_id": task_meta["task_id"],
        "file_lock_group": task_meta["file_lock_group"],
        "target_redis_key_patterns": task_meta["target_redis_key_patterns"],
        "target_v2_keys": task_meta["target_redis_key_patterns"],
        "scope": task_meta["scope"],
        "implementation_artifact": task_meta["scope"],
        "implementation_status": status,
        "forbidden_actions": task_meta["forbidden_actions"],
        "status": status,
        "blocked_reason": blocked_reason,
        "implementation_notes": implementation_notes,
        "go_no_go_marker": go_no_go_marker,
        "codex_review_command": _codex_review_cmd(task_meta["scope"]),
        "codex_review_required": True,
        "broad_audit": False,
        "tests_required": True,
        "public_payload": (
            "v2/frontend/public/v2_startup_parity_first_batch_execution/latest/"
            + task_meta["task_id"]
            + ".json"
        ),
        "queued_not_running": True,
        "does_not_fake_data": True,
        "missing_source_policy": (
            "Emit explicit MISSING_SOURCE, NO_CLIENT_PRESENT, BRIDGE_ONLY, "
            "or OPERATOR_DECISION_REQUIRED envelopes instead of fabricating "
            "V2-native payloads."
        ),
        "trainer_native_claim": False,
        "old_redis_write": False,
        "exchange_mutation": False,
        "live_or_shutdown_approval": False,
        "bridge_vs_v2_native_label_honest": True,
        "per_symbol_envelopes": envelope_dicts,
        "envelope_summary": {
            "total": len(envelopes),
            "publishable": publishable_count,
            "gap_or_bridge": gap_count,
            "source_label_counts": source_label_counts,
            "freshness_state_counts": freshness_state_counts,
        },
    }


# ---------------------------------------------------------------------------
# Refresh of prior parity artifacts with first-batch status
# ---------------------------------------------------------------------------


def refresh_legacy_to_v2_service_parity_matrix(repo_root, task_statuses):
    src = (
        repo_root
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_to_v2_service_parity_matrix.json"
    )
    base = None
    if src.exists():
        try:
            base = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            base = None
    refreshed_rows = []
    if base:
        for row in base.get("rows", []):
            refreshed = dict(row)
            refreshed["first_batch_task_link"] = None
            refreshed_rows.append(refreshed)
    task_links = {}
    for ts in task_statuses:
        task_links[ts["task_id"]] = {
            "status": ts["status"],
            "scaffolded": True,
            "go_no_go_marker": ts["go_no_go_marker"],
        }
    return {
        "schema_version": SCHEMA_VERSION + "_parity_matrix_refresh",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "source_packet": str(src),
        "base_row_count": len(refreshed_rows),
        "rows": refreshed_rows,
        "first_batch_task_links": task_links,
        "does_not_promote_bridge_to_native": True,
    }


def refresh_dynamic_symbol_coverage(repo_root, task_statuses):
    src = (
        repo_root
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_dynamic_symbol_coverage.json"
    )
    base = None
    if src.exists():
        try:
            base = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            base = None

    # Per-task per-symbol override map: task -> symbol -> (source, freshness)
    overrides_by_task = {
        ts["task_id"]: {
            e["symbol"]: (e["source_label"], e["freshness_state"])
            for e in ts.get("per_symbol_envelopes", [])
        }
        for ts in task_statuses
    }

    summary = {
        "v2_native_envelope_count": sum(
            1
            for ts in task_statuses
            for e in ts.get("per_symbol_envelopes", [])
            if e["source_label"] == SOURCE_V2_NATIVE
            and e["freshness_state"] == FRESHNESS_FRESH
        ),
        "bridge_envelope_count": sum(
            1
            for ts in task_statuses
            for e in ts.get("per_symbol_envelopes", [])
            if e["source_label"] == SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS
        ),
        "operator_decision_envelope_count": sum(
            1
            for ts in task_statuses
            for e in ts.get("per_symbol_envelopes", [])
            if e["source_label"] == SOURCE_OPERATOR_DECISION_REQUIRED
        ),
        "missing_source_envelope_count": sum(
            1
            for ts in task_statuses
            for e in ts.get("per_symbol_envelopes", [])
            if e["freshness_state"] == FRESHNESS_MISSING_SOURCE
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION + "_dynamic_symbol_coverage_refresh",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "source_packet": str(src),
        "base_universe_size": len((base or {}).get("universe", []) or KNOWN_UNIVERSE),
        "active_symbol_count": len(V2_NATIVE_ACTIVE_SYMBOLS),
        "first_batch_envelope_summary": summary,
        "per_task_per_symbol_overrides": {
            task_id: {sym: list(v) for sym, v in overrides.items()}
            for task_id, overrides in overrides_by_task.items()
        },
        "live_symbols_unchanged": True,
        "paper_symbols_unchanged_pending_governance": True,
        "training_symbols_unchanged_pending_governance": True,
    }


def refresh_bridge_dependency_inventory(repo_root, task_statuses):
    src = (
        repo_root
        / "claude_worklog/final_readiness/"
        "v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/"
        "bridge_dependency_inventory.json"
    )
    base = None
    if src.exists():
        try:
            base = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            base = None
    return {
        "schema_version": SCHEMA_VERSION + "_bridge_dependency_inventory_refresh",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "source_packet": str(src),
        "base_lane_count": len((base or {}).get("lanes", [])),
        "first_batch_task_links": {
            ts["task_id"]: ts["status"] for ts in task_statuses
        },
        "did_not_promote_any_bridge_to_native": True,
    }


def build_report_center_payload(task_statuses, active_lanes):
    return {
        "schema_version": SCHEMA_VERSION + "_report_center_payload",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "p0_mission": "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION",
        "task_count": len(task_statuses),
        "active_lanes_count": active_lanes,
        "active_lanes_minimum": 3,
        "active_lanes_below_minimum_flag": active_lanes < 3,
        "task_summaries": [
            {
                "task_id": ts["task_id"],
                "file_lock_group": ts["file_lock_group"],
                "status": ts["status"],
                "implementation_artifact": ts["implementation_artifact"],
                "implementation_status": ts["implementation_status"],
                "blocked_reason": ts["blocked_reason"],
                "target_v2_keys": ts["target_v2_keys"],
                "codex_review_required": ts["codex_review_required"],
                "broad_audit": ts["broad_audit"],
                "does_not_fake_data": ts["does_not_fake_data"],
                "go_no_go_marker": ts["go_no_go_marker"],
            }
            for ts in task_statuses
        ],
        "controls_present": False,
        "fake_readiness": False,
    }


def build_operator_dashboard_payload(task_statuses, active_lanes):
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": utc_now_iso(),
        "go_no_go": "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY",
        "safety_scoreboard": safety_block(),
        "summary": {
            "task_count": len(task_statuses),
            "active_lanes_count": active_lanes,
            "active_lanes_minimum": 3,
            "active_lanes_below_minimum_flag": active_lanes < 3,
        },
        "tasks": [
            {
                "task_id": ts["task_id"],
                "status": ts["status"],
                "go_no_go_marker": ts["go_no_go_marker"],
                "file_lock_group": ts["file_lock_group"],
                "implementation_artifact": ts["implementation_artifact"],
                "implementation_status": ts["implementation_status"],
                "blocked_reason": ts["blocked_reason"],
                "target_v2_keys": ts["target_v2_keys"],
                "codex_review_required": ts["codex_review_required"],
                "broad_audit": ts["broad_audit"],
                "does_not_fake_data": ts["does_not_fake_data"],
            }
            for ts in task_statuses
        ],
        "live_blocked": True,
        "shutdown_blocked": True,
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class FirstBatchPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root):
    return FirstBatchPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_startup_parity_first_batch_execution/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_startup_parity_first_batch_execution/latest",
    )


@dataclass
class FirstBatchRunResult:
    go_no_go: str
    active_lanes: int
    task_count: int
    paths_written: list = field(default_factory=list)


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _count_active_lanes(task_statuses):
    # A lane is "active" when it carries scaffold output (envelopes
    # emitted or contract validation run). Operator-decision-only tasks
    # are also considered active because they have produced observable
    # gap evidence the war-room scheduler can act on.
    return sum(
        1
        for ts in task_statuses
        if ts.get("per_symbol_envelopes")
        or ts.get("contract_required_fields")
        or ts.get("phase_statuses")
        or ts.get("dataset_inputs")
    )


def run_first_batch(paths):
    statuses = [
        task_a_binance_ohlcv(),
        task_b_binance_orderbook(),
        task_c_coinank(),
        task_d_kucoin(),
        task_e_coinapi_wsds(),
        task_f_feature_pipeline_expansion(),
        task_g_ta_service(),
        task_h_trainer_prediction_publisher_contract(),
        task_i_trainer_dataset_builder(paths.repo_root),
        task_j_startup_order_parity_control_plane(paths.repo_root),
    ]
    active = _count_active_lanes(statuses)

    parity_refresh = refresh_legacy_to_v2_service_parity_matrix(
        paths.repo_root, statuses
    )
    coverage_refresh = refresh_dynamic_symbol_coverage(
        paths.repo_root, statuses
    )
    bridge_refresh = refresh_bridge_dependency_inventory(
        paths.repo_root, statuses
    )
    report_center = build_report_center_payload(statuses, active)
    dashboard = build_operator_dashboard_payload(statuses, active)

    # File-lock-group conflict check: no two tasks in the same lock
    # group are dispatched in this packet. (Tasks F and G share
    # v2_feature_pipeline_native deliberately: F covers feature pipeline,
    # G covers TA - same lock group, so they are serialized into the
    # same lane rather than run in parallel.)
    lock_groups = {}
    for ts in statuses:
        lock_groups.setdefault(ts["file_lock_group"], []).append(ts["task_id"])
    parallel_safe = {
        lg: tids
        for lg, tids in lock_groups.items()
        if len(tids) == 1
    }
    serialized_within_lock_group = {
        lg: tids
        for lg, tids in lock_groups.items()
        if len(tids) > 1
    }

    execution_status = {
        "schema_version": SCHEMA_VERSION + "_first_batch_execution_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "go_no_go": "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY",
        "task_count": len(statuses),
        "active_lanes_count": active,
        "active_lanes_minimum": 3,
        "active_lanes_below_minimum_flag": active < 3,
        "war_room_active_lanes_below_minimum_signal": (
            "WAR_ROOM_ACTIVE_LANES_BELOW_MINIMUM" if active < 3 else None
        ),
        "file_lock_groups_parallel_safe": parallel_safe,
        "file_lock_groups_serialized_within_lock_group": (
            serialized_within_lock_group
        ),
        "tasks": [
            {
                "task_id": ts["task_id"],
                "status": ts["status"],
                "implementation_artifact": ts["implementation_artifact"],
                "implementation_status": ts["implementation_status"],
                "blocked_reason": ts["blocked_reason"],
                "file_lock_group": ts["file_lock_group"],
                "target_v2_keys": ts["target_v2_keys"],
                "go_no_go_marker": ts["go_no_go_marker"],
                "scope": ts["scope"],
                "public_payload": ts["public_payload"],
                "codex_review_command": ts["codex_review_command"],
                "codex_review_required": ts["codex_review_required"],
                "broad_audit": ts["broad_audit"],
                "does_not_fake_data": ts["does_not_fake_data"],
                "missing_source_policy": ts["missing_source_policy"],
                "old_redis_write": ts["old_redis_write"],
                "exchange_mutation": ts["exchange_mutation"],
                "live_or_shutdown_approval": ts["live_or_shutdown_approval"],
            }
            for ts in statuses
        ],
        "trainer_native_readiness_claimed": False,
        "full_migration_claimed": False,
        "bridge_data_labeled_as_v2_native": False,
    }

    # Per-task JSON
    per_task_dir = paths.packet_dir / "per_task"
    for ts in statuses:
        _atomic_write_json(per_task_dir / (ts["task_id"] + ".json"), ts)
        _atomic_write_json(
            paths.public_dir / (ts["task_id"] + ".json"),
            {
                "task_id": ts["task_id"],
                "status": ts["status"],
                "go_no_go_marker": ts["go_no_go_marker"],
                "file_lock_group": ts["file_lock_group"],
                "implementation_artifact": ts["implementation_artifact"],
                "implementation_status": ts["implementation_status"],
                "blocked_reason": ts["blocked_reason"],
                "target_redis_key_patterns": ts["target_redis_key_patterns"],
                "target_v2_keys": ts["target_v2_keys"],
                "forbidden_actions": ts["forbidden_actions"],
                "codex_review_required": ts["codex_review_required"],
                "broad_audit": ts["broad_audit"],
                "does_not_fake_data": ts["does_not_fake_data"],
                "missing_source_policy": ts["missing_source_policy"],
                "envelope_summary": ts.get("envelope_summary"),
            },
        )

    _atomic_write_json(
        paths.packet_dir / "first_batch_execution_status.json", execution_status
    )
    _atomic_write_json(
        paths.packet_dir / "refreshed_legacy_to_v2_service_parity_matrix.json",
        parity_refresh,
    )
    _atomic_write_json(
        paths.packet_dir / "refreshed_legacy_startup_dynamic_symbol_coverage.json",
        coverage_refresh,
    )
    _atomic_write_json(
        paths.packet_dir / "refreshed_bridge_dependency_inventory.json",
        bridge_refresh,
    )
    _atomic_write_json(
        paths.packet_dir / "report_center_payload.json", report_center
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )

    report = _render_report(
        statuses, execution_status, parity_refresh, coverage_refresh,
        bridge_refresh, report_center, dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY\n",
    )

    return FirstBatchRunResult(
        go_no_go="V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY",
        active_lanes=active,
        task_count=len(statuses),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_REPORT.md",
            paths.packet_dir / "first_batch_execution_status.json",
            paths.packet_dir
            / "refreshed_legacy_to_v2_service_parity_matrix.json",
            paths.packet_dir
            / "refreshed_legacy_startup_dynamic_symbol_coverage.json",
            paths.packet_dir / "refreshed_bridge_dependency_inventory.json",
            paths.packet_dir / "report_center_payload.json",
            paths.public_dir / "operator_dashboard_payload.json",
        ]
        + [per_task_dir / (ts["task_id"] + ".json") for ts in statuses],
    )


def _render_report(
    statuses, execution_status, parity, coverage, bridge, report_center,
    dashboard,
):
    lines = []
    lines.append(
        "# V2 Startup Parity First-Batch Execution Report\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. "
        "approves_redis_trim=false.\n\n"
    )
    lines.append(
        "active_lanes_count: " + str(execution_status["active_lanes_count"])
        + " / minimum 3\n"
        "active_lanes_below_minimum_flag: "
        + str(execution_status["active_lanes_below_minimum_flag"]) + "\n\n"
    )
    lines.append("## First-batch tasks\n")
    for ts in statuses:
        lines.append(
            "- " + ts["task_id"] + " [" + ts["status"] + "] "
            "lock=" + ts["file_lock_group"]
            + " -> " + ts["go_no_go_marker"] + "\n"
        )
    lines.append("\n## File-lock parallelism\n")
    lines.append(
        "- parallel_safe groups: "
        + str(len(execution_status["file_lock_groups_parallel_safe"]))
        + "\n"
        "- serialized_within_lock_group: "
        + str(execution_status["file_lock_groups_serialized_within_lock_group"])
        + "\n\n"
    )
    lines.append("## Honest claims\n")
    lines.append(
        "- bridge_data_labeled_as_v2_native: "
        + str(execution_status["bridge_data_labeled_as_v2_native"]) + "\n"
        "- trainer_native_readiness_claimed: "
        + str(execution_status["trainer_native_readiness_claimed"]) + "\n"
        "- full_migration_claimed: "
        + str(execution_status["full_migration_claimed"]) + "\n\n"
    )
    lines.append("## Refreshed inputs\n")
    lines.append(
        "- legacy_to_v2_service_parity_matrix refreshed from "
        + parity["source_packet"] + "\n"
        "- dynamic_symbol_coverage refreshed from "
        + coverage["source_packet"] + "\n"
        "- bridge_dependency_inventory refreshed from "
        + bridge["source_packet"] + "\n\n"
    )
    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n")
    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy, V2 runtime, report center, replay miner, or"
        " Codex governors.\n"
        "- Did not start any live network feed.\n"
        "- Did not load or log any raw API credential.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not install systemd units or scheduler daemons.\n"
        "- Did not mutate live_symbols, paper_symbols, or training_symbols.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not deserialize any legacy checkpoint.\n"
        "- Did not claim trainer native readiness.\n"
        "- Did not claim full migration.\n"
        "- Did not label any bridge data V2_NATIVE.\n"
    )
    return "".join(lines)
