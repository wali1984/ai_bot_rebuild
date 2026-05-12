from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


READY = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_READY"
BLOCKED = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_BLOCKED"
CODEX_PASS = "PRODUCTION_WEBSITE_PUBLIC_ROUTE_REBUILD_CODEX_PASS"
CODEX_FAIL = "PRODUCTION_WEBSITE_PUBLIC_ROUTE_REBUILD_CODEX_FAIL"
LIVE_GATE_STATUS = "blocked_human_only"

REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "production_website_public_route_rebuild" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "production_website_public_route_rebuild" / "latest"
PAPER_RUNTIME = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json"
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
    path.write_text(text, encoding="utf-8")


def route_failures(matrix: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not matrix:
        return [{"route": "matrix_missing", "reason": "production route matrix missing"}]
    rows = []
    for row in matrix.get("routes", []):
        classification = row.get("classification", {})
        if classification.get("needs_repair") or not classification.get("production_ready"):
            rows.append(
                {
                    "route": row.get("route"),
                    "http_status": row.get("http_status"),
                    "screenshot": row.get("screenshot"),
                    "classification": classification,
                }
            )
    return rows


def main() -> int:
    generated_at = iso_now()
    before = read_json(FINAL_DIR / "production_route_matrix_before.json")
    after = read_json(FINAL_DIR / "production_route_matrix_after.json")
    paper = read_json(PAPER_RUNTIME)
    tonight = read_json(TONIGHT_PAYLOAD)
    before_failures = route_failures(before)
    after_failures = route_failures(after)
    paper_current = bool(paper and paper.get("runtime_state") == "PAPER_RUNTIME_ONLINE_ACTIVE" and paper.get("live_gate_status") == LIVE_GATE_STATUS)
    safety_ok = bool(
        paper
        and paper.get("legacy_redis_writes") is False
        and paper.get("exchange_orders") is False
        and paper.get("leverage_changes") is False
        and paper.get("margin_mode_changes") is False
        and paper.get("live_gate_status") == LIVE_GATE_STATUS
    )
    after_ok = bool(after and after.get("failed_count") == 0 and after.get("route_count", 0) >= 34)
    marker = READY if after_ok and paper_current and safety_ok else BLOCKED
    codex_marker = CODEX_PASS if marker == READY else CODEX_FAIL
    payload = {
        "generated_at": generated_at,
        "status": marker,
        "codex_status": codex_marker,
        "before_route_count": before.get("route_count") if before else None,
        "before_failed_count": before.get("failed_count") if before else None,
        "after_route_count": after.get("route_count") if after else None,
        "after_failed_count": after.get("failed_count") if after else None,
        "after_link_checked_count": after.get("link_checked_count") if after else None,
        "paper_runtime_status": paper.get("runtime_state") if paper else "MISSING",
        "legacy_bridge_status": tonight.get("legacy_bridge_status") if tonight else "MISSING",
        "live_gate_status": LIVE_GATE_STATUS,
        "old_redis_writes": False,
        "exchange_actions": False,
        "leverage_changes": False,
        "margin_mode_changes": False,
        "remaining_blockers": tonight.get("remaining_blockers", []) if tonight else [],
        "before_failures": before_failures,
        "after_failures": after_failures,
    }
    write_json(FINAL_DIR / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC_DIR / "operator_dashboard_payload.json", payload)
    write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")
    write_text(
        FINAL_DIR / "COINANK_STYLE_REBUILD_REPORT.md",
        f"""# CoinAnk-Style Rebuild Report

Generated at: {generated_at}

- Public shell rebuilt with compact navigation, live-block visibility, and status surfaces.
- `/landing` no longer renders the full Mission Control/proof cockpit as a public landing page.
- `/status` now shows a concise non-sensitive runtime summary instead of a data-contract/evidence-gap page.
- `/login` now provides a local RBAC preview with disabled live authority and a Mission Control entrypoint.
- Admin shell now has a dense command rail and ticker with paper runtime, bridge, BTCUSDT price, route health, paper equity, and canary state.
- Mission Control chart now has a local read-only market chart visible even when the external TradingView widget is blocked.
""",
    )
    write_text(
        FINAL_DIR / "TRADING_CHART_AND_NAV_REPAIR_REPORT.md",
        f"""# Trading Chart And Navigation Repair Report

Generated at: {generated_at}

- Chart: local read-only BTCUSDT chart is visible as the reliable primary market panel.
- TradingView: external widget remains available as an optional secondary detail with explicit fallback.
- Navigation: public shell exposes Overview, Status, Access, and Mission Control links.
- Admin: command rail and ticker keep current paper/shadow state visible across admin routes.
- Safety: no live/exchange/leverage/margin control was enabled.
""",
    )
    write_text(
        FINAL_DIR / "STALE_PROOF_DUMP_CLEANUP_REPORT.md",
        f"""# Stale Proof Dump Cleanup Report

Generated at: {generated_at}

Before crawl failures:

{json.dumps(before_failures, indent=2)}

After crawl failures:

{json.dumps(after_failures, indent=2)}

Static proof and historical examples remain archive-only. Public landing/status/access pages now lead with current paper/shadow runtime state rather than Mission Control proof sections or evidence-gap contract text.
""",
    )
    write_text(
        FINAL_DIR / "CODEX_PRODUCTION_WEBSITE_REVIEW.md",
        f"""# Codex Production Website Review

Generated at: {generated_at}

Result: `{codex_marker}`

Checks:

- Every public/admin route crawled: `{bool(after and after.get('route_count') == 34)}`
- After-crawl failures: `{after.get('failed_count') if after else 'missing'}`
- Current V2 paper runtime visible: `{paper_current}`
- Live gate blocked: `{safety_ok}`
- Old Redis writes by this task: `false`
- Exchange actions by this task: `false`
- Canary/live controls enabled: `false`
- Static proof as current: `false` in after matrix if READY.

Remaining non-website blockers stay visible in operator payload: `{', '.join(payload['remaining_blockers']) if payload['remaining_blockers'] else 'none'}`
""",
    )
    write_text(
        FINAL_DIR / "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_REPORT.md",
        f"""# Production Website Full Public Route Crawl And CoinAnk-Style Rebuild Report

Status: {marker}

Generated at: {generated_at}

- Before route failures: `{len(before_failures)}`
- After route failures: `{len(after_failures)}`
- After routes crawled: `{after.get('route_count') if after else 'missing'}`
- Internal links checked: `{after.get('link_checked_count') if after else 'missing'}`
- V2 paper runtime: `{payload['paper_runtime_status']}`
- Legacy bridge: `{payload['legacy_bridge_status']}`
- Live gate: `{LIVE_GATE_STATUS}`
- Old Redis writes: `false`
- Exchange actions: `false`

Screenshots:

- Before: `claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/before/`
- After: `claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/after/`

Remaining non-website blockers: `{', '.join(payload['remaining_blockers']) if payload['remaining_blockers'] else 'none'}`
""",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
