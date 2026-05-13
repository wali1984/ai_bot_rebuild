from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.evidence.account_permission_contract import (
    LIVE_GATE_STATUS,
    classify_account_payloads,
    load_json_payloads,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_independent_v2_support" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_independent_v2_support" / "latest"


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def account_evidence_paths(root: Path) -> list[Path]:
    candidates = [
        root / "v2" / "frontend" / "public" / "account_permission_and_soak" / "latest" / "operator_dashboard_payload.json",
        root / "v2" / "frontend" / "public" / "readonly_market_exchange_data_plane" / "latest" / "operator_dashboard_payload.json",
        root / "v2" / "frontend" / "public" / "v2_live_observer_shadow_twin" / "latest" / "operator_dashboard_payload.json",
        root / "v2" / "frontend" / "public" / "operator_runtime" / "live_observer" / "latest" / "current_runtime_truth_payload.json",
        root / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "risk_runtime_payload.json",
        root / "claude_worklog" / "final_readiness" / "account_permission_and_soak" / "latest" / "operator_dashboard_payload.json",
    ]
    return [path for path in candidates if path.exists()]


def build_status(root: Path = REPO_ROOT) -> dict[str, Any]:
    paths = account_evidence_paths(root)
    payloads = load_json_payloads(paths, root=root)
    status = classify_account_payloads(now=datetime.now(timezone.utc), payloads=payloads).to_dict()
    status.update(
        {
            "codex_lane": "CODEX_INDEPENDENT_BUILDER_LANE_ACTIVE",
            "live_gate": LIVE_GATE_STATUS,
            "exchange_mutation_performed": False,
            "old_redis_write_performed": False,
            "private_key_printed": False,
            "api_key_dumped": False,
        }
    )
    return status


def build_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Account Permission Contract Report",
            "",
            f"Generated: {payload['generated_at']}",
            f"Live gate: `{payload['live_gate']}`",
            f"Account evidence: `{payload['account_evidence_status']}`",
            f"Trade permission: `{payload['trade_permission_status']}`",
            f"Margin evidence: `{payload['margin_evidence_status']}`",
            f"Leverage evidence: `{payload['leverage_evidence_status']}`",
            f"Mutation guard: `{payload['mutation_guard_status']}`",
            f"Canary ready: `{payload['canary_ready']}`",
            "",
            "Classifications:",
            *(f"- `{item}`" for item in payload["classifications"]),
            "",
            "Canary blockers:",
            *(f"- `{item}`" for item in payload["canary_blockers"] or ["none"]),
            "",
            "Evidence sources:",
            *(f"- `{item}`" for item in payload["source_paths"] or ["none"]),
            "",
            "The checker reads public evidence only and does not call exchange mutation APIs.",
        ]
    )


def write_outputs(payload: dict[str, Any]) -> None:
    _write_json(FINAL_DIR / "account_permission_contract_status.json", payload)
    _write_json(PUBLIC_DIR / "account_permission_contract_status.json", payload)
    _write_text(FINAL_DIR / "ACCOUNT_PERMISSION_CONTRACT_REPORT.md", build_report(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify account and permission evidence safely.")
    parser.add_argument("--write", action="store_true", help="write contract artifacts")
    args = parser.parse_args(argv)
    payload = build_status(REPO_ROOT)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
