"""V2-owned trainer runtime CLI (dry-run / no-train only).

Probes trainer module imports under v2/legacy_owned_runtime/. Does NOT
start any training loop, does NOT initialize CUDA, does NOT load model
weights. This is a paper-only smoke that proves the V2-owned import path
resolves the trainer modules without touching the legacy bot root.
"""
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
PUBLIC_STATUS = REPO / "v2/frontend/public/operator_runtime/v2_owned_trainer/latest/status.json"

TRAINER_MODULES = [
    "rl.hybrid_trainer",
    "rl.environment",
    "rl.gymnasium_wrapper",
    "rl.unified_feature_builder",
    "rl.obs_schema",
    "rl.agents.masa_agent",
    "rl.supervised_trainer",
    "rl.reward_functions",
    "rl.constrained_reward",
    "rl.fee_ratio_reward_shaping",
    "rl.hedge_reward_functions",
    "rl.checkpoint_manager",
    "rl.continuous_learner",
    "rl.enhanced_architectures",
    "rl.moe_router",
    "rl.calibrated_confidence",
    "rl.confidence_gates",
    "rl.threshold_ramper",
    "rl.uncertainty",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2-owned trainer smoke")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--symbols", default=None)
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--no-train-runtime-active", action="store_true", default=True)
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
    probes = probe_imports(TRAINER_MODULES)
    probe_summary = summarize_import_probes(probes)

    status = base_status("v2_owned_trainer")
    status.update({
        "sys_path_added": added,
        "symbols": list(symbols),
        "symbol_count": len(symbols),
        "module_count": len(TRAINER_MODULES),
        **probe_summary,
        "training_started": False,
        "cuda_initialized": False,
        "model_weights_loaded": False,
        "trainer_invariants": {
            "no_training_started": True,
            "no_cuda_initialized": True,
            "no_model_weights_loaded": True,
            "paper_only": True,
        },
    })
    emit_status(args.out, status)
    print(json.dumps({k: status[k] for k in (
        "resolved_count", "external_dependency_missing_count", "legacy_root_rejected_count", "smoke_pass",
    )}))
    return 0 if status["smoke_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
