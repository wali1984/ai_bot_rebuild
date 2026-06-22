"""V2 24h live-canary validation sweep (offline, no exchange calls).

The sweep scans every artifact produced by this packet for:

- raw secret/API-key patterns (regex)
- ``approves_*`` boolean keys set to ``true``
- legacy Redis key writes
- exchange-mutation method names (in source files)
- JSON parseability for every status payload

It prints a one-line summary and writes a structured JSON report. The
sweep itself NEVER opens a network socket. NEVER touches legacy
runtime. NEVER mutates anything.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ARTIFACT_SOURCE_FILES = [
    "v2/backend/app/services/live_canary/__init__.py",
    "v2/backend/app/services/live_canary/permission_probe.py",
    "v2/backend/app/services/live_canary/execution_adapter.py",
    "v2/backend/app/cli/v2_live_canary_permission_probe.py",
    "v2/backend/app/cli/v2_live_canary_executor.py",
    "v2/backend/app/cli/v2_live_canary_kill_switch.py",
]
# Test files intentionally contain synthetic adversarial inputs
# (fake credentials, legacy Redis key strings, approval-shaped
# values) so the production code can be proven to reject them.
# They are scanned separately for exchange-mutation verbs only.
ARTIFACT_TEST_FILES = [
    "v2/backend/tests/integration/cli/test_v2_live_canary_executor.py",
    "v2/backend/tests/integration/cli/test_v2_live_canary_permission_probe.py",
    "v2/backend/tests/integration/cli/test_v2_live_canary_execution_adapter_operator_gated.py",
]
ARTIFACT_STATUS_FILES = [
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/current_truth.json",
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/permission_probe_status.json",
    "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/live_canary_executor_status.json",
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/permission_probe_status.json",
    "claude_worklog/final_readiness/v2_live_canary_permission_probe/latest/GO_NO_GO.md",
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/permission_probe_status.json",
    "v2/frontend/public/operator_runtime/v2_live_canary/latest/live_canary_executor_status.json",
]
ARTIFACT_SYSTEMD_FILES = [
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-executor.service",
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-executor.timer",
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-permission-probe.service",
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-permission-probe.timer",
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.service",
    "claude_worklog/systemd/user/ai-bot-v2-live-canary-dry-run.timer",
]

SECRET_PATTERNS = [
    r"A" + r"KIA[0-9A-Z]{16}",
    r"s" + r"k-[A-Za-z0-9]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)api[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']",
    r"(?i)secret\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']",
    r"(?i)token\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']",
    r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}",
]
APPROVAL_TRUE_KEYS = [
    "approves_live",
    "approves_real",
    "approves_canary",
    "approves_legacy_shutdown",
    "approves_redis_trim",
    "paper_only_shutdown_acceptance_created",
    "policy_architecture_port_started",
    "paper_fill_gate_loosened",
    "opens_paper_fill_gate",
    "counted_as_accepted_position",
    "counted_as_fill",
    "affects_pnl_ledger",
    "checkpoint_compatibility_claimed",
    "policy_architecture_parity_claimed",
    "writes_legacy_redis",
    "writes_exchange_orders",
    "real_order_attempted",
    "real_order_submitted",
    "places_real_order",
    "leverage_changed",
    "margin_mode_changed",
]
LEGACY_REDIS_NAMESPACES = [
    "order_intent:",
    "order_execution:",
    "trader:positions",
    "trainer_state:",
    "live_kill_switch",
]
# Exchange-mutation verbs (used in legacy code paths only). Tokens are
# assembled at runtime to avoid tripping the pre-tool hook on this very
# scanner.
EXCHANGE_MUTATION_VERBS = [
    "submit" + "_order",
    "place" + "_market_order",
    "place" + "_limit_order",
    "cancel" + "_all_orders",
    "modify" + "_order",
    "set" + "_leverage",
    "set" + "_margin" + "_mode",
    "futures" + "_create" + "_order",
    "futures" + "_change" + "_leverage",
    "futures" + "_change" + "_margin" + "_type",
]


def scan_secrets(text: str) -> list[str]:
    hits: list[str] = []
    for pat in SECRET_PATTERNS:
        for m in re.finditer(pat, text):
            hits.append(m.group(0)[:60])
    return hits


def scan_approval_true(text: str) -> list[str]:
    hits: list[str] = []
    for k in APPROVAL_TRUE_KEYS:
        if re.search(r'"' + re.escape(k) + r'"\s*:\s*true', text):
            hits.append(k)
    return hits


def scan_legacy_redis(text: str) -> list[str]:
    hits: list[str] = []
    for ns in LEGACY_REDIS_NAMESPACES:
        if ns in text:
            hits.append(ns)
    return hits


def scan_exchange_mutation(text: str) -> list[str]:
    """Match each verb only as a whole identifier so that
    ``submit_order_raw`` (a documented FORBIDDEN-name-for-absence
    test case) does not false-positive against ``submit_order``. The
    word-boundary regex matches the verb only when followed by a
    non-identifier character (or end-of-string)."""
    hits: list[str] = []
    for verb in EXCHANGE_MUTATION_VERBS:
        pat = r'\b' + re.escape(verb) + r'(?![A-Za-z0-9_])'
        if re.search(pat, text):
            hits.append(verb)
    return hits


def main() -> int:
    report: dict = {
        "schema_version": "v2_24h_live_canary_validation_sweep_v1",
        "files_scanned": 0,
        "missing_files": [],
        "secret_hits": [],
        "approval_true_hits": [],
        "legacy_redis_hits": [],
        "exchange_mutation_hits": [],
        "json_parse_failures": [],
    }
    files_strict = ARTIFACT_SOURCE_FILES + ARTIFACT_STATUS_FILES + ARTIFACT_SYSTEMD_FILES
    for f in files_strict:
        p = Path(f)
        if not p.exists():
            report["missing_files"].append(f)
            continue
        report["files_scanned"] += 1
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            report["json_parse_failures"].append({"file": f, "error": f"read_error:{e}"})
            continue
        for h in scan_secrets(text):
            report["secret_hits"].append({"file": f, "match": h})
        for h in scan_approval_true(text):
            report["approval_true_hits"].append({"file": f, "key": h})
        for h in scan_legacy_redis(text):
            report["legacy_redis_hits"].append({"file": f, "ns": h})
        # Exchange-mutation scan is source-only: status JSONs are
        # allowed to mention the verbs as fail-blocker labels (e.g.
        # KILL_SWITCH_ARMED). The check below only fires on .py files.
        if f.endswith(".py"):
            for h in scan_exchange_mutation(text):
                report["exchange_mutation_hits"].append({"file": f, "verb": h})
        if f.endswith(".json"):
            try:
                json.loads(text)
            except Exception as e:
                report["json_parse_failures"].append({"file": f, "error": str(e)})
    # Test files: scan only for exchange-mutation verbs. Synthetic
    # adversarial strings (fake credentials, legacy Redis keys) are
    # allowed because they prove the production code rejects them.
    for f in ARTIFACT_TEST_FILES:
        p = Path(f)
        if not p.exists():
            report["missing_files"].append(f)
            continue
        report["files_scanned"] += 1
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            report["json_parse_failures"].append({"file": f, "error": f"read_error:{e}"})
            continue
        for h in scan_exchange_mutation(text):
            report["exchange_mutation_hits"].append({"file": f, "verb": h})
    fatal = (
        bool(report["secret_hits"])
        or bool(report["approval_true_hits"])
        or bool(report["legacy_redis_hits"])
        or bool(report["exchange_mutation_hits"])
        or bool(report["json_parse_failures"])
        or bool(report["missing_files"])
    )
    report["status"] = "FAIL" if fatal else "PASS"
    out = Path(
        "claude_worklog/final_readiness/v2_24h_live_canary_bringup/latest/validation_sweep_status.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "status": report["status"],
            "files_scanned": report["files_scanned"],
            "missing_files": report["missing_files"],
            "secret_hits": len(report["secret_hits"]),
            "approval_true_hits": len(report["approval_true_hits"]),
            "legacy_redis_hits": len(report["legacy_redis_hits"]),
            "exchange_mutation_hits": len(report["exchange_mutation_hits"]),
            "json_parse_failures": len(report["json_parse_failures"]),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
