"""Safe quarantine workflow for stale pipeline-trust runtime evidence."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from v2.backend.app.services.market_state_integrity.trust import (
        mark_runtime_trust_denied,
        validate_prediction_trust_contract,
    )
except ModuleNotFoundError:  # pragma: no cover - supports app.* test imports
    from app.services.market_state_integrity.trust import (  # type: ignore[no-redef]
        mark_runtime_trust_denied,
        validate_prediction_trust_contract,
    )

SCAN_PATTERNS: tuple[str, ...] = (
    "v2:prediction:*",
    "v2:risk:decisions",
    "v2:risk:gateway:decisions",
    "v2:orchestrator:decisions",
    "v2:signals:paper:*",
    "v2:paper:intents",
    "v2:features:microfeat:*",
    "v2:market:kucoin:*",
)

QUARANTINE_VERSION = "pipeline_trust_quarantine_v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quarantine_pipeline_trust_stale_records")
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", ""))
    parser.add_argument("--output-dir", default="pipeline_trust_quarantine")
    parser.add_argument("--apply", action="store_true", help="mutate targeted stale records after backup")
    parser.add_argument("--dry-run", action="store_true", help="default; report and backup plan only")
    parser.add_argument("--max-keys", type=int, default=5000)
    parser.add_argument("--review-file", default="")
    parser.add_argument("--only-review-group", action="append", default=[])
    parser.add_argument("--exclude-review-group", action="append", default=[])
    parser.add_argument("--only-reason", action="append", default=[])
    parser.add_argument("--exclude-reason", action="append", default=[])
    parser.add_argument("--only-key-pattern", action="append", default=[])
    parser.add_argument("--exclude-key-pattern", action="append", default=[])
    parser.add_argument("--max-targets", type=int, default=None)
    parser.add_argument("--expect-targets", type=int, default=None)
    parser.add_argument("--require-backup", action="store_true")
    parser.add_argument("--require-review-file", action="store_true")
    parser.add_argument("--fail-if-v3-targeted", action="store_true")
    parser.add_argument("--fail-if-live-order-targeted", action="store_true")
    parser.add_argument("--fail-if-manual-review-targeted", action="store_true")
    parser.add_argument("--fail-if-do-not-touch-targeted", action="store_true")
    args = parser.parse_args(argv)
    if not args.redis_url:
        raise SystemExit("--redis-url or REDIS_URL is required")
    client = redis_client(args.redis_url)
    report = quarantine_pipeline_trust_stale_records(
        client=client,
        output_root=Path(args.output_dir),
        apply=bool(args.apply),
        max_keys=int(args.max_keys),
        review_file=Path(args.review_file) if args.review_file else None,
        only_review_groups=tuple(args.only_review_group or ()),
        exclude_review_groups=tuple(args.exclude_review_group or ()),
        only_reasons=tuple(args.only_reason or ()),
        exclude_reasons=tuple(args.exclude_reason or ()),
        only_key_patterns=tuple(args.only_key_pattern or ()),
        exclude_key_patterns=tuple(args.exclude_key_pattern or ()),
        max_targets=args.max_targets,
        expect_targets=args.expect_targets,
        require_backup=bool(args.require_backup),
        require_review_file=bool(args.require_review_file),
        fail_if_v3_targeted=bool(args.fail_if_v3_targeted),
        fail_if_live_order_targeted=bool(args.fail_if_live_order_targeted),
        fail_if_manual_review_targeted=bool(args.fail_if_manual_review_targeted),
        fail_if_do_not_touch_targeted=bool(args.fail_if_do_not_touch_targeted),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def quarantine_pipeline_trust_stale_records(
    *,
    client: Any,
    output_root: Path,
    apply: bool = False,
    max_keys: int = 5000,
    patterns: Iterable[str] = SCAN_PATTERNS,
    review_file: Path | None = None,
    only_review_groups: tuple[str, ...] = (),
    exclude_review_groups: tuple[str, ...] = (),
    only_reasons: tuple[str, ...] = (),
    exclude_reasons: tuple[str, ...] = (),
    only_key_patterns: tuple[str, ...] = (),
    exclude_key_patterns: tuple[str, ...] = (),
    max_targets: int | None = None,
    expect_targets: int | None = None,
    require_backup: bool = False,
    require_review_file: bool = False,
    fail_if_v3_targeted: bool = False,
    fail_if_live_order_targeted: bool = False,
    fail_if_manual_review_targeted: bool = False,
    fail_if_do_not_touch_targeted: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    run_dir = output_root / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    review_targets, review_summary = load_review_targets(review_file, require_review_file=require_review_file)
    plan: list[dict[str, Any]] = []
    backups: list[dict[str, Any]] = []
    mutations: list[tuple[str, str, Any]] = []
    candidate_keys: list[str] = []
    excluded_counts: dict[str, int] = {
        "review_group": 0,
        "reason": 0,
        "key_pattern": 0,
        "unmatched_review": 0,
        "v3": 0,
        "live_order": 0,
        "manual_review": 0,
        "do_not_touch": 0,
    }
    seen: set[str] = set()
    for pattern in patterns:
        for key in client.scan_iter(match=pattern, count=250):
            key = str(key)
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > max_keys:
                break
            value_type = redis_type(client, key)
            value = read_value(client, key, value_type)
            mutated, reasons = quarantine_value(key, value, now)
            if not reasons:
                continue
            candidate_keys.append(key)
            review_entry = review_targets.get(key) if review_targets is not None else None
            selected, reject_reason = target_selected(
                key=key,
                value=value,
                reasons=tuple(reasons),
                review_entry=review_entry,
                review_required=review_targets is not None,
                only_review_groups=only_review_groups,
                exclude_review_groups=exclude_review_groups,
                only_reasons=only_reasons,
                exclude_reasons=exclude_reasons,
                only_key_patterns=only_key_patterns,
                exclude_key_patterns=exclude_key_patterns,
            )
            if review_targets is not None and reject_reason == "unmatched_review":
                raise SystemExit(f"target not matched to review file: {key}")
            if fail_if_v3_targeted and reject_reason == "v3":
                raise SystemExit(f"refusing to target pipeline_trust_v3 record: {key}")
            if fail_if_live_order_targeted and reject_reason == "live_order":
                raise SystemExit(f"refusing to target live/exchange order key: {key}")
            if not selected:
                excluded_counts[reject_reason] = excluded_counts.get(reject_reason, 0) + 1
                continue
            selected_group = str((review_entry or {}).get("review_group") or "")
            trust_schema_version = str((review_entry or {}).get("trust_schema_version") or "")
            if isinstance(value, dict) and not trust_schema_version:
                trust_schema_version = str(value.get("trust_schema_version") or "")
            if fail_if_v3_targeted and trust_schema_version == "pipeline_trust_v3":
                excluded_counts["v3"] += 1
                raise SystemExit(f"refusing to target pipeline_trust_v3 record: {key}")
            if fail_if_live_order_targeted and live_order_key(key):
                excluded_counts["live_order"] += 1
                raise SystemExit(f"refusing to target live/exchange order key: {key}")
            if fail_if_manual_review_targeted and selected_group == "REQUIRES_MANUAL_REVIEW":
                excluded_counts["manual_review"] += 1
                raise SystemExit(f"refusing to target manual-review record: {key}")
            if fail_if_do_not_touch_targeted and selected_group == "DO_NOT_TOUCH":
                excluded_counts["do_not_touch"] += 1
                raise SystemExit(f"refusing to target do-not-touch record: {key}")
            backups.append({"redis_key": key, "redis_type": value_type, "value": value})
            plan.append(
                {
                    "redis_key": key,
                    "redis_type": value_type,
                    "reasons": reasons,
                    "review_group": selected_group or None,
                    "action": write_action(value_type),
                }
            )
            mutations.append((key, value_type, mutated))
    candidate_fingerprint = fingerprint_keys(candidate_keys)
    selected_fingerprint = fingerprint_keys(str(item.get("redis_key") or "") for item in plan)
    review_target_fingerprint = str(review_summary.get("target_keys_fingerprint") or "")
    review_safe_fingerprint = str(review_summary.get("safe_target_keys_fingerprint") or "")
    if review_targets is not None and review_target_fingerprint and review_target_fingerprint != candidate_fingerprint:
        raise SystemExit(
            "review fingerprint mismatch: current dry-run target set does not match review sidecar"
        )
    if (
        review_targets is not None
        and review_safe_fingerprint
        and set(only_review_groups) == {"SAFE_TO_QUARANTINE"}
        and review_safe_fingerprint != selected_fingerprint
    ):
        raise SystemExit(
            "review safe-target fingerprint mismatch: selected safe set does not match review sidecar"
        )
    if max_targets is not None and len(plan) > int(max_targets):
        raise SystemExit(f"selected target count {len(plan)} exceeds --max-targets {max_targets}")
    if expect_targets is not None and len(plan) != int(expect_targets):
        raise SystemExit(f"selected target count {len(plan)} does not match --expect-targets {expect_targets}")
    write_jsonl(run_dir / "backup.jsonl", backups)
    if apply and not require_backup:
        raise SystemExit("--apply requires --require-backup")
    if apply and require_backup and not (run_dir / "backup.jsonl").exists():
        raise SystemExit("backup is required before apply")
    if apply:
        if require_review_file and review_targets is None:
            raise SystemExit("scoped apply requires --review-file")
        for key, value_type, mutated in mutations:
            write_value(client, key, value_type, mutated)
    reason_counts: dict[str, int] = {}
    pattern_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    review_group_counts: dict[str, int] = {}
    v3_target_count = 0
    live_order_target_count = 0
    for item, backup in zip(plan, backups, strict=False):
        for reason in item.get("reasons") or []:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        pattern_name = target_key_pattern(str(item.get("redis_key") or ""))
        pattern_counts[pattern_name] = pattern_counts.get(pattern_name, 0) + 1
        action = str(item.get("action") or "")
        action_counts[action] = action_counts.get(action, 0) + 1
        group = str(item.get("review_group") or "unreviewed")
        review_group_counts[group] = review_group_counts.get(group, 0) + 1
        value = backup.get("value")
        if isinstance(value, dict) and value.get("trust_schema_version") == "pipeline_trust_v3":
            v3_target_count += 1
        if live_order_key(str(item.get("redis_key") or "")):
            live_order_target_count += 1
    report = {
        "generated_at": now,
        "mode": "apply" if apply else "dry_run",
        "dry_run": not apply,
        "keys_scanned": len(seen),
        "records_targeted": len(plan),
        "records_mutated": len(mutations) if apply else 0,
        "records_skipped": sum(excluded_counts.values()),
        "patterns_scanned": list(patterns),
        "backup_path": str(run_dir / "backup.jsonl"),
        "review_file": str(review_file) if review_file else None,
        "require_review_file": bool(require_review_file),
        "require_backup": bool(require_backup),
        "expect_targets": expect_targets,
        "max_targets": max_targets,
        "selected_counts": {
            "by_key_pattern": pattern_counts,
            "by_reason": reason_counts,
            "by_action": action_counts,
            "by_review_group": review_group_counts,
            "pipeline_trust_v3": v3_target_count,
            "live_or_exchange_order": live_order_target_count,
        },
        "fingerprints": {
            "candidate_target_keys": candidate_fingerprint,
            "selected_target_keys": selected_fingerprint,
            "review_target_keys": review_target_fingerprint or None,
            "review_safe_target_keys": review_safe_fingerprint or None,
        },
        "excluded_counts": excluded_counts,
        "plan": plan,
        "safety": {
            "uses_flushdb": False,
            "deletes_live_order_records": False,
            "mutates_live_orders": False,
        },
    }
    (run_dir / "quarantine_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def load_review_targets(
    review_file: Path | None, *, require_review_file: bool
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any]]:
    if review_file is None:
        if require_review_file:
            raise SystemExit("--require-review-file requires --review-file")
        return None, {}
    path = review_file
    if path.suffix.lower() in {".md", ".markdown"}:
        sidecar = path.with_suffix(".targets.json")
        if not sidecar.exists():
            raise SystemExit(f"review sidecar not found for markdown review: {sidecar}")
        path = sidecar
    if not path.exists():
        raise SystemExit(f"review file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("targets") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("review file must contain a target list or {'targets': [...]}")
    targets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or row.get("redis_key") or "")
        if not key:
            continue
        targets[key] = row
    summary = dict(payload.get("summary") or {}) if isinstance(payload, dict) else {}
    return targets, summary


def target_selected(
    *,
    key: str,
    value: Any,
    reasons: tuple[str, ...],
    review_entry: dict[str, Any] | None,
    review_required: bool,
    only_review_groups: tuple[str, ...],
    exclude_review_groups: tuple[str, ...],
    only_reasons: tuple[str, ...],
    exclude_reasons: tuple[str, ...],
    only_key_patterns: tuple[str, ...],
    exclude_key_patterns: tuple[str, ...],
) -> tuple[bool, str]:
    if review_required and review_entry is None:
        return False, "unmatched_review"
    group = str((review_entry or {}).get("review_group") or "")
    if review_required and not group:
        return False, "unmatched_review"
    if only_review_groups and group not in set(only_review_groups):
        return False, "review_group"
    if exclude_review_groups and group in set(exclude_review_groups):
        return False, "review_group"
    reason_set = set(reasons)
    if only_reasons and not reason_set.intersection(only_reasons):
        return False, "reason"
    if exclude_reasons and reason_set.intersection(exclude_reasons):
        return False, "reason"
    if only_key_patterns and not any(fnmatch.fnmatch(key, pattern) for pattern in only_key_patterns):
        return False, "key_pattern"
    if exclude_key_patterns and any(fnmatch.fnmatch(key, pattern) for pattern in exclude_key_patterns):
        return False, "key_pattern"
    if isinstance(value, dict) and value.get("trust_schema_version") == "pipeline_trust_v3":
        return False, "v3"
    if live_order_key(key):
        return False, "live_order"
    return True, ""


def live_order_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("live_order", "exchange_order", "order_transport"))


def target_key_pattern(key: str) -> str:
    if key.startswith("v2:prediction:rl_core:"):
        return "v2:prediction:rl_core:*"
    if key.startswith("v2:prediction:"):
        return "v2:prediction:*"
    if key.startswith("v2:signals:paper:"):
        return "v2:signals:paper:*:tf" if len(key.split(":")) >= 5 else "v2:signals:paper:*"
    if key == "v2:paper:intents":
        return "v2:paper:intents"
    if key in {"v2:risk:decisions", "v2:risk:gateway:decisions", "v2:orchestrator:decisions"}:
        return key
    if key.startswith("v2:features:microfeat:"):
        return "v2:features:microfeat:*"
    if key.startswith("v2:market:kucoin:"):
        return "v2:market:kucoin:*"
    return "unknown"


def write_action(value_type: str) -> str:
    if value_type == "string":
        return "SET same key with quarantined payload"
    if value_type == "list":
        return "LSET targeted list items"
    if value_type == "hash":
        return "HSET targeted hash fields"
    return f"unknown:{value_type}"


def fingerprint_keys(values: Iterable[str]) -> str:
    keys = sorted(str(value) for value in values if str(value))
    return hashlib.sha256(json.dumps(keys, sort_keys=True).encode("utf-8")).hexdigest()


def quarantine_value(key: str, value: Any, now: str) -> tuple[Any, list[str]]:
    if isinstance(value, list):
        mutated_rows = []
        reasons: list[str] = []
        changed = False
        for row in value:
            mutated, row_reasons = quarantine_value(key, row, now)
            mutated_rows.append(mutated)
            if row_reasons:
                changed = True
                reasons.extend(row_reasons)
        return (mutated_rows if changed else value), sorted(set(reasons))
    if not isinstance(value, Mapping):
        return value, []
    row = dict(value)
    reasons = classify_quarantine_reasons(key, row)
    if not reasons:
        return value, []
    contract = validate_prediction_trust_contract(row, require_replay_write=True)
    row = mark_runtime_trust_denied(row, contract) if contract.active else row
    row.update(
        {
            "quarantined": True,
            "quarantine_version": QUARANTINE_VERSION,
            "quarantined_at": now,
            "quarantine_reasons": sorted(set(reasons)),
            "feature_eligible": False,
            "trainer_consumable": False,
            "prediction_eligible": False,
            "risk_eligible": False,
            "paper_eligible": False,
            "routed_to_paper": False,
            "pre_trade_allowed": False,
            "approved": False,
            "positive_training_sample": False,
        }
    )
    return row, sorted(set(reasons))


def classify_quarantine_reasons(key: str, row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    lowered = key.lower()
    contract = validate_prediction_trust_contract(row, require_replay_write=True)
    if contract.active and not contract.allowed:
        reasons.append("ACTIVE_STALE_TRUST_CONTRACT_MISSING")
    if "features:microfeat" in lowered and (not row.get("available_at") or not row.get("feature_cutoff")):
        reasons.append("COINAPI_MICROFEATURE_MISSING_TRUST_TIMESTAMPS")
    if "market:kucoin" in lowered and malformed_ohlc(row):
        reasons.append("KUCOIN_MALFORMED_OHLC")
    if "prediction" in lowered and (not row.get("mtf_snapshot_id") or not row.get("replay_snapshot_id")):
        reasons.append("STALE_PREDICTION_UNREPLAYABLE")
    if "signals:paper" in lowered and (not row.get("mtf_snapshot_id") or not row.get("replay_snapshot_id")):
        reasons.append("STALE_PAPER_SIGNAL_UNREPLAYABLE")
    return reasons


def malformed_ohlc(row: Mapping[str, Any]) -> bool:
    try:
        open_px = float(row.get("open"))
        high_px = float(row.get("high"))
        low_px = float(row.get("low"))
        close_px = float(row.get("close"))
    except (TypeError, ValueError):
        return False
    prices = (open_px, high_px, low_px, close_px)
    if any(value != value or value <= 0 for value in prices):
        return True
    return not (low_px <= open_px <= high_px and low_px <= close_px <= high_px)


def redis_type(client: Any, key: str) -> str:
    value_type = client.type(key)
    if isinstance(value_type, bytes):
        return value_type.decode("utf-8", errors="replace")
    return str(value_type)


def read_value(client: Any, key: str, value_type: str) -> Any:
    if value_type == "string":
        return parse_json_maybe(client.get(key))
    if value_type == "list":
        return [parse_json_maybe(item) for item in client.lrange(key, 0, 999)]
    if value_type == "hash":
        return {field: parse_json_maybe(value) for field, value in client.hgetall(key).items()}
    return None


def write_value(client: Any, key: str, value_type: str, value: Any) -> None:
    if value_type == "string":
        client.set(key, json.dumps(value, sort_keys=True, default=str))
    elif value_type == "list" and isinstance(value, list):
        for index, item in enumerate(value):
            client.lset(key, index, json.dumps(item, sort_keys=True, default=str))
    elif value_type == "hash" and isinstance(value, dict):
        for field, item in value.items():
            client.hset(key, field, json.dumps(item, sort_keys=True, default=str))


def parse_json_maybe(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"-0123456789tfn":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str))
            handle.write("\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
