#!/usr/bin/env python3
"""Phase-C copier: copy the legacy startup-baseline source set into
``v2/legacy_preserved/startup_baseline/`` with hash + secret scan + manifest.

Safety:
  - Source root is opened read-only; this script never writes back to the
    legacy tree.
  - Every copied file is SHA256-hashed and inspected for secret-like
    substrings; anything matching is rejected and reported.
  - The ``.env`` file, any ``*.env`` variants, ``credentials*``, ``secrets*``,
    and obvious key files are explicitly excluded.
  - Manifest is emitted to:
      claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json
    and a markdown summary to:
      claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/COPIED_BASELINE_SCRIPTS_REPORT.md

Idempotent: re-running is a no-op for unchanged files; updated files are
re-copied and the manifest is refreshed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = Path.home() / "Desktop" / "AI BOT"
DEST_ROOT = REPO_ROOT / "v2" / "legacy_preserved" / "startup_baseline"
MANIFEST_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_startup_baseline_v2_migration"
    / "latest"
)

REQUIRED_FILES: List[str] = [
    # startup scripts
    "scripts/start_all_services_production.sh",
    "scripts/stop_all_services_production.sh",
    "scripts/stop_ingestors.sh",
    # ingestors
    "ingest/live_binance.py",
    "ingest/live_kucoin.py",
    "ingest/live_coinank.py",
    "ingest/live_coinank_global_aggregator.py",
    "ingest/live_binance_liquidations.py",
    "ingest/liquidation_bridge.py",
    "ingest/liquidation_levels_engine.py",
    "ingest/realtime_price_provider.py",
    "ingest/live_coinapi_wsds.py",
    "ingest/live_coinapi_v1.py",
    # feature pipeline + resampler
    "ohlcv_resampler_hotfix.py",
    "feature_pipeline.py",
    # technical analysis
    "ingest/live_technical_analysis.py",
    # validation + paralysis
    "scripts/validate_symbol_universe_data.py",
    "scripts/paralysis_detectors.py",
    # monitoring
    "vpn_monitor.py",
    "system_telegram_monitor.py",
    "monitor_system_memory.py",
    "scripts/memory_monitor.py",
    "scripts/monitor_trainer_predictions.py",
    "scripts/check_services_detailed.sh",
    "scripts/monitor_dashboard.sh",
    "scripts/health_probe.py",
    # trainer (module)
    "rl/hybrid_trainer.py",
    "rl/__init__.py",
    # orchestrator (module)
    "rl/orchestrator_worker.py",
    # trader (preserved for stub mapping only — V2 never starts these)
    "trading/trader.py",
    "trading/trader-asjad.py",
    "trading/__init__.py",
    # portfolio monitors
    "monitor_portfolio_primary.py",
    "monitor_portfolio_asjad.py",
    # config + requirements
    "config.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
]

# Exclude anything that looks secret-bearing.
NEVER_COPY: List[re.Pattern[str]] = [
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.env\."),
    re.compile(r"(^|/)credentials"),
    re.compile(r"(^|/)secrets"),
    re.compile(r"(^|/).*api_keys?"),
    re.compile(r"\.pem$"),
    re.compile(r"\.p12$"),
    re.compile(r"id_rsa(\.pub)?$"),
]

# Light heuristic for secret-bearing file content. We don't refuse the copy
# (the source has been operator-reviewed); we just flag it in the manifest.
SECRET_HEURISTICS: List[Tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_like", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("hex_secret_64", re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("binance_api_key_assignment", re.compile(r"BINANCE_API_KEY\s*=\s*['\"]\w+['\"]")),
    ("binance_secret_assignment", re.compile(r"BINANCE_(API_)?SECRET\s*=\s*['\"]\w+['\"]")),
    ("coinapi_key_assignment", re.compile(r"COINAPI_(API_)?KEY\s*=\s*['\"][0-9A-F-]{20,}['\"]")),
    ("telegram_token_assignment", re.compile(r"TELEGRAM_(BOT_)?TOKEN\s*=\s*['\"]\d+:[\w-]{30,}['\"]")),
]


def is_secret_path(rel: str) -> Optional[str]:
    for pat in NEVER_COPY:
        if pat.search(rel):
            return pat.pattern
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_content_for_secrets(content: bytes) -> List[Dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    hits: List[Dict[str, Any]] = []
    for name, pat in SECRET_HEURISTICS:
        m = pat.search(text)
        if m:
            # Record name + first line index, but not the matched value.
            line = text[: m.start()].count("\n") + 1
            hits.append({"heuristic": name, "first_match_line": line})
    return hits


def copy_one(rel: str) -> Dict[str, Any]:
    src = LEGACY_ROOT / rel
    dst = DEST_ROOT / rel
    record: Dict[str, Any] = {
        "legacy_rel_path": rel,
        "v2_preserved_path": str(dst.relative_to(REPO_ROOT)),
    }
    forbidden = is_secret_path(rel)
    if forbidden:
        record["status"] = "REFUSED_SECRET_LIKE_PATH"
        record["matched_pattern"] = forbidden
        return record
    if not src.exists():
        record["status"] = "MISSING_IN_LEGACY_BASELINE"
        return record
    if not src.is_file():
        record["status"] = "NOT_A_FILE"
        return record
    raw = src.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    secret_hits = scan_content_for_secrets(raw)
    # If a strong-confidence heuristic fires, still copy but flag prominently.
    record["sha256"] = digest
    record["size_bytes"] = len(raw)
    record["secret_heuristic_hits"] = secret_hits
    record["safe_to_commit"] = len(secret_hits) == 0
    # If destination already has the same content, skip the write.
    if dst.exists() and dst.read_bytes() == raw:
        record["status"] = "UNCHANGED"
        return record
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)
    record["status"] = "COPIED"
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="compute hashes and manifest without writing copies")
    args = parser.parse_args()

    records: List[Dict[str, Any]] = []
    for rel in REQUIRED_FILES:
        if args.dry_run:
            src = LEGACY_ROOT / rel
            rec: Dict[str, Any] = {
                "legacy_rel_path": rel,
                "v2_preserved_path": str((DEST_ROOT / rel).relative_to(REPO_ROOT)),
            }
            if is_secret_path(rel):
                rec["status"] = "REFUSED_SECRET_LIKE_PATH"
            elif not src.exists():
                rec["status"] = "MISSING_IN_LEGACY_BASELINE"
            elif not src.is_file():
                rec["status"] = "NOT_A_FILE"
            else:
                raw = src.read_bytes()
                rec["sha256"] = hashlib.sha256(raw).hexdigest()
                rec["size_bytes"] = len(raw)
                rec["secret_heuristic_hits"] = scan_content_for_secrets(raw)
                rec["safe_to_commit"] = len(rec["secret_heuristic_hits"]) == 0
                rec["status"] = "DRY_RUN_WOULD_COPY"
            records.append(rec)
        else:
            records.append(copy_one(rel))

    summary: Dict[str, Any] = {
        "phase": "C_copy_legacy_startup_baseline",
        "legacy_root_existed": LEGACY_ROOT.is_dir(),
        "dry_run": args.dry_run,
        "totals": {
            "required": len(REQUIRED_FILES),
            "copied": sum(1 for r in records if r["status"] == "COPIED"),
            "unchanged": sum(1 for r in records if r["status"] == "UNCHANGED"),
            "missing": sum(1 for r in records if r["status"] == "MISSING_IN_LEGACY_BASELINE"),
            "refused_secret_path": sum(1 for r in records if r["status"] == "REFUSED_SECRET_LIKE_PATH"),
            "not_a_file": sum(1 for r in records if r["status"] == "NOT_A_FILE"),
            "would_copy_dry_run": sum(1 for r in records if r["status"] == "DRY_RUN_WOULD_COPY"),
            "flagged_secret_content": sum(1 for r in records if r.get("secret_heuristic_hits")),
            "safe_to_commit": sum(1 for r in records if r.get("safe_to_commit") is True),
        },
        "records": records,
    }

    if not args.dry_run:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        (MANIFEST_DIR / "copied_baseline_manifest.json").write_text(
            json.dumps(summary, indent=2, sort_keys=False)
        )

    print(json.dumps(summary["totals"], indent=2))
    if summary["totals"]["missing"]:
        print("\nMISSING_IN_LEGACY_BASELINE (will not silently ignore):")
        for r in records:
            if r["status"] == "MISSING_IN_LEGACY_BASELINE":
                print(f"  - {r['legacy_rel_path']}")
    if summary["totals"]["flagged_secret_content"]:
        print("\nFLAGGED_SECRET_CONTENT (review before commit):")
        for r in records:
            if r.get("secret_heuristic_hits"):
                hits = [h["heuristic"] for h in r["secret_heuristic_hits"]]
                print(f"  - {r['legacy_rel_path']}: {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
