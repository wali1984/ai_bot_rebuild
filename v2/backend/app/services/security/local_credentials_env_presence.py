"""Presence-only probe for the operator-maintained credentials env file.

The canonical secret store is ``.local_secrets/live_credentials.env``.
This module:

* never logs, returns, or stores any secret VALUE
* returns only the set of variable NAMES present in the file
* is safe to call at startup; missing file is reported as
  ``file_present=False``
* keeps callers from accidentally serialising secrets — the public
  ``probe_local_credentials_env_presence`` function returns dataclass
  fields that hold names only and an integer line count

The function is callable from the V2 paper-startup supervisor's API key
audit (which already records env-var names only). It augments
``os.environ`` probing for operators who keep their secrets in the
local env file rather than shell exports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


DEFAULT_LOCAL_CREDENTIALS_PATH = Path(".local_secrets/live_credentials.env")

# Strict KEY=VALUE line matcher. Optional leading "export ", uppercase
# names with digits/underscore. We only capture the NAME (group 1).
_KEY_LINE_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*="
)


@dataclass(frozen=True)
class LocalCredentialsPresenceResult:
    file_path: str
    file_present: bool
    parse_error: str | None = None
    present_var_names: tuple[str, ...] = field(default_factory=tuple)
    raw_secret_value_read_or_emitted: bool = False
    line_count_observed: int | None = None


def probe_local_credentials_env_presence(
    repo_root: Path,
    *,
    relative_path: Path = DEFAULT_LOCAL_CREDENTIALS_PATH,
) -> LocalCredentialsPresenceResult:
    """Read the env file and return only the variable NAMES it defines.

    Never opens any other file. Never returns a value. The function
    refuses to keep a value in any local variable beyond the line scan
    loop; only ``name`` is captured.
    """
    full_path = (repo_root / relative_path).resolve()
    if not full_path.exists() or not full_path.is_file():
        return LocalCredentialsPresenceResult(
            file_path=str(full_path),
            file_present=False,
        )
    try:
        text = full_path.read_text(encoding="utf-8")
    except OSError as err:
        return LocalCredentialsPresenceResult(
            file_path=str(full_path),
            file_present=True,
            parse_error=f"read_error:{type(err).__name__}",
        )
    names: list[str] = []
    seen: set[str] = set()
    line_count = 0
    for line in text.splitlines():
        line_count += 1
        # Skip comments and blanks before regex to avoid even touching
        # value-bearing trailing text.
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _KEY_LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    # Defensive: the result NEVER includes any captured value. The
    # value side of the line never enters a local variable; only the
    # name does.
    return LocalCredentialsPresenceResult(
        file_path=str(full_path),
        file_present=True,
        present_var_names=tuple(names),
        line_count_observed=line_count,
        raw_secret_value_read_or_emitted=False,
    )


def merge_env_presence(
    env_names: Iterable[str],
    *,
    env_getter,
    file_present_names: Iterable[str],
) -> dict[str, str]:
    """Combine os.environ presence + local-credentials-file presence.

    Returns a name -> source-label dict. Source labels:

      * ``"OS_ENV_AND_LOCAL_FILE"`` — present in both
      * ``"OS_ENV_ONLY"`` — only in os.environ (shell export)
      * ``"LOCAL_FILE_ONLY"`` — only in the credentials file
      * ``"ABSENT"`` — neither source defines it

    Never reads or returns a value. Caller must not call the env_getter
    function for anything other than presence (truthy/falsy).
    """
    file_names = set(file_present_names)
    out: dict[str, str] = {}
    for name in env_names:
        in_os = bool(env_getter(name))
        in_file = name in file_names
        if in_os and in_file:
            out[name] = "OS_ENV_AND_LOCAL_FILE"
        elif in_os:
            out[name] = "OS_ENV_ONLY"
        elif in_file:
            out[name] = "LOCAL_FILE_ONLY"
        else:
            out[name] = "ABSENT"
    return out
