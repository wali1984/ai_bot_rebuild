#!/usr/bin/env python3
"""Paper-recovery model: train a non-promotable recovery checkpoint and infer.

This is Path C of the emergency paper-recovery pass.  Because no V2-safe native
checkpoint exists (the only one is legacy-metadata-only, correctly refused), we
train a *minimal, non-promotable, paper-only* recovery checkpoint on the current
admitted truthful cohort against a bounded reduced ABI, then use it to emit a
fresh recovery prediction with a finite TTL.

Hard invariants:
* recovery checkpoint is tagged paper_only / non_promotable / non live-eligible,
* economic quality is NEVER claimed from this training,
* the 1,000-row / champion / A+ gates are untouched — they keep blocking
  *promotion*, not this paper-recovery inference,
* runs on the trainer torch/CUDA env via subprocess; never imported into the
  control-plane FastAPI process.

Usage:
  <trainer-python> -m v2.backend.app.cli.v2_paper_recovery_model --train
  <trainer-python> -m v2.backend.app.cli.v2_paper_recovery_model --infer \
      --symbol BTCUSDT --timeframe 5m
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_ROOT = Path(
    os.environ.get(
        "V2_NATIVE_TRAINER_DATA_ROOT",
        "/home/wali/ai_bot_local_data/v2_native_trainer",
    )
)
LEDGER = DATA_ROOT / "durable_feature_snapshot_ledger.sqlite3"
LABEL_ARCHIVE = DATA_ROOT / "canonical_finalized_5m_label_archive.sqlite3"
# Runtime checkpoint dir — writable + gitignored, reachable from both the
# trainer torch env and the control-plane process (repo-relative default).
_REPO_ROOT = Path(__file__).resolve().parents[4]
CKPT_DIR = Path(
    os.environ.get(
        "PAPER_RECOVERY_CKPT_DIR",
        str(_REPO_ROOT / ".local_models" / "paper_recovery"),
    )
)
CKPT_PATH = CKPT_DIR / "paper_recovery_checkpoint_v1.pt"
CKPT_META = CKPT_DIR / "paper_recovery_checkpoint_v1.json"
INPUT_WIDTH = 39
ACTION_LABELS = ("short", "hold", "long")
LABEL_DEADBAND_BPS = 5.0  # |ret| < 5bps -> hold
RECOVERY_PRED_KEY = "v2:prediction:recovery:{symbol}:{timeframe}"
RECOVERY_PRED_TTL_SECONDS = 240
SEED = 12345


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------
# Data assembly (truthful features + forward-return labels)
# ----------------------------------------------------------------------
def _load_eligible_rows(limit: int) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=15)
    try:
        cur = con.execute(
            "SELECT symbol, timeframe, ppo_decision_time_us, feature_abi_sha256, "
            "record_json FROM feature_snapshot_records "
            "WHERE strict_training_eligible=1 ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        rows: list[dict[str, Any]] = []
        for symbol, timeframe, dt_us, abi, record_json in cur.fetchall():
            try:
                fe = json.loads(record_json)["frozen_envelope"]
                vec = [float(x) for x in fe["feature_values"]]
            except (KeyError, ValueError, TypeError):
                continue
            if len(vec) != INPUT_WIDTH or any(x != x for x in vec):
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "decision_us": int(dt_us) if dt_us is not None else None,
                    "abi": abi,
                    "vector": vec,
                }
            )
        return rows
    finally:
        con.close()


def _forward_return_label(symbol: str, decision_us: int | None) -> int | None:
    """Truthful forward 5m return -> class (0 short, 1 hold, 2 long), else None."""

    if decision_us is None:
        return None
    decision_ms = decision_us // 1000
    con = sqlite3.connect(f"file:{LABEL_ARCHIVE}?mode=ro", uri=True, timeout=15)
    try:
        cur = con.execute(
            "SELECT candle_close_time_ms, payload_json FROM canonical_5m_candles "
            "WHERE symbol=? AND candle_close_time_ms>=? "
            "ORDER BY candle_close_time_ms ASC LIMIT 2",
            (symbol, decision_ms),
        )
        got = cur.fetchall()
        if len(got) < 2:
            return None
        try:
            c0 = float(json.loads(got[0][1])["close"])
            c1 = float(json.loads(got[1][1])["close"])
        except (KeyError, ValueError, TypeError):
            return None
        if c0 <= 0:
            return None
        ret_bps = (c1 - c0) / c0 * 1e4
        if ret_bps > LABEL_DEADBAND_BPS:
            return 2
        if ret_bps < -LABEL_DEADBAND_BPS:
            return 0
        return 1
    finally:
        con.close()


def _build_dataset(limit: int) -> tuple[list[list[float]], list[int]]:
    rows = _load_eligible_rows(limit)
    xs: list[list[float]] = []
    ys: list[int] = []
    for row in rows:
        label = _forward_return_label(row["symbol"], row["decision_us"])
        if label is None:
            continue
        xs.append(row["vector"])
        ys.append(label)
    return xs, ys


# ----------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------
def _build_model(torch: Any):
    import torch.nn as nn

    return nn.Sequential(
        nn.Linear(INPUT_WIDTH, 64),
        nn.ReLU(),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Linear(32, len(ACTION_LABELS)),
    )


def train(min_rows: int, max_rows: int, epochs: int) -> dict[str, Any]:
    import torch

    torch.manual_seed(SEED)
    if not torch.cuda.is_available():
        return {"status": "FAIL", "reason": "CUDA_NOT_AVAILABLE"}
    device = torch.device("cuda")

    xs, ys = _build_dataset(max_rows)
    if len(xs) < min(min_rows, 1):
        return {
            "status": "FAIL",
            "reason": "INSUFFICIENT_ADMITTED_ROWS",
            "rows": len(xs),
            "minimum": min_rows,
        }
    # Normalise inputs (store stats in the checkpoint for inference parity).
    import statistics

    cols = list(zip(*xs, strict=False))
    means = [statistics.fmean(c) for c in cols]
    stds = [max(1e-6, statistics.pstdev(c)) for c in cols]
    xnorm = [[(v - means[i]) / stds[i] for i, v in enumerate(row)] for row in xs]

    x = torch.tensor(xnorm, dtype=torch.float32, device=device)
    y = torch.tensor(ys, dtype=torch.long, device=device)
    # Small holdout when possible.
    n = x.shape[0]
    holdout = max(1, n // 5) if n >= 10 else 0
    x_tr, y_tr = x[holdout:], y[holdout:]
    x_ho, y_ho = x[:holdout], y[:holdout]

    model = _build_model(torch).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss()

    cuda_proof = {
        "model_on_cuda": next(model.parameters()).is_cuda,
        "batch_on_cuda": bool(x_tr.is_cuda),
    }
    steps = 0
    last_loss = None
    model.train()
    for _ in range(max(2, epochs)):
        opt.zero_grad()
        logits = model(x_tr)
        loss = loss_fn(logits, y_tr)
        loss.backward()
        opt.step()
        steps += 1
        last_loss = float(loss.detach().cpu())
    cuda_proof["loss_on_cuda"] = bool(loss.is_cuda)
    cuda_proof["optimizer_state_on_cuda"] = _optimizer_on_cuda(opt)

    # Holdout accuracy (informational only — economic quality NOT claimed).
    ho_acc = None
    if holdout:
        model.eval()
        with torch.no_grad():
            pred = model(x_ho).argmax(dim=1)
            ho_acc = float((pred == y_ho).float().mean().cpu())

    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": {k: v.cpu() for k, v in model.state_dict().items()},
        "input_width": INPUT_WIDTH,
        "action_labels": list(ACTION_LABELS),
        "norm_means": means,
        "norm_stds": stds,
    }
    torch.save(payload, CKPT_PATH)
    weight_hash = _sha256_bytes(CKPT_PATH.read_bytes())
    checkpoint_id = "paper_recovery_ckpt_" + weight_hash[:24]
    abi_sha256 = _reduced_abi_sha256(means, stds)

    meta = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_path": str(CKPT_PATH),
        "weight_sha256": weight_hash,
        "reduced_feature_abi_sha256": abi_sha256,
        "input_width": INPUT_WIDTH,
        "action_labels": list(ACTION_LABELS),
        "train_rows": len(x_tr),
        "holdout_rows": int(holdout),
        "holdout_accuracy": ho_acc,
        "cuda_optimizer_steps": steps,
        "cuda_proof": cuda_proof,
        "last_loss": last_loss,
        "trained_at": _iso(_now()),
        # Non-promotable / paper-only tags (spec section 2).
        "paper_only": True,
        "recovery_checkpoint": True,
        "non_promotable": True,
        "checkpoint_promotion_authorized": False,
        "live_eligible": False,
        "routes_to_live": False,
        "economic_quality_claimed": False,
        "status": "OK",
    }
    CKPT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _optimizer_on_cuda(opt: Any) -> bool:
    for group_state in opt.state.values():
        for value in group_state.values():
            if hasattr(value, "is_cuda"):
                return bool(value.is_cuda)
    return True  # no state yet (before first step is impossible here)


def _reduced_abi_sha256(means: list[float], stds: list[float]) -> str:
    material = json.dumps(
        {"input_width": INPUT_WIDTH, "labels": ACTION_LABELS, "means": means, "stds": stds},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_bytes(material.encode("utf-8"))


# ----------------------------------------------------------------------
# Inference -> fresh recovery prediction
# ----------------------------------------------------------------------
def _load_latest_snapshot(symbol: str, timeframe: str) -> dict[str, Any] | None:
    con = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=15)
    try:
        cur = con.execute(
            "SELECT record_json FROM feature_snapshot_records "
            "WHERE symbol=? AND timeframe=? ORDER BY rowid DESC LIMIT 1",
            (symbol, timeframe),
        )
        got = cur.fetchone()
        if not got:
            return None
        return json.loads(got[0]).get("frozen_envelope")
    finally:
        con.close()


def infer(symbol: str, timeframe: str, publish: bool) -> dict[str, Any]:
    import torch

    if not CKPT_PATH.exists() or not CKPT_META.exists():
        return {"status": "FAIL", "reason": "RECOVERY_CHECKPOINT_MISSING"}
    meta = json.loads(CKPT_META.read_text())
    snap = _load_latest_snapshot(symbol, timeframe)
    if snap is None:
        return {"status": "FAIL", "reason": "NO_SNAPSHOT"}
    vec = [float(x) for x in snap.get("feature_values", [])]
    if len(vec) != INPUT_WIDTH or any(v != v for v in vec):
        return {"status": "FAIL", "reason": "SNAPSHOT_VECTOR_INVALID"}

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = torch.load(CKPT_PATH, map_location=device, weights_only=False)
    model = _build_model(torch).to(device)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    means, stds = payload["norm_means"], payload["norm_stds"]
    xnorm = [[(vec[i] - means[i]) / stds[i] for i in range(INPUT_WIDTH)]]
    with torch.no_grad():
        logits = model(torch.tensor(xnorm, dtype=torch.float32, device=device))
        probs = torch.softmax(logits, dim=1)[0].cpu().tolist()
    idx = int(max(range(len(probs)), key=lambda i: probs[i]))
    action = ACTION_LABELS[idx]
    confidence = float(probs[idx])
    best_side = {"short": "short", "long": "long", "hold": "hold"}[action]

    now = _now()
    vector_hash = _sha256_bytes(
        json.dumps(vec, separators=(",", ":")).encode("utf-8")
    )
    prediction = {
        # identity
        "prediction_id": "recovery_pred_" + _sha256_bytes(
            f"{symbol}{timeframe}{now.timestamp()}".encode()
        )[:24],
        "decision_id": "recovery_dec_" + _sha256_bytes(
            f"{symbol}{now.timestamp()}".encode()
        )[:24],
        "signal_id": "recovery_sig_" + vector_hash[:16],
        "symbol": symbol,
        "timeframe": timeframe,
        # timing
        "generated_at": _iso(now),
        "generated_utc": _iso(now),
        "decision_time": snap.get("ppo_decision_time") or _iso(now),
        "available_at": snap.get("available_at") or _iso(now),
        "feature_cutoff": snap.get("feature_cutoff"),
        "ttl_seconds": RECOVERY_PRED_TTL_SECONDS,
        # model output
        "best_side": best_side,
        "selected_action": action,
        "selected_action_index": idx,
        "action_labels": list(ACTION_LABELS),
        "action_probabilities": probs,
        "confidence_raw": confidence,
        "confidence_calibrated": confidence,
        "confidence_source": "PAPER_RECOVERY_MODEL",
        # provenance
        "checkpoint_id": meta["checkpoint_id"],
        "checkpoint_source": "PAPER_RECOVERY_NON_PROMOTABLE",
        "model_id": meta["checkpoint_id"],
        "model_version": "paper_recovery_v1",
        "feature_snapshot_id": snap.get("feature_snapshot_id"),
        "feature_abi_sha256": snap.get("feature_abi_sha256"),
        "reduced_feature_abi_sha256": meta["reduced_feature_abi_sha256"],
        "feature_vector_hash": snap.get("model_vector_sha256") or vector_hash,
        # recovery tags — non-promotable, paper-only, never live
        "paper_recovery_only": True,
        "pit_waiver": True,
        "pit_evidence_mode": "SNAPSHOT_LEVEL_RECOVERY_WAIVER",
        "pit_strict_complete": False,
        "strict_pit_eligible": False,
        "non_promotable_checkpoint": True,
        "economic_certification": "FAIL",
        "trainer_eligible": False,
        "valid_for_training": False,
        "live_eligible": False,
        "routes_to_live": False,
        "valid_for_live": False,
        "approves_live": False,
        "places_real_order": False,
        "exchange_mutation": False,
        "live_gate": "blocked_human_only",
        "producer": "v2_paper_recovery_model",
    }
    result = {"status": "OK", "prediction": prediction}
    if publish:
        import redis

        r = redis.Redis(
            host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_timeout=4
        )
        key = RECOVERY_PRED_KEY.format(symbol=symbol, timeframe=timeframe)
        r.set(key, json.dumps(prediction), ex=RECOVERY_PRED_TTL_SECONDS)
        result["published_key"] = key
        result["ttl_seconds"] = RECOVERY_PRED_TTL_SECONDS
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-recovery model train/infer")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--infer", action="store_true")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--min-rows", type=int, default=200)
    parser.add_argument("--max-rows", type=int, default=2000)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args(argv)

    if args.train:
        out = train(args.min_rows, args.max_rows, args.epochs)
        print(json.dumps({k: v for k, v in out.items()}, default=str))
        return 0 if out.get("status") == "OK" else 3
    if args.infer:
        out = infer(args.symbol, args.timeframe, publish=not args.no_publish)
        print(json.dumps(out, default=str))
        return 0 if out.get("status") == "OK" else 3
    parser.error("one of --train or --infer is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
