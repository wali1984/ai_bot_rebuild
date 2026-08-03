"""Phase 3: CoinAPI / CoinAnk secret + operator-decision closure.

Reads only the env-var NAMES from .local_secrets/legacy.env. Never
records values; emits per-key presence and a classification.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LEGACY_ENV_PATH = Path(".local_secrets/legacy.env")

WATCHED_KEYS: tuple[str, ...] = (
    "COINAPI_API_KEY",
    "COINANK_API_KEY",
    "COINAPI_PRIMARY_EXCHANGE_ID",
    "ENABLE_COINAPI",
    "COINANK_ENABLED",
)

TARGET_WORKLOG = Path(
    "claude_worklog/final_readiness/core_completion_blocker_burndown/latest/coinapi_coinank_secret_decision_status.json"
)
TARGET_PUBLIC = Path(
    "v2/frontend/public/core_completion_blocker_burndown/latest/coinapi_coinank_secret_decision_status.json"
)


def _detect_env_names(env_path: Path, watched: tuple[str, ...]) -> dict[str, bool]:
    present: dict[str, bool] = {k: False for k in watched}
    if not env_path.exists():
        return present
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if name in present:
            present[name] = True
    return present


def main() -> int:
    name_presence = _detect_env_names(LEGACY_ENV_PATH, WATCHED_KEYS)
    # Process env trumps file presence at runtime.
    runtime_presence: dict[str, bool] = {
        k: bool(os.environ.get(k) or name_presence.get(k, False))
        for k in WATCHED_KEYS
    }
    coinapi_classification = (
        "AVAILABLE_FOR_READ_ONLY_DATA"
        if runtime_presence["COINAPI_API_KEY"]
        else "OPERATOR_SECRET_REQUIRED"
    )
    coinank_classification = (
        "AVAILABLE_FOR_READ_ONLY_DATA"
        if runtime_presence["COINANK_API_KEY"]
        else "OPERATOR_SECRET_REQUIRED"
    )
    out = {
        "phase": "P3_COINAPI_COINANK_SECRET_DECISION",
        "schema_version": "v2_coinapi_coinank_secret_decision_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "legacy_env_path_scanned": str(LEGACY_ENV_PATH),
        "watched_keys": list(WATCHED_KEYS),
        "key_presence": runtime_presence,
        "coinapi_classification": coinapi_classification,
        "coinank_classification": coinank_classification,
        "raw_secret_values_recorded": False,
        "live_gate_field": "blocked_human_only",
        "live_symbols_field": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "notes": (
            "AVAILABLE_FOR_READ_ONLY_DATA means the API key is present in the "
            "local secret vault for this host. It does NOT authorize live "
            "trading. Per-ingestor classification for the V2 native ingestors "
            "payload uses these results in Phase 4."
        ),
    }
    body = json.dumps(out, indent=2, sort_keys=True) + "\n"
    TARGET_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    TARGET_WORKLOG.write_text(body)
    TARGET_PUBLIC.write_text(body)
    print(
        "coinapi",
        coinapi_classification,
        "coinank",
        coinank_classification,
        "raw_recorded",
        False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
