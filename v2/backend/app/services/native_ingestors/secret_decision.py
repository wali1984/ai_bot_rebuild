"""Redacted local-secret decision source for native ingestors.

Reads only key NAMES (line prefixes before `=`) from a local vault
file. Never reads, returns, prints, logs, or publishes raw values.

Public surface:

- ``key_name_available(name)`` -> bool
- ``decision_snapshot()`` -> dict (key-names only; no values)

Consumers (e.g. ``registry.py``) call these to classify ingestors
into AVAILABLE_FOR_READ_ONLY_DATA / OPERATOR_SECRET_REQUIRED /
operator-decision states. The decision source is paper-only and
never authorizes live trading.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_VAULT_PATH = Path(".local_secrets/legacy.env")
SCHEMA_VERSION = "v2_native_ingestor_secret_decision_v1"


def _read_key_names_from_vault(path: Path) -> set[str]:
    """Return the set of key NAMES present in the local vault file.

    The function reads only the substring before the first ``=`` on each
    non-comment line. It NEVER returns or stores values.
    """
    names: set[str] = set()
    if not path.exists() or not path.is_file():
        return names
    try:
        text = path.read_text()
    except OSError:
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        # Allow common shell prefixes like ``export FOO=...``.
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name:
            names.add(name)
    return names


def key_name_available(
    name: str,
    *,
    vault_path: Path = DEFAULT_VAULT_PATH,
    env: dict | None = None,
) -> bool:
    """Return True if ``name`` is present in os.environ OR in the vault.

    The function does not read or return the value. ``env`` defaults to
    the live process env if not supplied (useful for tests).
    """
    if not name:
        return False
    process_env = os.environ if env is None else env
    if process_env.get(name):
        return True
    names = _read_key_names_from_vault(Path(vault_path))
    return name in names


def decision_snapshot(
    *,
    vault_path: Path = DEFAULT_VAULT_PATH,
    env: dict | None = None,
    watched: Iterable[str] = (
        "COINAPI_API_KEY",
        "COINAPI_KEY",
        "COINANK_API_KEY",
        "ENABLE_COINAPI",
        "COINANK_ENABLED",
        "COINAPI_PRIMARY_EXCHANGE_ID",
        "BINANCE_API_KEY",
        "KUCOIN_API_KEY",
    ),
) -> dict:
    """Return a key-name presence snapshot. Never includes values."""
    process_env = os.environ if env is None else env
    vault_names = _read_key_names_from_vault(Path(vault_path))
    presence: dict[str, bool] = {}
    for k in watched:
        presence[k] = bool(process_env.get(k)) or (k in vault_names)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "vault_path_scanned": str(vault_path),
        "vault_path_exists": Path(vault_path).exists(),
        "key_presence_redacted": presence,
        "raw_secret_values_recorded": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
    }
