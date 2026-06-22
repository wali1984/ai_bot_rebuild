"""Safe credential loader for ``live_credentials.env``.

Loads env var **names only** from the canonical credentials file. The
returned value mapping is intentionally redacted: each key maps to one of
``KEY_PRESENT_BY_NAME`` or ``KEY_ABSENT_BY_NAME``. Raw secret values are
never returned, logged, or written to any artifact by this module.

Typical usage::

    from v2.backend.app.services.safe_env_loader import load_credentials

    report = load_credentials()
    # report["keys"]["BINANCE_API_KEY"] -> "KEY_PRESENT_BY_NAME"
    # report["values_exposed"] -> False

The module also exposes :func:`bind_to_environ` which, when called
explicitly with ``apply=True``, copies the named values from the
credentials file into ``os.environ`` for in-process consumers that need
them. The raw values still never leave the local process memory.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional


KEY_PRESENT = "KEY_PRESENT_BY_NAME"
KEY_ABSENT = "KEY_ABSENT_BY_NAME"
KEY_EMPTY_VALUE = "KEY_EMPTY_VALUE"

DEFAULT_CREDENTIALS_PATH = Path(
    "/home/wali/Desktop/AI BOT REBUILD/.local_secrets/live_credentials.env"
)

# Repo root resolved from this file: .../v2/backend/app/services/safe_env_loader.py
_REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_LOCAL_PATH = _REPO_ROOT / "v2" / ".env.local"
ALT_DATA_PATH = _REPO_ROOT / ".local_secrets" / "alternative_data.env"
LIVE_CREDENTIALS_PATH = _REPO_ROOT / ".local_secrets" / "live_credentials.env"

# Layered credential source order. ``v2/.env.local`` is the canonical operator
# file (user-maintained); the .local_secrets files supplement it for keys that
# only live there (e.g. LunarCrush / Nansen alt-data). First file that supplies
# a non-empty value for a name wins.
LAYERED_CREDENTIAL_PATHS = (ENV_LOCAL_PATH, ALT_DATA_PATH, LIVE_CREDENTIALS_PATH)

# Data-provider API keys that paper/shadow ingestors legitimately need. This is
# the ONLY set auto-bound into ``os.environ`` by :func:`bootstrap_process_env`.
#
# Deliberately EXCLUDED from the auto-bootstrap (default-blocked safety posture):
#   - live exchange private keys (BINANCE_API_KEY/SECRET, *_ASJAD, *_BROTHER,
#     *_FUT_*, testnet keys) — only the operator-gated live canary/executor may
#     bind these, via an explicit opt-in path.
#   - behaviour/risk flags (LIVE_TRAINING_ENABLED, TRADE_MODE, MAX_LEVERAGE,
#     ALLOW_LEVERAGE_SET, ENABLE_* ...) — these must flow through versioned
#     config admin, never silent env injection.
#   - messaging enablement (TELEGRAM_ENABLED, channel IDs) — operator-gated.
DATA_PROVIDER_CREDENTIAL_NAMES = (
    "COINANK_API_KEY",
    "COINAPI_API_KEY",
    "TOKENMETRICS_API_KEY",
    "ARKHAM_API_KEY",
    "COINGLASS_API_KEY",
    "COINGECKO_API_KEY",
    "ASKSURF_API_KEY",
    "SURF_API_KEY",
    "LUNARCRUSH_API_KEY",
    "NANSEN_API_KEY",
    "ALPHAVANTAGE_API_KEY",
)

# Required exchange credentials (names only; aliases enumerated explicitly).
REQUIRED_BINANCE_KEY_NAMES = ("BINANCE_API_KEY", "BINANCE_API_SECRET")

# Adapter-stub historical aliases (for back-compat presence check).
LEGACY_BINANCE_ALIAS_NAMES = ("BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET")

# Optional V2 alt-data / messaging credential aliases that *may* be present.
OPTIONAL_V2_CREDENTIAL_ALIASES = (
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "COINANK_API_KEY",
    "TOKENMETRICS_API_KEY",
    "COINAPI_API_KEY",
    "ARKHAM_API_KEY",
    "COINGLASS_API_KEY",
    "COINGECKO_API_KEY",
    "ASKSURF_API_KEY",
    "SURF_API_KEY",
)


def _parse_env_file_names_and_values(path: Path) -> Dict[str, str]:
    """Parse a dotenv-style file. Returns name->raw value mapping.

    Raw values are kept *only* inside this function call's return value
    and are never logged. Callers that don't need the values should call
    :func:`load_credentials` instead, which strips values immediately.
    """
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # strip optional surrounding quotes without leaking content
        if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def _redact(name_to_value: Mapping[str, str]) -> Dict[str, str]:
    """Convert name->value into name->presence sentinel."""
    redacted: Dict[str, str] = {}
    for name, value in name_to_value.items():
        if value is None or value == "":
            redacted[name] = KEY_EMPTY_VALUE
        else:
            redacted[name] = KEY_PRESENT
    return redacted


def load_credentials(
    path: Optional[Path] = None,
    *,
    required: Iterable[str] = REQUIRED_BINANCE_KEY_NAMES,
    aliases: Iterable[str] = LEGACY_BINANCE_ALIAS_NAMES,
    optional: Iterable[str] = OPTIONAL_V2_CREDENTIAL_ALIASES,
) -> Dict[str, object]:
    """Return a redacted presence report. Values are never included.

    Parameters
    ----------
    path
        Path to ``live_credentials.env``. Defaults to the project canonical
        ``.local_secrets/live_credentials.env``.

    Returns
    -------
    dict
        ``{"keys": {name: sentinel}, "missing_required": [...],
            "values_exposed": False, "path": "..."}``
    """
    p = Path(path) if path is not None else DEFAULT_CREDENTIALS_PATH
    parsed = _parse_env_file_names_and_values(p)
    redacted = _redact(parsed)

    seen = set(parsed.keys())
    missing_required = [k for k in required if k not in seen or not parsed.get(k)]
    missing_aliases = [k for k in aliases if k not in seen or not parsed.get(k)]
    optional_present = [k for k in optional if k in seen and parsed.get(k)]

    return {
        "path": str(p),
        "path_exists": p.is_file(),
        "keys": redacted,
        "key_count": len(parsed),
        "required_key_names": list(required),
        "alias_key_names": list(aliases),
        "optional_key_names_present": optional_present,
        "missing_required_by_name": missing_required,
        "missing_aliases_by_name": missing_aliases,
        "values_exposed": False,
        "loader_module": __name__,
    }


def bind_to_environ(
    path: Optional[Path] = None,
    *,
    apply: bool = False,
    keys: Optional[Iterable[str]] = None,
    overwrite: bool = False,
) -> Dict[str, str]:
    """Copy named values from the credentials file into ``os.environ``.

    The raw values are placed into ``os.environ`` only — they are not
    returned by this function (the returned mapping uses sentinels).
    Callers must pass ``apply=True`` to opt in to mutation.
    """
    p = Path(path) if path is not None else DEFAULT_CREDENTIALS_PATH
    parsed = _parse_env_file_names_and_values(p)
    selected = list(keys) if keys is not None else list(parsed.keys())
    bound: Dict[str, str] = {}
    for name in selected:
        if name not in parsed:
            bound[name] = KEY_ABSENT
            continue
        if (name in os.environ) and not overwrite and not apply:
            bound[name] = KEY_PRESENT
            continue
        if apply and (overwrite or name not in os.environ):
            os.environ[name] = parsed[name]
        bound[name] = KEY_PRESENT if parsed[name] else KEY_EMPTY_VALUE
    return bound


def bootstrap_process_env(
    *,
    apply: bool = True,
    names: Iterable[str] = DATA_PROVIDER_CREDENTIAL_NAMES,
    paths: Iterable[Path] = LAYERED_CREDENTIAL_PATHS,
    overwrite: bool = False,
) -> Dict[str, object]:
    """Bind data-provider API keys from the layered credential files into env.

    For each allow-listed name, the first ``paths`` entry that supplies a
    non-empty value wins and is copied into ``os.environ`` (unless already set
    and ``overwrite`` is False). ``v2/.env.local`` is the canonical primary
    source; the .local_secrets files supplement it.

    Raw values are placed only into ``os.environ`` — never returned, logged, or
    written to any artifact. The returned report uses presence sentinels and is
    safe to serialise into worklog status payloads.

    Only :data:`DATA_PROVIDER_CREDENTIAL_NAMES` are bound by default. Live
    exchange private keys and behaviour/risk flags are intentionally never
    auto-bound (see the constant's docstring), preserving the default-blocked
    live-trading posture.
    """
    name_list = list(names)
    path_list = [Path(p) for p in paths]
    # Parse each source once (values held only in local scope).
    parsed_by_path = [(_p, _parse_env_file_names_and_values(_p)) for _p in path_list]

    report_keys: Dict[str, str] = {}
    bound_names: list[str] = []
    source_of: Dict[str, str] = {}
    for name in name_list:
        if (name in os.environ) and os.environ.get(name) and not overwrite:
            report_keys[name] = KEY_PRESENT
            source_of[name] = "os_environ_preexisting"
            continue
        resolved_value: Optional[str] = None
        resolved_path: Optional[str] = None
        for p, parsed in parsed_by_path:
            v = parsed.get(name)
            if v:
                resolved_value = v
                resolved_path = str(p)
                break
        if resolved_value is None:
            report_keys[name] = KEY_ABSENT
            continue
        if apply:
            os.environ[name] = resolved_value
        report_keys[name] = KEY_PRESENT
        bound_names.append(name)
        source_of[name] = resolved_path or "?"

    return {
        "keys": report_keys,
        "bound_names": bound_names,
        "bound_count": len(bound_names),
        "absent_names": [n for n in name_list if report_keys.get(n) == KEY_ABSENT],
        "source_paths_checked": [str(p) for p in path_list],
        "source_paths_existing": [str(p) for p, _ in parsed_by_path if p.is_file()],
        "name_to_source_file": source_of,
        "values_exposed": False,
        "applied_to_os_environ": apply,
        "loader_module": __name__,
    }
