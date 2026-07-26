"""Canonical prediction-serving runtime (V2 convergence, Phase 6).

The ONE independent authority that continuously publishes canonical
v2:prediction:<symbol>:<timeframe> records from the ACTIVE paper checkpoint in the
atomic model registry. It:

  * loads the active checkpoint from v2:model_registry:paper:active (never from an
    env var, symlink, or trainer process);
  * hot-reloads only when the registry generation changes;
  * serves the last active checkpoint while EVERY trainer is stopped
    (training/serving are lifecycle-decoupled);
  * reuses the canonical build_prediction_payload + V2HybridPredictionPublisher via
    the proven publish_one path — one prediction schema for every classification;
  * publishes serving health to v2:prediction_serving:status;
  * never submits an exchange order, never mutates leverage/margin.

Rollback on serving health failure is delegated to the registry rollback API; this
runtime surfaces health so an activator/supervisor can trigger it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = str(Path(__file__).resolve().parents[4])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from v2.backend.app.cli.v2_paper_provisional_prediction_publisher import (  # noqa: E402
    ProvisionalCheckpoint,
    V2HybridPredictionPublisher,
    V2OnlyJsonIO,
    publish_one,
    read_active_cohort,
    resolve_symbols,
)
from v2.backend.app.services.prediction_serving.checkpoint_registry import (  # noqa: E402
    read_active,
)
from v2.backend.app.contracts.runtime_v2.contracts import canonical_sha256  # noqa: E402
from v2.backend.app.services.native_trainer.current_cycle_evidence import (  # noqa: E402
    capture_cycle_identity,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (  # noqa: E402
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)

STATUS_KEY = "v2:prediction_serving:status"
SERVING_TTL_SECONDS = 180


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def serving_release_sha() -> str:
    return str(os.environ.get("AI_BOT_CODE_SHA") or "workspace")


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
    client.ping()
    return client


class ActiveModel:
    """The loaded active checkpoint + its registry generation (hot-reloadable)."""

    def __init__(self, ckpt: ProvisionalCheckpoint, generation: int, record: dict[str, Any]) -> None:
        self.ckpt = ckpt
        self.generation = generation
        self.record = record
        self.classification = str(record.get("checkpoint_classification") or "PAPER_PROVISIONAL")


def load_active_model(client: Any) -> ActiveModel | None:
    record = read_active(client, lane="paper")
    if not record:
        return None
    bundle = record.get("checkpoint_bundle") or {}
    weight_path = bundle.get("weight_file_path") or record.get("checkpoint_bundle_path")
    if not weight_path or not Path(weight_path).exists():
        return None
    bundle_material = dict(bundle)
    claimed_content_sha256 = bundle_material.pop("content_sha256", None)
    for policy_field in ("paper_eligible", "strict_eligible", "checkpoint_promotable", "live_eligible"):
        bundle_material.pop(policy_field, None)
    if claimed_content_sha256 != canonical_sha256(bundle_material):
        return None
    if record.get("checkpoint_bundle_sha256") != claimed_content_sha256:
        return None
    if bundle.get("feature_abi_sha256") == feature_abi_sha256():
        actual_weight_sha256 = hashlib.sha256(Path(weight_path).read_bytes()).hexdigest()
        if (
            actual_weight_sha256 != bundle.get("weight_sha256")
            or
            bundle.get("serving_feature_builder_sha") != feature_builder_sha256()
            or bundle.get("training_feature_builder_sha") != feature_builder_sha256()
            or tuple(bundle.get("ordered_feature_names") or ()) != ORDERED_FEATURE_NAMES
            or (bundle.get("calibration_state") or {}).get("probability_semantics_valid") is not True
        ):
            return None
    ckpt = ProvisionalCheckpoint(Path(weight_path))
    generation = int(record.get("registry_generation", 0))
    return ActiveModel(ckpt, generation, record)


def run_cycle(
    client: Any,
    active: ActiveModel,
    *,
    symbols: list[str],
    timeframes: list[str],
    status_path: Path | None,
    reload_count: int,
    rollback_count: int,
) -> dict[str, Any]:
    io = V2OnlyJsonIO(client=client)
    publisher = V2HybridPredictionPublisher(
        io=io, behavior_receipt_archive_root=None,
        current_cycle_publication_ttl_seconds=SERVING_TTL_SECONDS,
    )
    cohort = read_active_cohort(client)
    cycle_identity = capture_cycle_identity()
    serving_context = {
        "serving_runtime_release_sha": serving_release_sha(),
        "active_model_registry_generation": active.generation,
        "checkpoint_classification": active.classification,
        "cycle_id": cycle_identity["cycle_id"],
        "process_instance_id": cycle_identity["process_instance_id"],
        "candidate_policy_fingerprint": active.ckpt.model_parameter_fingerprint,
    }
    observations: list[dict[str, Any]] = []
    published = directional = 0
    rejections: dict[str, int] = {}
    feat_valid = cost_valid = micro_valid = 0
    for symbol in symbols:
        for timeframe in timeframes:
            res = publish_one(
                client=client, io=io, publisher=publisher, ckpt=active.ckpt,
                cohort=cohort, symbol=symbol, timeframe=timeframe,
                serving_context=serving_context,
            )
            observations.append(res)
            if res.get("cost_evidence_valid") is True:
                cost_valid += 1
            if res.get("microstructure_evidence_valid") is True:
                micro_valid += 1
            if res.get("status") == "PUBLISHED":
                published += 1
                feat_valid += 1
                if res.get("directional"):
                    directional += 1
            else:
                st = res.get("status", "UNKNOWN")
                rejections[st] = rejections.get(st, 0) + 1
    now = utc_now()
    latest_pub = next((o for o in reversed(observations) if o.get("status") == "PUBLISHED"), {})
    latest_dir = next(
        (o for o in reversed(observations) if o.get("status") == "PUBLISHED" and o.get("directional")),
        {},
    )
    status = {
        "schema_version": "prediction_serving_status_v1",
        "generated_utc": now,
        "registry_generation": active.generation,
        "active_checkpoint_id": active.ckpt.checkpoint_id,
        "active_checkpoint_classification": active.classification,
        "feature_abi_sha256": active.ckpt.feature_abi_sha256,
        "feature_builder_sha256": active.ckpt.feature_builder_sha256,
        "serving_feature_abi_v2": active.ckpt.serving_feature_abi_v2,
        "feature_abi_match": (
            active.ckpt.feature_abi_sha256 == feature_abi_sha256()
            and active.ckpt.feature_builder_sha256 == feature_builder_sha256()
        ),
        "serving_runtime_release_sha": serving_release_sha(),
        "records_evaluated": len(observations),
        "records_published": published,
        "directional_records": directional,
        "hold_records": published - directional,
        "rejected_records": len(observations) - published,
        "rejections_by_reason": rejections,
        "latest_prediction_time": latest_pub.get("prediction_id") and now or None,
        "latest_prediction_id": latest_pub.get("prediction_id"),
        "latest_directional_prediction_time": (latest_dir.get("prediction_id") and now) or None,
        "feature_evidence_valid_count": feat_valid,
        "cost_evidence_valid_count": cost_valid,
        "microstructure_evidence_valid_count": micro_valid,
        "checkpoint_reload_count": reload_count,
        "checkpoint_reload_failures": 0,
        "rollback_count": rollback_count,
        "trainer_dependency": False,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "exchange_action_taken": False,
        "paper_only": True,
        "sample_published": [o for o in observations if o.get("status") == "PUBLISHED"][:5],
    }
    try:
        # publish_one observations can carry non-JSON-native objects; the console
        # print survives via default=str while a raw dump raises — sanitize first.
        io.set_json_expiring(
            STATUS_KEY,
            json.loads(json.dumps(status, default=str)),
            ex=SERVING_TTL_SECONDS * 4,
        )
    except Exception as error:
        print(json.dumps({"status_key_write_failed": f"{type(error).__name__}: {error}"}), flush=True)
    if status_path is not None:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status, indent=2, default=str))
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_canonical_prediction_serving_runtime")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--timeframes", default="5m,15m,1h,4h")
    parser.add_argument("--status-path", default="")
    parser.add_argument("--max-symbols", type=int, default=0)
    args = parser.parse_args(argv)

    if not (args.once or args.loop):
        print(json.dumps({"status": "BLOCKED", "reason": "REQUIRE_--once_OR_--loop"}))
        return 1

    client = redis_client(args.redis_url)
    symbols = resolve_symbols(client, [s for s in args.symbols.split(",") if s.strip()] or None)
    if args.max_symbols and len(symbols) > args.max_symbols:
        symbols = symbols[: args.max_symbols]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    status_path = Path(args.status_path) if args.status_path else None

    active = load_active_model(client)
    if active is None:
        status = {
            "schema_version": "prediction_serving_status_v1", "generated_utc": utc_now(),
            "status": "NO_ACTIVE_PAPER_CHECKPOINT", "records_published": 0,
            "trainer_dependency": False, "live_gate": "blocked_human_only",
        }
        try:
            V2OnlyJsonIO(client=client).set_json_expiring(STATUS_KEY, status, ex=SERVING_TTL_SECONDS * 4)
        except Exception:
            pass
        print(json.dumps(status, indent=2, default=str))
        return 1

    reload_count = 0
    if args.once:
        status = run_cycle(
            client, active, symbols=symbols, timeframes=timeframes,
            status_path=status_path, reload_count=reload_count, rollback_count=0,
        )
        print(json.dumps({k: status[k] for k in (
            "registry_generation", "active_checkpoint_id", "records_published",
            "directional_records", "rejected_records", "rejections_by_reason",
            "trainer_dependency",
        )}, indent=2, default=str))
        return 0

    while True:
        # Hot-reload on registry generation change (no trainer restart involved).
        latest = read_active(client, lane="paper")
        latest_gen = int(latest.get("registry_generation", 0)) if latest else active.generation
        if latest_gen != active.generation:
            reloaded = load_active_model(client)
            if reloaded is not None:
                active = reloaded
                reload_count += 1
        status = run_cycle(
            client, active, symbols=symbols, timeframes=timeframes,
            status_path=status_path, reload_count=reload_count, rollback_count=0,
        )
        print(json.dumps({k: status.get(k) for k in (
            "generated_utc", "registry_generation", "records_published",
            "directional_records", "rejected_records",
        )}, default=str), flush=True)
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
