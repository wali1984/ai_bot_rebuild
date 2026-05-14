#!/usr/bin/env python3
"""Patch V2 worker/review descriptors with the symbol-universe contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
FINAL_APPROVAL_TOKEN = (
    REPO_ROOT / "claude_worklog" / "approvals" / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
)
REDIS_TRIM_APPROVAL = (
    REPO_ROOT
    / "claude_worklog"
    / "approvals"
    / "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
)

CONTRACT_ID = "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"

CONTRACT_FORBIDDEN = [
    "hardcoded_current_25_symbols_as_full_universe",
    "train_or_trade_all_discovered_symbols_automatically",
    "coinank_symbols_treated_as_tradable_without_binance_usdm_confirmation",
]

CONTRACT_TESTS = [
    "symbol_universe_contract_required",
    "symbol_scope_roles_distinguished",
    "no_hardcoded_current_25_symbols_as_full_universe",
    "no_train_or_trade_all_discovered_symbols_automatically",
    "coinank_symbols_require_binance_usdm_confirmation_before_tradable",
]

CONTRACT_PUBLIC_FIELDS = [
    "symbol_universe_contract",
    "symbol_universe_source_path",
    "legacy_active_symbols",
    "discovered_symbols",
    "observed_symbols",
    "training_symbols",
    "paper_symbols",
    "live_blocked_symbols",
    "binance_usdm_confirmed_symbols",
]

CONTRACT_PROMPT = (
    "\n\nSYMBOL_UNIVERSE_CONTRACT_REQUIRED. Every V2 worker must read active "
    "symbol scope from the V2 Symbol Universe service "
    "(`v2/backend/app/services/symbol_universe/service.py`) or from a V2 "
    "public symbol-universe payload if present. If the public payload is absent, "
    "classify it as MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD and still use the "
    "service contract instead of hardcoding scope. The worker output and tests "
    "must distinguish `legacy_active_symbols`, `discovered_symbols`, "
    "`observed_symbols`, `training_symbols`, `paper_symbols`, and "
    "`live_blocked_symbols`. No worker may hardcode the current 25 symbols as "
    "the full universe. No worker may train or trade all discovered symbols "
    "automatically. CoinAnk symbols are market-intelligence candidates only "
    "until confirmed by Binance USD-M tradability evidence; do not treat "
    "CoinAnk symbols as directly tradable without Binance USD-M confirmation."
)

CODEX_REVIEW_PROMPT = (
    "\n\nSYMBOL_UNIVERSE_CONTRACT_REQUIRED REVIEW GATE. Fail this review if the "
    "worker does not read symbol scope from the V2 Symbol Universe service or a "
    "V2 public symbol-universe payload, if it fails to distinguish "
    "`legacy_active_symbols`, `discovered_symbols`, `observed_symbols`, "
    "`training_symbols`, `paper_symbols`, and `live_blocked_symbols`, if it "
    "hardcodes the current 25 symbols as the full universe, if it trains/trades "
    "all discovered symbols automatically, or if it treats CoinAnk symbols as "
    "directly tradable without Binance USD-M confirmation. Missing public "
    "symbol-universe payload must be reported as an evidence gap, not replaced "
    "by hardcoded truth."
)


def append_unique(values: list[Any], item: Any) -> bool:
    if item not in values:
        values.append(item)
        return True
    return False


def patch_descriptor(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    task_id = str(data.get("task_id") or "")
    agent = str(data.get("agent") or "")
    if agent not in {"claude", "codex"}:
        return False
    if not (task_id.startswith("claude_port_v2") or task_id.startswith("codex_review_v2")):
        return False

    changed = False

    data["symbol_universe_contract"] = CONTRACT_ID
    changed = True

    forbidden = data.setdefault("forbidden", [])
    if isinstance(forbidden, list):
        for item in CONTRACT_FORBIDDEN:
            changed |= append_unique(forbidden, item)

    if agent == "claude":
        tests = data.setdefault("required_tests", [])
        if isinstance(tests, list):
            for item in CONTRACT_TESTS:
                changed |= append_unique(tests, item)

        fields = data.setdefault("required_public_payload_fields", [])
        if isinstance(fields, list):
            for item in CONTRACT_PUBLIC_FIELDS:
                changed |= append_unique(fields, item)

        required_inputs = data.setdefault("required_input_files", [])
        if isinstance(required_inputs, list):
            changed |= append_unique(required_inputs, "v2/backend/app/services/symbol_universe/service.py")

        prompt = str(data.get("prompt") or "")
        if CONTRACT_ID not in prompt:
            data["prompt"] = prompt + CONTRACT_PROMPT
            changed = True

    if agent == "codex":
        fail_conditions = data.setdefault("fail_conditions", [])
        if isinstance(fail_conditions, list):
            for item in [
                "symbol_universe_contract_missing",
                "symbol_scope_roles_not_distinguished",
                "hardcoded_current_25_symbols_as_full_universe",
                "train_or_trade_all_discovered_symbols_automatically",
                "coinank_symbols_tradable_without_binance_usdm_confirmation",
                "missing_symbol_universe_public_payload_hidden_or_mocked",
            ]:
                changed |= append_unique(fail_conditions, item)

        required_inputs = data.setdefault("required_input_files", [])
        if isinstance(required_inputs, list):
            changed |= append_unique(required_inputs, "v2/backend/app/services/symbol_universe/service.py")

        prompt = str(data.get("prompt") or "")
        if CONTRACT_ID not in prompt:
            data["prompt"] = prompt + CODEX_REVIEW_PROMPT
            changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    if FINAL_APPROVAL_TOKEN.exists():
        raise SystemExit(f"FINAL_APPROVAL_TOKEN_PRESENT: {FINAL_APPROVAL_TOKEN}")
    if REDIS_TRIM_APPROVAL.exists():
        raise SystemExit(f"REDIS_TRIM_APPROVAL_PRESENT: {REDIS_TRIM_APPROVAL}")

    paths = list(TASKS_DIR.glob("claude_port_v2*.json")) + list(TASKS_DIR.glob("codex_review_v2*.json"))
    changed_paths = [str(p.relative_to(REPO_ROOT)) for p in sorted(paths) if patch_descriptor(p)]
    print(json.dumps({"contract": CONTRACT_ID, "changed_count": len(changed_paths), "changed": changed_paths}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
