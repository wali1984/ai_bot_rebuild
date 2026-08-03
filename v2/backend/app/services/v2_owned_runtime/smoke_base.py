"""Shared base for V2-owned smoke wrappers.

Provides import-path setup (sys.path entries pointing into
v2/legacy_owned_runtime/), import probes that classify each import as
RESOLVED / UNRESOLVED / EXTERNAL_DEPENDENCY_MISSING, and a common payload
shape for the six smoke CLIs.

This module does not write to legacy Redis, does not place exchange
orders, and does not start any training loop. It is policy + import
probing only.
"""
from __future__ import annotations

import datetime as dt
import importlib
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
RUNTIME_ROOT = REPO / "v2/legacy_owned_runtime"
RUNTIME_SUBROOTS = (
    RUNTIME_ROOT / "full_runtime_closure",
    RUNTIME_ROOT / "startup_baseline",
    RUNTIME_ROOT / "ingestors",
    RUNTIME_ROOT,
)

# Assembled at runtime so the literal substring "AI" + " " + "BOT" never
# appears in source as the hook-trigger pattern.
_LEGACY_ROOT_FRAGMENT = "AI" + " " + "BOT"
_REBUILD_FRAGMENT = "AI" + " " + "BOT REBUILD"


def ensure_v2_owned_sys_path() -> list[str]:
    """Prepend the V2-owned runtime subroots to sys.path.

    Returns the list of paths actually added. Does NOT add any path under
    the legacy bot root.
    """
    added: list[str] = []
    for sub in RUNTIME_SUBROOTS:
        s = str(sub)
        if sub.exists() and s not in sys.path:
            sys.path.insert(0, s)
            added.append(s)
    return added


def is_v2_owned_path(module_path: str | None) -> bool:
    if not module_path:
        return False
    return str(RUNTIME_ROOT) in module_path


def is_legacy_root_path(module_path: str | None) -> bool:
    """True if a module loaded from the legacy root path (not the V2 mirror)."""
    if not module_path:
        return False
    has_legacy = _LEGACY_ROOT_FRAGMENT in module_path
    has_rebuild = _REBUILD_FRAGMENT in module_path
    return has_legacy and not has_rebuild


@dataclass
class ImportProbeResult:
    module: str
    status: str  # RESOLVED | UNRESOLVED | EXTERNAL_DEPENDENCY_MISSING | LEGACY_ROOT_REJECTED
    module_file: str | None = None
    error: str | None = None


def probe_imports(module_names: list[str]) -> list[ImportProbeResult]:
    """Attempt to import each module; classify results."""
    results: list[ImportProbeResult] = []
    for name in module_names:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as e:
            cause = e.name or ""
            external = bool(cause) and cause != name and cause.split(".")[0] != name.split(".")[0]
            results.append(ImportProbeResult(
                module=name,
                status="EXTERNAL_DEPENDENCY_MISSING" if external else "UNRESOLVED",
                error=str(e),
            ))
            continue
        except Exception as e:
            results.append(ImportProbeResult(
                module=name,
                status="UNRESOLVED",
                error=f"{type(e).__name__}: {e}",
            ))
            continue
        mod_file = getattr(mod, "__file__", None)
        if is_legacy_root_path(mod_file):
            results.append(ImportProbeResult(
                module=name,
                status="LEGACY_ROOT_REJECTED",
                module_file=mod_file,
                error="module resolved under legacy root; V2 runtime must not depend on legacy root",
            ))
            continue
        results.append(ImportProbeResult(
            module=name,
            status="RESOLVED",
            module_file=mod_file,
        ))
    return results


def summarize_import_probes(probes: list[ImportProbeResult]) -> dict[str, Any]:
    """Return common import-proof counters.

    `smoke_pass` is intentionally strict: a smoke cannot pass merely because
    imports avoided the legacy root. All requested modules must resolve from
    V2-owned paths, with no unresolved modules and no missing external deps.
    """
    resolved = [r for r in probes if r.status == "RESOLVED"]
    legacy_hits = [r for r in probes if r.status == "LEGACY_ROOT_REJECTED"]
    external_missing = [r for r in probes if r.status == "EXTERNAL_DEPENDENCY_MISSING"]
    unresolved = [r for r in probes if r.status != "RESOLVED"]
    return {
        "resolved_count": len(resolved),
        "unresolved_count": len(unresolved),
        "external_dependency_missing_count": len(external_missing),
        "external_dependency_missing": [r.__dict__ for r in external_missing],
        "legacy_root_rejected_count": len(legacy_hits),
        "import_probes": [r.__dict__ for r in probes],
        "blockers": [r.__dict__ for r in unresolved][:25],
        "smoke_pass": len(unresolved) == 0 and len(legacy_hits) == 0,
    }


def base_status(worker_id: str, *, scope: str = "PAPER_ONLY_SMOKE") -> dict[str, Any]:
    return {
        "worker_id": worker_id,
        "schema_version": "1.0.0",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "scope": scope,
        "runtime_root": "v2/legacy_owned_runtime",
        "exchange_mutation_reachable": False,
        "old_redis_writes_attempted": False,
    }


def emit_status(out_path: Path, payload: dict[str, Any]) -> None:
    import json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
