"""Offline, GPU-saturating batch trainer for the native CUDA MASA/PPO model.

Purpose
-------
The online streaming loop spends most of its cycle building examples on the CPU.
This tool decouples the two: it builds an isolated trusted-example view from the
durable replay archive, then runs many GPU gradient steps at a large batch size.
It measures GPU utilisation and throughput so the speed-up is verified, not
assumed. Legacy Python-object example caches are deliberately ignored: the
durable archive is rebuilt on every invocation instead of deserializing an
untrusted executable object graph.

Safety / boundaries
--------------------
- Offline and report-only by design. It does NOT run the live prediction loop,
  does NOT place any order, does NOT change leverage/margin, and does NOT touch
  the LIVE checkpoint directory. The exchange gate stays ``blocked_human_only``.
- ``--save-offline DIR`` writes trained weights to a NON-LIVE directory only
  (default ``.local_models/v2_native_rl_masa_ppo_offline``). It never writes the
  live path (``.local_models/v2_native_rl_masa_ppo``), so the running trainer is
  never mutated. Promotion to live remains an explicit, separate operator step.
- Reuses the REAL ``V2HybridTrainerDataLoader`` + ``V2HybridPPOTrainer`` so the
  learning transfers directly to the online loop.

See also: v2/docs/TRAINER_OFFLINE_RETRAIN_RUNBOOK.md
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Sequence

# Reuse the point-in-time leakage audit + safety helpers from the sweep tool so
# the two offline trainers share one fail-closed timing contract.
from v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep import (
    point_in_time_safety_report,
)

LIVE_CHECKPOINT_DIR = ".local_models/v2_native_rl_masa_ppo"
DEFAULT_OFFLINE_DIR = ".local_models/v2_native_rl_masa_ppo_offline"
# Compatibility-only CLI value. Files at this path are never read or written.
DEFAULT_CACHE_PATH = "claude_worklog/trainer_atlas/offline_batch_example_cache.pkl"
LEGACY_OBJECT_CACHE_BLOCKER = "LEGACY_OBJECT_CACHE_DESERIALIZATION_QUARANTINED"


# ─────────────────────────────── GPU sampler ────────────────────────────────


class GpuUtilizationSampler:
    """Background sampler for GPU utilisation/VRAM via nvidia-smi.

    Read-only; if nvidia-smi is unavailable the samples are simply empty and the
    report notes that GPU telemetry was unavailable (training still runs).
    """

    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = max(0.1, float(interval_s))
        self._util: list[float] = []
        self._vram_mb: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = True

    def _sample_once(self) -> tuple[float, float] | None:
        import subprocess  # noqa: PLC0415 - local, read-only telemetry

        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            self._available = False
            return None
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return None
        try:
            util_s, vram_s = line[0].split(",")
            return float(util_s.strip()), float(vram_s.strip())
        except (ValueError, IndexError):
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._sample_once()
            if sample is not None:
                self._util.append(sample[0])
                self._vram_mb.append(sample[1])
            if not self._available:
                return
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "GpuUtilizationSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def report(self) -> dict[str, Any]:
        if not self._util:
            return {
                "gpu_telemetry_available": bool(self._available),
                "samples": 0,
                "gpu_utilization_mean_pct": None,
                "gpu_utilization_max_pct": None,
                "vram_used_max_mb": None,
            }
        return {
            "gpu_telemetry_available": True,
            "samples": len(self._util),
            "gpu_utilization_mean_pct": round(sum(self._util) / len(self._util), 2),
            "gpu_utilization_max_pct": round(max(self._util), 2),
            "vram_used_max_mb": round(max(self._vram_mb), 1) if self._vram_mb else None,
        }


# ─────────────────────────────── cache layer ────────────────────────────────


def build_independent_archive_view(real_root: Path, view_root: Path) -> Path:
    """Create a temp archive view that symlinks DATA but keeps its OWN cursors.

    ``load_trusted_replay_examples`` persists a replay cursor that the LIVE
    trainer also consumes; reading through the real root would advance that
    cursor and starve the running loop. This view symlinks the read-only data
    (blobs/index/manifest) into a fresh directory and deliberately omits the
    ``*_cursor.json`` files, so the offline loader starts at offset 0 and writes
    its cursor into the throwaway view — the live cursor is never touched.
    """
    view_root.mkdir(parents=True, exist_ok=True)
    for entry in real_root.iterdir():
        if entry.name.endswith("_cursor.json"):
            continue  # keep offline cursor state isolated from the live loop
        link = view_root / entry.name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(entry.resolve())
    return view_root


def seed_offline_view_cursor_near_tail(
    view_root: Path,
    *,
    hours_back: float = float(os.getenv("V2_OFFLINE_SEED_HOURS_BACK", "16") or 16.0),
    backfill_hours_back: float = float(
        os.getenv("V2_OFFLINE_BACKFILL_HOURS_BACK", "96") or 96.0
    ),
) -> dict[str, Any]:
    """Seed the offline view's replay cursor ~hours_back before the manifest tail.

    The independent view omits cursor files, so the offline loader started at
    byte 0 — the OLDEST snapshots (June 22 at last audit, 3+ weeks stale). The
    archive is append-only (~13k snapshots/hour), so 'first 21k from offset 0'
    reproduced the same ancient window on every cache rebuild: bit-identical
    H2L verdicts across rebuilds proved the flywheel never saw new data. Seeding
    near the tail makes every rebuild train on the newest labelable rows, so
    the brain-development loop actually follows the market. hours_back must
    clear the 4.5h label embargo with headroom for label-horizon candles.

    Binary-search on the manifest's monotone ``created_at`` ISO strings; a
    mid-line offset is safe because the manifest reader skips unparseable
    partial lines.
    """
    meta: dict[str, Any] = {"seeded": False, "hours_back": hours_back}
    manifest = view_root / "manifest.jsonl"
    try:
        size = manifest.stat().st_size
    except OSError:
        return meta
    if size <= 0:
        return meta
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    target_iso = (
        datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _created_at_after(offset: int) -> str | None:
        with manifest.open("rb") as handle:
            handle.seek(offset)
            if offset:
                handle.readline()  # discard the partial line
            line = handle.readline()
        if not line:
            return None
        try:
            value = json.loads(line).get("created_at")
            return str(value) if value else None
        except Exception:
            return None

    def _seek(target: str) -> int | None:
        first = _created_at_after(0)
        if first is None or first >= target:
            return None  # archive younger than the requested window
        lo, hi = 0, size
        while hi - lo > 65536:
            mid = (lo + hi) // 2
            created = _created_at_after(mid)
            if created is None or created >= target:
                hi = mid
            else:
                lo = mid
        return int(lo)

    frontier_offset = _seek(target_iso)
    if frontier_offset is None:
        # Archive younger than the window: start at 0, nothing to seed.
        meta["reason"] = "archive_younger_than_window"
        return meta
    try:
        (view_root / "trusted_replay_cursor.json").write_text(
            json.dumps(
                {
                    "manifest_offset": int(frontier_offset),
                    "frontier_reached": False,
                    "backfill_lane": False,
                    "seeded_near_tail": True,
                    "seed_target_created_at": target_iso,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        return meta
    # Seed the durable-label BACKFILL cursor DEEPER than the frontier so the
    # backfill lane scans the [deep, frontier] window of trainer-consumable,
    # matured rows.  Seeding it AT the frontier makes the loader treat the lane
    # as exhausted (cursor >= backfill_stop) and wrap to byte 0 — the ancient
    # pre-consumable head — which yields zero trainable rows.  The default
    # lookback stays inside the trainer-consumable era (began ~2026-07-28).
    backfill_target_iso = (
        datetime.now(tz=timezone.utc) - timedelta(hours=backfill_hours_back)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    backfill_offset = _seek(backfill_target_iso)
    backfill_offset = min(
        int(backfill_offset if backfill_offset is not None else 0),
        int(frontier_offset),
    )
    try:
        (view_root / "trusted_replay_backfill_cursor.json").write_text(
            json.dumps(
                {
                    "manifest_offset": int(backfill_offset),
                    "frontier_reached": False,
                    "backfill_lane": True,
                    "seeded_near_tail": True,
                    "seed_target_created_at": backfill_target_iso,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    meta.update(
        {
            "seeded": True,
            "manifest_offset": int(frontier_offset),
            "backfill_manifest_offset": int(backfill_offset),
            "manifest_size": int(size),
            "seed_target_created_at": target_iso,
            "backfill_seed_target_created_at": backfill_target_iso,
        }
    )
    return meta


# --------------------------------------------------------------------------
# Safe example-tensor cache (non-executable). The legacy pickle cache is
# deliberately never opened (executable object graphs). This cache serializes
# the built TrainingExamples to gzipped JSON via dataclasses.fields (numbers,
# strings, lists, and the trust_row provenance dict only -- no code), so the
# expensive CPU example-assembly runs once and the GPU then trains continuously
# across cycles instead of idling ~15 min per rebuild. SAFETY NET: reconstructed
# examples are re-run through point_in_time_safety_report before use, so a
# malformed or stale cache can never feed the trainer -- it falls back to a fresh
# build. Env-gated (default OFF): V2_OFFLINE_EXAMPLE_TENSOR_CACHE_PATH +
# V2_OFFLINE_EXAMPLE_TENSOR_CACHE_MAX_AGE_SECONDS (default 600s TTL so data still
# refreshes). The loop's --rebuild-cache (REBUILD_EVERY) forces a fresh build.
_EXAMPLE_TENSOR_CACHE_SCHEMA = "offline_example_tensor_cache_v1"


def _example_tensor_cache_config() -> tuple[str | None, float]:
    path = os.getenv("V2_OFFLINE_EXAMPLE_TENSOR_CACHE_PATH", "").strip()
    if not path:
        return None, 0.0
    try:
        max_age = float(
            os.getenv("V2_OFFLINE_EXAMPLE_TENSOR_CACHE_MAX_AGE_SECONDS", "600") or 600
        )
    except (TypeError, ValueError):
        max_age = 600.0
    return path, max(0.0, max_age)


def _training_example_to_jsonable(example: Any) -> dict[str, Any]:
    import dataclasses  # noqa: PLC0415

    tensor = example.tensor
    tensor_dict = {}
    for f in dataclasses.fields(tensor):
        if not f.init:
            continue
        value = getattr(tensor, f.name)
        tensor_dict[f.name] = list(value) if isinstance(value, tuple) else value
    row: dict[str, Any] = {}
    for f in dataclasses.fields(example):
        if not f.init:
            continue
        if f.name == "tensor":
            row["tensor"] = tensor_dict
            continue
        value = getattr(example, f.name)
        row[f.name] = list(value) if isinstance(value, tuple) else value
    return row


def _training_example_from_jsonable(row: Mapping[str, Any], example_cls: Any, tensor_cls: Any) -> Any:
    import dataclasses  # noqa: PLC0415

    tensor_row = row.get("tensor") or {}
    tensor_kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(tensor_cls):
        if not f.init:
            continue
        value = tensor_row.get(f.name)
        tensor_kwargs[f.name] = tuple(value) if isinstance(value, list) else value
    tensor = tensor_cls(**tensor_kwargs)
    example_kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(example_cls):
        if not f.init:
            continue
        if f.name == "tensor":
            example_kwargs["tensor"] = tensor
            continue
        value = row.get(f.name)
        if f.name == "payload_keys" and isinstance(value, list):
            value = tuple(value)
        example_kwargs[f.name] = value
    return example_cls(**example_kwargs)


def _save_examples_tensor_cache(examples: Sequence[Any], path: str) -> None:
    import gzip  # noqa: PLC0415

    payload = {
        "schema_version": _EXAMPLE_TENSOR_CACHE_SCHEMA,
        "count": len(examples),
        "rows": [_training_example_to_jsonable(ex) for ex in examples],
    }
    tmp = f"{path}.tmp"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(tmp, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def _load_examples_tensor_cache(path: str, max_age_seconds: float) -> tuple[list[Any] | None, str]:
    import gzip  # noqa: PLC0415

    p = Path(path)
    if not p.is_file():
        return None, "CACHE_ABSENT"
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return None, "CACHE_STAT_FAILED"
    if age > max_age_seconds:
        return None, f"CACHE_STALE:{int(age)}s>{int(max_age_seconds)}s"
    try:
        with gzip.open(p, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        return None, f"CACHE_UNREADABLE:{type(exc).__name__}"
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _EXAMPLE_TENSOR_CACHE_SCHEMA:
        return None, "CACHE_SCHEMA_MISMATCH"
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (  # noqa: PLC0415
        TrainingExample,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (  # noqa: PLC0415
        FeatureTensorRecord,
    )
    try:
        examples = [
            _training_example_from_jsonable(row, TrainingExample, FeatureTensorRecord)
            for row in payload.get("rows", [])
            if isinstance(row, Mapping)
        ]
    except Exception as exc:  # noqa: BLE001
        return None, f"CACHE_RECONSTRUCT_FAILED:{type(exc).__name__}"
    if not examples:
        return None, "CACHE_EMPTY"
    # SAFETY NET: re-validate the reconstructed examples through the same
    # point-in-time audit the trainer enforces. A faithful round-trip passes; any
    # reconstruction defect fails here and forces a fresh build (never trains).
    try:
        from v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep import (  # noqa: PLC0415
            point_in_time_safety_report,
        )

        pit = point_in_time_safety_report(examples)
    except Exception as exc:  # noqa: BLE001
        return None, f"CACHE_PIT_REVALIDATION_ERROR:{type(exc).__name__}"
    if not pit.get("passed"):
        return None, "CACHE_PIT_REVALIDATION_FAILED"
    return examples, "CACHE_HIT"


def load_or_build_examples(
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    limit: int,
    cache_path: str | None,
    rebuild_cache: bool,
) -> tuple[list[Any], dict[str, Any]]:
    """Build trusted examples from an isolated durable-archive view.

    ``cache_path`` and ``rebuild_cache`` remain accepted for installed-unit and
    operator CLI compatibility.  The legacy cache contained executable Python
    object graphs and therefore cannot be authenticated as immutable trainer
    input.  It is never opened, decoded, overwritten, or deleted.  Telemetry
    explicitly records that the durable archive was rebuilt instead.

    Reads go through an independent archive view (see
    ``build_independent_archive_view``) so the live trainer's replay cursor is
    never advanced.
    """
    legacy_cache_present = bool(cache_path and Path(cache_path).is_file())
    meta: dict[str, Any] = {
        "cache_path": cache_path,
        "cache_hit": False,
        "cache_read_attempted": False,
        "cache_write_attempted": False,
        "legacy_object_cache_present": legacy_cache_present,
        "legacy_object_cache_ignored": legacy_cache_present,
        "legacy_object_cache_blocker": LEGACY_OBJECT_CACHE_BLOCKER,
        "rebuild_cache_requested": bool(rebuild_cache),
        "durable_archive_rebuilt": True,
        "external_object_deserialization_used": False,
    }

    # Safe example-tensor cache fast path: reuse a fresh, PIT-revalidated cache so
    # the GPU trains continuously instead of rebuilding the whole example set
    # every cycle. Skipped when the loop requests a rebuild (REBUILD_EVERY).
    _tensor_cache_path, _tensor_cache_max_age = _example_tensor_cache_config()
    meta["example_tensor_cache_enabled"] = bool(_tensor_cache_path)
    if _tensor_cache_path and not rebuild_cache:
        _cached, _cache_reason = _load_examples_tensor_cache(
            _tensor_cache_path, _tensor_cache_max_age
        )
        meta["example_tensor_cache_reason"] = _cache_reason
        if _cached is not None:
            meta["example_tensor_cache_hit"] = True
            meta["examples"] = len(_cached)
            meta["cache_hit"] = True
            return _cached, meta
        meta["example_tensor_cache_hit"] = False

    import tempfile  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (  # noqa: PLC0415
        default_archive_root,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (  # noqa: PLC0415
        data_loader as _data_loader_module,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (  # noqa: PLC0415
        V2HybridTrainerDataLoader,
    )

    # OFFLINE-PROCESS-ONLY scan widening. Labels need +4h future candles from
    # the row's OWN (symbol, timeframe) series. Redis closed-candle retention
    # is far too short for tail-seeded rows (1m series spans ~3h; several
    # majors' series are nil), so labels must come from IN-CHUNK archive
    # candles — and at ~13k snapshots/hour the live cap (16,384/chunk ≈ 75min)
    # can never span the 4h label horizon. One wide chunk (~100k rows ≈ 7.5h)
    # lets later archive rows label earlier ones, symbol gaps included. The
    # subprocess boundary keeps the resident trainer's caps untouched.
    _offline_scan_cap = int(os.getenv("V2_OFFLINE_REPLAY_MAX_SCAN", "100000"))
    _data_loader_module.TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE = _offline_scan_cap
    _data_loader_module.TRUSTED_REPLAY_MIN_SCAN_PER_CYCLE = _offline_scan_cap
    meta["offline_replay_scan_cap"] = _offline_scan_cap

    real_root = default_archive_root()
    view_root = Path(tempfile.mkdtemp(prefix="v2_offline_archive_view_"))
    build_independent_archive_view(real_root, view_root)
    meta["archive_view_root"] = str(view_root)
    meta["live_cursor_untouched"] = True
    meta["offline_cursor_seed"] = seed_offline_view_cursor_near_tail(view_root)
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=view_root)
    # The offline bulk lane trains from the durable canonical-5m label archive
    # (backfill=True in the load loop below).  The frontier lane sources labels
    # from the short-retention Redis 5m working set, which has already expired
    # for the >4h-matured snapshots the offline cursor targets
    # (NO_CANONICAL_5M_LABEL_CANDLES_AFTER_DECISION), so it can never label
    # historical rows.  seed_offline_view_cursor_near_tail seeds BOTH the
    # frontier cursor (near tail) and the deeper backfill cursor, so the backfill
    # lane scans recent, trainer-consumable, matured rows instead of the ancient
    # pre-consumable archive head at byte 0.

    started = time.perf_counter()
    examples: list[Any] = []
    # Highest-quality supervised rows first: real closed-trade outcomes.
    try:
        examples.extend(loader.load_training_examples(
            symbols=[s.strip().upper() for s in symbols if s.strip()],
            timeframes=[t.strip().lower() for t in timeframes if t.strip()],
            limit=limit,
            trusted_only=True,
            closed_trade_only=True,
        ))
    except Exception as exc:  # pragma: no cover - closed-trade lane is best-effort
        meta["closed_trade_lane_error"] = str(exc)
    # Bulk historical archive rows via the isolated cursor (repeated chunks).
    stagnation = 0
    while len(examples) < limit and stagnation < 3:
        before = len(examples)
        chunk = loader.load_trusted_replay_examples(
            limit=limit - len(examples), backfill=True
        )
        examples.extend(chunk)
        if len(examples) <= before or not chunk:
            stagnation += 1
        else:
            stagnation = 0
    meta["load_seconds"] = round(time.perf_counter() - started, 3)
    meta["examples"] = len(examples)
    # Persist the freshly-built examples to the safe tensor cache so subsequent
    # cycles (within the TTL) skip the expensive rebuild and keep the GPU busy.
    if _tensor_cache_path and examples:
        try:
            _save_examples_tensor_cache(examples, _tensor_cache_path)
            meta["example_tensor_cache_written"] = True
        except Exception as exc:  # noqa: BLE001 - cache is best-effort, never fatal
            meta["example_tensor_cache_write_error"] = f"{type(exc).__name__}"
    return examples, meta


# ─────────────────────────────── training ───────────────────────────────────


def _model_risk_composite(model: Any, examples: list[Any]) -> tuple[float, dict[str, Any]]:
    """Out-of-sample risk-adjusted score for checkpoint selection (Sortino + CVaR).

    Runs the in-memory model on held-out examples, takes the argmax action, and
    builds a per-trade realised-return series (long=+move, short=-move). The
    composite ``sortino + cvar/1000`` rewards risk-adjusted return and penalises
    tail loss, aligning offline checkpoint selection with the H2L promotion gate,
    which requires better Sortino AND CVaR. Loss-optimal checkpoints have worse
    tail risk and get refused -- selecting by this composite fixes that. Returns
    (score, summary); score is -inf when the policy makes no directional trades.
    """
    import torch  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.risk_metrics import (  # noqa: PLC0415
        risk_adjusted_summary,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
        build_window_lookup,
        model_batch_tensor,
    )

    net = getattr(model, "net", None)
    if net is None or not examples:
        return float("-inf"), {}
    returns: list[float] = []
    _temporal = bool(getattr(model, "temporal_encoder_enabled", False))
    _seq_len = int(getattr(model, "temporal_seq_len", 16))
    _lookup = build_window_lookup(list(examples), seq_len=_seq_len) if _temporal else None
    try:
        net.eval()
        with torch.no_grad():
            x = model_batch_tensor(
                torch, list(examples), temporal=_temporal, seq_len=_seq_len,
                window_lookup=_lookup, device="cpu",
            )
            x = torch.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6).to(device=model.device)
            actions = torch.argmax(net(x)["logits"], dim=-1).detach().cpu().tolist()
        for r, a in zip(examples, actions):
            move = float(getattr(r, "label_expected_move_after_cost_bps", 0.0) or 0.0)
            if a == 1:
                returns.append(move)
            elif a == 2:
                returns.append(-move)
    except Exception:  # pragma: no cover - selection heuristic, never fatal
        return float("-inf"), {}
    finally:
        net.train()
    summary = risk_adjusted_summary(returns)
    sortino = summary.get("sortino_ratio")
    if sortino is None or not returns:
        return float("-inf"), summary
    cvar = summary.get("cvar")
    score = float(sortino) + (float(cvar) / 1000.0 if cvar is not None else 0.0)
    return score, summary


def run_batch_training(
    examples: Sequence[Any],
    *,
    epochs: int,
    steps_per_epoch: int,
    batch_size: int,
    learning_rate: float,
    entropy_coefficient: float,
    weight_decay: float,
    dropout: float,
    validation_fraction: float,
    from_checkpoint: bool,
    gpu_sample_interval_s: float = 0.5,
    early_stop_patience: int = 0,
    min_epochs: int = 5,
) -> dict[str, Any]:
    """Run many GPU gradient steps on the real trainer; verify GPU saturation.

    Fail-closed on point-in-time leakage before spending GPU cycles.

    When ``early_stop_patience > 0`` this keeps the BEST out-of-sample
    (validation) checkpoint rather than the last epoch and stops once validation
    has not improved for ``early_stop_patience`` epochs. This is the genuine
    anti-overfit mechanism the legacy trainer used (checkpoint on best
    validation): it prevents the run from training past the generalization
    optimum into memorization.
    """
    if not examples:
        raise ValueError("offline batch training requires at least one example")
    pit = point_in_time_safety_report(examples)
    if not pit["passed"]:
        raise ValueError(
            "offline batch training blocked by point-in-time safety violations: "
            + json.dumps(pit, default=str)
        )

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (  # noqa: PLC0415
        V2HybridPPOTrainer,
    )

    # Hard per-process VRAM cap so this offline trainer can never starve the
    # online resident trainer sharing the same GPU (they are both hidden-2048
    # models on one 16GB RTX). Within the cap an oversized batch OOMs and the
    # loop retries -- non-fatal -- instead of exhausting the online trainer's
    # VRAM and hanging it. Env-tunable; unset = uncapped (single-GPU-owner runs).
    _mem_frac = os.environ.get("V2_OFFLINE_CUDA_MEMORY_FRACTION")
    if _mem_frac:
        try:
            import torch  # noqa: PLC0415

            _frac = float(_mem_frac)
            if torch.cuda.is_available() and 0.0 < _frac <= 1.0:
                torch.cuda.set_per_process_memory_fraction(_frac, 0)
        except Exception:  # pragma: no cover - best-effort guard
            pass

    input_dim = len(examples[0].tensor.model_vector)
    prev_dropout = os.environ.get("V2_TRAINER_DROPOUT")
    os.environ["V2_TRAINER_DROPOUT"] = str(dropout)
    try:
        model = V2HybridPolicyModel(input_dim=input_dim)
    finally:
        if prev_dropout is None:
            os.environ.pop("V2_TRAINER_DROPOUT", None)
        else:
            os.environ["V2_TRAINER_DROPOUT"] = prev_dropout

    _warm_start_info: dict[str, Any] | None = None
    if from_checkpoint:
        from pathlib import Path as _P  # noqa: PLC0415

        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
            V2HybridCheckpointManager,
        )
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: PLC0415
            VERIFIED_SERVING_LINEAGE,
        )

        # Warm-start source. By default the offline lane warm-starts from the
        # canonical VERIFIED_SERVING live checkpoint. When the live checkpoint's
        # causal ledger is corrupt/unavailable (blocking warm-start and forcing a
        # cold start that reproduces identical checkpoints every cycle), the
        # offline lane can instead continue its OWN clean candidate lineage:
        # V2_OFFLINE_WARMSTART_FROM_OWN_LINEAGE=1 warm-starts from the offline save
        # dir (default DEFAULT_OFFLINE_DIR) and accepts its SERVING_CANDIDATE
        # lineage. EVERY integrity check (loadable, model_state_restored,
        # identity, evidence, weight sha256) is preserved unchanged -- only the
        # lineage-KIND requirement is widened to the offline candidate lineages,
        # so a corrupt or forged checkpoint is still rejected. This turns the
        # offline lane into a genuine self-improving loop (gen N -> gen N+1) that
        # gives the GPU meaningful work each cycle instead of a cold-start no-op.
        _warm_own_lineage = os.getenv(
            "V2_OFFLINE_WARMSTART_FROM_OWN_LINEAGE", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if _warm_own_lineage:
            _warm_dir = os.getenv("V2_OFFLINE_WARMSTART_DIR", DEFAULT_OFFLINE_DIR)
            _allowed_lineages = frozenset(
                {VERIFIED_SERVING_LINEAGE, "SERVING_CANDIDATE", "LEGACY_SERVING_CANDIDATE"}
            )
        else:
            _warm_dir = LIVE_CHECKPOINT_DIR
            _allowed_lineages = frozenset({VERIFIED_SERVING_LINEAGE})
        warm_start = V2HybridCheckpointManager(
            _P(_warm_dir)
        ).load_latest_weights(
            model,
            allowed_lineage_kinds=_allowed_lineages,
        )
        required_warm_start = (
            warm_start.get("latest_checkpoint_loadable") is True
            and warm_start.get("model_state_restored") is True
            and warm_start.get("checkpoint_identity_verified") is True
            and warm_start.get("checkpoint_evidence_verified") is True
            and warm_start.get("weight_file_sha256_verified") is True
            and warm_start.get("lineage_kind") in _allowed_lineages
        )
        if not required_warm_start:
            if _warm_own_lineage:
                # Own-lineage warm-start is best-effort: an incompatible or
                # absent prior candidate (e.g. feature-ABI/input-dim drift since
                # the last offline checkpoint) must NOT crash the lane. Fall back
                # to a fresh cold start (the model keeps its random init) and
                # record why, so a mismatch degrades to cold-start instead of a
                # restart loop. Integrity is unaffected: a checkpoint that failed
                # verification is simply not loaded.
                meta_warm_start_fallback = {
                    "warm_start_attempted": True,
                    "warm_start_source": _warm_dir,
                    "warm_start_applied": False,
                    "warm_start_fallback_reason": "OWN_LINEAGE_WARM_START_NOT_LOADABLE_COLD_START_FALLBACK",
                    "warm_start_detail": warm_start,
                }
                _warm_start_info = meta_warm_start_fallback
            else:
                raise ValueError(
                    "offline warm-start requires an integrity-verified checkpoint "
                    f"(source={_warm_dir}, allowed_lineages={sorted(_allowed_lineages)}): "
                    + json.dumps(warm_start, sort_keys=True, default=str)
                )
        else:
            _warm_start_info = {
                "warm_start_attempted": True,
                "warm_start_source": _warm_dir,
                "warm_start_applied": True,
                "lineage_kind": warm_start.get("lineage_kind"),
            }

    trainer = V2HybridPPOTrainer(
        model=model,
        learning_rate=learning_rate,
        entropy_coefficient=entropy_coefficient,
        supervised_entropy_bonus=0.0,
        weight_decay=weight_decay,
    )

    import tempfile as _tempfile  # noqa: PLC0415

    epoch_reports: list[dict[str, Any]] = []
    total_steps = 0
    loss_first: float | None = None
    loss_last: float | None = None
    best_val: float | None = None
    best_epoch: int | None = None
    best_risk: float | None = None
    best_risk_summary: dict[str, Any] = {}
    epochs_since_improve = 0
    stopped_early = False
    # Select the promoted checkpoint by out-of-sample RISK-ADJUSTED return
    # (Sortino + CVaR), not just supervised val loss: loss-optimal checkpoints
    # have worse tail risk and are refused by the H2L risk gate, so pure val-loss
    # selection never produces a promotable model. Revert with
    # V2_OFFLINE_SELECT_BY_VAL_LOSS=1. The risk-eval slice is the tail held-out
    # fraction (a selection heuristic; the H2L head-to-head is the real disjoint gate).
    _select_by_val_loss = os.getenv("V2_OFFLINE_SELECT_BY_VAL_LOSS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }
    _risk_eval_n = min(len(examples), max(256, int(len(examples) * max(validation_fraction, 0.1))))
    _risk_eval_examples = list(examples[-_risk_eval_n:]) if _risk_eval_n else []
    _best_blob = Path(_tempfile.mkdtemp(prefix="v2_offline_bestval_")) / "best.weights.npz"
    wall_started = time.perf_counter()
    with GpuUtilizationSampler(interval_s=gpu_sample_interval_s) as sampler:
        for epoch in range(max(1, int(epochs))):
            result = trainer.train(
                examples,
                steps=steps_per_epoch,
                batch_size=batch_size,
                validation_fraction=validation_fraction,
            )
            total_steps += int(steps_per_epoch)
            if loss_first is None:
                loss_first = result.loss_before
            loss_last = result.loss_after
            val = result.metrics.get("validation_supervised_loss")
            epoch_reports.append(
                {
                    "epoch": epoch,
                    "loss_before": result.loss_before,
                    "loss_after": result.loss_after,
                    "validation_supervised_loss": val,
                    "train_val_generalization_gap": result.metrics.get("train_val_generalization_gap"),
                    "ppo_entropy": result.metrics.get("ppo_entropy"),
                    "learning_mode": result.metrics.get("learning_mode"),
                }
            )
            # Best-checkpoint selection + early stopping (anti-overfit). Default
            # criterion is the out-of-sample risk composite (so the promoted
            # checkpoint passes the H2L Sortino/CVaR gate); val-loss under env flag.
            if early_stop_patience > 0:
                improved = False
                if not _select_by_val_loss:
                    risk_score, risk_summary = _model_risk_composite(model, _risk_eval_examples)
                    if best_risk is None or risk_score > best_risk + 1e-9:
                        best_risk = risk_score
                        best_risk_summary = risk_summary
                        best_val = float(val) if isinstance(val, (int, float)) else best_val
                        best_epoch = epoch
                        improved = True
                elif isinstance(val, (int, float)) and (best_val is None or val < best_val - 1e-6):
                    best_val = float(val)
                    best_epoch = epoch
                    improved = True
                if improved:
                    epochs_since_improve = 0
                    try:
                        model.save_weight_blob(_best_blob)  # snapshot the best checkpoint
                    except Exception:  # pragma: no cover
                        pass
                else:
                    epochs_since_improve += 1
                    # Never stop before the min_epochs floor, so the run always
                    # trains a meaningful number of passes (default >= 5) even if
                    # the metric plateaus early on a noisy first epoch.
                    if epochs_since_improve >= early_stop_patience and (epoch + 1) >= max(1, int(min_epochs)):
                        stopped_early = True
                        break
        gpu = sampler.report()
    # Restore the best-validation weights so the returned/saved model is the
    # best-generalizing checkpoint, not whatever the last (possibly overfit) epoch produced.
    if early_stop_patience > 0 and best_epoch is not None and _best_blob.exists():
        try:
            model.load_weight_blob(_best_blob)
        except Exception:  # pragma: no cover
            pass
    wall_seconds = max(1e-6, time.perf_counter() - wall_started)

    rows_processed = int(len(examples)) * total_steps
    # Model identity/architecture — surfaced so the read-only trainer-status API
    # can populate the deep-telemetry panel (tensor input dim, feature count,
    # architecture) from the lane that is ACTUALLY training, instead of leaving
    # those cells blank while the hybrid/online observer publishes nothing.
    _arch: dict[str, Any] = {}
    try:
        _arch = {
            "input_dim": int(model.input_dim),
            "hidden_size": int(getattr(model, "hidden_size", 0)) or None,
            "residual_blocks": int(getattr(model, "residual_block_count", 0)) or None,
            "attention_heads": int(getattr(model, "attention_heads", 0)) or None,
            "temporal_encoder": getattr(model, "temporal_encoder", "") or "",
            "temporal_encoder_enabled": bool(getattr(model, "temporal_encoder_enabled", False)),
            "temporal_seq_len": int(getattr(model, "temporal_seq_len", 0)) or None,
        }
    except Exception:  # pragma: no cover - telemetry must never break training
        _arch = {}

    return {
        "schema_version": "trainer_offline_batch_train_v1",
        "warm_start": _warm_start_info,
        "input_dim": _arch.get("input_dim"),
        "feature_dim": _arch.get("input_dim"),
        "model_architecture": _arch or None,
        "examples": len(examples),
        "epochs": int(max(1, epochs)),
        "steps_per_epoch": int(steps_per_epoch),
        "batch_size": int(batch_size),
        "total_gradient_steps": total_steps,
        "wall_seconds": round(wall_seconds, 3),
        "gradient_steps_per_second": round(total_steps / wall_seconds, 3),
        "rows_processed": rows_processed,
        "rows_per_second": round(rows_processed / wall_seconds, 1),
        "loss_first": loss_first,
        "loss_last": loss_last,
        "loss_improved": (loss_first is not None and loss_last is not None and loss_last < loss_first),
        "best_validation_loss": best_val,
        "best_epoch": best_epoch,
        "checkpoint_selection_criterion": "val_loss" if _select_by_val_loss else "risk_adjusted_composite",
        "best_risk_composite": best_risk,
        "best_risk_sortino": best_risk_summary.get("sortino_ratio"),
        "best_risk_cvar": best_risk_summary.get("cvar"),
        "best_risk_trades": best_risk_summary.get("count"),
        "early_stop_patience": int(early_stop_patience),
        "stopped_early": bool(stopped_early),
        "epochs_run": len(epoch_reports),
        "kept_best_val_checkpoint": bool(early_stop_patience > 0 and best_epoch is not None),
        "gpu": gpu,
        "epoch_reports": epoch_reports,
        "point_in_time_safety": pit,
        "trained_model": model,
        # explicit safety posture
        "offline_only": True,
        "writes_live_checkpoint": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }


def save_offline_weights(model: Any, offline_dir: str) -> dict[str, Any]:
    """Persist trained weights to a NON-LIVE directory only.

    Refuses to write anywhere under the live checkpoint directory so the running
    trainer can never be mutated by this tool.
    """
    resolved = Path(offline_dir).resolve()
    live = Path(LIVE_CHECKPOINT_DIR).resolve()
    if resolved == live or live in resolved.parents or resolved in live.parents:
        raise ValueError(
            f"refusing to save into or around the live checkpoint dir ({LIVE_CHECKPOINT_DIR}); "
            "offline batch trainer must never mutate the running trainer"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )

    try:
        import torch  # noqa: PLC0415

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        cuda_active = torch.cuda.is_available()
    except Exception:  # pragma: no cover
        device, cuda_active = "cpu", False

    manager = V2HybridCheckpointManager(resolved)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=int(model.input_dim),
        device=device,
        cuda_active=cuda_active,
        write_weight_blob=True,
    )
    return {
        "offline_dir": str(resolved),
        "is_live_dir": False,
        "saved": True,
        "checkpoint_id": getattr(manifest, "checkpoint_id", None) or (manifest.get("checkpoint_id") if isinstance(manifest, dict) else None),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true",
                   help="use the BTC/ETH/SOL smoke-test set (test only)")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=65536, help="max trusted rows to load into the cache")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--steps-per-epoch", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=8192)
    p.add_argument("--learning-rate", type=float, default=1e-4)
    p.add_argument("--entropy-coefficient", type=float, default=0.01)
    p.add_argument("--weight-decay", type=float, default=0.02)
    p.add_argument("--dropout", type=float, default=0.10)
    p.add_argument("--validation-fraction", type=float, default=0.2)
    p.add_argument("--from-checkpoint", action="store_true", help="warm-start from the current LIVE checkpoint (read-only)")
    p.add_argument("--early-stop-patience", type=int, default=0,
                   help="keep the best-validation checkpoint and stop after N epochs without improvement (0=off)")
    p.add_argument("--min-epochs", type=int, default=5,
                   help="always train at least this many epochs before early stopping can trigger (default 5)")
    p.add_argument("--cache-path", default=DEFAULT_CACHE_PATH)
    p.add_argument("--no-cache", action="store_true", help="do not read/write the example cache")
    p.add_argument("--rebuild-cache", action="store_true", help="ignore any existing cache and rebuild it")
    p.add_argument("--save-offline", nargs="?", const=DEFAULT_OFFLINE_DIR, default=None,
                   help="save trained weights to a NON-LIVE dir (never the live checkpoint dir)")
    p.add_argument("--output", default=None, help="write the report JSON here")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    args = parse_args(argv)
    cache_path = None if args.no_cache else args.cache_path
    examples, load_meta = load_or_build_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
        timeframes=args.timeframes.split(","),
        limit=args.limit,
        cache_path=cache_path,
        rebuild_cache=args.rebuild_cache,
    )
    if not examples:
        print(json.dumps({"error": "no trusted training examples loaded", "offline_only": True}))
        return 2

    report = run_batch_training(
        examples,
        epochs=args.epochs,
        steps_per_epoch=args.steps_per_epoch,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        entropy_coefficient=args.entropy_coefficient,
        weight_decay=args.weight_decay,
        dropout=args.dropout,
        validation_fraction=args.validation_fraction,
        from_checkpoint=args.from_checkpoint,
        early_stop_patience=args.early_stop_patience,
        min_epochs=args.min_epochs,
    )
    model = report.pop("trained_model", None)
    report["load"] = load_meta
    if args.save_offline and model is not None:
        report["save"] = save_offline_weights(model, args.save_offline)

    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(text)
    print(text)
    gpu = report.get("gpu", {})
    print(
        "OFFLINE_BATCH_TRAIN:",
        f"examples={report['examples']}",
        f"steps={report['total_gradient_steps']}",
        f"rows/s={report['rows_per_second']}",
        f"gpu_util_mean={gpu.get('gpu_utilization_mean_pct')}%",
        f"gpu_util_max={gpu.get('gpu_utilization_max_pct')}%",
        f"loss {report['loss_first']} -> {report['loss_last']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
