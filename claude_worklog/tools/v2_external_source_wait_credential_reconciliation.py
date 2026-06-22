"""Reconcile external-source wait against credential env-name aliases.

This lane answers whether TRUE_EXTERNAL_SOURCE_WAIT is legitimate or caused by
missing alias mapping.  It records env var names and presence only; it never
persists, prints, or compares raw credential values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LANE_ID = "v2_external_source_wait_credential_reconciliation"
GO_READY = "V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_READY"
GO_BLOCKED = "V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_BLOCKED"

WORKLOG_DIR = ROOT / "claude_worklog" / "final_readiness" / LANE_ID / "latest"
PUBLIC_DIR = ROOT / "v2" / "frontend" / "public" / LANE_ID / "latest"
TASK_MIRROR_DIR = ROOT / "claude_worklog" / "final_readiness" / "v2_closed_loop_execution" / "latest" / "tasks"
LOCAL_SECRET_FILES = (
    ROOT / ".local_secrets" / "live_credentials.env",
    ROOT / ".local_secrets" / "legacy.env",
    ROOT / ".local_secrets" / "legacy_config.py",
)
EXTERNAL_PACKET = (
    ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_final_production_equivalence_blocker_resolution_sprint"
    / "latest"
    / "external_source_decision_packet.json"
)
FAMILY_MATRIX = (
    ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_operator_selected_required_implementation_backlog_execution"
    / "latest"
    / "lanes"
    / "lane_5_full_observation_operator_family"
    / "full_observation_remaining_family_matrix.json"
)

SAFETY = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
    "creates_approval_tokens": False,
    "activates_paid_feeds": False,
    "raw_values_read": False,
    "raw_values_printed": False,
}

PROVIDER_ALIASES = {
    "glassnode": {
        "canonical_env_var_name": "GLASSNODE_API_KEY",
        "alias_env_var_names": (
            "GLASSNODE_API_KEY",
            "GLASSNODE_KEY",
            "GLASSNODE_TOKEN",
            "V2_GLASSNODE_API_KEY",
            "LEGACY_GLASSNODE_API_KEY",
        ),
    },
    "cryptoquant": {
        "canonical_env_var_name": "CRYPTOQUANT_API_KEY",
        "alias_env_var_names": (
            "CRYPTOQUANT_API_KEY",
            "CRYPTO_QUANT_API_KEY",
            "CRYPTOQUANT_KEY",
            "CQ_API_KEY",
            "V2_CRYPTOQUANT_API_KEY",
            "LEGACY_CRYPTOQUANT_API_KEY",
        ),
    },
    "santiment": {
        "canonical_env_var_name": "SANTIMENT_API_KEY",
        "alias_env_var_names": (
            "SANTIMENT_API_KEY",
            "SANTIMENT_KEY",
            "SANTIMENT_TOKEN",
            "SANBASE_API_KEY",
            "V2_SANTIMENT_API_KEY",
            "LEGACY_SANTIMENT_API_KEY",
        ),
    },
    "tokenmetrics": {
        "canonical_env_var_name": "TOKEN_METRICS_API_KEY",
        "alias_env_var_names": (
            "TOKEN_METRICS_API_KEY",
            "TOKENMETRICS_API_KEY",
            "TOKENMETRICS_KEY",
            "TOKEN_METRICS_KEY",
            "TM_API_KEY",
            "V2_TOKENMETRICS_API_KEY",
            "LEGACY_TOKENMETRICS_API_KEY",
        ),
    },
}

SOURCE_FAMILY_PROVIDERS = {
    "onchain_btc": ("glassnode", "cryptoquant", "santiment"),
    "onchain_eth": ("glassnode", "cryptoquant", "santiment"),
    "unified_feature_family.token_metrics": ("tokenmetrics",),
}

PROVIDER_CLIENT_CANDIDATES = {
    "glassnode": (
        "v2/backend/app/adapters/external_sources/glassnode.py",
        "v2/backend/app/services/external_sources/glassnode.py",
    ),
    "cryptoquant": (
        "v2/backend/app/adapters/external_sources/cryptoquant.py",
        "v2/backend/app/services/external_sources/cryptoquant.py",
    ),
    "santiment": (
        "v2/backend/app/adapters/external_sources/santiment.py",
        "v2/backend/app/services/external_sources/santiment.py",
    ),
    "tokenmetrics": (
        "v2/backend/app/adapters/external_sources/tokenmetrics.py",
        "v2/backend/app/services/external_sources/tokenmetrics.py",
    ),
}

FREE_TIER_CONFIRM_ENV_NAMES = (
    "V2_EXTERNAL_SOURCE_FREE_TIER_CONFIRMED",
    "V2_EXTERNAL_SOURCE_CODEX_SAFE_CONFIRMED",
)
WATCHED_ENV_NAMES = frozenset(
    {
        name
        for provider in PROVIDER_ALIASES.values()
        for name in provider["alias_env_var_names"]
    }
    | set(FREE_TIER_CONFIRM_ENV_NAMES)
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mirror_json(name: str, payload: dict[str, Any]) -> None:
    write_json(WORKLOG_DIR / name, payload)
    write_json(PUBLIC_DIR / name, payload)


def safe_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _name_from_assignment_prefix(prefix: bytes) -> str | None:
    text = prefix.decode("utf-8", errors="ignore").strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*$", text)
    return match.group(1) if match else None


def scan_assignment_names_only(path: Path) -> set[str]:
    """Scan assignment names without retaining bytes after '='."""

    names: set[str] = set()
    if not path.exists():
        return names
    prefix = bytearray()
    with path.open("rb") as handle:
        while True:
            byte = handle.read(1)
            if not byte:
                name = _name_from_assignment_prefix(bytes(prefix))
                if name:
                    names.add(name)
                break
            if byte == b"=":
                name = _name_from_assignment_prefix(bytes(prefix))
                if name:
                    names.add(name)
                prefix.clear()
                while True:
                    skipped = handle.read(1)
                    if not skipped or skipped in {b"\n", b"\r"}:
                        break
                continue
            if byte in {b"\n", b"\r"}:
                prefix.clear()
                continue
            if len(prefix) < 256:
                prefix.extend(byte)
    return names


def build_name_presence_index() -> dict[str, Any]:
    names: dict[str, dict[str, Any]] = {}

    def add(name: str, source: dict[str, str]) -> None:
        row = names.setdefault(name, {"name": name, "present": True, "sources": []})
        if source not in row["sources"]:
            row["sources"].append(source)

    for name in os.environ:
        if name in WATCHED_ENV_NAMES:
            add(name, {"source_type": "process_environment"})
    local_files = []
    for path in LOCAL_SECRET_FILES:
        file_names = scan_assignment_names_only(path)
        relevant_file_names = {name for name in file_names if name in WATCHED_ENV_NAMES}
        local_files.append(
                {
                    "file_name": path.name,
                    "relative_path": safe_relative_path(path) if path.exists() else str(path),
                    "exists": path.exists(),
                    "relevant_name_count": len(relevant_file_names),
                "raw_values_read": False,
                "raw_values_printed": False,
            }
        )
        for name in relevant_file_names:
            add(
                name,
                {
                    "source_type": "local_secret_file",
                    "file_name": path.name,
                    "relative_path": safe_relative_path(path) if path.exists() else str(path),
                },
            )
    return {
        "schema_version": "v2_external_source_credential_name_presence_v1",
        "generated_utc": utc_iso(),
        "credential_sources_checked": local_files,
        "names": names,
        "raw_values_read": False,
        "raw_values_printed": False,
    }


def provider_client_status(provider: str) -> dict[str, Any]:
    candidates = list(PROVIDER_CLIENT_CANDIDATES.get(provider, ()))
    existing = [path for path in candidates if (ROOT / path).exists()]
    return {
        "provider": provider,
        "client_exists": bool(existing),
        "candidate_paths_checked": candidates,
        "existing_client_paths": existing,
    }


def safe_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def seed_provider_adapter_task_if_safe(provider: str, source_family: str) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore

    provider_id = safe_id(provider)
    family_id = safe_id(source_family)
    impl_id = f"external_source_reconcile_{provider_id}_{family_id}_adapter_impl"
    codex_id = f"codex_review_{impl_id}"
    lock_group = f"external_source_reconcile_{provider_id}_{family_id}"
    safe_envelope = {
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    impl_task = {
        "task_id": impl_id,
        "task_type": "CLAUDE_IMPLEMENTATION",
        "lane_type": "CLAUDE_IMPLEMENTATION",
        "mission_category": "observation_completeness",
        "lane_group": "proof-claude",
        "owner": "CLAUDE",
        "agent": "claude",
        "status": "pending",
        "file_lock_group": lock_group,
        "paired_task_id": codex_id,
        "safe_envelope": safe_envelope,
        "scope_paths": [
            "v2/backend/app/adapters",
            "v2/backend/app/services/rl_core",
            "v2/backend/tests",
        ],
        "prompt": (
            f"Implement a disabled-by-default V2 external-source adapter for {provider} "
            f"covering {source_family}. Use env var names only in logs/artifacts. Do not "
            "read or print raw credential values. Do not activate paid feeds. Do not write "
            "old Redis. Do not call exchange mutation. Do not enable live/canary/shutdown. "
            "Keep live_gate=blocked_human_only and live_symbols=[]."
        ),
    }
    codex_task = {
        "task_id": codex_id,
        "task_type": "CODEX_REVIEW",
        "lane_type": "CODEX_REVIEW",
        "mission_category": "observation_completeness",
        "lane_group": "proof-codex",
        "owner": "CODEX",
        "agent": "codex",
        "status": "pending",
        "file_lock_group": lock_group,
        "paired_task_id": impl_id,
        "depends_on_task_id": impl_id,
        "safe_envelope": safe_envelope,
        "scope_paths": ["v2/backend/app", "v2/backend/tests", "claude_worklog/final_readiness"],
        "prompt": (
            f"Review {impl_id}. Verify no raw credential values, no paid-feed activation, "
            "no old Redis writes, no exchange mutation, no live/canary/shutdown approvals, "
            "and no fake external-source completion without real payload/data."
        ),
    }
    store = SQLiteLeaseStore()
    try:
        if store.get_task(impl_id) or store.get_task(codex_id):
            return {
                "seeded": False,
                "status": "EXISTING_TASK_REFERENCED",
                "implementation_task_id": impl_id,
                "codex_review_task_id": codex_id,
            }
        store.create_task(impl_task, status="pending")
        store.create_task(codex_task, status="pending")
    finally:
        store.close()
    TASK_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    (TASK_MIRROR_DIR / f"{impl_id}.json").write_text(
        json.dumps(impl_task, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (TASK_MIRROR_DIR / f"{codex_id}.json").write_text(
        json.dumps(codex_task, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "seeded": True,
        "status": "NEW_PAIRED_TASKS_SEEDED",
        "implementation_task_id": impl_id,
        "codex_review_task_id": codex_id,
    }


def reconcile_sources(name_index: dict[str, Any], *, seed_tasks: bool = True) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    external_packet = read_json(EXTERNAL_PACKET, {"items": []})
    present_names = name_index.get("names", {})
    provider_clients = {provider: provider_client_status(provider) for provider in PROVIDER_ALIASES}
    seed_rows: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = []

    for item in external_packet.get("items", []):
        family_rows = []
        family_payload_complete_count = 0
        for family in item.get("source_families", []):
            provider_rows = []
            family_key_present = False
            family_client_missing_with_key = False
            for provider in SOURCE_FAMILY_PROVIDERS.get(str(family), ()):
                alias_names = list(PROVIDER_ALIASES[provider]["alias_env_var_names"])
                all_present_aliases = [name for name in alias_names if name in present_names]
                local_present_aliases = [
                    name
                    for name in all_present_aliases
                    if any(
                        source.get("source_type") == "local_secret_file"
                        for source in present_names.get(name, {}).get("sources", [])
                    )
                ]
                present_aliases = local_present_aliases or all_present_aliases
                source_names = sorted(
                    {
                        source.get("relative_path") or source.get("source_type")
                        for name in present_aliases
                        for source in present_names.get(name, {}).get("sources", [])
                    }
                )
                client = provider_clients[provider]
                key_present = bool(present_aliases)
                family_key_present = family_key_present or key_present
                client_missing_with_key = key_present and not client["client_exists"]
                family_client_missing_with_key = family_client_missing_with_key or client_missing_with_key
                seed_status = {"seeded": False, "status": "NOT_NEEDED_OR_NOT_SAFE"}
                if client_missing_with_key and seed_tasks:
                    seed_status = seed_provider_adapter_task_if_safe(provider, str(family))
                    seed_rows.append(
                        {
                            "provider": provider,
                            "source_family": family,
                            **seed_status,
                        }
                    )
                provider_rows.append(
                    {
                        "provider": provider,
                        "canonical_env_var_name": PROVIDER_ALIASES[provider]["canonical_env_var_name"],
                        "alias_env_var_names_checked": alias_names,
                        "key_present_by_name": key_present,
                        "present_env_alias_names": present_aliases,
                        "presence_sources_by_name_only": source_names,
                        "client_exists": client["client_exists"],
                        "client_missing_with_key_present": client_missing_with_key,
                        "paid_tier_operator_gated": True,
                        "implementation_task_seed_status": seed_status.get("status"),
                        "implementation_task_id": seed_status.get("implementation_task_id"),
                        "codex_review_task_id": seed_status.get("codex_review_task_id"),
                        "raw_values_read": False,
                        "raw_values_printed": False,
                    }
                )
            if not family_key_present:
                classification = "SOURCE_MISSING_KEY_OPERATOR_REQUIRED"
            elif family_client_missing_with_key:
                classification = "SOURCE_KEY_PRESENT_CLIENT_MISSING_TASK_SEEDED_OR_REFERENCED"
            else:
                classification = "SOURCE_KEY_PRESENT_OPERATOR_OR_DATA_PAYLOAD_REQUIRED"
            family_rows.append(
                {
                    "source_family": family,
                    "classification": classification,
                    "key_present_by_name": family_key_present,
                    "provider_rows": provider_rows,
                    "source_marked_complete": False,
                    "payload_or_data_present": False,
                    "paid_tier_operator_gated": True,
                }
            )
        source_items.append(
            {
                "blocker_id": item.get("blocker_id"),
                "source_requirement": item.get("source_requirement"),
                "family_rows": family_rows,
                "source_marked_complete": family_payload_complete_count > 0,
                "source_completion_without_payload": False,
                "operator_accepted": False,
            }
        )

    provider_gap_status = {
        "schema_version": "v2_external_source_provider_client_gap_status_v1",
        "generated_utc": utc_iso(),
        "providers": provider_clients,
        "providers_with_key_present_client_missing": sorted(
            {
                row["provider"]
                for item in source_items
                for family in item["family_rows"]
                for row in family["provider_rows"]
                if row["client_missing_with_key_present"]
            }
        ),
        "safety": SAFETY,
    }
    seed_status = {
        "schema_version": "v2_external_source_safe_task_seed_status_v1",
        "generated_utc": utc_iso(),
        "seed_rows": seed_rows,
        "seeded_or_referenced_count": len(seed_rows),
        "paid_feed_activation_attempted": False,
        "safety": SAFETY,
    }
    reconciliation = {
        "schema_version": "v2_external_source_wait_credential_reconciliation_status_v1",
        "generated_utc": utc_iso(),
        "lane_id": LANE_ID,
        "alias_mappings_checked": True,
        "items": source_items,
        "raw_values_read": False,
        "raw_values_printed": False,
        "raw_key_values_exposed": False,
        "external_source_marked_complete_without_payload_count": 0,
        "safety": SAFETY,
    }
    return reconciliation, provider_gap_status, seed_status


def build_impact_matrix(reconciliation: dict[str, Any]) -> dict[str, Any]:
    family_matrix = read_json(FAMILY_MATRIX, {})
    existing_rows = {
        row.get("family_id"): row
        for row in family_matrix.get("matrix", [])
        if isinstance(row, dict) and row.get("family_id")
    }
    rows = []
    for item in reconciliation.get("items", []):
        for family in item.get("family_rows", []):
            source_family = family["source_family"]
            matrix_row = None
            for lookup_key in (
                str(source_family),
                str(source_family).replace("unified_feature_family.", "unified_features."),
                str(source_family).replace("unified_feature_family.", ""),
            ):
                matrix_row = existing_rows.get(lookup_key)
                if matrix_row:
                    break
            rows.append(
                {
                    "source_family": source_family,
                    "classification": family["classification"],
                    "key_present_by_name": family["key_present_by_name"],
                    "blocks_full_observation": True,
                    "blocks_model_edge": True,
                    "source_marked_complete": False,
                    "payload_or_data_present": False,
                    "claim_1911_dim_completion": False,
                    "existing_family_matrix_reference": matrix_row.get("current_status_source") if matrix_row else None,
                    "external_keys_required_by_name": matrix_row.get("external_keys_required_by_name", []) if matrix_row else [],
                }
            )
    return {
        "schema_version": "v2_full_observation_external_source_impact_matrix_v1",
        "generated_utc": utc_iso(),
        "rows": rows,
        "source_marked_complete_without_payload_count": 0,
        "full_observation_completion_claimed": False,
        "model_edge_completion_claimed": False,
        "safety": SAFETY,
    }


def build_status(
    reconciliation: dict[str, Any],
    provider_gaps: dict[str, Any],
    seed_status: dict[str, Any],
    impact_matrix: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if reconciliation["external_source_marked_complete_without_payload_count"]:
        blockers.append("EXTERNAL_SOURCE_MARKED_COMPLETE_WITHOUT_PAYLOAD")
    go_no_go = GO_BLOCKED if blockers else GO_READY
    return {
        "schema_version": "v2_external_source_wait_credential_reconciliation_operator_dashboard_v1",
        "generated_utc": utc_iso(),
        "lane_id": LANE_ID,
        "go_no_go": go_no_go,
        "ready": go_no_go == GO_READY,
        "root_cause_remains_true_external_source_wait": True,
        "alias_mappings_checked": reconciliation["alias_mappings_checked"],
        "external_source_marked_complete_without_payload_count": reconciliation[
            "external_source_marked_complete_without_payload_count"
        ],
        "providers_with_key_present_client_missing": provider_gaps[
            "providers_with_key_present_client_missing"
        ],
        "seeded_or_referenced_count": seed_status["seeded_or_referenced_count"],
        "full_observation_impact_row_count": len(impact_matrix["rows"]),
        "blockers": blockers,
        "raw_values_read": False,
        "raw_values_printed": False,
        "raw_key_values_exposed": False,
        "paid_feed_activation_attempted": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "safety": SAFETY,
    }


def write_report(status: dict[str, Any], reconciliation: dict[str, Any]) -> None:
    lines = [
        "# V2 External Source Wait Credential Reconciliation",
        "",
        f"Generated: {status['generated_utc']}",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "This packet checks external-source credential presence by env var name and alias only.",
        "It does not read or print raw credential values and does not activate paid feeds.",
        "",
        "## Summary",
        "",
        f"- alias_mappings_checked: `{status['alias_mappings_checked']}`",
        f"- providers_with_key_present_client_missing: `{status['providers_with_key_present_client_missing']}`",
        f"- seeded_or_referenced_count: `{status['seeded_or_referenced_count']}`",
        f"- external_source_marked_complete_without_payload_count: `{status['external_source_marked_complete_without_payload_count']}`",
        "",
        "## Safety",
        "",
        "- `live_gate=blocked_human_only`",
        "- `live_symbols=[]`",
        "- no live/canary/shutdown approval",
        "- no old Redis writes",
        "- no exchange mutation",
        "- no raw credential values",
    ]
    for item in reconciliation.get("items", []):
        lines.extend(["", f"## {item['blocker_id']}", ""])
        for family in item.get("family_rows", []):
            lines.append(
                f"- {family['source_family']}: {family['classification']} "
                f"(key_present_by_name={family['key_present_by_name']})"
            )
    (WORKLOG_DIR / "V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    shutil.copy2(
        WORKLOG_DIR / "V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_REPORT.md",
        PUBLIC_DIR / "V2_EXTERNAL_SOURCE_WAIT_CREDENTIAL_RECONCILIATION_REPORT.md",
    )


def run_once(*, seed_tasks: bool = True) -> dict[str, Any]:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    name_index = build_name_presence_index()
    reconciliation, provider_gaps, seed_status = reconcile_sources(name_index, seed_tasks=seed_tasks)
    impact_matrix = build_impact_matrix(reconciliation)
    status = build_status(reconciliation, provider_gaps, seed_status, impact_matrix)

    (WORKLOG_DIR / "GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    (PUBLIC_DIR / "GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    mirror_json("credential_name_presence_by_source.json", name_index)
    mirror_json("external_source_alias_reconciliation_status.json", reconciliation)
    mirror_json("provider_client_gap_status.json", provider_gaps)
    mirror_json("safe_external_source_task_seed_status.json", seed_status)
    mirror_json("full_observation_external_source_impact_matrix.json", impact_matrix)
    mirror_json("operator_dashboard_payload.json", status)
    write_report(status, reconciliation)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-seed", action="store_true")
    args = parser.parse_args(argv)
    status = run_once(seed_tasks=not args.no_seed)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["go_no_go"] == GO_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
