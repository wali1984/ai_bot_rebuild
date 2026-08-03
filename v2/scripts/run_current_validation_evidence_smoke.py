#!/usr/bin/env python3
"""Validate already-produced current-validation result artifacts.

This command checks whether local JSON/JSONL validation-result artifacts cover
every command in docs/product-readiness-status.json pending_validation_queue and
report a passing result after the latest changes. It does not execute tests,
builds, lint, Playwright, backend services, database migrations, exchange calls,
or live trading actions.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
PASS_STATUSES = {"pass", "passed", "ok", "success", "succeeded", "green"}
FAIL_STATUSES = {"fail", "failed", "error", "errored", "red", "timeout", "timed_out"}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "pass", "passed", "ok", "verified"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "fail", "failed", "missing", "pending", "none", "null"}


@dataclass(frozen=True)
class LoadedArtifact:
    path: str
    payload: Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix.lower() in JSON_SUFFIXES:
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in JSON_SUFFIXES:
                    yield child


def _load_json_artifacts(paths: Sequence[Path], warnings: list[str]) -> list[LoadedArtifact]:
    loaded: list[LoadedArtifact] = []
    for path in _iter_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".jsonl":
                for index, line in enumerate(text.splitlines(), start=1):
                    stripped = line.strip()
                    if stripped:
                        loaded.append(LoadedArtifact(path=f"{path}:{index}", payload=json.loads(stripped)))
            else:
                loaded.append(LoadedArtifact(path=str(path), payload=json.loads(text)))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Skipped {path}: {exc}")
    return loaded


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _status_value(row: dict[str, Any]) -> str:
    return str(row.get("status") or row.get("result") or row.get("outcome") or "").strip().lower()


def _command_value(row: dict[str, Any]) -> str | None:
    for key in ("command", "cmd", "validation_command", "pending_validation_command"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "validations", "commands", "entries"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if _command_value(payload):
        return [payload]
    return []


def _read_required_commands(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    commands = payload.get("pending_validation_queue") if isinstance(payload, dict) else None
    if not isinstance(commands, list):
        raise ValueError("readiness status snapshot must contain pending_validation_queue list")
    return [str(command).strip() for command in commands if str(command).strip()]


def build_report(*, readiness_status_path: Path, validation_result_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    try:
        required_commands = _read_required_commands(readiness_status_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        required_commands = []
        warnings.append(f"Readiness status snapshot could not be read: {exc}")
    artifacts = _load_json_artifacts(validation_result_paths, warnings)
    if not artifacts:
        warnings.append("No current-validation result artifacts were found")

    result_by_command: dict[str, dict[str, Any]] = {}
    skipped_commands: set[str] = set()
    failed_commands: set[str] = set()
    stale_commands: set[str] = set()
    live_trading_enabled = False
    exchange_mutation_enabled = False

    for artifact in artifacts:
        for row in _entries(artifact.payload):
            command = _command_value(row)
            if not command:
                continue
            status = _status_value(row)
            if status in FAIL_STATUSES:
                failed_commands.add(command)
            if status in {"skip", "skipped"} or _as_bool(row.get("skipped")) is True:
                skipped_commands.add(command)
            after_latest_changes = _as_bool(row.get("after_latest_changes"))
            current = _as_bool(row.get("current"))
            if after_latest_changes is not True and current is not True:
                stale_commands.add(command)
            if _as_bool(row.get("live_trading_enabled")) is True:
                live_trading_enabled = True
            if _as_bool(row.get("exchange_mutation_enabled")) is True:
                exchange_mutation_enabled = True
            if status in PASS_STATUSES and command not in result_by_command:
                result_by_command[command] = {"artifact": artifact.path, **row}

    missing_commands = [command for command in required_commands if command not in result_by_command]
    non_current_commands = [command for command in required_commands if command in stale_commands]
    skipped_required = [command for command in required_commands if command in skipped_commands]
    failed_required = [command for command in required_commands if command in failed_commands]
    missing_fields: list[str] = []
    if not required_commands:
        missing_fields.append("pending_validation_queue")
    if missing_commands:
        missing_fields.append("all_pending_validation_commands_passed")
    if non_current_commands:
        missing_fields.append("validation_results_after_latest_changes")
    if skipped_required:
        missing_fields.append("no_skipped_validation_commands")
    if failed_required:
        missing_fields.append("no_failed_validation_commands")
    if live_trading_enabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled:
        missing_fields.append("exchange_mutation_disabled")

    passed = bool(required_commands and artifacts) and not missing_fields
    return {
        "current_validation_evidence_status": "passed" if passed else "failed",
        "source": "local_current_validation_evidence_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "required_command_count": len(required_commands),
        "passed_command_count": len([command for command in required_commands if command in result_by_command]),
        "missing_commands": missing_commands,
        "non_current_commands": non_current_commands,
        "skipped_commands": skipped_required,
        "failed_commands": failed_required,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness-status-path", type=Path, default=Path("docs/product-readiness-status.json"))
    parser.add_argument("--validation-result-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(
        readiness_status_path=args.readiness_status_path,
        validation_result_paths=args.validation_result_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["current_validation_evidence_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
