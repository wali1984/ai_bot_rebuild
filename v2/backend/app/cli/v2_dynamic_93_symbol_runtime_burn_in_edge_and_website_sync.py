"""V2 dynamic 93-symbol burn-in, edge, provider, and website-sync gate.

This packet is a read-only aggregator over the V2 dynamic runtime. It checks
the expanded symbol universe, per-symbol data freshness, trainer quality,
post-hoc replay/edge evidence, provider blockers, website wiring, and live
readiness blockers. It never writes Redis, never calls an exchange endpoint,
and never emits live/canary approval.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.v2_symbol_runtime_universe import BASELINE_25_SYMBOLS


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
LANE_ID = "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync"

GO_NO_GO_READY = "V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_READY"
GO_NO_GO_BLOCKED = "V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_BLOCKED"

TARGET_DYNAMIC_SYMBOL_COUNT = 93
TIMEFRAME = "1m"
EASTERN = ZoneInfo("America/New_York")

FRESHNESS_LIMITS_SECONDS = {
    "market": 15 * 60,
    "feature": 15 * 60,
    "ta": 30 * 60,
    "prediction": 30 * 60,
    "candidate": 30 * 60,
    "trainer": 60 * 60,
    "provider": 6 * 60 * 60,
    "edge": 30 * 60,
    "website": 6 * 60 * 60,
}


@dataclass(frozen=True)
class PacketPaths:
    worklog_dir: Path
    public_dir: Path
    operator_runtime_dir: Path


def default_paths(repo_root: Path = REPO_ROOT) -> PacketPaths:
    return PacketPaths(
        worklog_dir=repo_root / "claude_worklog" / "final_readiness" / LANE_ID / "latest",
        public_dir=repo_root / "v2" / "frontend" / "public" / LANE_ID / "latest",
        operator_runtime_dir=repo_root
        / "v2"
        / "frontend"
        / "public"
        / "operator_runtime"
        / LANE_ID
        / "latest",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso(dt: datetime) -> str:
    return dt.astimezone(EASTERN).isoformat(timespec="seconds")


def _generated_block(now: datetime) -> dict[str, str]:
    return {
        "generated_at": _est_iso(now),
        "generated_est": _est_iso(now),
        "generated_utc": _utc_iso(now),
        "timezone": "America/New_York",
    }


def _safety_block() -> dict[str, Any]:
    return {
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "trade_all_discovered_symbols": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "places_real_order": False,
        "calls_exchange_mutation": False,
        "calls_test_order_endpoint": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "raw_credential_value_exposed": False,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _connect_redis() -> Any | None:  # pragma: no cover - exercised in runtime path
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _redis_get_json(redis_client: Any | None, key: str) -> Any | None:
    if redis_client is None or not key.startswith("v2:"):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _timestamp_from_payload(payload: Any) -> datetime | None:
    if not isinstance(payload, Mapping):
        return None
    for key in (
        "generated_utc",
        "generated_at",
        "generated_est",
        "fetched_utc",
        "last_seen_utc",
        "current_price_source_utc",
        "last_run_ts",
    ):
        dt = _parse_dt(payload.get(key))
        if dt is not None:
            return dt
    return None


def _age_seconds(payload: Any, *, now: datetime) -> int | None:
    ts = _timestamp_from_payload(payload)
    if ts is None:
        return None
    return max(0, int((now - ts).total_seconds()))


def _freshness(payload: Any, *, now: datetime, limit_seconds: int) -> dict[str, Any]:
    if payload is None:
        return {"state": "MISSING_SOURCE", "age_seconds": None, "limit_seconds": limit_seconds}
    age = _age_seconds(payload, now=now)
    if age is None:
        return {"state": "TIMESTAMP_MISSING", "age_seconds": None, "limit_seconds": limit_seconds}
    return {
        "state": "FRESH" if age <= limit_seconds else "STALE",
        "age_seconds": age,
        "limit_seconds": limit_seconds,
    }


def _as_symbol_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        sym = item.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _resolve_runtime_symbols(repo_root: Path) -> tuple[list[str], dict[str, Any]]:
    symbol_payload_path = (
        repo_root
        / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
    )
    payload = _read_json(symbol_payload_path)
    if isinstance(payload, Mapping):
        for key in (
            "training_symbols",
            "paper_symbols",
            "live_data_symbols",
            "trainer_live_symbols",
            "paper_shadow_live_symbols",
            "discovered_symbols",
            "dynamic_discovered_symbols",
            "observed_symbols",
        ):
            symbols = _as_symbol_list(payload.get(key))
            if symbols:
                return symbols, {
                    "source_path": str(symbol_payload_path),
                    "source_field": key,
                    "source_status": "PUBLIC_SYMBOL_UNIVERSE_PAYLOAD",
                    "source_generated_at": payload.get("generated_at") or payload.get("generated_utc"),
                }
    return list(BASELINE_25_SYMBOLS), {
        "source_path": str(symbol_payload_path),
        "source_field": "BASELINE_25_SYMBOLS",
        "source_status": "FALLBACK_BASELINE_25",
        "source_generated_at": None,
    }


def _load_public_payloads(repo_root: Path) -> dict[str, Any]:
    public = repo_root / "v2/frontend/public"
    paths = {
        "symbol_universe": public / "operator_runtime/symbol_universe/latest/symbol_universe_status.json",
        "dynamic_discovery": public
        / "operator_runtime/v2_dynamic_symbol_discovery/latest/dynamic_symbol_discovery_status.json",
        "candidate_publisher": public
        / "operator_runtime/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json",
        "altdata_scoring": public
        / "operator_runtime/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json",
        "trainer_live_loop": public
        / "operator_runtime/v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json",
        "native_trainer_dataset": public
        / "v2_native_trainer_dataset_and_baseline_model/latest/operator_dashboard_payload.json",
        "post_hoc_replay": public
        / "v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json",
        "post_hoc_dashboard": public
        / "v2_post_hoc_replay_outcome_miner/latest/operator_dashboard_payload.json",
        "post_hoc_edge_metrics": public
        / "v2_post_hoc_replay_outcome_miner/latest/edge_metrics_summary.json",
        "native_edge_dashboard": public / "v2_native_edge_proof/latest/operator_dashboard_payload.json",
        "website_alignment": public
        / "v2_website_data_alignment_and_control_plane/latest/operator_dashboard_payload.json",
        "nansen": public
        / "operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json",
        "lunarcrush": public
        / "operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json",
        "coinapi_rest": public
        / "operator_runtime/v2_coinapi_rest_ingestor/latest/v2_coinapi_rest_ingestor_status.json",
        "coinapi_wsds": public
        / "operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json",
        "kucoin": public
        / "operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json",
        "coinank": public
        / "operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",
    }
    return {name: {"path": str(path), "payload": _read_json(path)} for name, path in paths.items()}


def _candidate_map(candidate_payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(candidate_payload, Mapping):
        return {}
    rows = candidate_payload.get("candidates")
    if not isinstance(rows, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            sym = str(row.get("symbol") or "").strip().upper()
            if sym:
                mapped[sym] = dict(row)
    return mapped


def _counter_increment(counter: Counter[str], value: Any, fallback: str = "UNKNOWN") -> None:
    text = str(value or fallback)
    counter[text] += 1


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    nums = sorted(v for v in (_number(value) for value in values) if v is not None)
    if not nums:
        return {"count": 0, "min": None, "p50": None, "p90": None, "max": None, "mean": None}
    p50 = nums[len(nums) // 2]
    p90 = nums[min(len(nums) - 1, int((len(nums) - 1) * 0.9))]
    return {
        "count": len(nums),
        "min": nums[0],
        "p50": p50,
        "p90": p90,
        "max": nums[-1],
        "mean": statistics.fmean(nums),
    }


def _input_presence(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, Mapping):
        return {}
    presence = payload.get("input_presence")
    if isinstance(presence, Mapping):
        return {str(k): bool(v) for k, v in presence.items()}
    return {}


def _nested_mapping(payload: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_number(*values: Any) -> int | None:
    nums: list[int] = []
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, list):
            nums.append(len(value))
            continue
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            nums.append(number)
    return max(nums) if nums else None


def _provider_status(provider: str, payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    source_counts = payload.get("source_status_counts")
    if isinstance(source_counts, Mapping) and source_counts:
        return ",".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))
    status = _first_text(
        payload.get("classification"),
        payload.get("status"),
        payload.get("source_status"),
        payload.get("go_no_go"),
    )
    if status:
        return status
    if provider == "coinank" and isinstance(payload.get("global_aggregate_result"), Mapping):
        blockers = payload.get("missing_api_blockers")
        return "V2_COINANK_GLOBAL_AGGREGATE_PARTIAL" if blockers else "V2_COINANK_GLOBAL_AGGREGATE_OK"
    return _first_text(payload.get("source"), payload.get("current_gate_state"))


def _provider_symbol_count(provider: str, payload: Any) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    fetch = _nested_mapping(payload, "fetch")
    public_rest_fetch = _nested_mapping(payload, "public_rest_fetch")
    feature_input = _nested_mapping(payload, "v2_redis_feature_input")
    aggregate = _nested_mapping(payload, "global_aggregate_result")
    return _first_number(
        payload.get("symbol_count"),
        payload.get("symbols_count"),
        payload.get("symbols"),
        payload.get("symbols_v2"),
        fetch.get("symbols_requested"),
        fetch.get("symbols_fetched"),
        public_rest_fetch.get("symbols_requested"),
        public_rest_fetch.get("symbols_fetched"),
        feature_input.get("symbols_requested"),
        feature_input.get("symbols_with_any_input"),
        aggregate.get("n_symbols_observed"),
    )


def _provider_successful_symbol_count(provider: str, payload: Any) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    explicit_success = _first_number(payload.get("successful_symbol_count"))
    if explicit_success is not None:
        return explicit_success
    fetch = _nested_mapping(payload, "fetch")
    public_rest_fetch = _nested_mapping(payload, "public_rest_fetch")
    feature_input = _nested_mapping(payload, "v2_redis_feature_input")
    aggregate = _nested_mapping(payload, "global_aggregate_result")
    if provider == "coinapi_rest":
        return _first_number(payload.get("orderbooks_present_count"), fetch.get("symbols_fetched"))
    if provider == "coinapi_wsds":
        return _first_number(payload.get("symbols_count"), payload.get("symbols"))
    if provider == "coinank":
        return _first_number(feature_input.get("symbols_with_any_input"), aggregate.get("n_symbols_observed"))
    if provider == "kucoin":
        return _first_number(public_rest_fetch.get("symbols_fetched"), payload.get("symbols_v2"))
    return None


def _provider_write_count(payload: Any) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    stats = _nested_mapping(payload, "stats")
    aggregate = _nested_mapping(payload, "global_aggregate_result")
    return _first_number(
        payload.get("v2_redis_keys_written_count"),
        payload.get("v2_redis_global_keys_written_count"),
        payload.get("v2_redis_keys_written"),
        payload.get("v2_redis_global_keys_written"),
        stats.get("snapshots_written"),
        stats.get("microfeatures_written"),
        aggregate.get("v2_keys_written"),
    )


def _symbol_in_public_provider(symbol: str, provider: str, payload: Any, redis_client: Any | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    symbols = set(_as_symbol_list(payload.get("symbols")))
    symbols.update(_as_symbol_list(payload.get("symbols_v2")))
    if symbol in symbols:
        return True
    if provider == "coinank":
        feature_input = _nested_mapping(payload, "v2_redis_feature_input")
        if symbol in _as_symbol_list(payload.get("symbols")) and _number(feature_input.get("symbols_with_any_input")):
            return True
    redis_keys = {
        "kucoin": [
            f"v2:market:kucoin:latest:{symbol}",
            f"v2:market:kucoin:funding:{symbol}",
            f"v2:features:kucoin:{symbol}:latest",
        ],
        "coinapi_rest": [
            f"v2:market:coinapi:rest:status:{symbol}",
            f"v2:market:coinapi:rest:orderbook:{symbol}",
            f"v2:features:coinapi_rest:{symbol}:latest",
        ],
        "coinapi_wsds": [
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:1m",
        ],
    }.get(provider, [])
    if redis_client is None:
        return False
    for key in redis_keys:
        try:
            if bool(redis_client.exists(key)):
                return True
        except Exception:
            continue
    return False


def _current_provider_presence(
    *,
    symbol: str,
    public_payloads: Mapping[str, Any],
    redis_client: Any | None,
) -> dict[str, bool]:
    provider_payloads = {
        "kucoin": public_payloads["kucoin"]["payload"],
        "coinapi_rest": public_payloads["coinapi_rest"]["payload"],
        "coinapi_wsds": public_payloads["coinapi_wsds"]["payload"],
        "coinank": public_payloads["coinank"]["payload"],
    }
    return {
        provider: _symbol_in_public_provider(symbol, provider, payload, redis_client)
        for provider, payload in provider_payloads.items()
    }


def build_runtime_burn_in_status(
    *,
    repo_root: Path,
    symbols: list[str],
    symbol_provenance: Mapping[str, Any],
    public_payloads: Mapping[str, Any],
    redis_client: Any | None,
    now: datetime,
) -> dict[str, Any]:
    candidate_payload = public_payloads["candidate_publisher"]["payload"]
    candidates = _candidate_map(candidate_payload)
    symbol_universe = public_payloads["symbol_universe"]["payload"]
    split_counts = {
        "discovered_symbols": len(_as_symbol_list((symbol_universe or {}).get("discovered_symbols"))),
        "training_symbols": len(_as_symbol_list((symbol_universe or {}).get("training_symbols"))),
        "paper_symbols": len(_as_symbol_list((symbol_universe or {}).get("paper_symbols"))),
        "live_data_symbols": len(_as_symbol_list((symbol_universe or {}).get("live_data_symbols"))),
        "live_symbols": len(_as_symbol_list((symbol_universe or {}).get("live_symbols"))),
        "execution_live_symbols": len(_as_symbol_list((symbol_universe or {}).get("execution_live_symbols"))),
    }

    per_symbol_rows: list[dict[str, Any]] = []
    freshness_counts: dict[str, Counter[str]] = {
        "market": Counter(),
        "feature": Counter(),
        "ta": Counter(),
        "prediction": Counter(),
    }
    provider_presence_counts: Counter[str] = Counter()
    blocked_reason_counts: Counter[str] = Counter()
    candidate_state_counts: Counter[str] = Counter()

    redis_available = redis_client is not None
    for symbol in symbols:
        market = _redis_get_json(redis_client, f"v2:market:prices:{symbol}")
        feature = _redis_get_json(redis_client, f"v2:features:latest:{symbol}:{TIMEFRAME}")
        ta = _redis_get_json(redis_client, f"v2:features:ta:{symbol}:{TIMEFRAME}")
        prediction = _redis_get_json(redis_client, f"v2:prediction:{symbol}:{TIMEFRAME}")
        altdata = _redis_get_json(redis_client, f"v2:altdata:symbol_score:{symbol}")
        paper_history = _redis_get_json(redis_client, f"v2:paper:position_history:{symbol}")
        shadow_outcome = _redis_get_json(redis_client, f"v2:paper:shadow_outcome:{symbol}")
        candidate = candidates.get(symbol, {})

        market_freshness = _freshness(market, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["market"])
        feature_freshness = _freshness(feature, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["feature"])
        ta_freshness = _freshness(ta, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["ta"])
        prediction_freshness = _freshness(
            prediction, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["prediction"]
        )
        for name, value in (
            ("market", market_freshness),
            ("feature", feature_freshness),
            ("ta", ta_freshness),
            ("prediction", prediction_freshness),
        ):
            freshness_counts[name][value["state"]] += 1

        candidate_state = str(candidate.get("candidate_state") or "MISSING_CANDIDATE_ROW")
        candidate_state_counts[candidate_state] += 1

        provider_presence = _input_presence(altdata)
        provider_presence.update(
            _current_provider_presence(
                symbol=symbol,
                public_payloads=public_payloads,
                redis_client=redis_client,
            )
        )
        for provider, present in provider_presence.items():
            if present:
                provider_presence_counts[provider] += 1

        blocked_reasons: list[str] = []
        if market_freshness["state"] != "FRESH":
            blocked_reasons.append(f"MARKET_{market_freshness['state']}")
        if feature_freshness["state"] != "FRESH":
            blocked_reasons.append(f"FEATURE_{feature_freshness['state']}")
        if ta_freshness["state"] != "FRESH":
            blocked_reasons.append(f"TA_{ta_freshness['state']}")
        if prediction_freshness["state"] != "FRESH":
            blocked_reasons.append(f"PREDICTION_{prediction_freshness['state']}")
        for reason in candidate.get("missing_provider_flags") or []:
            blocked_reasons.append(str(reason))
        for reason in candidate.get("blocked_reasons") or []:
            blocked_reasons.append(str(reason))
        for reason in (prediction or {}).get("paper_fill_gate_block_reasons") or []:
            blocked_reasons.append(str(reason))
        paper_reason = (shadow_outcome or {}).get("block_reason")
        if isinstance(paper_reason, str) and paper_reason:
            blocked_reasons.extend([r for r in paper_reason.split(";") if r])
        for reason in blocked_reasons:
            blocked_reason_counts[reason] += 1

        per_symbol_rows.append(
            {
                "symbol": symbol,
                "market": market_freshness,
                "feature": feature_freshness,
                "ta": ta_freshness,
                "prediction": prediction_freshness,
                "candidate_state": candidate_state,
                "candidate_reason": candidate.get("candidate_reason"),
                "paper_symbol_state": {
                    "position_state": (paper_history or {}).get("position_state"),
                    "accepted_intent_count": (paper_history or {}).get("accepted_intent_count"),
                    "held_intent_count": (paper_history or {}).get("held_intent_count"),
                    "shadow_decision_label": (shadow_outcome or {}).get("decision_label"),
                    "paper_fill_gate_status": (prediction or {}).get("paper_fill_gate_status"),
                    "paper_fill_allowed": (prediction or {}).get("paper_fill_allowed"),
                },
                "provider_contribution": provider_presence,
                "blocked_reasons": sorted(set(blocked_reasons)),
            }
        )

    return {
        "schema_version": "v2_dynamic_93_symbol_runtime_burn_in_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "runtime_status": (
            "BURN_IN_OBSERVED_DYNAMIC_93"
            if len(symbols) == TARGET_DYNAMIC_SYMBOL_COUNT
            else "BURN_IN_BLOCKED_SYMBOL_COUNT_NOT_93"
        ),
        "target_symbol_count": TARGET_DYNAMIC_SYMBOL_COUNT,
        "symbol_count": len(symbols),
        "three_symbol_default_returned": symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "symbol_provenance": dict(symbol_provenance),
        "symbol_split_counts": split_counts,
        "redis_available": redis_available,
        "freshness_limits_seconds": FRESHNESS_LIMITS_SECONDS,
        "freshness_counts": {k: dict(v) for k, v in freshness_counts.items()},
        "candidate_count": len(candidates),
        "candidate_state_counts": dict(candidate_state_counts),
        "provider_presence_counts": dict(provider_presence_counts),
        "blocked_reason_counts": dict(blocked_reason_counts),
        "symbols": symbols,
        "per_symbol_rows": per_symbol_rows,
    }


def build_trainer_quality_status(
    *,
    symbols: list[str],
    public_payloads: Mapping[str, Any],
    redis_client: Any | None,
    now: datetime,
) -> dict[str, Any]:
    trainer_status = public_payloads["trainer_live_loop"]["payload"]
    trainer_freshness = _freshness(
        trainer_status, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["trainer"]
    )

    trainer_source_distribution: Counter[str] = Counter()
    model_source_distribution: Counter[str] = Counter()
    checkpoint_blocker_distribution: Counter[str] = Counter()
    real_feature_count = 0
    missing_feature_count = 0
    stale_feature_count = 0
    confidences: list[Any] = []
    expected_moves_after_cost: list[Any] = []

    for symbol in symbols:
        feature = _redis_get_json(redis_client, f"v2:features:latest:{symbol}:{TIMEFRAME}")
        prediction = _redis_get_json(redis_client, f"v2:prediction:{symbol}:{TIMEFRAME}")
        if isinstance(feature, Mapping):
            real_feature_count += int(feature.get("real_feature_count") or 0)
            missing_feature_count += int(feature.get("missing_feature_count") or 0)
            stale_flags = feature.get("stale_feature_flags") or []
            if isinstance(stale_flags, list):
                stale_feature_count += len(stale_flags)
        if isinstance(prediction, Mapping):
            _counter_increment(trainer_source_distribution, prediction.get("trainer_source"))
            _counter_increment(
                model_source_distribution,
                prediction.get("trainer_online_mode") or prediction.get("checkpoint_id"),
            )
            _counter_increment(checkpoint_blocker_distribution, prediction.get("checkpoint_blocker"))
            confidences.append(prediction.get("confidence_calibrated"))
            expected_moves_after_cost.append(prediction.get("expected_move_after_cost_bps"))

    return {
        "schema_version": "v2_dynamic_93_trainer_quality_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "trainer_status_freshness": trainer_freshness,
        "classification": (trainer_status or {}).get("classification"),
        "row_count": (trainer_status or {}).get("row_count"),
        "train_rows": (trainer_status or {}).get("train_rows"),
        "validation_rows": (trainer_status or {}).get("validation_rows"),
        "trained_model_available": bool((trainer_status or {}).get("trained_model_available")),
        "symbol_count": len(symbols),
        "real_feature_count": real_feature_count,
        "missing_feature_count": missing_feature_count,
        "stale_feature_count": stale_feature_count,
        "trainer_source_distribution": dict(trainer_source_distribution),
        "model_source_distribution": dict(model_source_distribution),
        "checkpoint_blocker_distribution": dict(checkpoint_blocker_distribution),
        "confidence_distribution": _distribution(confidences),
        "expected_move_after_cost_distribution_bps": _distribution(expected_moves_after_cost),
    }


def _load_replay_rows(path: Path, symbols: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows, {"path": str(path), "status": "MISSING_REPLAY_BUNDLE_FILE"}
    errors = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                errors += 1
                continue
            if not isinstance(payload, dict):
                continue
            symbol = str(payload.get("symbol") or "").upper()
            if symbol in symbols:
                rows.append(payload)
    return rows, {"path": str(path), "status": "OK", "json_error_count": errors}


def _aggregate_replay_by_symbol(replay_rows: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {
        symbol: {
            "symbol": symbol,
            "bundle_count": 0,
            "after_cost_5m_sample_count": 0,
            "after_cost_5m_values": [],
            "label_counts": Counter(),
            "risk_block_reason_counts": Counter(),
        }
        for symbol in symbols
    }
    for row in replay_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in aggregates:
            continue
        agg = aggregates[symbol]
        agg["bundle_count"] += 1
        label = str(row.get("label") or "unknown")
        agg["label_counts"][label] += 1
        five_min = ((row.get("future_outcomes") or {}).get("5m") or {})
        after_cost = _number(five_min.get("after_cost_return_bps"))
        if after_cost is not None:
            agg["after_cost_5m_sample_count"] += 1
            agg["after_cost_5m_values"].append(after_cost)
        gate = row.get("paper_gate_decision") or {}
        for reason in gate.get("paper_fill_gate_block_reasons") or []:
            agg["risk_block_reason_counts"][str(reason)] += 1
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        agg = aggregates[symbol]
        values = agg.pop("after_cost_5m_values")
        out.append(
            {
                **agg,
                "mean_after_cost_5m_bps": statistics.fmean(values) if values else None,
                "label_counts": dict(agg["label_counts"]),
                "risk_block_reason_counts": dict(agg["risk_block_reason_counts"]),
            }
        )
    return out


def build_edge_recompute_status(
    *,
    repo_root: Path,
    symbols: list[str],
    public_payloads: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    post_hoc = public_payloads["post_hoc_replay"]["payload"]
    native_edge = public_payloads["native_edge_dashboard"]["payload"]
    post_hoc_freshness = _freshness(post_hoc, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["edge"])
    native_edge_freshness = _freshness(
        native_edge, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["edge"]
    )
    metric_summary = (
        (post_hoc or {}).get("evaluator_metric_summary")
        or (public_payloads["post_hoc_edge_metrics"]["payload"] or {}).get("metric_summary")
        or {}
    )
    replay_rows, replay_file_status = _load_replay_rows(
        repo_root
        / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl",
        set(symbols),
    )
    by_symbol = _aggregate_replay_by_symbol(replay_rows, symbols)
    bundle_counts = sorted((row["bundle_count"] for row in by_symbol), reverse=True)
    top5_bundle_count = sum(bundle_counts[:5])
    total_bundle_count = sum(bundle_counts)
    after_cost = _number(metric_summary.get("after_cost_pnl_delta"))
    ci_lower = _number(metric_summary.get("after_cost_ci_lower_bps"))
    verdict = str(metric_summary.get("verdict") or (post_hoc or {}).get("verdict") or "MISSING_EDGE_VERDICT")
    edge_proven = verdict == "EDGE_CLAIMED" and after_cost is not None and after_cost > 0 and ci_lower is not None and ci_lower > 0

    return {
        "schema_version": "v2_dynamic_93_edge_recompute_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "edge_recompute_status": "EDGE_PROVEN" if edge_proven else "EDGE_NOT_PROVEN",
        "edge_proven": edge_proven,
        "primary_blocker": None if edge_proven else "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "post_hoc_replay_freshness": post_hoc_freshness,
        "native_edge_dashboard_freshness": native_edge_freshness,
        "native_edge_dashboard_sample_count": (native_edge or {}).get("sample_count"),
        "dynamic_symbols_in_post_hoc_status": len(_as_symbol_list((post_hoc or {}).get("symbols"))),
        "symbols_evaluated": len(symbols),
        "bundles_total": (post_hoc or {}).get("bundles_total") or len(replay_rows),
        "label_counts": (post_hoc or {}).get("label_counts") or {},
        "windows_filled": (post_hoc or {}).get("windows_filled") or {},
        "verdict": verdict,
        "verdict_reason": metric_summary.get("verdict_reason") or (post_hoc or {}).get("verdict_reason"),
        "after_cost_expectancy_bps": after_cost,
        "after_cost_ci_lower_bps": ci_lower,
        "after_cost_ci_upper_bps": metric_summary.get("after_cost_ci_upper_bps"),
        "false_positive_rate": metric_summary.get("false_positive_rate"),
        "false_negative_rate": metric_summary.get("false_negative_rate"),
        "false_positive_count": ((post_hoc or {}).get("label_counts") or {}).get("false_positive"),
        "false_negative_count": ((post_hoc or {}).get("label_counts") or {}).get("false_negative"),
        "trainer_vs_strategy_comparison": {
            "v2_vs_legacy_action_match_rate": metric_summary.get("v2_vs_legacy_action_match_rate"),
            "v2_hold_due_checkpoint_count": metric_summary.get("v2_hold_due_checkpoint_count"),
            "v2_hold_due_strict_gate_count": metric_summary.get("v2_hold_due_strict_gate_count"),
        },
        "opportunity_concentration": {
            "bundle_count_total": total_bundle_count,
            "top5_symbol_bundle_count": top5_bundle_count,
            "top5_symbol_bundle_share": (
                round(top5_bundle_count / total_bundle_count, 6) if total_bundle_count else None
            ),
        },
        "replay_bundle_file_status": replay_file_status,
        "by_symbol_pnl": by_symbol,
    }


def _provider_row(provider: str, payload: Any, now: datetime) -> dict[str, Any]:
    source_counts = (payload or {}).get("source_status_counts") if isinstance(payload, Mapping) else None
    stats = _nested_mapping(payload, "stats")
    fetch = _nested_mapping(payload, "fetch")
    public_rest_fetch = _nested_mapping(payload, "public_rest_fetch")
    feature_input = _nested_mapping(payload, "v2_redis_feature_input")
    return {
        "provider": provider,
        "freshness": _freshness(payload, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["provider"]),
        "status": _provider_status(provider, payload) or "MISSING_PROVIDER_STATUS",
        "source_status_counts": dict(source_counts) if isinstance(source_counts, Mapping) else {},
        "successful_symbol_count": _provider_successful_symbol_count(provider, payload),
        "symbol_count": _provider_symbol_count(provider, payload),
        "keys_written_count": _provider_write_count(payload),
        "orderbooks_present_count": (payload or {}).get("orderbooks_present_count") if isinstance(payload, Mapping) else None,
        "ohlcv_present_count": (payload or {}).get("ohlcv_present_count") if isinstance(payload, Mapping) else None,
        "symbols_fetched": _first_number(fetch.get("symbols_fetched"), public_rest_fetch.get("symbols_fetched")),
        "symbols_with_any_input": _first_number(feature_input.get("symbols_with_any_input")),
        "messages_received": _first_number(stats.get("messages_received")),
        "snapshots_written": _first_number(stats.get("snapshots_written")),
        "microfeatures_written": _first_number(stats.get("microfeatures_written")),
        "stream_connected": (payload or {}).get("stream_connected") if isinstance(payload, Mapping) else None,
        "redis_ok": (payload or {}).get("redis_ok") if isinstance(payload, Mapping) else None,
        "blocked_reason": (payload or {}).get("blocked_reason") if isinstance(payload, Mapping) else None,
        "missing_api_blockers": (payload or {}).get("missing_api_blockers") if isinstance(payload, Mapping) else None,
        "network_call_attempted": (payload or {}).get("network_call_attempted") if isinstance(payload, Mapping) else None,
        "key_present": (payload or {}).get("key_present") if isinstance(payload, Mapping) else None,
        "raw_credential_value_exposed": bool((payload or {}).get("raw_credential_value_exposed") or False)
        if isinstance(payload, Mapping)
        else False,
        "writes_legacy_redis": bool((payload or {}).get("writes_legacy_redis") or False)
        if isinstance(payload, Mapping)
        else False,
        "writes_exchange_orders": bool((payload or {}).get("writes_exchange_orders") or False)
        if isinstance(payload, Mapping)
        else False,
    }


def build_provider_contribution_status(
    *,
    symbols: list[str],
    public_payloads: Mapping[str, Any],
    redis_client: Any | None,
    now: datetime,
) -> dict[str, Any]:
    dynamic_discovery = public_payloads["dynamic_discovery"]["payload"]
    provider_payloads = {
        "coingecko": _redis_get_json(redis_client, "v2:altdata:coingecko:status")
        or (dynamic_discovery or {}).get("coingecko_status"),
        "surf": _redis_get_json(redis_client, "v2:altdata:surf:status")
        or (dynamic_discovery or {}).get("surf_status"),
        "coinglass": _redis_get_json(redis_client, "v2:altdata:coinglass:status")
        or (dynamic_discovery or {}).get("coinglass_status"),
        "nansen": public_payloads["nansen"]["payload"],
        "lunarcrush": public_payloads["lunarcrush"]["payload"],
        "coinapi_rest": public_payloads["coinapi_rest"]["payload"],
        "coinapi_wsds": public_payloads["coinapi_wsds"]["payload"],
        "kucoin": public_payloads["kucoin"]["payload"],
        "coinank": public_payloads["coinank"]["payload"],
    }
    provider_rows = [_provider_row(provider, payload, now) for provider, payload in provider_payloads.items()]

    per_symbol_provider_counts: Counter[str] = Counter()
    missing_provider_flags: Counter[str] = Counter()
    symbol_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        altdata = _redis_get_json(redis_client, f"v2:altdata:symbol_score:{symbol}")
        presence = _input_presence(altdata)
        presence.update(
            _current_provider_presence(
                symbol=symbol,
                public_payloads=public_payloads,
                redis_client=redis_client,
            )
        )
        for provider, present in presence.items():
            if present:
                per_symbol_provider_counts[provider] += 1
        for flag in (altdata or {}).get("missing_provider_flags") or []:
            missing_provider_flags[str(flag)] += 1
        symbol_rows.append(
            {
                "symbol": symbol,
                "provider_presence": presence,
                "missing_provider_flags": (altdata or {}).get("missing_provider_flags") or [],
                "fallback_behavior": (
                    "SCORING_CONTINUES_WITH_MISSING_PROVIDER_FLAGS_VISIBLE"
                    if isinstance(altdata, Mapping)
                    else "ALT_DATA_SCORE_MISSING"
                ),
            }
        )

    return {
        "schema_version": "v2_dynamic_provider_contribution_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "provider_rows": provider_rows,
        "provider_presence_counts_by_symbol": dict(per_symbol_provider_counts),
        "missing_provider_flag_counts": dict(missing_provider_flags),
        "paid_or_plan_blockers_visible": {
            "coinglass": "API_PLAN_BLOCKED_401_UPGRADE_PLAN",
            "lunarcrush": "API_PAYMENT_REQUIRED_402",
        },
        "fallback_behavior_when_provider_absent": (
            "Candidate publisher and scoring continue with provider-specific missing flags; "
            "missing optional providers do not authorize live/canary."
        ),
        "symbol_rows": symbol_rows,
    }


def build_website_sync_status(
    *,
    repo_root: Path,
    runtime_burn_in: Mapping[str, Any],
    trainer_quality: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    provider_contribution: Mapping[str, Any],
    public_payloads: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    symbols_page = repo_root / "v2/frontend/src/pages/symbols/index.tsx"
    try:
        symbols_page_text = symbols_page.read_text(encoding="utf-8")
    except Exception:
        symbols_page_text = ""
    website_alignment = public_payloads["website_alignment"]["payload"]
    status = {
        "schema_version": "v2_dynamic_website_sync_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "website_sync_status": "WEBSITE_SYNCED" if LANE_ID in symbols_page_text else "WEBSITE_SYNC_BLOCKED_PAYLOAD_NOT_WIRED",
        "symbols_page_path": str(symbols_page),
        "symbols_page_reads_dynamic_93_payload": LANE_ID in symbols_page_text,
        "website_alignment_payload_freshness": _freshness(
            website_alignment, now=now, limit_seconds=FRESHNESS_LIMITS_SECONDS["website"]
        ),
        "shows_93_dynamic_symbols": runtime_burn_in.get("symbol_count") == TARGET_DYNAMIC_SYMBOL_COUNT,
        "shows_training_paper_live_data_execution_split": bool(runtime_burn_in.get("symbol_split_counts")),
        "shows_provider_status": bool(provider_contribution.get("provider_rows")),
        "shows_candidate_states": bool(runtime_burn_in.get("candidate_state_counts")),
        "shows_trainer_quality": bool(trainer_quality.get("row_count") is not None),
        "shows_paper_backtest_edge": bool(edge_recompute.get("verdict")),
        "live_controls_disabled": True,
        "disabled_live_control_reasons": [
            "live_gate=blocked_human_only",
            "live_symbols=[]",
            "execution_live_symbols=[]",
            "paper edge not proven",
            "operator risk caps and exchange permission still required",
        ],
        "next_operator_gates": [
            "risk thresholds",
            "capital recovery settings",
            "read-only exchange permission probe approval",
            "canary/live approval after edge proof only",
        ],
    }
    return status


def build_live_readiness_recompute_status(
    *,
    runtime_burn_in: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    provider_contribution: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    edge_proven = bool(edge_recompute.get("edge_proven"))
    recommendations: list[str] = []
    if not edge_proven:
        recommendations.append("BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN")
    recommendations.append("BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED")
    recommendations.append("BLOCK_LIVE_EXCHANGE_PERMISSION_REQUIRED")
    provider_flags = provider_contribution.get("missing_provider_flag_counts") or {}
    if provider_flags:
        recommendations.append("BLOCK_LIVE_PROVIDER_GATES_OPTIONAL")
    canary_line = (
        "CANARY_OPERATOR_DECISION_REQUIRED"
        if edge_proven
        and runtime_burn_in.get("symbol_count") == TARGET_DYNAMIC_SYMBOL_COUNT
        and not provider_flags
        else "CANARY_OPERATOR_DECISION_NOT_REACHED"
    )
    return {
        "schema_version": "v2_dynamic_live_readiness_recompute_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "live_ready": False,
        "canary_ready": False,
        "live_readiness_status": "BLOCKED",
        "primary_recommendation": recommendations[0],
        "recommendations": recommendations,
        "canary_operator_decision_line": canary_line,
        "forbidden_readiness_markers_emitted": False,
        "plain_english_summary": {
            "live_blocked_because": (
                "The 93-symbol runtime is present, but paper/backtest edge is not proven."
            ),
            "canary_blocked_because": (
                "Canary remains unavailable until edge, risk caps, and exchange permission gates pass."
            ),
            "next_automatic_action": "Continue V2 paper/shadow burn-in and replay outcome mining.",
            "next_operator_decision": (
                "Only after edge proof: choose risk caps, exchange read-only permission probe, and canary approval."
            ),
        },
    }


def _safety_ok(payloads: Iterable[Mapping[str, Any]]) -> bool:
    for payload in payloads:
        if payload.get("live_gate") != "blocked_human_only":
            return False
        if payload.get("live_symbols") != []:
            return False
        if payload.get("execution_live_symbols") not in ([], None):
            return False
        for key in (
            "approves_live",
            "approves_canary",
            "writes_legacy_redis",
            "writes_exchange_orders",
            "places_exchange_orders",
            "calls_exchange_mutation",
            "leverage_changed",
            "margin_mode_changed",
        ):
            if bool(payload.get(key)):
                return False
    return True


def _decide_go_no_go(
    *,
    runtime_burn_in: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    website_sync: Mapping[str, Any],
    live_readiness: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    if runtime_burn_in.get("symbol_count") != TARGET_DYNAMIC_SYMBOL_COUNT:
        blockers.append(
            {
                "id": "SYMBOL_COUNT_NOT_93",
                "detail": f"symbol_count={runtime_burn_in.get('symbol_count')}",
            }
        )
    if runtime_burn_in.get("three_symbol_default_returned"):
        blockers.append({"id": "THREE_SYMBOL_DEFAULT_RETURNED", "detail": "BTC/ETH/SOL smoke set active"})
    if not edge_recompute.get("edge_proven"):
        blockers.append(
            {
                "id": "PAPER_BACKTEST_EDGE_NOT_PROVEN",
                "detail": edge_recompute.get("verdict") or "missing edge verdict",
            }
        )
    if not website_sync.get("symbols_page_reads_dynamic_93_payload"):
        blockers.append(
            {
                "id": "WEBSITE_SYMBOLS_PAGE_NOT_WIRED",
                "detail": "Symbols page does not read the dynamic 93 payload.",
            }
        )
    if live_readiness.get("live_ready") or live_readiness.get("canary_ready"):
        blockers.append({"id": "FORBIDDEN_LIVE_OR_CANARY_READY", "detail": "live/canary readiness was emitted"})
    if not _safety_ok((runtime_burn_in, edge_recompute, website_sync, live_readiness)):
        blockers.append({"id": "SAFETY_PIN_VIOLATION", "detail": "One or more safety pins changed"})
    return (GO_NO_GO_BLOCKED if blockers else GO_NO_GO_READY), blockers


def build_operator_dashboard_payload(
    *,
    go_no_go: str,
    blockers: list[dict[str, Any]],
    runtime_burn_in: Mapping[str, Any],
    trainer_quality: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    provider_contribution: Mapping[str, Any],
    website_sync: Mapping[str, Any],
    live_readiness: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync_dashboard_v1",
        **_generated_block(now),
        **_safety_block(),
        "go_no_go": go_no_go,
        "status": "BLOCKED" if go_no_go == GO_NO_GO_BLOCKED else "READY",
        "blockers": blockers,
        "summary": {
            "dynamic_symbol_count": runtime_burn_in.get("symbol_count"),
            "target_dynamic_symbol_count": TARGET_DYNAMIC_SYMBOL_COUNT,
            "training_symbols": (runtime_burn_in.get("symbol_split_counts") or {}).get("training_symbols"),
            "paper_symbols": (runtime_burn_in.get("symbol_split_counts") or {}).get("paper_symbols"),
            "live_data_symbols": (runtime_burn_in.get("symbol_split_counts") or {}).get("live_data_symbols"),
            "live_symbols": 0,
            "execution_live_symbols": 0,
            "candidate_count": runtime_burn_in.get("candidate_count"),
            "candidate_state_counts": runtime_burn_in.get("candidate_state_counts"),
            "trainer_row_count": trainer_quality.get("row_count"),
            "trainer_train_rows": trainer_quality.get("train_rows"),
            "trainer_validation_rows": trainer_quality.get("validation_rows"),
            "trained_model_available": trainer_quality.get("trained_model_available"),
            "edge_verdict": edge_recompute.get("verdict"),
            "edge_proven": edge_recompute.get("edge_proven"),
            "after_cost_expectancy_bps": edge_recompute.get("after_cost_expectancy_bps"),
            "primary_live_recommendation": live_readiness.get("primary_recommendation"),
            "website_sync_status": website_sync.get("website_sync_status"),
        },
        "runtime_burn_in": runtime_burn_in,
        "trainer_quality": trainer_quality,
        "edge_recompute": edge_recompute,
        "provider_contribution": provider_contribution,
        "website_sync": website_sync,
        "live_readiness": live_readiness,
        "required_visible_text": [
            "93-symbol dynamic runtime is paper/shadow only.",
            "Live trading is blocked.",
            "Canary is blocked.",
            "Paper/backtest edge is not proven until metrics prove it.",
            "CoinGlass/LunarCrush paid or plan blockers remain visible.",
        ],
    }


def _write_report(path: Path, dashboard: Mapping[str, Any]) -> None:
    summary = dashboard.get("summary") or {}
    blockers = dashboard.get("blockers") or []
    lines = [
        "# V2 Dynamic 93-Symbol Runtime Burn-In, Edge, and Website Sync",
        "",
        f"Generated EST: {dashboard.get('generated_est')}",
        "",
        f"GO/NO-GO: `{dashboard.get('go_no_go')}`",
        "",
        "## Summary",
        "",
        f"- dynamic_symbol_count: `{summary.get('dynamic_symbol_count')}`",
        f"- candidate_count: `{summary.get('candidate_count')}`",
        f"- trainer_row_count: `{summary.get('trainer_row_count')}`",
        f"- edge_verdict: `{summary.get('edge_verdict')}`",
        f"- after_cost_expectancy_bps: `{summary.get('after_cost_expectancy_bps')}`",
        f"- primary_live_recommendation: `{summary.get('primary_live_recommendation')}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker.get('id')}`: {blocker.get('detail')}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- live_gate: `blocked_human_only`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- writes_legacy_redis: `false`",
            "- writes_exchange_orders: `false`",
            "- canary/live approval: `false`",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def run_once(
    *,
    repo_root: Path = REPO_ROOT,
    redis_client_override: Any | None = None,
    write_files: bool = True,
) -> dict[str, Any]:
    now = _now()
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    symbols, symbol_provenance = _resolve_runtime_symbols(repo_root)
    public_payloads = _load_public_payloads(repo_root)
    runtime_burn_in = build_runtime_burn_in_status(
        repo_root=repo_root,
        symbols=symbols,
        symbol_provenance=symbol_provenance,
        public_payloads=public_payloads,
        redis_client=redis_client,
        now=now,
    )
    trainer_quality = build_trainer_quality_status(
        symbols=symbols,
        public_payloads=public_payloads,
        redis_client=redis_client,
        now=now,
    )
    edge_recompute = build_edge_recompute_status(
        repo_root=repo_root,
        symbols=symbols,
        public_payloads=public_payloads,
        now=now,
    )
    provider_contribution = build_provider_contribution_status(
        symbols=symbols,
        public_payloads=public_payloads,
        redis_client=redis_client,
        now=now,
    )
    website_sync = build_website_sync_status(
        repo_root=repo_root,
        runtime_burn_in=runtime_burn_in,
        trainer_quality=trainer_quality,
        edge_recompute=edge_recompute,
        provider_contribution=provider_contribution,
        public_payloads=public_payloads,
        now=now,
    )
    live_readiness = build_live_readiness_recompute_status(
        runtime_burn_in=runtime_burn_in,
        edge_recompute=edge_recompute,
        provider_contribution=provider_contribution,
        now=now,
    )
    go_no_go, blockers = _decide_go_no_go(
        runtime_burn_in=runtime_burn_in,
        edge_recompute=edge_recompute,
        website_sync=website_sync,
        live_readiness=live_readiness,
    )
    dashboard = build_operator_dashboard_payload(
        go_no_go=go_no_go,
        blockers=blockers,
        runtime_burn_in=runtime_burn_in,
        trainer_quality=trainer_quality,
        edge_recompute=edge_recompute,
        provider_contribution=provider_contribution,
        website_sync=website_sync,
        live_readiness=live_readiness,
        now=now,
    )

    if write_files:
        paths = default_paths(repo_root)
        for out_dir in (paths.worklog_dir, paths.public_dir, paths.operator_runtime_dir):
            _write_json(out_dir / "v2_dynamic_93_symbol_runtime_burn_in_status.json", runtime_burn_in)
            _write_json(out_dir / "v2_dynamic_93_trainer_quality_status.json", trainer_quality)
            _write_json(out_dir / "v2_dynamic_93_edge_recompute_status.json", edge_recompute)
            _write_json(out_dir / "v2_dynamic_provider_contribution_status.json", provider_contribution)
            _write_json(out_dir / "v2_dynamic_website_sync_status.json", website_sync)
            _write_json(out_dir / "v2_dynamic_live_readiness_recompute_status.json", live_readiness)
            _write_json(out_dir / "operator_dashboard_payload.json", dashboard)
            _write_text(out_dir / "GO_NO_GO.md", go_no_go + "\n")
        _write_report(paths.worklog_dir / "V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_REPORT.md", dashboard)
        _write_report(paths.public_dir / "V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_REPORT.md", dashboard)

    return dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-files", action="store_true")
    args = parser.parse_args(argv)

    while True:
        payload = run_once(write_files=not args.no_files)
        summary = {
            "go_no_go": payload["go_no_go"],
            "dynamic_symbol_count": payload["summary"]["dynamic_symbol_count"],
            "edge_verdict": payload["summary"]["edge_verdict"],
            "primary_live_recommendation": payload["summary"]["primary_live_recommendation"],
            "live_gate": payload["live_gate"],
            "live_symbols": payload["live_symbols"],
            "execution_live_symbols": payload["execution_live_symbols"],
        }
        print(json.dumps(payload if args.json else summary, indent=2, sort_keys=True, default=str))
        if not args.loop:
            return 0
        try:
            time.sleep(max(60, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
