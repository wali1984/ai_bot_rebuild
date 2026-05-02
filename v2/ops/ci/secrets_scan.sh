#!/usr/bin/env bash
# CI stage: secrets scan
# Required from milestone B per 07_TEST_AND_CI_PLAN.md §5.
# Uses gitleaks. Scans the repo working tree (no git history, no remote).
# Local-native; never reads .env or secrets/ contents into stdout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"

cd "$REPO_ROOT"

if ! command -v gitleaks >/dev/null 2>&1; then
  cat >&2 <<MSG
[ci/secrets] gitleaks not installed.
Install via:
  Linux:   curl -sSL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz | tar -xz gitleaks && sudo mv gitleaks /usr/local/bin/
  macOS:   brew install gitleaks
  Go:      go install github.com/gitleaks/gitleaks/v8@latest
[ci/secrets] WARN: skipping (advisory in this environment)
MSG
  exit 0
fi

CONFIG_ARG=()
if [ -f "$V2_ROOT/ops/ci/gitleaks.toml" ]; then
  CONFIG_ARG=(--config "$V2_ROOT/ops/ci/gitleaks.toml")
fi

echo "[ci/secrets] gitleaks detect (working tree, no-git, redacted)"
set +e
gitleaks detect \
  --source "$REPO_ROOT" \
  --no-git \
  --redact \
  --verbose \
  "${CONFIG_ARG[@]}"
rc=$?
set -e

if [ "$rc" -ne 0 ]; then
  echo "[ci/secrets] FAIL: gitleaks reported findings (see redacted output above)" >&2
  exit "$rc"
fi
echo "[ci/secrets] OK"
