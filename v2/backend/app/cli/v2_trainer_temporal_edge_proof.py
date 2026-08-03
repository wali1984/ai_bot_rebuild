"""WI-1 Steps 2-3: offline edge-proof of a temporal (GRU) encoder vs single-frame MLP.

The V2 model has ~zero risk-adjusted edge and consumes one frozen frame. Before
touching the core model, this OFFLINE probe answers the only question that
matters: does a temporal encoder over a no-lookahead window produce better
risk-adjusted edge than a single-frame baseline on the same data + split?

Two probes with identical heads and capacity are trained on the SAME
time-ordered train split (supervised: cross-entropy on the label action +
MSE on the after-cost move) and evaluated on the SAME held-out (later-in-time)
split by the risk composite (Sortino + CVaR) used by the H2L promotion gate:
  - TemporalGRUProbe: GRU over the seq_len window -> last hidden -> heads.
  - SingleFrameMLPProbe: MLP over the window's last frame only -> heads.

Time-based split (train = earlier, eval = later) keeps it strictly causal and
leakage-free. Read-only, offline, GPU-heavy training only; never writes a live
checkpoint, never trades. If the GRU wins, temporal integration is warranted.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.cli.v2_trainer_offline_batch_train import load_or_build_examples
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.risk_metrics import (
    risk_adjusted_summary,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (
    build_example_windows,
)

ACTION_COUNT = 7


def _returns_from_actions(examples: Sequence[Any], actions: Sequence[int]) -> list[float]:
    returns: list[float] = []
    for ex, a in zip(examples, actions, strict=False):
        move = float(getattr(ex, "label_expected_move_after_cost_bps", 0.0) or 0.0)
        if a == 1:
            returns.append(move)
        elif a == 2:
            returns.append(-move)
    return returns


def run_edge_proof(
    *,
    windows: list[Any],
    seq_len: int,
    feature_dim: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    hidden: int,
    eval_fraction: float,
    device: str = "cuda",
) -> dict[str, Any]:
    import torch  # noqa: PLC0415
    from torch import nn  # noqa: PLC0415

    if not torch.cuda.is_available():
        device = "cpu"
    dev = torch.device(device)

    # Strictly causal time split: windows preserve input order (kept examples);
    # sort by the example's decision proxy already applied per-group, but for the
    # split we use the flat kept order which is the archive's time order.
    n = len(windows)
    cut = max(1, int(n * (1.0 - eval_fraction)))
    train_w, eval_w = windows[:cut], windows[cut:]
    if not train_w or not eval_w:
        return {"error": "INSUFFICIENT_WINDOWS", "windows": n}

    def _tensors(ws: list[Any]) -> tuple[Any, Any, Any, list[Any]]:
        seqs = [[list(f) for f in w.window] for w in ws]
        x = torch.tensor(seqs, dtype=torch.float32)  # (N, T, F)
        x = torch.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6)
        acts = torch.tensor(
            [int(getattr(w.example, "label_action_index", 0) or 0) for w in ws],
            dtype=torch.long,
        )
        moves = torch.tensor(
            [float(getattr(w.example, "label_expected_move_after_cost_bps", 0.0) or 0.0) for w in ws],
            dtype=torch.float32,
        )
        return x, acts, moves, [w.example for w in ws]

    xtr, atr, mtr, _ = _tensors(train_w)
    xev, aev, mev, ev_examples = _tensors(eval_w)
    xtr, atr, mtr = xtr.to(dev), atr.to(dev), mtr.to(dev)
    xev = xev.to(dev)

    class _Heads(nn.Module):
        def __init__(self, hidden_dim: int) -> None:
            super().__init__()
            self.action = nn.Linear(hidden_dim, ACTION_COUNT)
            self.move = nn.Linear(hidden_dim, 1)

        def forward(self, h):  # noqa: ANN001
            return self.action(h), self.move(h).squeeze(-1)

    class TemporalGRUProbe(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.gru = nn.GRU(feature_dim, hidden, num_layers=1, batch_first=True)
            self.heads = _Heads(hidden)

        def forward(self, x):  # noqa: ANN001  x: (N,T,F)
            out, _ = self.gru(x)
            return self.heads(out[:, -1, :])

    class SingleFrameMLPProbe(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(feature_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU()
            )
            self.heads = _Heads(hidden)

        def forward(self, x):  # noqa: ANN001  x: (N,T,F) -> use last frame
            return self.heads(self.net(x[:, -1, :]))

    def _train_eval(model: Any, name: str) -> dict[str, Any]:
        model = model.to(dev)
        opt = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.02)
        ce, mse = nn.CrossEntropyLoss(), nn.MSELoss()
        idx = torch.arange(xtr.shape[0])
        for _ep in range(max(1, epochs)):
            perm = idx[torch.randperm(idx.shape[0])]
            for start in range(0, perm.shape[0], batch_size):
                b = perm[start: start + batch_size]
                opt.zero_grad()
                logits, move = model(xtr[b])
                loss = ce(logits, atr[b]) + 0.001 * mse(move, mtr[b] / 100.0)
                loss.backward()
                opt.step()
        model.eval()
        with torch.no_grad():
            logits, _ = model(xev)
            actions = torch.argmax(logits, dim=-1).detach().cpu().tolist()
        returns = _returns_from_actions(ev_examples, actions)
        summ = risk_adjusted_summary(returns)
        sortino = summ.get("sortino_ratio")
        cvar = summ.get("cvar")
        composite = (float(sortino) + (float(cvar) / 1000.0 if cvar is not None else 0.0)) if sortino is not None else None
        return {
            "probe": name,
            "risk_composite": composite,
            "sortino": sortino,
            "cvar": cvar,
            "win_rate": summ.get("win_rate"),
            "trades": summ.get("count"),
            "params": sum(p.numel() for p in model.parameters()),
        }

    gru = _train_eval(TemporalGRUProbe(), "temporal_gru")
    mlp = _train_eval(SingleFrameMLPProbe(), "single_frame_mlp")
    g, m = gru.get("risk_composite"), mlp.get("risk_composite")
    temporal_wins = g is not None and m is not None and g > m
    return {
        "schema_version": "trainer_temporal_edge_proof_v1",
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "seq_len": seq_len,
        "feature_dim": feature_dim,
        "device": str(dev),
        "train_windows": len(train_w),
        "eval_windows": len(eval_w),
        "temporal_gru": gru,
        "single_frame_mlp": mlp,
        "temporal_wins": bool(temporal_wins),
        "temporal_edge_delta": (g - m) if (g is not None and m is not None) else None,
        "verdict": (
            "TEMPORAL_ENCODER_IMPROVES_EDGE_INTEGRATE"
            if temporal_wins
            else "TEMPORAL_ENCODER_NO_EDGE_GAIN_DO_NOT_INTEGRATE"
        ),
        "offline_only": True,
        "writes_live_checkpoint": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=20000)
    p.add_argument("--seq-len", type=int, default=16)
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--batch-size", type=int, default=2048)
    p.add_argument("--learning-rate", type=float, default=1e-3)
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--eval-fraction", type=float, default=0.25)
    p.add_argument("--cache-path", default="claude_worklog/trainer_atlas/temporal_edge_proof_cache.pkl")
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    args = parse_args(argv)
    examples, _ = load_or_build_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        limit=args.limit,
        cache_path=args.cache_path,
        rebuild_cache=False,
    )
    windows = build_example_windows(examples, seq_len=args.seq_len)
    if not windows:
        print(json.dumps({"error": "NO_WINDOWS"}))
        return 1
    feature_dim = len(windows[0].window[-1])
    report = run_edge_proof(
        windows=windows,
        seq_len=args.seq_len,
        feature_dim=feature_dim,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        hidden=args.hidden,
        eval_fraction=args.eval_fraction,
    )
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        from pathlib import Path  # noqa: PLC0415
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
    print(text)
    print(
        "TEMPORAL_EDGE_PROOF:",
        f"verdict={report.get('verdict')}",
        f"gru_composite={report.get('temporal_gru', {}).get('risk_composite')}",
        f"mlp_composite={report.get('single_frame_mlp', {}).get('risk_composite')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
