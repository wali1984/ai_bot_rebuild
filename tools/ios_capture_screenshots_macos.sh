#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "IOS_SIMULATOR_SCREENSHOTS_REQUIRE_MACOS_XCODE_HOST"
  exit 78
fi

command -v xcrun >/dev/null || { echo "IOS_SIMULATOR_SCREENSHOTS_REQUIRE_MACOS_XCODE_HOST"; exit 78; }
command -v xcodebuild >/dev/null || { echo "IOS_SIMULATOR_SCREENSHOTS_REQUIRE_MACOS_XCODE_HOST"; exit 78; }

GOAL_ID="${GOAL_ID:-V2_ENTERPRISE_WEB_IOS_REALTIME_TRADING_CONTROL_CENTER_AND_DATA_TRUTH_COMPLETION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${IOS_SCREENSHOT_OUTPUT_DIR:-$REPO_ROOT/goal_state/$GOAL_ID/ios_simulator_screenshots}"
STATUS_JSON="$OUT_DIR/ios_simulator_screenshot_status.json"
API_BASE_URL="${IOS_SCREENSHOT_API_BASE_URL:-https://dashboard.wajidali.us}"
API_SOURCE_MODE="${IOS_SCREENSHOT_API_SOURCE_MODE:-staging_api}"
ALLOW_PARTIAL="${IOS_SCREENSHOT_ALLOW_PARTIAL:-0}"
HARNESS_COMMAND="${IOS_SCREENSHOT_HARNESS_COMMAND:-}"

REQUIRED_SCREENS=(
  "login"
  "dashboard"
  "market"
  "providers_ingestors"
  "trainer_ai"
  "risk_control"
  "live_readiness"
  "a_plus_inventory"
  "paper_probation"
  "portfolio"
)

mkdir -p "$OUT_DIR"
cd "$REPO_ROOT"

write_status() {
  local status="$1"
  local message="$2"
  local all_captured="${3:-false}"
  local simulator_udid="${SIMULATOR_UDID:-}"
  local simulator_name="${SIMULATOR_NAME:-}"
  local simulator_runtime="${SIMULATOR_RUNTIME:-}"
  local xcode_version
  xcode_version="$(xcodebuild -version 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]*$//')"

  python3 - "$STATUS_JSON" "$GOAL_ID" "$status" "$message" "$all_captured" "$OUT_DIR" "$API_BASE_URL" "$API_SOURCE_MODE" "$simulator_udid" "$simulator_name" "$simulator_runtime" "$xcode_version" "$HARNESS_COMMAND" "${REQUIRED_SCREENS[@]}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from glob import glob

(
    status_path,
    goal_id,
    status,
    message,
    all_captured,
    out_dir,
    api_base_url,
    api_source_mode,
    simulator_udid,
    simulator_name,
    simulator_runtime,
    xcode_version,
    harness_command,
    *required_screens,
) = sys.argv[1:]

def screenshot_candidates(screen: str) -> list[str]:
    names = {
        screen,
        screen.replace("_", "-"),
        screen.replace("_", ""),
        f"{screen}_screen",
        f"{screen.replace('_', '-')}-screen",
    }
    paths: list[str] = []
    for name in names:
        paths.extend(glob(os.path.join(out_dir, f"{name}.png")))
    return sorted(set(paths))

screens = []
missing = []
for screen in required_screens:
    candidates = screenshot_candidates(screen)
    captured = bool(candidates)
    if not captured:
        missing.append(screen)
    screens.append(
        {
            "screen": screen,
            "required": True,
            "captured": captured,
            "path": os.path.relpath(candidates[0], os.getcwd()) if candidates else None,
            "missing_reason": None if captured else (
                "IOS_SCREENSHOT_NAVIGATION_HARNESS_NOT_PRESENT"
                if not harness_command
                else "IOS_SCREENSHOT_HARNESS_DID_NOT_PRODUCE_SCREEN"
            ),
        }
    )

payload = {
    "schema_version": "ios_simulator_screenshot_status_v1",
    "goal_id": goal_id,
    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": status,
    "message": message,
    "all_required_screens_captured": all_captured.lower() == "true",
    "missing_screens": missing,
    "required_screens": required_screens,
    "screens": screens,
    "api_source_mode": api_source_mode,
    "api_base_url": api_base_url,
    "screenshot_harness_present": bool(harness_command),
    "screenshot_harness_command_configured": bool(harness_command),
    "screenshot_harness_boundary": (
        "Operator-provided IOS_SCREENSHOT_HARNESS_COMMAND is responsible for authenticated navigation screenshots."
        if harness_command
        else "The real app was launched and the login screen was captured; authenticated screen navigation requires a macOS UI-test or harness command and screenshots are not faked."
    ),
    "simulator": {
        "device_udid": simulator_udid,
        "device_name": simulator_name,
        "runtime": simulator_runtime,
    },
    "toolchain": {
        "xcodebuild_version": xcode_version,
        "xcrun_present": True,
        "xcodebuild_present": True,
    },
    "linux_exit_code": 78,
    "raw_credentials_captured": False,
    "order_submitted": False,
    "test_order_submitted": False,
    "leverage_mutated": False,
    "margin_mutated": False,
}

os.makedirs(os.path.dirname(status_path), exist_ok=True)
with open(status_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")
PY
}

cleanup_simulator() {
  if [[ -n "${SIMULATOR_UDID:-}" ]]; then
    xcrun simctl shutdown "$SIMULATOR_UDID" >/dev/null 2>&1 || true
    xcrun simctl delete "$SIMULATOR_UDID" >/dev/null 2>&1 || true
  fi
}
trap cleanup_simulator EXIT

if ! command -v xcodegen >/dev/null 2>&1; then
  write_status "BLOCKED_MISSING_XCODEGEN" "xcodegen is required to generate v2/mobile/AIBotV2.xcodeproj from project.yml on macOS." false
  exit 1
fi

# `swift test` rebuilds the whole SwiftPM package on the macOS host, which
# fails on the iOS/watchOS app targets (WatchKit is watchOS-only; @Observable
# needs macOS 14). Drop those app targets from the SwiftPM graph for the
# contract test only — Package.swift honors AIBOT_SPM_EXCLUDE_APP_TARGETS.
# The app itself is still built below via xcodegen + xcodebuild against the
# iOS simulator SDK (which leaves the variable unset).
AIBOT_SPM_EXCLUDE_APP_TARGETS=1 swift test --package-path v2/mobile

(
  cd v2/mobile
  xcodegen generate --spec project.yml
)

read -r DEVICE_TYPE_ID SIMULATOR_RUNTIME < <(
  python3 <<'PY'
import json
import subprocess
import sys

def load(args):
    return json.loads(subprocess.check_output(args, text=True))

device_types = load(["xcrun", "simctl", "list", "devicetypes", "-j"]).get("devicetypes", [])
runtimes = load(["xcrun", "simctl", "list", "runtimes", "-j"]).get("runtimes", [])

preferred_devices = ["iPhone 16 Pro", "iPhone 15 Pro", "iPhone 14 Pro", "iPhone 13 Pro"]
device = next((d for name in preferred_devices for d in device_types if d.get("name") == name), None)
if device is None:
    device = next((d for d in device_types if str(d.get("name", "")).startswith("iPhone")), None)

ios_runtimes = [
    r for r in runtimes
    if r.get("isAvailable") and str(r.get("identifier", "")).startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
]
ios_runtimes.sort(key=lambda r: r.get("version", ""), reverse=True)
runtime = ios_runtimes[0] if ios_runtimes else None

if not device or not runtime:
    sys.exit(2)

print(device["identifier"], runtime["identifier"])
PY
)

if [[ -z "${DEVICE_TYPE_ID:-}" || -z "${SIMULATOR_RUNTIME:-}" ]]; then
  write_status "BLOCKED_NO_AVAILABLE_IOS_SIMULATOR_RUNTIME" "No available iPhone simulator device type and iOS runtime pair was found on this macOS/Xcode host." false
  exit 1
fi

SIMULATOR_NAME="NERVYX Screenshot iPhone"
SIMULATOR_UDID="$(xcrun simctl create "$SIMULATOR_NAME" "$DEVICE_TYPE_ID" "$SIMULATOR_RUNTIME")"
xcrun simctl boot "$SIMULATOR_UDID" || true
xcrun simctl bootstatus "$SIMULATOR_UDID" -b

DERIVED_DATA="${RUNNER_TEMP:-/tmp}/nervyx-ios-screenshots-derived"
rm -rf "$DERIVED_DATA"
xcodebuild \
  -project v2/mobile/AIBotV2.xcodeproj \
  -scheme AIBotV2 \
  -destination "id=$SIMULATOR_UDID" \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP_PATH="$(find "$DERIVED_DATA/Build/Products" -name "AIBotV2.app" -type d | head -n 1)"
if [[ -z "$APP_PATH" ]]; then
  write_status "FAILED_APP_BUNDLE_NOT_FOUND" "xcodebuild succeeded but AIBotV2.app was not found under derived data." false
  exit 1
fi

BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Info.plist")"
xcrun simctl install "$SIMULATOR_UDID" "$APP_PATH"
xcrun simctl launch "$SIMULATOR_UDID" "$BUNDLE_ID" -ApplePersistenceIgnoreState YES >/tmp/nervyx-ios-screenshot-launch.log
sleep 6
xcrun simctl io "$SIMULATOR_UDID" screenshot "$OUT_DIR/login.png"

if [[ -n "$HARNESS_COMMAND" ]]; then
  IOS_SCREENSHOT_UDID="$SIMULATOR_UDID" \
  IOS_SCREENSHOT_OUTPUT_DIR="$OUT_DIR" \
  IOS_SCREENSHOT_BUNDLE_ID="$BUNDLE_ID" \
  IOS_SCREENSHOT_API_BASE_URL="$API_BASE_URL" \
    bash -lc "$HARNESS_COMMAND"
fi

missing_count=0
for screen in "${REQUIRED_SCREENS[@]}"; do
  if ! compgen -G "$OUT_DIR/${screen}.png" >/dev/null && ! compgen -G "$OUT_DIR/${screen//_/-}.png" >/dev/null; then
    missing_count=$((missing_count + 1))
  fi
done

if [[ "$missing_count" -eq 0 ]]; then
  write_status "READY_IOS_SIMULATOR_SCREENSHOTS_CAPTURED" "All required iOS simulator screenshots were captured on macOS/Xcode." true
  exit 0
fi

write_status "PARTIAL_SCREENSHOTS_PENDING_NAVIGATION_HARNESS" "macOS/Xcode simulator launch succeeded, login screenshot was captured, and authenticated screens remain pending a real UI-test/navigation harness." false

if [[ "$ALLOW_PARTIAL" == "1" ]]; then
  exit 0
fi
exit 2
