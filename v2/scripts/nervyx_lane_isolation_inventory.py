#!/usr/bin/env python3
"""Generate NERVYX lane-isolation evidence.

The script is intentionally read-only against runtime systems. It reads git
metadata and filesystem contents, then writes evidence artifacts under docs/
and artifacts/. It does not reset, stash, clean, or modify trading state.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
DOCS_DIR = V2_ROOT / "docs"
ARTIFACTS_DIR = V2_ROOT / "artifacts"
BASE_BRANCH = "codex/nervyx-one-rebrand"

PROTECTED_TOKENS = (
    "trainer",
    "ppo",
    "masa",
    "strateg",
    "signal",
    "publisher",
    "orchestrator",
    "decision",
    "risk",
    "live_gate",
    "live-gate",
    "execution",
    "exchange",
    "redis",
    "migration",
    "repository",
    "repositories",
    "paper_trade_management",
    "paper_execution",
)

PROTECTED_PREFIXES = (
    "v2/backend/app/api/",
    "v2/backend/app/cli/",
    "v2/backend/app/composition/",
    "v2/backend/app/domain/",
    "v2/backend/app/services/",
    "v2/backend/app/repositories/",
    "v2/backend/alembic/",
    "v2/backend/migrations/",
)


def run(cmd: list[str], cwd: Path = REPO_ROOT, *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return proc


def git_text(args: list[str]) -> str:
    return run(["git", *args]).stdout.decode("utf-8", "replace").strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status_records() -> list[dict[str, str | None]]:
    raw = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]).stdout
    parts = raw.decode("utf-8", "surrogateescape").split("\0")
    records: list[dict[str, str | None]] = []
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        old_path = None
        if status.strip().startswith("R") or status.strip().startswith("C"):
            old_path = path
            if index < len(parts):
                path = parts[index]
                index += 1
        records.append({"status": status, "path": path, "old_path": old_path})
    return records


def classify_path(path: str, status: str) -> list[str]:
    p = path.lower()
    labels: list[str] = []
    if p.startswith(("v2/docs/", "docs/")) or "/docs/" in p or p.endswith(".md"):
        labels.append("DOCUMENTATION")
    if p.startswith("v2/frontend/src/brand/") or "nervyx-token" in p or "theme" in p and "frontend" in p:
        labels.append("THEME_OR_TOKEN")
    if p.startswith("rebranding/"):
        labels.append("BRAND_ASSET")
    if p.startswith("v2/frontend/") or p.startswith("frontend/"):
        labels.append("WEB_PRESENTATION")
    if p.startswith("v2/mobile/sources/aibotv2watch") or "watch" in p and p.endswith(".swift"):
        labels.append("WATCH_PRESENTATION")
    if p.startswith("v2/mobile/") or p.startswith("mobile/"):
        labels.append("IOS_PRESENTATION")
    if "websocket" in p or "realtime" in p or "ws" in p:
        labels.append("REALTIME_TRANSPORT_ADAPTER")
    if p.startswith("v2/backend/app/api/") and ("market_contracts.py" in p or "mobile.py" in p or "brand.py" in p):
        labels.append("READ_ONLY_API_ADAPTER")
    if "/tests/" in p or p.startswith("v2/frontend/tests/") or p.startswith("v2/mobile/tests/"):
        labels.append("TEST")
    if (
        p.startswith(("artifacts/", "v2/artifacts/", "claude_worklog/", "goal_state/", "logs/"))
        or "/latest/" in p
        or p.endswith((".json", ".jsonl", ".jsonl.gz", ".png", ".sha256"))
    ):
        labels.append("GENERATED_ARTIFACT")
    if is_protected_path(path):
        labels.append("PROTECTED_LANE_EXCEPTION")
    if p.startswith(("claude_worklog/", "goal_state/", "logs/")):
        labels.append("PREEXISTING_UNRELATED_CHANGE")
    if not labels:
        labels.append("PREEXISTING_UNRELATED_CHANGE" if status.strip() else "DOCUMENTATION")
    return sorted(set(labels))


def is_protected_path(path: str) -> bool:
    p = path.lower()
    if not p.startswith(PROTECTED_PREFIXES):
        return False
    return any(token in p for token in PROTECTED_TOKENS)


def all_base_paths(base: str) -> list[str]:
    raw = run(["git", "ls-tree", "-r", "--name-only", base, "v2/backend"], check=False).stdout
    return [
        line.strip()
        for line in raw.decode("utf-8", "replace").splitlines()
        if line.strip() and is_protected_path(line.strip())
    ]


def all_current_paths() -> list[str]:
    raw = run(["git", "ls-files", "-co", "--exclude-standard", "--", "v2/backend"], check=False).stdout
    return [
        line.strip()
        for line in raw.decode("utf-8", "replace").splitlines()
        if line.strip() and is_protected_path(line.strip())
    ]


def base_hashes(base: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in all_base_paths(base):
        proc = run(["git", "show", f"{base}:{path}"], check=False)
        if proc.returncode == 0:
            hashes[path] = sha256_bytes(proc.stdout)
    return hashes


def current_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in all_current_paths():
        full = REPO_ROOT / path
        if full.is_file():
            hashes[path] = file_sha256(full)
    return hashes


def write_hash_file(path: Path, hashes: dict[str, str]) -> None:
    path.write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())), encoding="utf-8")


def protected_diff(base: dict[str, str], current: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(set(base) | set(current)):
        before = base.get(path)
        after = current.get(path)
        if before == after:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "modified"
        rows.append(
            {
                "path": path,
                "status": status,
                "before_sha256": before or "",
                "after_sha256": after or "",
                "review_classification": protected_review_classification(path, status),
            }
        )
    return rows


def protected_review_classification(path: str, status: str) -> str:
    p = path.lower()
    if "/tests/" in p:
        return "TEST"
    if p.startswith("v2/backend/app/api/v2/") and any(name in p for name in ("market_contracts.py", "mobile.py", "brand.py", "monitoring_contracts.py", "status_contracts.py", "alerts_contracts.py")):
        return "READ_ONLY_API_ADAPTER_REVIEWED_BY_FOCUSED_TESTS"
    if "/api/" in p:
        return "API_SURFACE_REQUIRES_REVIEW"
    if "/cli/" in p:
        return "CLI_OR_PUBLISHER_REQUIRES_REVIEW"
    if "/composition/" in p or "/domain/" in p:
        return "DECISION_COMPOSITION_REQUIRES_REVIEW"
    if "/services/" in p:
        return "SERVICE_LOGIC_REQUIRES_REVIEW"
    return "PROTECTED_LANE_REQUIRES_REVIEW"


def write_modified_diff(base: str, rows: list[dict[str, str]], output: Path) -> None:
    modified = [row["path"] for row in rows if row["status"] == "modified"]
    if not modified:
        output.write_text("", encoding="utf-8")
        return
    chunks: list[str] = []
    for start in range(0, len(modified), 40):
        proc = run(["git", "diff", "--no-ext-diff", base, "--", *modified[start : start + 40]], check=False)
        chunks.append(proc.stdout.decode("utf-8", "replace"))
        if proc.stderr:
            chunks.append("\n# git diff stderr\n" + proc.stderr.decode("utf-8", "replace"))
    output.write_text("\n".join(chunks), encoding="utf-8")


def commits_since(base: str) -> list[str]:
    raw = run(["git", "log", "--oneline", "--reverse", f"{base}..HEAD"], check=False).stdout
    return [line for line in raw.decode("utf-8", "replace").splitlines() if line.strip()]


def worktrees() -> str:
    return run(["git", "worktree", "list"], check=False).stdout.decode("utf-8", "replace").strip()


def write_docs(
    *,
    generated_at: str,
    branch: str,
    head: str,
    base: str,
    inventory_count: int,
    inventory_sha: str,
    classification_counts: Counter[str],
    sample_records: list[dict[str, Any]],
    protected_rows: list[dict[str, str]],
    base_hash_path: Path,
    current_hash_path: Path,
    diff_path: Path,
    patch_path: Path,
) -> None:
    status_excerpt = "\n".join(
        f"{row['status']} {row['path']}" if not row.get("old_path") else f"{row['status']} {row['old_path']} -> {row['path']}"
        for row in sample_records[:120]
    )
    commits = commits_since(base)
    protected_counts = Counter(row["status"] for row in protected_rows)
    review_counts = Counter(row["review_classification"] for row in protected_rows)

    lane_doc = f"""# NERVYX Lane Isolation Final Evidence

- Generated at: `{generated_at}`
- Current branch: `{branch}`
- Current HEAD: `{head}`
- Rebrand branch used for merge-base: `{BASE_BRANCH}`
- Merge base: `{base}`

## Required Final Status

- NERVYX ONE WEB REBRAND: IN PROGRESS
- REALTIME WEB DATA: IN PROGRESS / field-level validation pending
- ADMIN/SUPERADMIN COVERAGE: IN PROGRESS
- IOS SOURCE WIRING: IN PROGRESS
- NATIVE IOS VALIDATION: BLOCKED - MACOS/XCODE REQUIRED
- WATCHOS VALIDATION: BLOCKED - MACOS/XCODE REQUIRED
- TESTFLIGHT: BLOCKED
- LANE ISOLATION: UNPROVEN until protected hash diffs are diffed and justified
- DATA PRESERVATION: UNPROVEN until the parity matrix reaches 100%
- REAL LIVE EXECUTION: BLOCKED

## Worktrees

```text
{worktrees()}
```

## Git Status Excerpt

The complete tracked/untracked inventory is in `artifacts/nervyx-changed-file-inventory.jsonl.gz`.

```text
{status_excerpt}
```

## Changed File Inventory

- Complete tracked/untracked status record count: `{inventory_count}`
- Compressed inventory: `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- Inventory checksum: `{inventory_sha}`
- Inventory checksum file: `artifacts/nervyx-changed-file-inventory.sha256`
- Classification summary: `artifacts/nervyx-changed-file-classification-summary.json`

## Commits Created Since Rebrand Merge Base

{chr(10).join(f"- `{line.split(' ', 1)[0]}` {line.split(' ', 1)[1] if ' ' in line else ''}" for line in commits) if commits else "- none"}

## Protected Lane Hash Result

- Base protected file hashes: `{sum(1 for _ in base_hash_path.read_text(encoding='utf-8').splitlines() if _)}`
- Current protected file hashes: `{sum(1 for _ in current_hash_path.read_text(encoding='utf-8').splitlines() if _)}`
- Protected hash mismatches/additions/deletions: `{len(protected_rows)}`
- Diff status counts: `{dict(sorted(protected_counts.items()))}`
- Review classification counts: `{dict(sorted(review_counts.items()))}`
- Base hash file: `docs/{base_hash_path.name}`
- Current hash file: `docs/{current_hash_path.name}`
- Base hash file checksum: `{file_sha256(base_hash_path)}`
- Current hash file checksum: `{file_sha256(current_hash_path)}`
- Diff artifact: `artifacts/{diff_path.name}`
- Diff artifact checksum: `{file_sha256(diff_path)}`
- Modified protected diff patch: `artifacts/{patch_path.name}`
- Modified protected diff patch checksum: `{file_sha256(patch_path)}`

The protected hash set intentionally over-includes adjacent backend API, CLI, composition/domain, service, repository, exchange, Redis, trainer, risk, execution, and migration-adjacent surfaces so protected-lane risk is visible instead of hidden.

## Isolation Verdict

UNPROVEN. The current protected hash set shows `{len(protected_rows)}` protected-lane diffs from the rebrand merge base. Completion still requires every protected diff to be identified, diffed, justified as presentation/read-only only where applicable, and separately tested. The modified protected files are diffed in `artifacts/{patch_path.name}`; added protected files remain identified in `artifacts/{diff_path.name}` and require owner review before isolation can be claimed.

Current first-diff sample:

| Status | Review Classification | Path |
|---|---|---|
{chr(10).join(f"| `{row['status']}` | `{row['review_classification']}` | `{row['path']}` |" for row in protected_rows[:30])}
"""
    (DOCS_DIR / "nervyx-lane-isolation-final.md").write_text(lane_doc, encoding="utf-8")

    changed_doc = f"""# NERVYX Changed File Classification

- Generated at: `{generated_at}`
- Current branch: `{branch}`
- Current HEAD: `{head}`
- Merge base: `{base}`
- Complete tracked/untracked status record count: `{inventory_count}`
- Compressed inventory: `artifacts/nervyx-changed-file-inventory.jsonl.gz`
- Inventory checksum: `{inventory_sha}`
- Machine-readable summary: `artifacts/nervyx-changed-file-classification-summary.json`

## Classification Counts

| Classification | Count |
|---|---:|
{chr(10).join(f"| `{key}` | {value} |" for key, value in sorted(classification_counts.items()))}

## Current Notes

- This is a current-state classification of every tracked and untracked changed path from `git status --porcelain=v1 -z --untracked-files=all`.
- The full per-file inventory is stored as compressed JSONL because the worktree contains hundreds of thousands of generated/runtime records.
- `PREEXISTING_UNRELATED_CHANGE` dominates because large generated/log/runtime surfaces already exist outside the NERVYX presentation lane.
- `PROTECTED_LANE_EXCEPTION` is non-zero and keeps lane isolation unproven until each protected exception is diffed, justified, and tested.
- `READ_ONLY_API_ADAPTER` covers current read-only presentation/data adapters only; it does not approve execution, risk, trainer, PPO, MASA, strategy, live-gate, order-routing, Redis producer, or database semantic changes.

## Sample Records

| Status | Classification | Path |
|---|---|---|
{chr(10).join(f"| `{row['status']}` | `{', '.join(row['classification'])}` | `{row['path']}` |" for row in sample_records[:40])}
"""
    (DOCS_DIR / "nervyx-changed-file-classification.md").write_text(changed_doc, encoding="utf-8")


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    branch = git_text(["branch", "--show-current"])
    head = git_text(["rev-parse", "HEAD"])
    base = git_text(["merge-base", "HEAD", BASE_BRANCH])

    records = status_records()
    classification_counts: Counter[str] = Counter()
    sample_records: list[dict[str, Any]] = []
    inventory_path = ARTIFACTS_DIR / "nervyx-changed-file-inventory.jsonl.gz"
    with gzip.open(inventory_path, "wt", encoding="utf-8") as handle:
        for record in records:
            labels = classify_path(str(record["path"]), str(record["status"]))
            for label in labels:
                classification_counts[label] += 1
            enriched = {**record, "classification": labels}
            if len(sample_records) < 200:
                sample_records.append(enriched)
            handle.write(json.dumps(enriched, sort_keys=True) + "\n")
    inventory_sha = file_sha256(inventory_path)
    (ARTIFACTS_DIR / "nervyx-changed-file-inventory.sha256").write_text(
        f"{inventory_sha}  artifacts/nervyx-changed-file-inventory.jsonl.gz\n",
        encoding="utf-8",
    )

    base_hash = base_hashes(base)
    current_hash = current_hashes()
    base_hash_path = DOCS_DIR / "nervyx-protected-lanes-base.sha256"
    current_hash_path = DOCS_DIR / "nervyx-protected-lanes-current.sha256"
    write_hash_file(base_hash_path, base_hash)
    write_hash_file(current_hash_path, current_hash)
    protected_rows = protected_diff(base_hash, current_hash)
    diff_path = ARTIFACTS_DIR / "nervyx-protected-lane-hash-diff.json"
    diff_payload = {
        "generated_at": generated_at,
        "branch": branch,
        "head": head,
        "base": base,
        "status": "UNPROVEN",
        "base_count": len(base_hash),
        "current_count": len(current_hash),
        "diff_count": len(protected_rows),
        "status_counts": dict(sorted(Counter(row["status"] for row in protected_rows).items())),
        "review_classification_counts": dict(
            sorted(Counter(row["review_classification"] for row in protected_rows).items())
        ),
        "rows": protected_rows,
    }
    diff_path.write_text(json.dumps(diff_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    patch_path = ARTIFACTS_DIR / "nervyx-protected-lane-modified-diffs.patch"
    write_modified_diff(base, protected_rows, patch_path)

    summary = {
        "generated_at": generated_at,
        "branch": branch,
        "head": head,
        "merge_base": base,
        "record_count": len(records),
        "classification_counts": dict(sorted(classification_counts.items())),
        "inventory_path": "artifacts/nervyx-changed-file-inventory.jsonl.gz",
        "inventory_sha256": inventory_sha,
        "protected_diff_count": len(protected_rows),
        "protected_status_counts": diff_payload["status_counts"],
        "protected_review_classification_counts": diff_payload["review_classification_counts"],
        "sample_records": sample_records[:40],
    }
    summary_path = ARTIFACTS_DIR / "nervyx-changed-file-classification-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write_docs(
        generated_at=generated_at,
        branch=branch,
        head=head,
        base=base,
        inventory_count=len(records),
        inventory_sha=inventory_sha,
        classification_counts=classification_counts,
        sample_records=sample_records,
        protected_rows=protected_rows,
        base_hash_path=base_hash_path,
        current_hash_path=current_hash_path,
        diff_path=diff_path,
        patch_path=patch_path,
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
