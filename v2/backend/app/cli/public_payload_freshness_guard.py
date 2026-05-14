from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_independent_v2_support" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_independent_v2_support" / "latest"
DEFAULT_STALE_AFTER_SECONDS = 15 * 60


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_seconds(now: datetime, value: Any) -> int | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _payload_paths(root: Path) -> list[Path]:
    public = root / "v2" / "frontend" / "public"
    paths: set[Path] = set()
    operator_runtime = public / "operator_runtime"
    if operator_runtime.exists():
        paths.update(path for path in operator_runtime.rglob("*.json") if path.is_file())
    paths.update(path for path in public.glob("*/latest/operator_dashboard_payload.json") if path.is_file())
    return sorted(paths)


def _go_no_go_paths(root: Path) -> list[Path]:
    return sorted((root / "claude_worklog" / "final_readiness").glob("*/latest/GO_NO_GO.md"))


def _walk(payload: Any, path: str = "$") -> list[tuple[str, Any]]:
    if isinstance(payload, dict):
        rows: list[tuple[str, Any]] = []
        for key, value in payload.items():
            rows.append((f"{path}.{key}", value))
            rows.extend(_walk(value, f"{path}.{key}"))
        return rows
    if isinstance(payload, list):
        rows = []
        for index, value in enumerate(payload):
            rows.append((f"{path}[{index}]", value))
            rows.extend(_walk(value, f"{path}[{index}]"))
        return rows
    return []


def _string_values(payload: Any) -> list[str]:
    return [str(value) for _, value in _walk(payload) if isinstance(value, str)]


def _has_source(payload: dict[str, Any]) -> bool:
    for path, value in _walk(payload):
        key = path.rsplit(".", 1)[-1].lower()
        if key in {
            "source",
            "sources",
            "source_path",
            "source_paths",
            "source_payload_path",
            "source_files",
            "evidence_source",
            "worker_id",
        } and value:
            return True
    return False


def _has_required_evidence(payload: dict[str, Any]) -> bool:
    keys = {path.rsplit(".", 1)[-1].lower() for path, _ in _walk(payload)}
    if {"generated_at", "source_paths"} & keys or {"evidence_status", "classifications"} & keys:
        return True
    if any(key.endswith("evidence_status") for key in keys):
        return True
    runtime_source_keys = {
        "source_payload_path",
        "source_files",
        "source_ingestor_refs",
        "source_key_refs",
        "source_snapshot_ids",
        "last_snapshot_id",
    }
    return bool(runtime_source_keys & keys)


def _approval_token_exists(root: Path) -> bool:
    approvals = root / "claude_worklog" / "approvals"
    return (approvals / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md").exists()


def inspect_payload(path: Path, payload: dict[str, Any], *, root: Path, now: datetime, stale_after_seconds: int) -> dict[str, Any]:
    generated_at = (
        payload.get("generated_at")
        or payload.get("last_run_ts")
        or payload.get("updated_at")
        or payload.get("timestamp")
        or payload.get("last_tick_at")
    )
    age = _age_seconds(now, generated_at)
    findings: list[str] = []
    if age is None:
        findings.append("MISSING_GENERATED_AT")
    elif age > stale_after_seconds:
        findings.append("STALE_PAYLOAD")
    if not _has_source(payload):
        findings.append("MISSING_SOURCE")

    strings = " ".join(_string_values(payload))
    lowered = strings.lower()
    for field_path, value in _walk(payload):
        key = field_path.rsplit(".", 1)[-1]
        if key.startswith("hist_") and "current" in field_path.lower() and value not in (None, "", [], {}):
            findings.append("HISTORICAL_FIELD_USED_AS_CURRENT")
            break
    current_paths = [
        str(value)
        for field_path, value in _walk(payload)
        if "current" in field_path.lower() and isinstance(value, str)
    ]
    current_text = " ".join(current_paths)
    if "STATIC_PROOF_FIXTURE" in current_text:
        findings.append("STATIC_PROOF_FIXTURE_USED_AS_CURRENT_TRUTH")
    if "DESIGN_MOCK_DATA" in current_text:
        findings.append("DESIGN_MOCK_DATA_USED_AS_CURRENT_TRUTH")

    live_gate_values = [
        str(value)
        for field_path, value in _walk(payload)
        if field_path.rsplit(".", 1)[-1] in {"live_gate", "live_gate_status", "live_status"}
    ]
    if any(value != "blocked_human_only" for value in live_gate_values):
        findings.append("LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY")

    if any("READY" in value for value in _string_values(payload)) and not _has_required_evidence(payload):
        findings.append("READY_CLAIM_WITH_MISSING_EVIDENCE")
    profitability_alive_claim = (
        "paper_runtime_alive" in lowered and "profitability" in lowered and "proof" in lowered
    )
    profitability_alive_negated = any(
        marker in lowered
        for marker in {
            "paper_runtime_alive_not_called_profitability_proof",
            "not called profitability proof",
            "does not claim profitability proof",
            "profitability proof pending",
            "profitability_proof_pending",
            "profitability_proof_status\": \"profitability_proof_pending",
            "simulated fills are not profitability proof",
            "simulated_fills_are_not_profitability_proof",
        }
    )
    if profitability_alive_claim and not profitability_alive_negated:
        findings.append("PAPER_RUNTIME_ALIVE_CALLED_PROFITABILITY_PROOF")
    if "backlog" in lowered and "migrated" in lowered:
        findings.append("BACKLOG_CALLED_MIGRATION")

    return {
        "path": _rel(root, path),
        "generated_at": generated_at,
        "age_seconds": age,
        "findings": sorted(set(findings)),
        "status": "PASS" if not findings else "BLOCKED",
    }


def inspect_go_no_go(path: Path, *, root: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except OSError:
        text = ""
    findings: list[str] = []
    if "READY" in text and "evidence missing" in text.lower():
        findings.append("READY_CLAIM_WITH_MISSING_EVIDENCE")
    if "backlog" in text.lower() and "migrated" in text.lower():
        findings.append("BACKLOG_CALLED_MIGRATION")
    return {
        "path": _rel(root, path),
        "findings": findings,
        "status": "PASS" if not findings else "BLOCKED",
    }


def build_guard(
    root: Path = REPO_ROOT,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    payload_results = [
        inspect_payload(path, payload, root=root, now=now, stale_after_seconds=stale_after_seconds)
        for path in _payload_paths(root)
        if (payload := _read_json(path)) is not None
    ]
    go_no_go_results = [inspect_go_no_go(path, root=root) for path in _go_no_go_paths(root)]
    approval_token_created = _approval_token_exists(root)
    findings = [
        finding
        for result in payload_results + go_no_go_results
        for finding in result["findings"]
    ]
    if approval_token_created:
        findings.append("APPROVAL_TOKEN_CREATED")
    unique_findings = sorted(set(findings))
    return {
        "generated_at": _iso_now(),
        "result": "PASS" if not unique_findings else "BLOCKED",
        "live_gate": "blocked_human_only",
        "stale_after_seconds": stale_after_seconds,
        "payloads_checked": len(payload_results),
        "go_no_go_files_checked": len(go_no_go_results),
        "approval_token_created": approval_token_created,
        "findings": unique_findings,
        "payload_results": payload_results,
        "go_no_go_results": go_no_go_results,
        "mutation_performed": False,
    }


def build_report(payload: dict[str, Any]) -> str:
    finding_rows = [
        f"- `{result['path']}`: {', '.join(result['findings'])}"
        for result in payload["payload_results"] + payload["go_no_go_results"]
        if result["findings"]
    ]
    return "\n".join(
        [
            "# Public Payload Freshness Guard Report",
            "",
            f"Generated: {payload['generated_at']}",
            f"Result: `{payload['result']}`",
            f"Live gate: `{payload['live_gate']}`",
            f"Payloads checked: {payload['payloads_checked']}",
            f"GO/NO-GO files checked: {payload['go_no_go_files_checked']}",
            f"Approval token created: `{payload['approval_token_created']}`",
            "",
            "Findings:",
            *(finding_rows or ["- none"]),
            "",
            "The guard is read-only and did not mutate public payloads.",
        ]
    )


def write_outputs(payload: dict[str, Any]) -> None:
    _write_json(FINAL_DIR / "public_payload_freshness_guard.json", payload)
    _write_json(PUBLIC_DIR / "public_payload_freshness_guard.json", payload)
    _write_text(FINAL_DIR / "PUBLIC_PAYLOAD_FRESHNESS_GUARD_REPORT.md", build_report(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate public payload freshness and truth labels.")
    parser.add_argument("--write", action="store_true", help="write guard artifacts")
    parser.add_argument("--stale-after-seconds", type=int, default=DEFAULT_STALE_AFTER_SECONDS)
    args = parser.parse_args(argv)
    payload = build_guard(REPO_ROOT, stale_after_seconds=args.stale_after_seconds)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
