#!/usr/bin/env python3
"""Crawl the local and public dashboard routes into a final-readiness packet.

This wrapper delegates browser work to the Playwright crawler in v2/frontend so
the route matrix logic stays in one place. It only reads HTTP pages and writes
V2/claude_worklog evidence artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "v2" / "frontend"
ARTIFACT_SLUG = "production_website_full_rebuild"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / ARTIFACT_SLUG / "latest"
PUBLIC_URL = "https://dashboard.wajidali.us"
LOCAL_URL = "http://127.0.0.1:5173"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_crawl(base_url: str, phase: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "PRODUCTION_CRAWL_ARTIFACT_SLUG": ARTIFACT_SLUG,
            "PRODUCTION_CRAWL_BASE_URL": base_url,
            "PRODUCTION_CRAWL_PHASE": phase,
        }
    )
    subprocess.run(
        ["npm", "run", "crawl:production-website"],
        cwd=FRONTEND,
        env=env,
        check=True,
    )
    return read_json(FINAL_DIR / f"production_route_matrix_{phase}.json")


def copy_previous_before_if_available() -> None:
    previous = REPO_ROOT / "claude_worklog" / "final_readiness" / "production_website_public_route_rebuild" / "latest"
    if not previous.exists():
        return
    source_matrix = previous / "production_route_matrix_before.json"
    if source_matrix.exists():
        shutil.copy2(source_matrix, FINAL_DIR / "production_route_matrix_before.json")
    source_screenshots = previous / "screenshots" / "before"
    target_screenshots = FINAL_DIR / "screenshots" / "before"
    if source_screenshots.exists():
        shutil.rmtree(target_screenshots, ignore_errors=True)
        shutil.copytree(source_screenshots, target_screenshots)


def combined_report(kind: str, public_matrix: dict[str, Any], local_matrix: dict[str, Any]) -> None:
    lines = [
        "# Public And Local Route Crawl Report",
        "",
        f"Mode: `{kind}`",
        "",
        "| Target | Base URL | Routes | Passed | Failed | Links Checked |",
        "|---|---|---:|---:|---:|---:|",
        f"| public | {public_matrix.get('base_url', PUBLIC_URL)} | {public_matrix.get('route_count', 0)} | {public_matrix.get('passed_count', 0)} | {public_matrix.get('failed_count', 0)} | {public_matrix.get('link_checked_count', 0)} |",
        f"| local | {local_matrix.get('base_url', LOCAL_URL)} | {local_matrix.get('route_count', 0)} | {local_matrix.get('passed_count', 0)} | {local_matrix.get('failed_count', 0)} | {local_matrix.get('link_checked_count', 0)} |",
        "",
        "Screenshots:",
        "",
        "- Before: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/before/`",
        "- Public after: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/after/`",
        "- Local after: `claude_worklog/final_readiness/production_website_full_rebuild/latest/screenshots/local_after/`",
        "",
        "Dangerous controls are recorded by the matrix and must remain disabled or approval-gated.",
    ]
    (FINAL_DIR / "PUBLIC_AND_LOCAL_ROUTE_CRAWL_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["before", "after", "both"], default="after")
    args = parser.parse_args()

    FINAL_DIR.mkdir(parents=True, exist_ok=True)

    if args.kind in {"before", "both"}:
        copy_previous_before_if_available()
        if not (FINAL_DIR / "production_route_matrix_before.json").exists():
            run_crawl(PUBLIC_URL, "before")

    public_matrix: dict[str, Any] = read_json(FINAL_DIR / "production_route_matrix_after.json")
    local_matrix: dict[str, Any] = read_json(FINAL_DIR / "production_route_matrix_local_after.json")

    if args.kind in {"after", "both"}:
        public_matrix = run_crawl(PUBLIC_URL, "after")
        local_matrix = run_crawl(LOCAL_URL, "local_after")
        write_json(FINAL_DIR / "public_route_matrix.json", public_matrix)
        write_json(FINAL_DIR / "local_route_matrix.json", local_matrix)
        combined_report(args.kind, public_matrix, local_matrix)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
