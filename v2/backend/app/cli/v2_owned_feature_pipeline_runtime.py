"""V2-owned feature pipeline runtime CLI (smoke / one-shot only)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2.backend.app.services.v2_owned_runtime.smoke_base import (
    base_status,
    emit_status,
    ensure_v2_owned_sys_path,
    probe_imports,
    summarize_import_probes,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

REPO = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = REPO / "v2/frontend/public/operator_runtime/v2_owned_feature_pipeline/latest/status.json"

MODULES = [
    "feature_pipeline",
    "rl.unified_feature_builder",
    "rl.obs_schema",
    "rl.tf_aggregator",
    "rl.microstructure_features",
    "rl.microstructure_aggregator",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2-owned feature pipeline smoke")
    p.add_argument("--once", action="store_true")
    p.add_argument("--symbols", default=None)
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--out", type=Path, default=PUBLIC_STATUS)
    args = p.parse_args(argv)
    symbols = tuple(
        resolve_symbols(
            explicit=(
                tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
                if args.symbols
                else None
            ),
            smoke_test=args.smoke_test,
        )
    )

    added = ensure_v2_owned_sys_path()
    probes = probe_imports(MODULES)
    probe_summary = summarize_import_probes(probes)

    status = base_status("v2_owned_feature_pipeline")
    status.update({
        "sys_path_added": added,
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "module_count": len(MODULES),
        **probe_summary,
        "feature_snapshot_built": False,
        "feature_snapshot_blocked_reason": "DEPENDS_ON_LEGACY_FEATURE_PIPELINE_COMPUTE_PYTHON_DEPS_TORCH_NUMPY_PANDAS",
    })
    emit_status(args.out, status)
    print(json.dumps({k: status[k] for k in ("resolved_count", "unresolved_count", "legacy_root_rejected_count", "smoke_pass")}))
    return 0 if status["smoke_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
