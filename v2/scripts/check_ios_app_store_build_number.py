#!/usr/bin/env python3
"""Fail before App Store upload when the iOS build number is not monotonic."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any

V2_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_YML = V2_ROOT / "mobile" / "project.yml"
DEFAULT_INFO_PLIST = V2_ROOT / "mobile" / "Sources" / "AIBotV2" / "Info.plist"
DEFAULT_GUARD_JSON = V2_ROOT / "mobile" / "app-store-build-guard.json"
PREVIOUS_BUILD_ENV_NAMES = (
    "ASC_PREVIOUS_BUILD_NUMBER",
    "APP_STORE_CONNECT_PREVIOUS_BUILD_NUMBER",
    "IOS_PREVIOUS_UPLOADED_BUILD",
    "LATEST_TESTFLIGHT_BUILD_NUMBER",
)


class BuildNumberError(ValueError):
    pass


def _parse_positive_int(value: Any, *, field: str) -> int:
    text = str(value).strip().strip('"').strip("'")
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise BuildNumberError(f"{field} must be a positive integer, got {value!r}")
    return int(text)


def _extract_project_setting(project_yml: Path, key: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*['\"]?([^'\"\n#]+)['\"]?\s*(?:#.*)?$")
    for line in project_yml.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    raise BuildNumberError(f"{key} was not found in {project_yml}")


def _extract_target_setting(project_yml: Path, *, target: str, key: str) -> str:
    target_pattern = re.compile(rf"^\s{{2}}{re.escape(target)}:\s*$")
    next_target_pattern = re.compile(r"^\s{2}\S[^:]*:\s*$")
    setting_pattern = re.compile(rf"^\s*{re.escape(key)}:\s*['\"]?([^'\"\n#]+)['\"]?\s*(?:#.*)?$")
    in_target = False
    for line in project_yml.read_text(encoding="utf-8").splitlines():
        if target_pattern.match(line):
            in_target = True
            continue
        if in_target and next_target_pattern.match(line):
            break
        if in_target:
            match = setting_pattern.match(line)
            if match:
                return match.group(1).strip()
    raise BuildNumberError(f"{key} for target {target} was not found in {project_yml}")


def read_project_metadata(project_yml: Path) -> dict[str, str]:
    return {
        "bundle_identifier": _extract_target_setting(project_yml, target="AIBotV2", key="PRODUCT_BUNDLE_IDENTIFIER"),
        "marketing_version": _extract_project_setting(project_yml, "MARKETING_VERSION"),
        "current_project_version": _extract_project_setting(project_yml, "CURRENT_PROJECT_VERSION"),
    }


def read_info_plist_metadata(info_plist: Path) -> dict[str, Any]:
    with info_plist.open("rb") as handle:
        payload = plistlib.load(handle)
    return {
        "display_name": payload.get("CFBundleDisplayName"),
        "bundle_version": payload.get("CFBundleVersion"),
        "short_version": payload.get("CFBundleShortVersionString"),
    }


def read_guard(guard_json: Path) -> dict[str, Any]:
    if not guard_json.exists():
        return {}
    return json.loads(guard_json.read_text(encoding="utf-8"))


def previous_build_from_env(env: dict[str, str]) -> tuple[int | None, str | None]:
    for name in PREVIOUS_BUILD_ENV_NAMES:
        value = env.get(name)
        if value is not None and value.strip():
            return _parse_positive_int(value, field=name), name
    return None, None


def evaluate_build_number(
    *,
    project_yml: Path = DEFAULT_PROJECT_YML,
    info_plist: Path = DEFAULT_INFO_PLIST,
    guard_json: Path = DEFAULT_GUARD_JSON,
    previous_build: int | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    project = read_project_metadata(project_yml)
    plist = read_info_plist_metadata(info_plist)
    guard = read_guard(guard_json)
    current_build = _parse_positive_int(project["current_project_version"], field="CURRENT_PROJECT_VERSION")

    env_previous_build, previous_source = previous_build_from_env(env)
    if previous_build is not None:
        previous = _parse_positive_int(previous_build, field="previous_build")
        previous_source = "--previous-build"
    elif env_previous_build is not None:
        previous = env_previous_build
    else:
        previous = _parse_positive_int(guard.get("previous_uploaded_build_number", 0), field="previous_uploaded_build_number")
        previous_source = str(guard_json)

    guard_required_minimum = guard.get("required_minimum_build_number")
    guard_required_minimum_int = (
        _parse_positive_int(guard_required_minimum, field="required_minimum_build_number")
        if guard_required_minimum is not None
        else 1
    )
    required_minimum_int = max(
        previous + 1,
        guard_required_minimum_int,
    )

    issues: list[str] = []
    if project["bundle_identifier"] != guard.get("bundle_identifier", project["bundle_identifier"]):
        issues.append("bundle_identifier_does_not_match_guard")
    if project["marketing_version"] != guard.get("marketing_version", project["marketing_version"]):
        issues.append("marketing_version_does_not_match_guard")
    if plist["bundle_version"] != "$(CURRENT_PROJECT_VERSION)":
        issues.append("info_plist_cf_bundle_version_must_use_current_project_version")
    if plist["short_version"] != "$(MARKETING_VERSION)":
        issues.append("info_plist_short_version_must_use_marketing_version")
    if current_build <= previous:
        issues.append("current_build_must_be_greater_than_previous_uploaded_build")
    if current_build < required_minimum_int:
        issues.append("current_build_below_required_minimum")

    return {
        "status": "passed" if not issues else "failed",
        "mode": "read_only_preflight",
        "bundle_identifier": project["bundle_identifier"],
        "marketing_version": project["marketing_version"],
        "current_build_number": current_build,
        "previous_uploaded_build_number": previous,
        "previous_build_source": previous_source,
        "required_minimum_build_number": required_minimum_int,
        "info_plist_bundle_version": plist["bundle_version"],
        "info_plist_short_version": plist["short_version"],
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check iOS build number monotonicity before App Store upload")
    parser.add_argument("--project-yml", type=Path, default=DEFAULT_PROJECT_YML)
    parser.add_argument("--info-plist", type=Path, default=DEFAULT_INFO_PLIST)
    parser.add_argument("--guard-json", type=Path, default=DEFAULT_GUARD_JSON)
    parser.add_argument("--previous-build", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        report = evaluate_build_number(
            project_yml=args.project_yml,
            info_plist=args.info_plist,
            guard_json=args.guard_json,
            previous_build=args.previous_build,
        )
    except (BuildNumberError, FileNotFoundError, json.JSONDecodeError, plistlib.InvalidFileException) as exc:
        report = {
            "status": "failed",
            "mode": "read_only_preflight",
            "issues": ["build_number_preflight_error"],
            "error": str(exc),
        }

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["status"] == "passed":
        print(
            "iOS App Store build number preflight passed: "
            f"current={report['current_build_number']} previous={report['previous_uploaded_build_number']}"
        )
    else:
        print("iOS App Store build number preflight failed:", ", ".join(report.get("issues", [])), file=sys.stderr)
        if report.get("error"):
            print(report["error"], file=sys.stderr)

    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
