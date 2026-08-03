"""Restore the exact economic cohort bound by a governed activation receipt."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ACTIVE_KEY = "v2:model_registry:paper:active"
ECONOMIC_COHORT_KEY = "v2:paper:economic_evaluation_cohort"
LEGACY_COHORT_KEY = "v2:paper:provisional_cohort_activation"
STATUS_KEY = "v2:operations:economic_cohort_binding"
SCHEMA_VERSION = "economic_cohort_binding_republisher_v1"


def _json_value(client: Any, key: str) -> dict[str, Any]:
    raw = client.get(key)
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _validate_binding(
    *,
    active: Mapping[str, Any],
    receipt_document: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    activation = receipt_document.get("activation_receipt")
    economic = receipt_document.get("economic_cohort")
    legacy = receipt_document.get("legacy_serving_cohort")
    if not all(isinstance(value, Mapping) for value in (activation, economic, legacy)):
        raise ValueError("DURABLE_ACTIVATION_RECEIPT_STRUCTURE_INVALID")
    activation = dict(activation)
    economic = dict(economic)
    legacy = dict(legacy)
    bundle = active.get("checkpoint_bundle")
    if not isinstance(bundle, Mapping):
        raise ValueError("ACTIVE_REGISTRY_CHECKPOINT_BUNDLE_MISSING")

    expected = {
        "generation": int(active.get("registry_generation") or 0),
        "checkpoint_id": str(active.get("checkpoint_id") or ""),
        "bundle_sha256": str(bundle.get("content_sha256") or ""),
        "feature_abi_sha256": str(bundle.get("feature_abi_sha256") or ""),
    }
    checks = {
        "active_generation_positive": expected["generation"] > 0,
        "active_checkpoint_present": bool(expected["checkpoint_id"]),
        "active_bundle_hash_present": len(expected["bundle_sha256"]) == 64,
        "active_feature_abi_present": len(expected["feature_abi_sha256"]) == 64,
        "receipt_generation_matches": int(activation.get("registry_generation") or 0)
        == expected["generation"],
        "receipt_checkpoint_matches": str(activation.get("checkpoint_id") or "")
        == expected["checkpoint_id"],
        "receipt_bundle_matches": str(
            activation.get("checkpoint_bundle_sha256") or ""
        )
        == expected["bundle_sha256"],
        "economic_generation_matches": int(economic.get("checkpoint_generation") or 0)
        == expected["generation"],
        "economic_checkpoint_matches": str(economic.get("checkpoint_id") or "")
        == expected["checkpoint_id"],
        "economic_bundle_matches": str(economic.get("checkpoint_bundle_sha256") or "")
        == expected["bundle_sha256"],
        "economic_feature_abi_matches": str(economic.get("feature_abi_sha256") or "")
        == expected["feature_abi_sha256"],
        "legacy_generation_matches": int(legacy.get("checkpoint_generation") or 0)
        == expected["generation"],
        "legacy_checkpoint_matches": str(legacy.get("checkpoint_id") or "")
        == expected["checkpoint_id"],
        "legacy_cohort_matches": str(legacy.get("paper_strategy_cohort_id") or "")
        == str(economic.get("cohort_id") or ""),
        "economic_window_frozen": economic.get("window_type")
        == "CHECKPOINT_GENERATION_NATURAL_DIRECTIONAL_CLOSES"
        and int(economic.get("minimum_natural_directional_closes") or 0) == 5,
        "economic_safety_flags": economic.get("paper_only") is True
        and economic.get("live_eligible") is False
        and economic.get("places_real_order") is False
        and economic.get("exchange_action_taken") is False,
        "legacy_safety_flags": legacy.get("paper_only") is True
        and legacy.get("live_eligible") is False
        and legacy.get("routes_to_live") is False
        and legacy.get("places_real_order") is False,
    }
    failures = sorted(key for key, passed in checks.items() if not passed)
    if failures:
        raise ValueError("COHORT_BINDING_VALIDATION_FAILED:" + ",".join(failures))
    return economic, legacy


def republish(
    client: Any,
    *,
    receipt_path: Path,
    status_path: Path | None = None,
) -> dict[str, Any]:
    document = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("DURABLE_ACTIVATION_RECEIPT_NOT_MAPPING")
    active = _json_value(client, ACTIVE_KEY)
    if not active:
        raise ValueError("ACTIVE_PAPER_REGISTRY_MISSING")
    economic, legacy = _validate_binding(
        active=active,
        receipt_document=document,
    )
    existing_economic = _json_value(client, ECONOMIC_COHORT_KEY)
    existing_legacy = _json_value(client, LEGACY_COHORT_KEY)
    if existing_economic and _canonical(existing_economic) != _canonical(economic):
        raise ValueError("ECONOMIC_COHORT_CONFLICT")
    if existing_legacy and _canonical(existing_legacy) != _canonical(legacy):
        raise ValueError("LEGACY_COHORT_CONFLICT")

    pipe = client.pipeline()
    pipe.multi()
    pipe.set(ECONOMIC_COHORT_KEY, json.dumps(economic, sort_keys=True))
    pipe.set(LEGACY_COHORT_KEY, json.dumps(legacy, sort_keys=True))
    results = pipe.execute()
    if results != [True, True]:
        raise RuntimeError(f"COHORT_REPUBLICATION_NOT_ACKNOWLEDGED:{results!r}")

    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(UTC).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "result": "PASS_EXISTING_IDENTICAL"
        if existing_economic
        else "PASS_RESTORED_FROM_DURABLE_ACTIVATION_RECEIPT",
        "checkpoint_generation": economic["checkpoint_generation"],
        "checkpoint_id": economic["checkpoint_id"],
        "cohort_id": economic["cohort_id"],
        "receipt_path": str(receipt_path),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    client.set(STATUS_KEY, json.dumps(status, sort_keys=True))
    if status_path is not None:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = status_path.with_suffix(f"{status_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, status_path)
    return status


def _connect_redis() -> Any:
    import redis

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
        socket_timeout=5,
    )
    client.ping()
    return client


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path(
            "goal_state/PERMANENT_SYSTEM_RECOVERY/governed_activation_receipt_v2.json"
        ),
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=Path(
            "goal_state/PERMANENT_SYSTEM_RECOVERY/economic_cohort_binding_status.json"
        ),
    )
    args = parser.parse_args()
    result = republish(
        _connect_redis(), receipt_path=args.receipt, status_path=args.status_path
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
