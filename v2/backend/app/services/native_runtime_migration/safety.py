"""Shared safety pins for the V2 native-runtime migration first-batch.

Every per-task status block and every emitted artifact in this packet
carries the same negative safety claims, so a Codex scan can verify the
batch against a single contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


LIVE_GATE_BLOCKED = "blocked_human_only"

KNOWN_UNIVERSE = (
    "1000BONKUSDT",
    "1000FLOKIUSDT",
    "1000PEPEUSDT",
    "1000SHIBUSDT",
    "ALICEUSDT",
    "ASTERUSDT",
    "AUCTIONUSDT",
    "AVNTUSDT",
    "BANKUSDT",
    "BARDUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "FARTCOINUSDT",
    "HIGHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "PENGUUSDT",
    "PIPPINUSDT",
    "RAVEUSDT",
    "RIVERUSDT",
    "SOLUSDT",
    "UNIUSDT",
    "WIFUSDT",
    "XRPUSDT",
)

# Historical 3-symbol initial bridge-migration set.
# This is NOT a production "currently active" symbol set — it documents the
# first 3 symbols that were lifted out of legacy raw-Redis into V2 native
# Redis (v2:* namespace) during the migration's initial batch. Callers that
# need the CURRENT live runtime symbol universe must use
# :func:`v2.backend.app.services.v2_symbol_runtime_universe.resolve_symbols`.
V2_NATIVE_INITIAL_BRIDGE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# Backwards-compatible alias retained so prior tests / callers keep working.
# Do NOT use this name in newly emitted payloads — emit
# `currently_active_symbols` from the dynamic universe resolver instead.
V2_NATIVE_ACTIVE_SYMBOLS = V2_NATIVE_INITIAL_BRIDGE_SYMBOLS


def v2_native_currently_active_symbols() -> tuple[str, ...]:
    """Return the CURRENT V2 native runtime symbol set.

    Resolves through the dynamic universe resolver so emitted payloads no
    longer pin a 3-symbol smoke-test set as "currently active". Operators
    must opt into the smoke-test 3 via ``V2_SYMBOL_PROFILE=smoke_test``.
    """
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    return tuple(resolve_symbols(smoke_test=False, include_baseline=True))


_SAFETY_PINS = {
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
    "did_not_change_leverage_or_margin_mode": True,
    "did_not_create_paper_only_shutdown_acceptance_file": True,
    "did_not_weaken_paper_fill_gate": True,
    "did_not_deserialize_legacy_checkpoint": True,
    "did_not_install_systemd_units_or_scheduler_daemons": True,
    "did_not_start_live_network_feed": True,
    "did_not_mutate_live_symbols_paper_symbols_or_training_symbols": True,
    "did_not_adopt_any_symbol_universe_candidate": True,
    "did_not_expose_raw_api_keys": True,
    "did_not_claim_trainer_native_readiness": True,
    "did_not_claim_full_migration": True,
}


def safety_block() -> dict[str, Any]:
    return dict(_SAFETY_PINS)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
