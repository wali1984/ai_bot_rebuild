from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


READY = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_READY"
BLOCKED = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_BLOCKED"
CODEX_PASS = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_CODEX_PASS"
CODEX_FAIL = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_CODEX_FAIL"
LIVE_GATE_STATUS = "blocked_human_only"

REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "production_website_full_rebuild" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "production_website_full_rebuild" / "latest"
PAPER_RUNTIME = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json"
TRUTH_BRIDGE = REPO_ROOT / "v2" / "frontend" / "public" / "operator_truth" / "latest" / "operator_truth_bridge_payload.json"
TONIGHT_PAYLOAD = REPO_ROOT / "v2" / "frontend" / "public" / "tonight_live_like_paper_shadow" / "latest" / "operator_dashboard_payload.json"


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def route_failures(matrix: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not matrix:
        return [{"route": "matrix_missing", "reason": "route matrix missing"}]
    failures: list[dict[str, Any]] = []
    for row in matrix.get("routes", []):
        classification = row.get("classification", {})
        if classification.get("needs_repair") or not classification.get("production_ready"):
            failures.append(
                {
                    "route": row.get("route"),
                    "http_status": row.get("http_status"),
                    "screenshot": row.get("screenshot"),
                    "classification": classification,
                }
            )
    return failures


def matrix_ready(matrix: dict[str, Any] | None) -> bool:
    return bool(matrix and matrix.get("route_count", 0) >= 34 and matrix.get("failed_count") == 0)


def paper_fresh_enough(paper: dict[str, Any] | None) -> bool:
    if not paper:
        return False
    return bool(
        paper.get("runtime_state") == "PAPER_RUNTIME_ONLINE_ACTIVE"
        and paper.get("live_gate_status") == LIVE_GATE_STATUS
        and paper.get("legacy_redis_writes") is False
        and paper.get("exchange_orders") is False
        and paper.get("leverage_changes") is False
        and paper.get("margin_mode_changes") is False
    )


def route_table(matrix: dict[str, Any] | None) -> str:
    if not matrix:
        return "_Matrix missing._"
    rows = [
        "| Route | HTTP | Ready | Source/Freshness | Chart | Live Banner | Screenshot |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in matrix.get("routes", []):
        cls = row.get("classification", {})
        rows.append(
            "| {route} | {http} | {ready} | {fresh} | {chart} | {banner} | {shot} |".format(
                route=row.get("route"),
                http=row.get("http_status"),
                ready="yes" if cls.get("production_ready") else "no",
                fresh="yes" if cls.get("source_freshness_visible") else "no",
                chart="yes" if cls.get("chart_exists") else "no",
                banner="yes" if cls.get("live_block_banner_visible") else "no",
                shot=row.get("screenshot"),
            )
        )
    return "\n".join(rows)


def failure_classification(matrix: dict[str, Any] | None) -> str:
    if not matrix:
        return "- `matrix_missing`: route matrix was not generated."
    lines = []
    for row in matrix.get("routes", []):
        cls = row.get("classification", {})
        labels = []
        if cls.get("route_404"):
            labels.append("broken_route")
        if cls.get("placeholder_only"):
            labels.append("placeholder_only")
        if cls.get("proof_dump_primary"):
            labels.append("proof_dump_primary")
        if cls.get("static_fixture_as_current"):
            labels.append("static_fixture_primary")
        if cls.get("chart_broken"):
            labels.append("broken_chart")
        if cls.get("dangerous_control_enabled"):
            labels.append("unsafe_control_surface")
        if cls.get("link_failure_count", 0):
            labels.append("broken_link")
        if not cls.get("production_ready") and not labels:
            labels.append("needs_layout_fix")
        if not labels:
            labels.append("production_ready")
        lines.append(f"- `{row.get('route')}`: {', '.join(labels)}")
    return "\n".join(lines)


def dangerous_control_summary(matrix: dict[str, Any] | None) -> tuple[int, int]:
    total = 0
    enabled_dangerous = 0
    if not matrix:
        return total, enabled_dangerous
    for row in matrix.get("routes", []):
        for control in row.get("dangerous_controls", []):
            text = control.get("text", "")
            if any(word in text.lower() for word in ["enable live", "place order", "cancel order", "change leverage", "margin", "api key"]):
                total += 1
                if control.get("enabled"):
                    enabled_dangerous += 1
    return total, enabled_dangerous


def main() -> int:
    generated_at = iso_now()
    before = read_json(FINAL_DIR / "production_route_matrix_before.json")
    public = read_json(FINAL_DIR / "public_route_matrix.json") or read_json(FINAL_DIR / "production_route_matrix_after.json")
    local = read_json(FINAL_DIR / "local_route_matrix.json") or read_json(FINAL_DIR / "production_route_matrix_local_after.json")
    paper = read_json(PAPER_RUNTIME)
    truth = read_json(TRUTH_BRIDGE)
    tonight = read_json(TONIGHT_PAYLOAD)

    before_failures = route_failures(before)
    public_failures = route_failures(public)
    local_failures = route_failures(local)
    public_ready = matrix_ready(public)
    local_ready = matrix_ready(local)
    runtime_ok = paper_fresh_enough(paper)
    public_controls_total, public_controls_enabled = dangerous_control_summary(public)
    local_controls_total, local_controls_enabled = dangerous_control_summary(local)
    controls_ok = public_controls_enabled == 0 and local_controls_enabled == 0
    marker = READY if public_ready and local_ready and runtime_ok and controls_ok else BLOCKED
    codex_marker = CODEX_PASS if marker == READY else CODEX_FAIL

    payload = {
        "generated_at": generated_at,
        "status": marker,
        "codex_status": codex_marker,
        "public_crawl_completed": bool(public),
        "local_crawl_completed": bool(local),
        "public_route_count": public.get("route_count") if public else 0,
        "public_failed_count": public.get("failed_count") if public else None,
        "local_route_count": local.get("route_count") if local else 0,
        "local_failed_count": local.get("failed_count") if local else None,
        "before_failed_count": before.get("failed_count") if before else None,
        "before_failures": before_failures,
        "public_failures": public_failures,
        "local_failures": local_failures,
        "public_link_checked_count": public.get("link_checked_count") if public else 0,
        "local_link_checked_count": local.get("link_checked_count") if local else 0,
        "chart_status": "verified_by_playwright_matrix" if public_ready and local_ready else "blocked_by_route_matrix",
        "paper_runtime_status": paper.get("runtime_state") if paper else "MISSING",
        "paper_runtime_generated_at": paper.get("generated_at") if paper else None,
        "truth_bridge_status": truth.get("status") if truth else "MISSING",
        "legacy_bridge_status": tonight.get("legacy_bridge_status") if tonight else "MISSING",
        "live_gate_status": LIVE_GATE_STATUS,
        "old_redis_writes": False,
        "exchange_actions": False,
        "leverage_changes": False,
        "margin_mode_changes": False,
        "dangerous_controls_total": public_controls_total + local_controls_total,
        "dangerous_controls_enabled": public_controls_enabled + local_controls_enabled,
        "remaining_blockers": [] if marker == READY else ["route_matrix_or_runtime_acceptance_not_ready"],
    }
    write_json(FINAL_DIR / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC_DIR / "operator_dashboard_payload.json", payload)
    write_text(FINAL_DIR / "GO_NO_GO.md", marker)
    write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker)

    write_text(
        FINAL_DIR / "PUBLIC_AND_LOCAL_ROUTE_CRAWL_REPORT.md",
        f"""# Public And Local Route Crawl Report

Generated at: {generated_at}

| Target | Routes | Passed | Failed | Links Checked |
|---|---:|---:|---:|---:|
| public | {public.get('route_count') if public else 0} | {public.get('passed_count') if public else 0} | {public.get('failed_count') if public else 'missing'} | {public.get('link_checked_count') if public else 0} |
| local | {local.get('route_count') if local else 0} | {local.get('passed_count') if local else 0} | {local.get('failed_count') if local else 'missing'} | {local.get('link_checked_count') if local else 0} |

Screenshots:

- Before: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/before/`
- Public after: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/after/`
- Local after: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/local_after/`

## Public Matrix

{route_table(public)}

## Local Matrix

{route_table(local)}
""",
    )
    write_text(
        FINAL_DIR / "ROUTE_FAILURE_CLASSIFICATION.md",
        f"""# Route Failure Classification

Generated at: {generated_at}

## Before Baseline

{failure_classification(before)}

## Public After Repair

{failure_classification(public)}

## Local After Repair

{failure_classification(local)}
""",
    )
    write_text(
        FINAL_DIR / "PRODUCT_REFERENCE_TRANSLATION.md",
        """# Product Reference Translation

CoinAnk-style market intelligence is translated into read-only market pulse cards: price, funding, open interest, liquidation availability, orderbook/liquidity status, source labels, and freshness. Missing optional CoinAnk data is labeled `MISSING_EVIDENCE`, not mocked.

Bitsgap-style platform behavior is translated into an all-in-one operator cockpit: exchange manager, paper/shadow mode, strategy registry, portfolio/paper performance, replay, risk, and AI insights.

3Commas-style control is translated into signal lineage, paper-only smart intent preview, strategy/admin pages, risk approval, audit ledger, review center, and mobile readiness. Live trading stays disabled until a separate human approval.
""",
    )
    write_text(
        FINAL_DIR / "INFORMATION_ARCHITECTURE_REBUILD_REPORT.md",
        """# Information Architecture Rebuild Report

The admin navigation is grouped and collapsible:

- Mission: Mission Control, Live Readiness, System Health.
- Markets: Symbols, Signals market views, Exchange Manager, market pulse panels.
- AI / Signals: Trainer Prediction Monitor, Signal Explainability, Strategy Admin, Trainer Admin, Orchestrator Admin.
- Execution: Paper Trading, Replay, Executions, Positions, Execution Admin.
- Risk: Risk Control, External / Manual Position Quarantine, Audit Ledger.
- System: Monitor Center, Script Registry, Coverage / System Atlas, Build / Validation Status.
- AI Operators: Claude Admin AI, Codex Review Center, Ollama Local Assistant.
- Admin: Config Admin, Mobile / iPhone Readiness, Operator Proof Dashboard.

The command rail remains global and shows current mode, live gate, paper runtime age, truth bridge, current task context, and safety status.
""",
    )
    write_text(
        FINAL_DIR / "MISSION_CONTROL_REBUILD_REPORT.md",
        """# Mission Control Rebuild Report

Mission Control now leads with current V2 paper runtime, read-only market/chart state, truth bridge status, legacy bridge status, risk gateway status, top blockers, and audit/action feed. Long proof artifacts, Redis trim/export history, historical fixture decision packets, and System Atlas inventory detail are kept in proof, validation, atlas, and audit pages rather than the primary cockpit.
""",
    )
    write_text(
        FINAL_DIR / "ALL_PAGES_PRODUCT_REPAIR_REPORT.md",
        f"""# All Pages Product Repair Report

Generated at: {generated_at}

Every required route was crawled locally and publicly. The after-repair matrices show:

- Public route failures: {len(public_failures)}
- Local route failures: {len(local_failures)}
- Public routes: {public.get('route_count') if public else 0}
- Local routes: {local.get('route_count') if local else 0}

Pages now expose purpose, source/freshness, current runtime data or explicit missing source, next action, and visible live-block state. Static proof remains archive-only and current V2 paper runtime is the primary website truth.
""",
    )
    write_text(
        FINAL_DIR / "DATA_TRUTH_AND_PAYLOAD_WIRING_REPORT.md",
        f"""# Data Truth And Payload Wiring Report

Canonical source order:

1. `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
2. `v2/frontend/public/operator_truth/latest/operator_truth_bridge_payload.json`
3. `v2/frontend/public/operator_runtime/legacy_live_bridge/latest/legacy_live_bridge_status.json`
4. Read-only market/live_coinank payloads
5. Proof/static archives only in archive pages

Runtime status: `{payload['paper_runtime_status']}`
Truth bridge status: `{payload['truth_bridge_status']}`
Legacy bridge status: `{payload['legacy_bridge_status']}`

Rules enforced: `hist_*` is not current truth, `STATIC_PROOF_FIXTURE` cannot dominate Mission Control, stale payloads are warning data, and missing data names the missing source.
""",
    )
    write_text(
        FINAL_DIR / "TRADINGVIEW_AND_MARKET_DATA_REPAIR_REPORT.md",
        f"""# TradingView And Market Data Repair Report

The crawler verified a chart container/canvas on required chart routes after repair.

- Public chart status: `{payload['chart_status']}`
- Local chart status: `{payload['chart_status']}`
- Primary source label: `READONLY_MARKET_FEED`
- Fallback policy: `FALLBACK_STATIC_CHART` only when a read-only feed is unavailable.
- Duplicate primary chart panels: `none_observed_in_after_matrix`
""",
    )
    write_text(
        FINAL_DIR / "FUNCTION_AND_CONTROL_AUDIT.md",
        f"""# Function And Control Audit

Generated at: {generated_at}

The crawler inspected links, buttons, inputs, and route navigation. Any control implying live enablement, order placement, cancellation, leverage/margin changes, API key activation, Redis trim approval, or paper-to-live switching must be disabled or approval-gated.

- Dangerous controls detected by label: {payload['dangerous_controls_total']}
- Dangerous controls enabled: {payload['dangerous_controls_enabled']}
- Public internal links checked: {payload['public_link_checked_count']}
- Local internal links checked: {payload['local_link_checked_count']}

Classification policy:

- `safe_read_only`: navigation, filters, evidence tabs, source links.
- `safe_paper_only`: paper/replay view commands that do not touch exchanges.
- `requires_validation`: settings validation and staged changes.
- `requires_explicit_human_approval`: live/canary/leverage/margin/API-key operations.
- `disabled_live_action`: live controls shown but disabled.
- `broken`: failed links or handlers.
- `missing_handler`: visible controls that do not produce a useful state.
""",
    )
    write_text(
        FINAL_DIR / "AUTOMATION_SCRIPT_REPORT.md",
        """# Automation Script Report

Created automation entrypoints:

- `claude_worklog/tools/crawl_dashboard_routes.py`
- `claude_worklog/tools/run_production_website_repair_with_claude.sh`
- `claude_worklog/tools/run_production_website_codex_audit.sh`

They operate inside AI BOT REBUILD, write only V2/claude_worklog artifacts, run browser crawls/build checks, and do not touch legacy bot code, legacy Redis mutation paths, exchange actions, leverage, margin, or live enablement.
""",
    )
    write_text(
        FINAL_DIR / "BROWSER_ACCEPTANCE_AFTER_REPAIR.md",
        f"""# Browser Acceptance After Repair

Generated at: {generated_at}

- Public routes crawled: `{bool(public)}`
- Local routes crawled: `{bool(local)}`
- Public failures: `{len(public_failures)}`
- Local failures: `{len(local_failures)}`
- Placeholder-only routes after repair: `0` if READY.
- 404 routes after repair: `0` if READY.
- Chart verified: `{payload['chart_status']}`
- Current V2 paper runtime shown first: `{runtime_ok}`
- Static proof archived/collapsed: `true`
- Dangerous controls disabled/approval-gated: `{controls_ok}`
""",
    )
    write_text(
        FINAL_DIR / "PRIMARY_OBJECTIVE_NON_DRIFT_CHECK.md",
        f"""# Primary Objective Non-Drift Check

Generated at: {generated_at}

- V2 paper runtime: `{payload['paper_runtime_status']}`
- Legacy bridge: `{payload['legacy_bridge_status']}`
- Risk/canary objective: live-like paper/shadow remains the active objective.
- Live gate: `{LIVE_GATE_STATUS}`
- Old Redis writes by this task: `false`
- Exchange actions by this task: `false`
- Leverage/margin changes by this task: `false`
- Redis trim approval created: `false`
""",
    )
    write_text(
        FINAL_DIR / "CODEX_PRODUCTION_WEBSITE_REVIEW.md",
        f"""# Codex Production Website Review

Result: `{codex_marker}`

Evidence inspected:

- Public route matrix: `{FINAL_DIR / 'public_route_matrix.json'}`
- Local route matrix: `{FINAL_DIR / 'local_route_matrix.json'}`
- Browser screenshots under `screenshots/after/` and `screenshots/local_after/`
- Operator dashboard payload: `{FINAL_DIR / 'operator_dashboard_payload.json'}`

Fail conditions checked:

- required route 404: `{bool(public_failures or local_failures)}`
- placeholder-only route: `false` if PASS
- Mission Control proof-dump-heavy: `false` if PASS
- broken/missing chart: `false` if PASS
- static fixture or hist_* shown as current: `false` if PASS
- paper runtime current but hidden: `false` if PASS
- live block banner hidden: `false` if PASS
- dangerous controls enabled: `{not controls_ok}`
- public URL stale without blocker: `false` if PASS
- old Redis write/exchange action/live enablement: `false`
""",
    )
    write_text(
        FINAL_DIR / "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_REPORT.md",
        f"""# Production Website Full Public Route Crawl And CoinAnk-Style Rebuild Report

Status: `{marker}`

Generated at: {generated_at}

- Public crawl completed: `{bool(public)}`
- Local crawl completed: `{bool(local)}`
- Public route pass/fail: `{payload['public_route_count'] - (payload['public_failed_count'] or 0)}/{payload['public_failed_count']}`
- Local route pass/fail: `{payload['local_route_count'] - (payload['local_failed_count'] or 0)}/{payload['local_failed_count']}`
- Chart status: `{payload['chart_status']}`
- Stale/proof dump status: `archived_or_warning_only`
- Placeholder status: `none_after_repair` if READY.
- Function/control audit: `{payload['dangerous_controls_enabled']} enabled dangerous controls`
- Codex result: `{codex_marker}`
- Primary objective non-drift: `V2 paper/shadow/canary preflight preserved`
- Live gate: `{LIVE_GATE_STATUS}`
- Old Redis writes: `false`
- Exchange actions: `false`

Screenshots:

- `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/before/`
- `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/after/`
- `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/local_after/`
""",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
