#!/usr/bin/env python3
"""Phase-B copier for the full rl/risk/services/utils/trading runtime closure.

Extends the prior startup-baseline copier: walks the deeper legacy trees
(`rl/`, `risk/`, `services/`, `utils/`, `trading/`, plus top-level helpers
like `config.py`, `config_accounts.py`, `telegram_alerts.py`) and copies
safe Python sources into `v2/legacy_preserved/full_runtime_closure/`.

Same safety contract as the startup-baseline copier:
  - Source root opened read-only via .read_bytes().
  - SHA256 + size per file.
  - Path-level exclusions for `.env`, secrets, credentials, private keys.
  - Content-level secret heuristics flag (but do not block) suspicious
    files; flagged files are NOT auto-copied — they go to a separate
    `flagged_for_operator_review.json` list and are excluded from the
    committed tree.
  - Binary checkpoint blobs are skipped (.pt, .pth, .pkl, .npz, .bin,
    .ckpt, .safetensors). They are inventoried in
    `binary_artifacts_skipped.json` for operator review.

Idempotent: re-running re-hashes and only writes changed bytes.
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
DEST_ROOT = REPO_ROOT / "v2" / "legacy_preserved" / "full_runtime_closure"
MANIFEST_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "legacy_rl_risk_trainer_trader_closure"
    / "latest"
)

# Folders to walk recursively.
PACKAGE_DIRS: List[str] = [
    "rl",
    "risk",
    "services",
    "utils",
    "trading",
]

# Top-level individual files.
TOP_LEVEL_FILES: List[str] = [
    "binance_websocket.py",
    "config.py",
    "config_accounts.py",
    "hybrid_rule_based_signals.py",
    "telegram_alerts.py",
]

# Scripts under scripts/ that match these patterns.
SCRIPTS_GLOB_PATTERNS: List[str] = [
    "*trainer*",
    "*risk*",
    "*trade*",
    "*hedge*",
    "*profit*",
    "*position*",
    "*orchestrator*",
]

# Path-level exclusions.
NEVER_COPY: List[re.Pattern[str]] = [
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.env\."),
    re.compile(r"(^|/)credentials"),
    re.compile(r"(^|/)secrets(?!_)"),  # keep `secrets.py` from stdlib alias if any
    re.compile(r"\.pem$"),
    re.compile(r"\.p12$"),
    re.compile(r"id_rsa(\.pub)?$"),
]

# Binary / checkpoint extensions we never want in the V2 tree.
BINARY_EXT: List[str] = [
    ".pt", ".pth", ".pkl", ".pickle", ".npz", ".npy",
    ".bin", ".ckpt", ".safetensors", ".onnx", ".h5",
    ".so", ".dll", ".dylib",
    ".zip", ".tar", ".gz", ".tgz", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".pdf",
    ".sqlite", ".db",
]

# Allow-list of text extensions we will copy (everything else gets skipped).
ALLOWED_TEXT_EXT: List[str] = [
    ".py", ".sh", ".bash",
    ".txt", ".md", ".rst",
    ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".json",
    ".sql",
    ".ps1",
    ".conf",
]

# Content-level secret heuristics (flag only; do not block copy).
SECRET_HEURISTICS: List[Tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_like", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("hex_secret_64", re.compile(r"\b[0-9a-fA-F]{64}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("binance_api_key_assignment", re.compile(r"BINANCE_API_KEY\s*=\s*['\"]\w{20,}['\"]")),
    ("binance_secret_assignment", re.compile(r"BINANCE_(API_)?SECRET\s*=\s*['\"]\w{20,}['\"]")),
    ("coinapi_key_assignment", re.compile(r"COINAPI_(API_)?KEY\s*=\s*['\"][0-9A-F-]{20,}['\"]")),
    ("telegram_token_assignment", re.compile(r"TELEGRAM_(BOT_)?TOKEN\s*=\s*['\"]\d+:[\w-]{30,}['\"]")),
    ("openai_key_like", re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b")),
]


def is_secret_path(rel: str) -> Optional[str]:
    for pat in NEVER_COPY:
        if pat.search(rel):
            return pat.pattern
    return None


def is_binary_or_disallowed(rel: str) -> Optional[str]:
    lower = rel.lower()
    for ext in BINARY_EXT:
        if lower.endswith(ext):
            return f"binary_extension:{ext}"
    # If it has a dot and the extension is not allow-listed, skip.
    suffix = Path(rel).suffix.lower()
    if suffix and suffix not in ALLOWED_TEXT_EXT:
        return f"non_text_extension:{suffix}"
    return None


def scan_content_for_secrets(content: bytes) -> List[Dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    hits: List[Dict[str, Any]] = []
    for name, pat in SECRET_HEURISTICS:
        m = pat.search(text)
        if m:
            line = text[: m.start()].count("\n") + 1
            hits.append({"heuristic": name, "first_match_line": line})
    return hits


def enumerate_targets() -> List[str]:
    """Compute the list of rel-paths under LEGACY_ROOT we intend to copy."""
    targets: List[str] = []
    for pkg in PACKAGE_DIRS:
        pkg_root = LEGACY_ROOT / pkg
        if not pkg_root.is_dir():
            continue
        for p in sorted(pkg_root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(LEGACY_ROOT).as_posix()
            targets.append(rel)
    for fn in TOP_LEVEL_FILES:
        if (LEGACY_ROOT / fn).is_file():
            targets.append(fn)
    scripts_root = LEGACY_ROOT / "scripts"
    if scripts_root.is_dir():
        for pat in SCRIPTS_GLOB_PATTERNS:
            for p in sorted(scripts_root.glob(pat)):
                if p.is_file():
                    rel = p.relative_to(LEGACY_ROOT).as_posix()
                    if rel not in targets:
                        targets.append(rel)
    return targets


def copy_one(rel: str, *, dry_run: bool) -> Dict[str, Any]:
    src = LEGACY_ROOT / rel
    dst = DEST_ROOT / rel
    record: Dict[str, Any] = {
        "legacy_rel_path": rel,
        "v2_preserved_path": str(dst.relative_to(REPO_ROOT)),
    }
    if (forbidden := is_secret_path(rel)) is not None:
        record["status"] = "REFUSED_SECRET_LIKE_PATH"
        record["matched_pattern"] = forbidden
        return record
    if (skip := is_binary_or_disallowed(rel)) is not None:
        record["status"] = "SKIPPED_BINARY_OR_DISALLOWED_EXTENSION"
        record["reason"] = skip
        if src.is_file():
            record["size_bytes"] = src.stat().st_size
        return record
    if not src.exists():
        record["status"] = "MISSING_IN_LEGACY_REPO"
        return record
    if not src.is_file():
        record["status"] = "NOT_A_FILE"
        return record
    raw = src.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    secret_hits = scan_content_for_secrets(raw)
    record["sha256"] = digest
    record["size_bytes"] = len(raw)
    record["secret_heuristic_hits"] = secret_hits
    record["safe_to_commit"] = len(secret_hits) == 0
    if secret_hits:
        # Do not copy flagged content; record it for operator review only.
        record["status"] = "FLAGGED_SECRET_CONTENT_NOT_COPIED"
        return record
    if dry_run:
        record["status"] = "DRY_RUN_WOULD_COPY"
        return record
    if dst.exists() and dst.read_bytes() == raw:
        record["status"] = "UNCHANGED"
        return record
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)
    record["status"] = "COPIED"
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = enumerate_targets()
    records: List[Dict[str, Any]] = [copy_one(t, dry_run=args.dry_run) for t in targets]

    summary: Dict[str, Any] = {
        "phase": "B_full_runtime_closure_copy",
        "legacy_root_existed": LEGACY_ROOT.is_dir(),
        "dry_run": args.dry_run,
        "targets_enumerated": len(targets),
        "totals_by_status": {},
        "records": records,
    }
    for r in records:
        st = r["status"]
        summary["totals_by_status"][st] = summary["totals_by_status"].get(st, 0) + 1

    if not args.dry_run:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        (MANIFEST_DIR / "full_runtime_copied_source_manifest.json").write_text(
            json.dumps(summary, indent=2)
        )
        # Separate slim manifests for flagged content and binary skips.
        flagged = [r for r in records if r["status"] == "FLAGGED_SECRET_CONTENT_NOT_COPIED"]
        if flagged:
            (MANIFEST_DIR / "flagged_for_operator_review.json").write_text(
                json.dumps({"count": len(flagged), "records": flagged}, indent=2)
            )
        binary = [r for r in records if r["status"] == "SKIPPED_BINARY_OR_DISALLOWED_EXTENSION"]
        if binary:
            (MANIFEST_DIR / "binary_artifacts_skipped.json").write_text(
                json.dumps({"count": len(binary), "records": binary}, indent=2)
            )

    print(json.dumps(summary["totals_by_status"], indent=2))
    print(f"targets_enumerated={len(targets)}")
    flagged_paths = [r["legacy_rel_path"] for r in records if r["status"] == "FLAGGED_SECRET_CONTENT_NOT_COPIED"]
    if flagged_paths:
        print(f"\nFLAGGED_SECRET_CONTENT_NOT_COPIED ({len(flagged_paths)}; review before committing source):")
        for p in flagged_paths[:25]:
            print(f"  - {p}")
    missing_paths = [r["legacy_rel_path"] for r in records if r["status"] == "MISSING_IN_LEGACY_REPO"]
    if missing_paths:
        print(f"\nMISSING_IN_LEGACY_REPO ({len(missing_paths)}):")
        for p in missing_paths[:10]:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
