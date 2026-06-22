# Codex Review: codex_review_autoseed_cuda_live_gate_single_pass_trader_runtime_not_started_r1

GO/NO-GO: `V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- blockers_simple: list[str] = []
- blockers_simple.append("Paper edge has not proven it can beat fees.")
- blockers_simple.append("Legacy shutdown is blocked until parity is proven.")
- blockers_simple.append("There are P0 runtime blockers still open.")
- blockers_simple.append(
- blockers: list[str] = []
- blockers_simple: list[str] = []
- blockers_simple.append("Paper edge has not proven it can beat fees.")
- blockers_simple.append("Legacy shutdown is blocked until parity is proven.")
- blockers_simple.append("There are P0 runtime blockers still open.")
- blockers_simple.append(
- 1. Fresh runtime payloads: pass
- 1. periodic static payload sync from this machine,
- blockers: list[str] = []
- blockers: list[str] = []
- blockers.append(LIVE_GATE_BLOCK)

## Raw Output (tail)

```text
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


codex
The patch introduces a security regression in the new SPA catch-all route that can leak arbitrary filesystem content, and a configuration regression where explicit symbol requests can be widened unexpectedly. These are concrete behavior changes that should be addressed before considering the patch correct.

Full review comments:

- [P1] Prevent path traversal before serving SPA files — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/main.py:210-224
  The catch-all SPA route builds `live_candidate`/`candidate` by concatenating user-supplied `full_path` with `public_dir`/`dist_dir` and only checks `is_file()`, so crafted paths with `..` segments can escape those directories and read arbitrary server files (e.g., `/../../../../etc/passwd`) when the backend is exposed publicly or on shared hosts. This bypasses the intended read-only payload/asset scope and should reject paths outside the two mount roots.

- [P2] Do not merge discovered symbols into explicit runtime requests — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/symbol_universe_public_payload.py:171-172
  When `default_to_discovered=True`, `_selected_subset` unconditionally does `requested + discovered`, so any explicit worker request like `requested_training=['BTCUSDT']` can be silently widened to include discovered symbols (for example `ETHUSDT`). This makes startup/runtime symbol scoping non-authoritative and can start workers on symbols the startup configuration did not request.
The patch introduces a security regression in the new SPA catch-all route that can leak arbitrary filesystem content, and a configuration regression where explicit symbol requests can be widened unexpectedly. These are concrete behavior changes that should be addressed before considering the patch correct.

Full review comments:

- [P1] Prevent path traversal before serving SPA files — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/main.py:210-224
  The catch-all SPA route builds `live_candidate`/`candidate` by concatenating user-supplied `full_path` with `public_dir`/`dist_dir` and only checks `is_file()`, so crafted paths with `..` segments can escape those directories and read arbitrary server files (e.g., `/../../../../etc/passwd`) when the backend is exposed publicly or on shared hosts. This bypasses the intended read-only payload/asset scope and should reject paths outside the two mount roots.

- [P2] Do not merge discovered symbols into explicit runtime requests — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/symbol_universe_public_payload.py:171-172
  When `default_to_discovered=True`, `_selected_subset` unconditionally does `requested + discovered`, so any explicit worker request like `requested_training=['BTCUSDT']` can be silently widened to include discovered symbols (for example `ETHUSDT`). This makes startup/runtime symbol scoping non-authoritative and can start workers on symbols the startup configuration did not request.
```
