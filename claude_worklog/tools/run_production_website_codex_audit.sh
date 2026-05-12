#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/Desktop/AI BOT REBUILD"
FINAL="$ROOT/claude_worklog/final_readiness/production_website_full_rebuild/latest"
cd "$ROOT"

python3 claude_worklog/tools/crawl_dashboard_routes.py --kind after
python3 -m v2.backend.app.cli.production_website_full_rebuild

python3 - <<'PY'
import json
from pathlib import Path

root = Path.home() / "Desktop" / "AI BOT REBUILD"
final = root / "claude_worklog" / "final_readiness" / "production_website_full_rebuild" / "latest"
required = ["public_route_matrix.json", "local_route_matrix.json"]
for name in required:
    payload = json.loads((final / name).read_text())
    if payload.get("failed_count") != 0:
        raise SystemExit(f"{name} failed_count={payload.get('failed_count')}")
    for row in payload.get("routes", []):
        cls = row.get("classification", {})
        if cls.get("placeholder_only"):
            raise SystemExit(f"placeholder route: {row.get('route')}")
        if cls.get("static_fixture_as_current"):
            raise SystemExit(f"static fixture current route: {row.get('route')}")
        if cls.get("proof_dump_primary"):
            raise SystemExit(f"proof dump primary route: {row.get('route')}")
        if cls.get("chart_broken"):
            raise SystemExit(f"broken chart route: {row.get('route')}")
        if cls.get("dangerous_control_enabled"):
            raise SystemExit(f"enabled dangerous control route: {row.get('route')}")

marker = (final / "CODEX_GO_NO_GO.md").read_text().strip()
expected = "PRODUCTION_WEBSITE_FULL_PUBLIC_ROUTE_CRAWL_AND_COINANK_STYLE_REBUILD_CODEX_PASS"
if marker != expected:
    raise SystemExit(f"codex marker {marker!r} != {expected!r}")
PY

echo "production_website_codex_audit: PASS"
