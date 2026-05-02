#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LEGACY_ROOT="/home/wali/Desktop/AI BOT"

cd "$ROOT"
umask 077

mkdir -p .local_secrets v2/secrets claude_worklog/secret_migration
chmod 700 .local_secrets v2/secrets

ensure_gitignore_entry() {
  local entry="$1"
  touch .gitignore
  if ! grep -Fxq "$entry" .gitignore; then
    printf '%s\n' "$entry" >> .gitignore
  fi
}

ensure_gitignore_entry ".local_secrets/"
ensure_gitignore_entry "v2/.env.local"
ensure_gitignore_entry "v2/secrets/"
ensure_gitignore_entry "*.local.env"
ensure_gitignore_entry "*.secret.local"
ensure_gitignore_entry "*.secrets.local"

env_found="no"
config_found="no"
env_copied="no"
config_copied="no"

if [ -f "$LEGACY_ROOT/.env" ]; then
  env_found="yes"
  cp "$LEGACY_ROOT/.env" .local_secrets/legacy.env
  cp "$LEGACY_ROOT/.env" v2/.env.local
  chmod 600 .local_secrets/legacy.env v2/.env.local
  env_copied="yes"
fi

if [ -f "$LEGACY_ROOT/config.py" ]; then
  config_found="yes"
  cp "$LEGACY_ROOT/config.py" .local_secrets/legacy_config.py
  cp "$LEGACY_ROOT/config.py" v2/secrets/legacy_config.local.py
  chmod 600 .local_secrets/legacy_config.py v2/secrets/legacy_config.local.py
  config_copied="yes"
fi

python3 - "$ROOT" "$env_found" "$config_found" "$env_copied" "$config_copied" <<'PY'
import ast
import os
import re
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
env_found, config_found, env_copied, config_copied = sys.argv[2:6]

manifest = root / "claude_worklog/secret_migration/01_SECRET_KEY_MANIFEST.md"
status = root / "claude_worklog/secret_migration/02_SECRET_MIGRATION_STATUS.md"
env_local = root / ".local_secrets/legacy.env"
config_local = root / ".local_secrets/legacy_config.py"

env_keys = []
if env_local.exists():
    for line in env_local.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            env_keys.append(key)
env_keys = sorted(set(env_keys))

config_names = []
if config_local.exists():
    try:
        tree = ast.parse(config_local.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        config_names.append(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                config_names.append(node.target.id)
    except SyntaxError:
        for line in config_local.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m:
                config_names.append(m.group(1))
config_names = sorted(set(config_names))

warnings = [name for name in config_names if name not in env_keys]

def mode_for(path: Path) -> str:
    if not path.exists():
        return "missing"
    return oct(stat.S_IMODE(path.stat().st_mode))[2:].zfill(3)

local_files = [
    root / ".local_secrets/legacy.env",
    root / "v2/.env.local",
    root / ".local_secrets/legacy_config.py",
    root / "v2/secrets/legacy_config.local.py",
]
permission_rows = [(str(p.relative_to(root)), mode_for(p)) for p in local_files if p.exists()]
permissions_ok = all(mode == "600" for _, mode in permission_rows)

lines = [
    "# Secret Key Manifest",
    "",
    "This manifest contains names only. It intentionally omits values.",
    "",
    "## Sources",
    f"- /home/wali/Desktop/AI BOT/.env: {'found' if env_found == 'yes' else 'missing'}",
    f"- /home/wali/Desktop/AI BOT/config.py: {'found' if config_found == 'yes' else 'missing'}",
    "",
    "## Detected .env key names",
]
lines.extend([f"- {k}" for k in env_keys] or ["- none detected"])
lines.extend([
    "",
    "## Detected config.py assignment names",
])
lines.extend([f"- {k}" for k in config_names] or ["- none detected"])
lines.extend([
    "",
    "## Counts",
    f"- env_key_count: {len(env_keys)}",
    f"- config_assignment_count: {len(config_names)}",
    f"- config_names_not_in_env_count: {len(warnings)}",
    "",
    "## Warnings",
])
lines.extend([f"- config assignment has no matching .env key name: {k}" for k in warnings] or ["- none"])
lines.extend([
    "",
    "SECRET_KEY_MANIFEST_VALUES_OMITTED",
])
manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

ready = (
    env_found == "yes"
    and config_found == "yes"
    and env_copied == "yes"
    and config_copied == "yes"
    and permissions_ok
)
status_lines = [
    "# Secret Migration Status",
    "",
    f"- .env source found: {env_found}",
    f"- config.py source found: {config_found}",
    f"- .env local copies created: {env_copied}",
    f"- config.py local snapshots created: {config_copied}",
    f"- restrictive permissions ok: {'yes' if permissions_ok else 'no'}",
    "- secret value exposure check: committed outputs contain names/status only",
    "",
    "## Local file permissions",
]
status_lines.extend([f"- {rel}: {mode}" for rel, mode in permission_rows] or ["- no local secret files created"])
status_lines.extend([
    "",
    "SECRET_MIGRATION_LOCAL_READY" if ready else "SECRET_MIGRATION_BLOCKED",
])
status.write_text("\n".join(status_lines) + "\n", encoding="utf-8")
print("SECRET_MIGRATION_LOCAL_READY" if ready else "SECRET_MIGRATION_BLOCKED")
PY
