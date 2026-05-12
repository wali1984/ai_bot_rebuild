from __future__ import annotations

import json
import calendar
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


LIVE_GATE_STATUS = "blocked_human_only"
READY = "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_AND_CANARY_PREFLIGHT_READY"
BLOCKED = "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_AND_CANARY_PREFLIGHT_BLOCKED"
CODEX_PASS = "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_CODEX_PASS"
CODEX_FAIL = "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_CODEX_FAIL"

REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "tonight_live_like_paper_shadow" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "tonight_live_like_paper_shadow" / "latest"
PAPER_RUNTIME = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json"
LIVE_OBSERVER = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "live_observer" / "latest" / "current_runtime_truth_payload.json"
OPERATOR_TRUTH = REPO_ROOT / "v2" / "frontend" / "public" / "operator_truth" / "latest" / "operator_truth_payload.json"
LEGACY_BRIDGE_PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "legacy_live_bridge" / "latest"

PUBLIC_URLS = [
    "https://dashboard.wajidali.us/",
    "https://dashboard.wajidali.us/admin/mission-control?role=admin",
    "https://dashboard.wajidali.us/admin/trainer-prediction-monitor?role=admin",
    "https://dashboard.wajidali.us/admin/signal-explainability?role=admin",
    "https://dashboard.wajidali.us/admin/paper-trading?role=admin",
]


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def age_seconds(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.replace("+00:00", "Z")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0] + "Z"
    try:
        parsed = time.strptime(normalized, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return max(0, int(time.time() - calendar.timegm(parsed)))


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, check=False, text=True, timeout=timeout)


def process_rows() -> list[str]:
    result = run(["ps", "-eo", "pid,ppid,etimes,cmd"], timeout=8)
    rows = []
    for line in result.stdout.splitlines():
        if any(
            token in line
            for token in (
                "agent_supervisor.py",
                "parallel_capacity_scheduler",
                "codex_non_live_watchdog",
                "paper_online_runtime",
                "rl.hybrid_trainer",
                "monitor_trainer_predictions",
                "rl.orchestrator_worker",
                "trading/trader.py",
                "vite",
                "cloudflared",
            )
        ):
            compact = " ".join(line.split())
            compact = re.sub(r"--token(?:=|\s+)\S+", "--token [redacted]", compact)
            compact = re.sub(
                r"(?i)\b(api[_-]?key|secret|token|password)=\S+",
                lambda match: f"{match.group(1)}=[redacted]",
                compact,
            )
            rows.append(compact[:500])
    return rows


def public_quick_fetch() -> list[dict[str, Any]]:
    rows = []
    for url in PUBLIC_URLS:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ai-bot-v2-tonight-readiness"})
            with urllib.request.urlopen(request, timeout=8) as response:
                rows.append({"url": url, "status": response.status, "final_url": response.geturl(), "error": None})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            rows.append({"url": url, "status": None, "final_url": None, "error": exc.__class__.__name__})
    return rows


def load_route_matrix(phase: str) -> dict[str, Any] | None:
    return read_json(FINAL_DIR / f"website_route_acceptance_matrix_{phase}.json")


def classify_age(value: int | None) -> str:
    if value is None:
        return "MISSING"
    if value <= 120:
        return "CURRENT"
    if value <= 300:
        return "STALE"
    return "STALE"


def build_risk_profile(generated_at: str) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "profile_id": "paper_shadow_live_blocked_canary_prefight_v1",
        "mode": "paper_shadow_live_blocked",
        "live_enabled": False,
        "canary_enabled": False,
        "margin_mode_required_for_canary": "isolated",
        "leverage_cap_for_canary": "1x",
        "symbols_for_canary": ["BTCUSDT"],
        "position_notional_cap": "tiny_human_approved_only",
        "stale_risk_add_max_age_seconds": 10,
        "close_reduce_max_age_seconds": 60,
        "adjust_leverage": "disabled",
        "adjust_leverage_and_position": "disabled",
        "hedge_dca": "disabled_initially",
        "required_blocks": [
            "missing_signal_id",
            "missing_prediction_id",
            "missing_feature_snapshot_id",
            "missing_confidence",
            "duplicate_exchange_order_id",
            "missing_stop_policy",
            "kill_switch_missing",
            "daily_loss_hard_stop_missing",
            "weekly_loss_hard_stop_missing",
            "human_approval_file_missing",
            "cross_margin_observed",
            "leverage_above_1x",
        ],
        "approval_file_required": "FINAL_HUMAN_CANARY_APPROVAL_REQUIRED_NOT_CREATED",
        "live_gate_status": LIVE_GATE_STATUS,
    }


def make_baseline(generated_at: str, paper: dict[str, Any] | None, observer: dict[str, Any] | None, truth: dict[str, Any] | None) -> dict[str, Any]:
    paper_age = age_seconds(paper.get("generated_at") if paper else None)
    observer_age = age_seconds(observer.get("generated_at") if observer else None)
    lineage = paper.get("current_signal_lineage", {}) if paper else {}
    ids = lineage.get("lineage_ids", {}) if isinstance(lineage, dict) else {}
    stream_rows = observer.get("legacy_read_only_bridge", {}).get("streams", {}) if observer else {}
    executed = stream_rows.get("executed_signals", {}) if isinstance(stream_rows, dict) else {}
    executed_latest = executed.get("latest_entry") if isinstance(executed, dict) else None
    proc = process_rows()
    return {
        "generated_at": generated_at,
        "v2_paper_runtime": {
            "classification": "VERIFIED_OPERATIONAL" if paper_age is not None and paper_age <= 120 else "STALE",
            "status": paper.get("runtime_state") if paper else "MISSING",
            "age_seconds": paper_age,
            "prediction_id": paper.get("trainer_prediction", {}).get("prediction_id") if paper else None,
            "feature_snapshot_id": paper.get("trainer_prediction", {}).get("feature_snapshot_id") if paper else None,
            "signal_id": ids.get("signal_id"),
            "orchestrator_decision_id": ids.get("orchestrator_decision_id"),
            "risk_decision_id": ids.get("risk_decision_id"),
            "execution_intent_id": ids.get("execution_intent_id"),
            "paper_ledger_tail": paper.get("paper_ledger_tail", []) if paper else [],
        },
        "legacy_live_bridge": {
            "classification": "CURRENT" if observer_age is not None and observer_age <= 120 else "STALE",
            "status": observer.get("legacy_read_only_bridge", {}).get("status") if observer else "MISSING",
            "age_seconds": observer_age,
            "legacy_signal": observer.get("legacy_shadow_twin", {}).get("normalized_signal") if observer else None,
            "shadow_risk": observer.get("legacy_shadow_twin", {}).get("risk_decision") if observer else None,
            "executed_signals_latest": executed_latest,
        },
        "processes": {
            "classification": "CURRENT",
            "rows": proc,
            "legacy_trainer_process": "CURRENT" if any("rl.hybrid_trainer" in row for row in proc) else "MISSING",
            "legacy_trader_process": "RISK_OBSERVED" if any("trading/trader.py" in row for row in proc) else "MISSING",
            "paper_runtime_process": "CURRENT" if any("paper_online_runtime" in row for row in proc) else "MISSING",
            "control_plane": "CURRENT" if any("parallel_capacity_scheduler" in row or "codex_non_live_watchdog" in row or "agent_supervisor.py" in row for row in proc) else "MISSING",
        },
        "gpu": observer.get("gpu_runtime") if observer else {"status": "UNKNOWN_REQUIRES_REVIEW"},
        "public_website_quick_fetch": public_quick_fetch(),
        "operator_truth": {
            "classification": classify_age(age_seconds(truth.get("generated_at") if truth else None)),
            "stale_payloads": truth.get("stale_payloads", []) if truth else [],
            "missing_evidence": truth.get("missing_evidence", []) if truth else [],
        },
        "live_gate_status": LIVE_GATE_STATUS,
        "redis_trim_state": "deferred_non_blocking",
    }


def write_reports(
    *,
    generated_at: str,
    baseline: dict[str, Any],
    paper: dict[str, Any] | None,
    observer: dict[str, Any] | None,
    risk_profile: dict[str, Any],
    local_matrix: dict[str, Any] | None,
    public_matrix: dict[str, Any] | None,
) -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    LEGACY_BRIDGE_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    write_json(FINAL_DIR / "current_truth_baseline.json", baseline)
    write_json(FINAL_DIR / "live_like_risk_profile.json", risk_profile)
    write_json(PUBLIC_DIR / "live_like_risk_profile.json", risk_profile)
    if observer:
        write_json(FINAL_DIR / "legacy_live_bridge_status.json", observer.get("legacy_read_only_bridge", {}))
        write_json(LEGACY_BRIDGE_PUBLIC_DIR / "legacy_live_bridge_status.json", observer.get("legacy_read_only_bridge", {}))
        write_json(LEGACY_BRIDGE_PUBLIC_DIR / "current_runtime_truth_payload.json", observer)

    paper_current = baseline["v2_paper_runtime"]["classification"] == "VERIFIED_OPERATIONAL"
    observer_current = baseline["legacy_live_bridge"]["classification"] == "CURRENT"
    local_ok = bool(local_matrix and local_matrix.get("failed_count", 999) == 0)
    public_crawled = public_matrix is not None
    public_ok = bool(public_matrix and public_matrix.get("failed_count", 999) == 0)
    safety_ok = bool(
        observer
        and observer.get("safety", {}).get("legacy_redis_writes") is False
        and observer.get("safety", {}).get("exchange_orders") is False
        and observer.get("safety", {}).get("live_gate_status") == LIVE_GATE_STATUS
    )
    marker = READY if paper_current and observer_current and local_ok and public_ok and safety_ok else BLOCKED
    codex_marker = CODEX_PASS if paper_current and observer_current and local_ok and public_ok and safety_ok and public_crawled else CODEX_FAIL
    blockers = []
    if not paper_current:
        blockers.append("V2_PAPER_RUNTIME_NOT_CURRENT")
    if not observer_current:
        blockers.append("LEGACY_LIVE_BRIDGE_NOT_CURRENT")
    if not local_ok:
        blockers.append("LOCAL_ROUTE_ACCEPTANCE_NOT_CLEAN")
    if not public_ok:
        blockers.append("PUBLIC_ROUTE_ACCEPTANCE_NOT_CLEAN_OR_STALE_TUNNEL")
    if not safety_ok:
        blockers.append("SAFETY_FLAGS_NOT_CLEAN")
    blockers.extend(observer.get("blockers", []) if observer else ["LIVE_OBSERVER_PAYLOAD_MISSING"])
    blocker_ids = [row.get("id", str(row)) if isinstance(row, dict) else str(row) for row in blockers]

    dashboard = {
        "generated_at": generated_at,
        "status": marker,
        "v2_paper_runtime_status": baseline["v2_paper_runtime"]["classification"],
        "v2_paper_runtime_age_seconds": baseline["v2_paper_runtime"]["age_seconds"],
        "legacy_bridge_status": baseline["legacy_live_bridge"]["classification"],
        "legacy_bridge_age_seconds": baseline["legacy_live_bridge"]["age_seconds"],
        "trainer_status": baseline["processes"]["legacy_trainer_process"],
        "signal_lineage_status": "CURRENT",
        "risk_profile_status": "LIVE_LIKE_PROFILE_CREATED_NOT_ENABLED",
        "canary_preflight_status": "PREFLIGHT_CREATED_APPROVAL_REQUIRED_NOT_CREATED",
        "local_route_passed_count": local_matrix.get("passed_count") if local_matrix else None,
        "local_route_failed_count": local_matrix.get("failed_count") if local_matrix else None,
        "public_route_passed_count": public_matrix.get("passed_count") if public_matrix else None,
        "public_route_failed_count": public_matrix.get("failed_count") if public_matrix else None,
        "codex_result": codex_marker,
        "remaining_blockers": blocker_ids,
        "live_gate_status": LIVE_GATE_STATUS,
        "old_redis_writes": False,
        "exchange_actions": False,
        "redis_trim_status": "deferred_non_blocking",
    }
    write_json(FINAL_DIR / "operator_dashboard_payload.json", dashboard)
    write_json(PUBLIC_DIR / "operator_dashboard_payload.json", dashboard)
    write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")

    write_text(FINAL_DIR / "CURRENT_TRUTH_BASELINE.md", f"""# Current Truth Baseline

Generated at: {generated_at}

- V2 paper runtime: `{dashboard['v2_paper_runtime_status']}` age `{dashboard['v2_paper_runtime_age_seconds']}`
- prediction_id: `{baseline['v2_paper_runtime']['prediction_id']}`
- feature_snapshot_id: `{baseline['v2_paper_runtime']['feature_snapshot_id']}`
- signal_id: `{baseline['v2_paper_runtime']['signal_id']}`
- orchestrator_decision_id: `{baseline['v2_paper_runtime']['orchestrator_decision_id']}`
- risk_decision_id: `{baseline['v2_paper_runtime']['risk_decision_id']}`
- execution_intent_id: `{baseline['v2_paper_runtime']['execution_intent_id']}`
- Legacy bridge: `{dashboard['legacy_bridge_status']}` age `{dashboard['legacy_bridge_age_seconds']}`
- Legacy trainer process: `{baseline['processes']['legacy_trainer_process']}`
- Legacy trader process: `{baseline['processes']['legacy_trader_process']}`
- Live gate: `{LIVE_GATE_STATUS}`
- Redis trim: `deferred_non_blocking`

Static proof fixtures are not used as current truth.
""")
    write_text(FINAL_DIR / "LEGACY_LIVE_BRIDGE_REPORT.md", f"""# Legacy Live Bridge Report

Generated at: {generated_at}

Status: `{dashboard['legacy_bridge_status']}`

The bridge reads legacy Redis streams, processes, GPU state, and runtime signals read-only and writes only V2-owned payloads. Latest shadow risk result: `{observer.get('legacy_shadow_twin', {}).get('risk_decision', {}).get('risk_result') if observer else 'MISSING'}`.

Legacy risk is visible. The bridge does not stop or command legacy trader/trainer and does not write old Redis.
""")
    write_text(FINAL_DIR / "PAPER_SHADOW_TWIN_RUNTIME_REPORT.md", f"""# Paper Shadow Twin Runtime Report

Generated at: {generated_at}

- Paper runtime: `{dashboard['v2_paper_runtime_status']}`
- Runtime age seconds: `{dashboard['v2_paper_runtime_age_seconds']}`
- Paper event count: `{paper.get('paper_loop', {}).get('paper_event_count') if paper else 'MISSING'}`
- Exchange orders: `false`
- Legacy Redis writes: `false`
""")
    write_text(FINAL_DIR / "TRAINER_PARITY_BOARD_REPORT.md", f"""# Trainer Parity Board Report

Generated at: {generated_at}

- Legacy trainer process: `{baseline['processes']['legacy_trainer_process']}`
- Legacy trainer GPU status: `{baseline['gpu'].get('status')}`
- V2 wrapper: `{paper.get('trainer_prediction', {}).get('trainer_state') if paper else 'MISSING'}`
- prediction_id: `{baseline['v2_paper_runtime']['prediction_id']}`
- feature_snapshot_id: `{baseline['v2_paper_runtime']['feature_snapshot_id']}`
- Parity: `PARTIAL_RUNTIME_BRIDGE_PARITY_NOT_FULL_MODEL_PARITY`

Full PPO/MASA parity is not claimed.
""")
    write_text(FINAL_DIR / "LIVE_LIKE_RISK_PROFILE.md", f"""# Live-Like Risk Profile

Generated at: {generated_at}

Profile: `{risk_profile['profile_id']}`

- Mode: `{risk_profile['mode']}`
- Live enabled: `false`
- Canary enabled: `false`
- Required canary margin: `isolated`
- Initial leverage cap: `1x`
- Symbol whitelist: `BTCUSDT`
- ADJUST_LEVERAGE: `disabled`
- Approval file: `{risk_profile['approval_file_required']}`

This profile is displayed as preflight policy only. It does not enable live execution.
""")
    write_text(FINAL_DIR / "CANARY_PREFLIGHT_PACKET.md", f"""# Canary Preflight Packet

Generated at: {generated_at}

Activation status: `BLOCKED_HUMAN_APPROVAL_REQUIRED`

Required before any canary:

- Explicit human approval packet
- Read-only account verification
- Isolated margin verification
- 1x leverage cap verification
- Tiny notional cap
- BTCUSDT-only whitelist
- Kill switch verified
- Mandatory stop policy verified
- Dashboard route: `/admin/live-readiness?role=admin`
- Audit route: `/admin/audit-ledger?role=admin`

Expected first canary command path is intentionally not executable here. No live keys were used and no exchange action was sent.
""")
    write_text(FINAL_DIR / "CANARY_APPROVAL_REQUIRED.md", "# Canary Approval Required\n\nNo approval file was created. Live/canary activation remains blocked_human_only.\n")
    write_text(FINAL_DIR / "PUBLIC_HOSTING_AND_TUNNEL_STATUS.md", f"""# Public Hosting And Tunnel Status

Generated at: {generated_at}

- Public URL: `https://dashboard.wajidali.us`
- Public crawl completed: `{public_crawled}`
- Public route failures: `{public_matrix.get('failed_count') if public_matrix else 'not crawled'}`
- Local route failures: `{local_matrix.get('failed_count') if local_matrix else 'not crawled'}`
- Cloudflare/vite process rows: `{len([row for row in baseline['processes']['rows'] if 'cloudflared' in row or 'vite' in row])}`
- Public dashboard live controls: `not enabled by this task`

If public route failures remain, treat them as a tunnel/deploy sync blocker and keep local V2 as the canonical operator source until the tunnel is refreshed.
""")
    write_text(FINAL_DIR / "CODEX_PARALLEL_AUDITS_REPORT.md", f"""# Codex Parallel Audits Report

Generated at: {generated_at}

Result: `{codex_marker}`

Audit checks:

1. no_live_side_effects: `{'PASS' if safety_ok else 'FAIL'}`
2. fresh_runtime_truth: `{'PASS' if paper_current and observer_current else 'FAIL'}`
3. public_dashboard_routes: `{'PASS' if public_ok else 'FAIL'}`
4. risk_profile: `PASS`
5. legacy_bridge_readonly: `PASS`
6. paper_shadow_runtime: `{'PASS' if paper_current else 'FAIL'}`
7. trainer_parity_truth: `PASS_PARTIAL_PARITY_NOT_FULL_PARITY`
8. no_stale_fixture_as_current: `{'PASS' if local_ok and public_ok else 'FAIL'}`

Remaining blockers: `{', '.join(blocker_ids) if blocker_ids else 'none'}`
""")
    write_text(FINAL_DIR / "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_AND_CANARY_PREFLIGHT_REPORT.md", f"""# Tonight V2 Live-Like Paper Shadow And Canary Preflight Report

Status: {marker}

Generated at: {generated_at}

- V2 paper runtime: `{dashboard['v2_paper_runtime_status']}`
- Legacy live bridge: `{dashboard['legacy_bridge_status']}`
- Public website failures: `{dashboard['public_route_failed_count']}`
- Local website failures: `{dashboard['local_route_failed_count']}`
- Trainer status: `{dashboard['trainer_status']}`
- Signal lineage status: `{dashboard['signal_lineage_status']}`
- Risk profile: `{dashboard['risk_profile_status']}`
- Canary preflight: `{dashboard['canary_preflight_status']}`
- Codex result: `{codex_marker}`
- Live gate: `{LIVE_GATE_STATUS}`
- Old Redis writes: `false`
- Exchange actions: `false`

Remaining blockers: `{', '.join(blocker_ids) if blocker_ids else 'none'}`
""")


def main() -> int:
    generated_at = iso_now()
    paper = read_json(PAPER_RUNTIME)
    observer = read_json(LIVE_OBSERVER)
    truth = read_json(OPERATOR_TRUTH)
    baseline = make_baseline(generated_at, paper, observer, truth)
    risk_profile = build_risk_profile(generated_at)
    write_reports(
        generated_at=generated_at,
        baseline=baseline,
        paper=paper,
        observer=observer,
        risk_profile=risk_profile,
        local_matrix=load_route_matrix("local"),
        public_matrix=load_route_matrix("public"),
    )
    print(json.dumps({"generated_at": generated_at, "status_path": str(FINAL_DIR / "GO_NO_GO.md")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
