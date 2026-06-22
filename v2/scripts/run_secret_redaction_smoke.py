#!/usr/bin/env python3
"""Generate a backend-only secret-redaction smoke artifact.

This command scans already-produced safe API payloads and logs for unredacted
credential-shaped fields. It does not read exchange secrets, call Binance, submit
orders, cancel orders, mutate leverage/margin, or touch the live gate.

Screenshots require an explicit human/CI attestation via --screenshots-reviewed;
this runner does not perform OCR and will not claim screenshot coverage without
that flag.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

TEXT_SUFFIXES = {
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SCREENSHOT_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
REDACTED_VALUES = {
    "",
    "*",
    "***",
    "****",
    "*****",
    "******",
    "[redacted]",
    "<redacted>",
    "redacted",
    "masked",
    "hidden",
    "unavailable",
    "pending",
    "not_configured",
    "configured",
    "binding_required",
    "none",
    "null",
}
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)[\"']?(?P<name>\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|secret|access[_-]?token|refresh[_-]?token|authorization|x-mbx-apikey|binance[_-]?api[_-]?key|binance[_-]?api[_-]?secret)\b)[\"']?"
    r"\s*[:=]\s*"
    r"(?P<quote>[\"']?)(?P<value>[^\"'\s,;}]+)(?P=quote)"
)
BEARER_TOKEN = re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+(?P<value>[a-z0-9._~+/=-]{12,})")
INLINE_SECRET_VALUE = re.compile(r"(?i)\b(?:sk|pk|ak|secret|token)_[a-z0-9][a-z0-9._-]{20,}\b")


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    line: int
    field: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_files(paths: Sequence[Path], suffixes: set[str]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix.lower() in suffixes:
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in suffixes:
                    yield child


def _is_redacted(value: str) -> bool:
    normalized = value.strip().strip('"\'').strip().lower()
    if normalized in REDACTED_VALUES:
        return True
    if set(normalized) <= {"*", "x", "-"}:
        return True
    if normalized.startswith("redacted") or normalized.endswith("redacted"):
        return True
    return False


def _scan_text_file(path: Path, category: str, max_bytes: int) -> tuple[list[Finding], str | None]:
    try:
        if path.stat().st_size > max_bytes:
            return [], f"Skipped {path}: larger than max_bytes"
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"Skipped {path}: {exc}"

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in SENSITIVE_ASSIGNMENT.finditer(line):
            name = match.group("name")
            value = match.group("value")
            if not _is_redacted(value):
                findings.append(Finding(category=category, path=str(path), line=line_number, field=name.lower()))
        for match in BEARER_TOKEN.finditer(line):
            value = match.group("value")
            if not _is_redacted(value):
                findings.append(Finding(category=category, path=str(path), line=line_number, field="authorization"))
        for match in INLINE_SECRET_VALUE.finditer(line):
            value = match.group(0)
            if not _is_redacted(value):
                findings.append(Finding(category=category, path=str(path), line=line_number, field="inline_secret_pattern"))
    return findings, None


def build_report(
    *,
    safe_api_payload_paths: Sequence[Path],
    log_paths: Sequence[Path],
    screenshot_paths: Sequence[Path],
    screenshots_reviewed: bool,
    max_bytes: int = 25_000_000,
) -> dict[str, object]:
    warnings: list[str] = []
    findings: list[Finding] = []

    payload_files = list(_iter_files(safe_api_payload_paths, TEXT_SUFFIXES))
    log_files = list(_iter_files(log_paths, TEXT_SUFFIXES))
    screenshot_files = list(_iter_files(screenshot_paths, SCREENSHOT_SUFFIXES))

    if not payload_files:
        warnings.append("No safe API payload artifacts were found for scanning")
    if not log_files:
        warnings.append("No log artifacts were found for scanning")
    if not screenshot_files:
        warnings.append("No screenshot artifacts were found for review")
    if screenshot_files and not screenshots_reviewed:
        warnings.append("Screenshot artifacts require explicit review attestation")

    for path in payload_files:
        file_findings, warning = _scan_text_file(path, "safe_api_payload", max_bytes)
        findings.extend(file_findings)
        if warning:
            warnings.append(warning)
    for path in log_files:
        file_findings, warning = _scan_text_file(path, "log", max_bytes)
        findings.extend(file_findings)
        if warning:
            warnings.append(warning)

    api_key_exposed = any("api" in finding.field and "key" in finding.field for finding in findings)
    api_secret_exposed = any("secret" in finding.field for finding in findings)
    access_token_exposed = any("token" in finding.field or finding.field == "authorization" for finding in findings)
    raw_exposed = bool(findings)
    checked_required_categories = bool(payload_files) and bool(log_files) and bool(screenshot_files) and screenshots_reviewed
    passed = checked_required_categories and not raw_exposed

    return {
        "secret_redaction_smoke_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_secret_redaction_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "checked_at": _utc_now(),
        "safe_api_payloads_checked": bool(payload_files),
        "logs_checked": bool(log_files),
        "screenshots_checked": bool(screenshot_files) and screenshots_reviewed,
        "screenshots_reviewed_attestation": screenshots_reviewed,
        "files_checked": {
            "safe_api_payloads": len(payload_files),
            "logs": len(log_files),
            "screenshots": len(screenshot_files),
        },
        "raw_credential_value_exposed": raw_exposed,
        "api_key_exposed": api_key_exposed,
        "api_secret_exposed": api_secret_exposed,
        "access_token_exposed": access_token_exposed,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "warnings": warnings,
        "findings_count": len(findings),
        "findings": [finding.__dict__ for finding in findings[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe secret-redaction smoke scan")
    parser.add_argument("--safe-api-payload-path", action="append", default=[], help="Safe API payload file or directory to scan")
    parser.add_argument("--log-path", action="append", default=[], help="Log file or directory to scan")
    parser.add_argument("--screenshot-path", action="append", default=[], help="Screenshot file or directory included in human/CI review")
    parser.add_argument("--screenshots-reviewed", action="store_true", help="Attest that screenshot artifacts were reviewed for credential exposure")
    parser.add_argument("--max-bytes", type=int, default=25_000_000, help="Maximum text artifact size to scan")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(
        safe_api_payload_paths=_paths(args.safe_api_payload_path),
        log_paths=_paths(args.log_path),
        screenshot_paths=_paths(args.screenshot_path),
        screenshots_reviewed=bool(args.screenshots_reviewed),
        max_bytes=int(args.max_bytes),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["secret_redaction_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
