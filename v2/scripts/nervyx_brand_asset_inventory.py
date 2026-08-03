#!/usr/bin/env python3
"""Generate NERVYX /rebranding asset inventory evidence.

This script is intentionally read-only for /rebranding. It inventories approved
source files, records checksum/type/dimension metadata, and maps existing web,
iOS, and watchOS usage evidence without copying or mutating assets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
REBRANDING_ROOT = Path(
    os.environ.get("NERVYX_REBRANDING_ROOT", WORKSPACE_ROOT / "rebranding")
).resolve()

DOC_PATH = REPO_ROOT / "docs" / "nervyx-brand-asset-final-inventory.md"
ARTIFACT_PATH = REPO_ROOT / "artifacts" / "nervyx-brand-asset-inventory.json"
SUMMARY_PATH = REPO_ROOT / "artifacts" / "nervyx-brand-asset-inventory-summary.json"

DESTINATION_ROOTS = [
    REPO_ROOT / "frontend" / "public" / "brand",
    REPO_ROOT / "frontend" / "public" / "icons",
    REPO_ROOT / "frontend" / "src" / "brand" / "generated",
    REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Assets.xcassets",
    REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Brand" / "Generated",
]
DESTINATION_FILES = [
    REPO_ROOT / "frontend" / "public" / "favicon.svg",
    REPO_ROOT / "frontend" / "public" / "manifest.webmanifest",
    REPO_ROOT / "frontend" / "src" / "pwa" / "manifest.ts",
    REPO_ROOT / "frontend" / "index.html",
    REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Info.plist",
    REPO_ROOT / "mobile" / "project.yml",
]

USAGE_SEARCH_ROOTS = [
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "mobile" / "Sources",
]
USAGE_SEARCH_FILES = [
    REPO_ROOT / "frontend" / "index.html",
    REPO_ROOT / "frontend" / "public" / "manifest.webmanifest",
    REPO_ROOT / "frontend" / "src" / "pwa" / "manifest.ts",
    REPO_ROOT / "mobile" / "project.yml",
]

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".plist",
    ".swift",
    ".ts",
    ".tsx",
    ".yml",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def file_type(path: Path) -> str:
    try:
        result = subprocess.run(
            ["file", "-b", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def svg_dimensions(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    viewbox = re.search(r'viewBox=["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)', text)
    if viewbox:
        return f"{viewbox.group(1)} x {viewbox.group(2)} viewBox"
    width = re.search(r'width=["\']([0-9.]+)', text)
    height = re.search(r'height=["\']([0-9.]+)', text)
    if width and height:
        return f"{width.group(1)} x {height.group(1)}"
    return None


def dimensions(path: Path, kind: str) -> str:
    image = re.search(r"(\d+)\s*x\s*(\d+)", kind)
    if image:
        return f"{image.group(1)} x {image.group(2)}"
    pages = re.search(r"(\d+)\s+page", kind)
    if pages:
        return f"{pages.group(1)} pages"
    if path.suffix.lower() == ".svg":
        return svg_dimensions(path) or "vector"
    if path.suffix.lower() == ".json":
        return "structured JSON"
    if path.suffix.lower() == ".css":
        return "stylesheet"
    if path.suffix.lower() == ".zip":
        return "archive"
    return "n/a"


def approved_purpose(name: str) -> str:
    lower = name.lower()
    if "brand-guide" in lower or "brand_guide" in lower or lower.endswith("readme.md"):
        return "Brand kit documentation"
    if lower.endswith(".zip"):
        return "Approved brand kit archive"
    if "brand-tokens" in lower or "theme.css" in lower or "theme-board" in lower:
        return "Theme/token source"
    if "app-icon" in lower or "favicon" in lower:
        return "App, favicon, and PWA icon source"
    if "social-banner" in lower:
        return "Open Graph and social preview image"
    if "logo" in lower or "wordmark" in lower or "symbol" in lower:
        return "Brand logo or mark variant"
    return "Brand asset"


def compatibility(name: str) -> str:
    lower = name.lower()
    if "on-light" in lower or "black" in lower or "dark.svg" in lower or "wordmark-dark" in lower:
        return "Light-surface compatible"
    if "on-midnight" in lower or "white" in lower or "light.svg" in lower or "wordmark-light" in lower:
        return "Dark-surface compatible"
    if "logo-horizontal-dark-1880" in lower or "logo-stacked-dark-1280" in lower:
        return "Light-surface compatible"
    if "logo-horizontal-light-1880" in lower:
        return "Dark-surface compatible"
    if "theme" in lower or "tokens" in lower:
        return "Defines dark/light/admin themes"
    return "Theme-neutral or source-dependent"


def collect_destination_files() -> list[Path]:
    files: set[Path] = set()
    for root in DESTINATION_ROOTS:
        if root.exists():
            files.update(path for path in root.rglob("*") if path.is_file())
    files.update(path for path in DESTINATION_FILES if path.exists())
    return sorted(files)


def destination_index() -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in collect_destination_files():
        index.setdefault(sha256(path), []).append(path)
    return index


def text_files() -> list[Path]:
    files: set[Path] = set(path for path in USAGE_SEARCH_FILES if path.exists())
    for root in USAGE_SEARCH_ROOTS:
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in TEXT_SUFFIXES:
                    files.add(path)
    return sorted(files)


def usage_matches(needles: Iterable[str], roots: tuple[str, ...] | None = None, limit: int = 8) -> list[str]:
    wanted = [needle for needle in needles if needle]
    matches: list[str] = []
    for path in text_files():
        relative = rel(path)
        if roots and not any(relative.startswith(root) for root in roots):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if any(needle in line for needle in wanted):
                snippet = line.strip()
                matches.append(f"{relative}:{line_number}: {snippet[:160]}")
                if len(matches) >= limit:
                    return matches
    return matches


def basename_needles(path: Path) -> list[str]:
    name = path.name
    stems = [name]
    if name.startswith("nervyx-one-"):
        stems.append(f"/brand/{name}")
        stems.append(f"/icons/{name}")
    if name == "nervyx-one-favicon.svg":
        stems.append("/favicon.svg")
    return stems


def generated_destinations(name: str) -> list[str]:
    lower = name.lower()
    paths: list[Path] = []
    if "app-icon-1024.png" in lower:
        paths.extend(
            [
                REPO_ROOT / "frontend" / "public" / "icons" / "icon-192.png",
                REPO_ROOT / "frontend" / "public" / "icons" / "icon-512.png",
            ]
        )
        paths.extend(sorted((REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Assets.xcassets" / "AppIcon.appiconset").glob("*.png")))
    if "brand-tokens.json" in lower:
        paths.extend(
            [
                REPO_ROOT / "frontend" / "src" / "brand" / "generated" / "nervyx-tokens.css",
                REPO_ROOT / "frontend" / "src" / "brand" / "generated" / "nervyx-tokens.ts",
                REPO_ROOT / "frontend" / "src" / "brand" / "generated" / "nervyx-theme-manifest.json",
                REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Brand" / "Generated" / "NervyxTokens.swift",
                REPO_ROOT / "mobile" / "Sources" / "AIBotV2" / "Brand" / "Generated" / "NervyxThemeManifest.swift",
            ]
        )
    return [rel(path) for path in paths if path.exists()]


def classify_usage(source_path: Path) -> tuple[list[str], list[str], list[str]]:
    needles = basename_needles(source_path)
    name = source_path.name.lower()
    if "brand-tokens" in name:
        needles.extend(["nervyxTokens", "NervyxTokens", "NervyxGeneratedThemeManifest"])
    if "app-icon" in name:
        needles.extend(["AppIcon", "icon-192.png", "icon-512.png"])
    if "social-banner" in name:
        needles.append("nervyx-one-social-banner.png")
    web = usage_matches(needles, roots=("v2/frontend/",), limit=8)
    ios = usage_matches(needles, roots=("v2/mobile/Sources/AIBotV2/", "v2/mobile/project.yml"), limit=8)
    watch = usage_matches(
        needles,
        roots=("v2/mobile/Sources/AIBotV2Watch/",),
        limit=8,
    )
    return web, ios, watch


def implementation_status(record: dict[str, object]) -> str:
    if record["web_usage"] or record["ios_usage"] or record["watchos_usage"]:
        return "SOURCE WIRED"
    if record["copied_generated_destinations"]:
        return "COPIED OR GENERATED - USAGE NOT FULLY PROVEN"
    return "INVENTORIED - USAGE NOT YET PROVEN"


def test_status(record: dict[str, object]) -> str:
    statuses = []
    if record["exact_checksum_destinations"]:
        statuses.append("checksum match")
    if record["generated_destinations"]:
        statuses.append("generated output recorded")
    if record["ios_usage"] or record["watchos_usage"]:
        statuses.append("native render blocked on macOS/Xcode")
    if not statuses:
        statuses.append("inventory only")
    return "; ".join(statuses)


def source_files() -> list[Path]:
    if not REBRANDING_ROOT.exists():
        raise SystemExit(f"Missing /rebranding source root: {REBRANDING_ROOT}")
    return sorted(path for path in REBRANDING_ROOT.rglob("*") if path.is_file())


def generate_records() -> list[dict[str, object]]:
    checksum_index = destination_index()
    records: list[dict[str, object]] = []
    for path in source_files():
        digest = sha256(path)
        kind = file_type(path)
        exact = [rel(item) for item in checksum_index.get(digest, [])]
        generated = generated_destinations(path.name)
        web_usage, ios_usage, watch_usage = classify_usage(path)
        destinations = sorted(set(exact + generated))
        record: dict[str, object] = {
            "source_path": rel(path),
            "checksum": digest,
            "file_type": kind,
            "dimensions": dimensions(path, kind),
            "approved_purpose": approved_purpose(path.name),
            "copied_generated_destinations": destinations,
            "exact_checksum_destinations": sorted(exact),
            "generated_destinations": sorted(generated),
            "web_usage": web_usage,
            "ios_usage": ios_usage,
            "watchos_usage": watch_usage,
            "dark_light_compatibility": compatibility(path.name),
        }
        record["implementation_status"] = implementation_status(record)
        record["test_status"] = test_status(record)
        records.append(record)
    return records


def surface_status(records: list[dict[str, object]]) -> list[dict[str, str]]:
    by_source = {Path(str(record["source_path"])).name: record for record in records}

    def proof(*needles: str, roots: tuple[str, ...] | None = None) -> str:
        matches = usage_matches(needles, roots=roots, limit=4)
        return "<br>".join(md_escape(match) for match in matches) if matches else "not proven"

    surfaces = [
        {
            "surface": "Web header logo",
            "approved_source": "nervyx-one-logo-horizontal-on-midnight.svg / nervyx-one-logo-horizontal-on-light.svg",
            "usage": proof("logoOnMidnight", "logoOnLight", roots=("v2/frontend/",)),
            "status": "SOURCE WIRED; rendered route audit still pending",
        },
        {
            "surface": "Web login logo/mark",
            "approved_source": "nervyx-one-symbol-gradient.svg",
            "usage": proof("nervyx-one-symbol-gradient.svg", roots=("v2/frontend/",)),
            "status": "SOURCE WIRED; visual audit pending",
        },
        {
            "surface": "Web landing logo",
            "approved_source": "nervyx-one-logo-horizontal-on-midnight.svg",
            "usage": proof("logoOnMidnight", "nervyx-one-logo-horizontal-on-midnight.svg", roots=("v2/frontend/",)),
            "status": "SOURCE WIRED; visual audit pending",
        },
        {
            "surface": "Favicon",
            "approved_source": "nervyx-one-favicon.svg",
            "usage": proof("/favicon.svg", roots=("v2/frontend/",)),
            "status": "CHECKSUM MATCHED AND REFERENCED",
        },
        {
            "surface": "PWA icons and manifest",
            "approved_source": "nervyx-one-app-icon-1024.png plus generated 192/512 icons",
            "usage": proof("icon-192.png", "icon-512.png", "manifest.webmanifest", roots=("v2/frontend/",)),
            "status": "CONFIGURED; browser install validation pending",
        },
        {
            "surface": "Open Graph and social metadata",
            "approved_source": "nervyx-one-social-banner.png",
            "usage": proof("nervyx-one-social-banner.png", roots=("v2/frontend/",)),
            "status": "SOURCE WIRED; external crawler preview not run",
        },
        {
            "surface": "Error/loading/empty states",
            "approved_source": "nervyx-one-brand-tokens.json",
            "usage": proof("nervyxTokens", "NERVYX_BRAND", roots=("v2/frontend/",)),
            "status": "THEME SOURCE WIRED; full route-state visual validation pending",
        },
        {
            "surface": "iOS AppIcon",
            "approved_source": "nervyx-one-app-icon-1024.png",
            "usage": proof("AppIcon", roots=("v2/mobile/",)),
            "status": "SOURCE CONFIGURED; native simulator/archive validation blocked",
        },
        {
            "surface": "iOS launch screen",
            "approved_source": "NERVYX ONE app identity and AppIcon",
            "usage": proof("UILaunchScreen", "CFBundleDisplayName", roots=("v2/mobile/",)),
            "status": "CONFIGURED; visual launch validation blocked",
        },
        {
            "surface": "iOS login/dashboard/navigation/settings",
            "approved_source": "NERVYX tokens and approved logo assets",
            "usage": proof("NERVYX ONE", "Nervyx", "nervyx-one-symbol-gradient.svg", roots=("v2/mobile/Sources/AIBotV2/",)),
            "status": "SOURCE WIRED; native UI validation blocked",
        },
        {
            "surface": "iOS notification presentation",
            "approved_source": "NERVYX app identity",
            "usage": proof("UNMutableNotificationContent", roots=("v2/mobile/Sources/AIBotV2/",)),
            "status": "SOURCE PRESENT; native notification rendering blocked",
        },
        {
            "surface": "TestFlight metadata",
            "approved_source": "Brand guide and app identity",
            "usage": "No App Store Connect processed-build evidence on Linux",
            "status": "BLOCKED",
        },
        {
            "surface": "watchOS app mark and dashboard/alert identity",
            "approved_source": "NERVYX ONE app identity",
            "usage": proof("NERVYX ONE", "WatchAlertsView", roots=("v2/mobile/Sources/AIBotV2Watch/", "v2/mobile/project.yml")),
            "status": "PARTIAL SOURCE WIRED; watch simulator validation blocked",
        },
        {
            "surface": "watchOS complication/icon assets",
            "approved_source": "No separate complication asset configured",
            "usage": proof("Complication", "CLK", roots=("v2/mobile/Sources/AIBotV2Watch/", "v2/mobile/project.yml")),
            "status": "NOT CONFIGURED IN CURRENT SNAPSHOT; native validation blocked",
        },
    ]

    for surface in surfaces:
        source_names = [item.strip() for item in surface["approved_source"].replace("plus generated 192/512 icons", "").split("/") if item.strip()]
        checksums = []
        for name in source_names:
            record = by_source.get(name)
            if record:
                checksums.append(str(record["checksum"])[:12])
        if checksums:
            surface["source_checksums"] = ", ".join(checksums)
        else:
            surface["source_checksums"] = "n/a"
    return surfaces


def md_escape(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def md_list(items: list[str]) -> str:
    if not items:
        return "not proven"
    return "<br>".join(md_escape(item) for item in items)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_doc(payload: dict[str, object]) -> str:
    records = payload["assets"]
    surfaces = payload["surfaces"]
    summary = payload["summary"]
    lines = [
        "# NERVYX Brand Asset Final Inventory",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Authoritative source: `{payload['rebranding_root']}`",
        "- Source is treated as read-only. This script only scans and records evidence.",
        "- Status: IN PROGRESS. Source/checksum wiring is stronger after this refresh, but native simulator, watchOS, TestFlight, and full visual route-state validation remain pending or blocked.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Source files inventoried | {summary['source_file_count']} |",
        f"| Assets with exact checksum destinations | {summary['assets_with_exact_checksum_destinations']} |",
        f"| Assets with generated destinations | {summary['assets_with_generated_destinations']} |",
        f"| Assets with web usage evidence | {summary['assets_with_web_usage']} |",
        f"| Assets with iOS usage evidence | {summary['assets_with_ios_usage']} |",
        f"| Assets with watchOS usage evidence | {summary['assets_with_watchos_usage']} |",
        f"| Web/native validation still blocked or pending | {summary['blocked_or_pending_validation_count']} |",
        "",
        "## Required Surface Evidence",
        "",
        "| Surface | Approved source | Source checksum prefix | Usage proof | Status |",
        "|---|---|---|---|---|",
    ]
    for surface in surfaces:
        lines.append(
            "| "
            + " | ".join(
                [
                    md_escape(surface["surface"]),
                    md_escape(surface["approved_source"]),
                    md_escape(surface["source_checksums"]),
                    md_escape(surface["usage"]),
                    md_escape(surface["status"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Asset Inventory",
            "",
            "| Source path | SHA256 | File type / dimensions | Approved purpose | Copied/generated destination | Web usage | iOS usage | watchOS usage | Dark/light compatibility | Implementation status | Test status |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    md_escape(record["source_path"]),
                    f"`{record['checksum']}`",
                    md_escape(f"{record['file_type']} / {record['dimensions']}"),
                    md_escape(record["approved_purpose"]),
                    md_list(record["copied_generated_destinations"]),
                    md_list(record["web_usage"]),
                    md_list(record["ios_usage"]),
                    md_list(record["watchos_usage"]),
                    md_escape(record["dark_light_compatibility"]),
                    md_escape(record["implementation_status"]),
                    md_escape(record["test_status"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Remaining Brand Gate Gaps",
            "",
            "- Full route-state visual validation for loading, error, and empty states under each role.",
            "- Authenticated admin and superadmin screenshots after backend-authenticated route audit reruns.",
            "- Native iPhone simulator launch, AppIcon, launch screen, navigation, settings/About, notification, accessibility, and no-clipping evidence.",
            "- Native watchOS simulator launch, watch sync, alert identity, icon/complication confirmation if configured, accessibility, and no-crash evidence.",
            "- Archive validation, TestFlight metadata, processed-build evidence, and App Store Connect status.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = generate_records()
    surfaces = surface_status(records)
    summary = {
        "source_file_count": len(records),
        "assets_with_exact_checksum_destinations": sum(1 for record in records if record["exact_checksum_destinations"]),
        "assets_with_generated_destinations": sum(1 for record in records if record["generated_destinations"]),
        "assets_with_web_usage": sum(1 for record in records if record["web_usage"]),
        "assets_with_ios_usage": sum(1 for record in records if record["ios_usage"]),
        "assets_with_watchos_usage": sum(1 for record in records if record["watchos_usage"]),
        "blocked_or_pending_validation_count": sum(
            1 for surface in surfaces if "pending" in surface["status"].lower() or "blocked" in surface["status"].lower()
        ),
    }
    payload = {
        "generated_at": generated_at,
        "repo_root": str(REPO_ROOT),
        "rebranding_root": str(REBRANDING_ROOT),
        "status": "IN_PROGRESS_NATIVE_VISUAL_TESTFLIGHT_BLOCKED",
        "summary": summary,
        "surfaces": surfaces,
        "assets": records,
    }

    write_json(ARTIFACT_PATH, payload)
    write_json(SUMMARY_PATH, {"generated_at": generated_at, "status": payload["status"], **summary})
    DOC_PATH.write_text(render_doc(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
