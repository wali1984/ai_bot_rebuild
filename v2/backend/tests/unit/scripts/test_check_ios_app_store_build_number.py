from __future__ import annotations

import json
import plistlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_ios_app_store_build_number import BuildNumberError, evaluate_build_number


def _write_project(tmp_path: Path, *, build: str = "5") -> Path:
    path = tmp_path / "project.yml"
    path.write_text(
        f"""name: AIBotV2
settings:
  base:
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: "{build}"
targets:
  AIBotV2Core:
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.wali1984.aibot-v2.core
  AIBotV2:
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.wali1984.aibot-v2
""",
        encoding="utf-8",
    )
    return path


def _write_info_plist(tmp_path: Path) -> Path:
    path = tmp_path / "Info.plist"
    with path.open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleDisplayName": "NERVYX ONE",
                "CFBundleShortVersionString": "$(MARKETING_VERSION)",
                "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
            },
            handle,
        )
    return path


def _write_guard(tmp_path: Path, *, previous: int = 4, minimum: int = 5) -> Path:
    path = tmp_path / "app-store-build-guard.json"
    path.write_text(
        json.dumps(
            {
                "bundle_identifier": "com.wali1984.aibot-v2",
                "marketing_version": "1.0.0",
                "previous_uploaded_build_number": previous,
                "required_minimum_build_number": minimum,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_ios_app_store_build_guard_passes_when_current_exceeds_previous(tmp_path: Path) -> None:
    report = evaluate_build_number(
        project_yml=_write_project(tmp_path, build="5"),
        info_plist=_write_info_plist(tmp_path),
        guard_json=_write_guard(tmp_path, previous=4, minimum=5),
        env={},
    )

    assert report["status"] == "passed"
    assert report["bundle_identifier"] == "com.wali1984.aibot-v2"
    assert report["current_build_number"] == 5
    assert report["previous_uploaded_build_number"] == 4
    assert report["issues"] == []


def test_ios_app_store_build_guard_fails_when_build_was_already_uploaded(tmp_path: Path) -> None:
    report = evaluate_build_number(
        project_yml=_write_project(tmp_path, build="5"),
        info_plist=_write_info_plist(tmp_path),
        guard_json=_write_guard(tmp_path, previous=5, minimum=6),
        env={},
    )

    assert report["status"] == "failed"
    assert "current_build_must_be_greater_than_previous_uploaded_build" in report["issues"]
    assert "current_build_below_required_minimum" in report["issues"]


def test_ios_app_store_build_guard_uses_ci_previous_build_override(tmp_path: Path) -> None:
    report = evaluate_build_number(
        project_yml=_write_project(tmp_path, build="5"),
        info_plist=_write_info_plist(tmp_path),
        guard_json=_write_guard(tmp_path, previous=4, minimum=5),
        env={"ASC_PREVIOUS_BUILD_NUMBER": "5"},
    )

    assert report["status"] == "failed"
    assert report["previous_uploaded_build_number"] == 5
    assert report["previous_build_source"] == "ASC_PREVIOUS_BUILD_NUMBER"
    assert "current_build_must_be_greater_than_previous_uploaded_build" in report["issues"]


def test_ios_app_store_build_guard_rejects_non_integer_build(tmp_path: Path) -> None:
    try:
        evaluate_build_number(
            project_yml=_write_project(tmp_path, build="5-beta"),
            info_plist=_write_info_plist(tmp_path),
            guard_json=_write_guard(tmp_path),
            env={},
        )
    except BuildNumberError as exc:
        assert "CURRENT_PROJECT_VERSION must be a positive integer" in str(exc)
    else:
        raise AssertionError("non-integer build number was accepted")
