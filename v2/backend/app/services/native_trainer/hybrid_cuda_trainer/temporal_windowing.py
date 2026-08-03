"""WI-1 Step 1: no-lookahead temporal windowing over training examples.

Crypto directional prediction is temporal, but the V2 model consumes a single
frozen frame (model_vector). This builds, for each example, a sequence of the
``seq_len`` most-recent feature frames for the SAME (symbol, timeframe), ordered
by decision_time and including ONLY frames at or before the example's own
decision_time (strict no-lookahead -- a window can never contain a frame from
the future relative to the decision it feeds). Windows shorter than seq_len are
left-padded by repeating the oldest available frame, with a padding mask so a
downstream encoder can ignore the padded positions.

Pure, offline, dependency-light utility (no torch): it only reorders and groups
existing example vectors. It does NOT touch the model or the online path -- the
temporal encoder (Step 2) consumes these windows, gated OFF by default, and is
edge-proven offline (Step 3) before any integration.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DEFAULT_SEQ_LEN = 16


@dataclass(frozen=True)
class WindowedExample:
    """A training example plus its no-lookahead temporal window."""

    example: Any
    # seq_len frames, oldest first, newest (== the example's own frame) last.
    window: tuple[tuple[float, ...], ...]
    # 1 for a real frame, 0 for a left-pad frame (repeated oldest).
    pad_mask: tuple[int, ...]
    real_frame_count: int


def _parse_decision_ms(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):  # noqa: UP038
        # epoch seconds or ms -> normalise to ms
        v = float(value)
        if not math.isfinite(v) or v <= 0.0:
            return None
        return v if v > 1e11 else v * 1000.0
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.timestamp() * 1000.0
    except (TypeError, ValueError):
        return None


def _group_key(example: Any) -> tuple[str, str]:
    return (
        str(getattr(example, "symbol", "") or "").upper(),
        str(getattr(example, "timeframe", "") or "").lower(),
    )


def _model_vector(example: Any) -> tuple[float, ...] | None:
    tensor = getattr(example, "tensor", None)
    vec = getattr(tensor, "model_vector", None)
    if vec is None:
        return None
    try:
        return tuple(float(v) for v in vec)
    except (TypeError, ValueError):
        return None


def build_example_windows(
    examples: Sequence[Any],
    *,
    seq_len: int = DEFAULT_SEQ_LEN,
) -> list[WindowedExample]:
    """Build a no-lookahead temporal window for each example.

    Examples are grouped by (symbol, timeframe) and ordered by decision_time
    (stable within equal timestamps by original index). Each example's window is
    the ``seq_len`` frames up to and including itself; shorter histories are
    left-padded with the oldest available frame. Examples without a usable
    model_vector or parseable immutable decision_time are skipped. Missing
    chronology is never replaced with input order. Output preserves the input
    order of the kept examples.
    """
    seq_len = max(1, int(seq_len))
    # Decorate with (group, decision_ms, original_index, vector), skipping unusable rows.
    decorated: list[tuple[tuple[str, str], float, int, tuple[float, ...], Any]] = []
    for idx, ex in enumerate(examples):
        vec = _model_vector(ex)
        if vec is None:
            continue
        dms = _parse_decision_ms(getattr(ex, "decision_time", None))
        if dms is None:
            # Fail closed: list position is not event-time evidence and can be
            # reversed by a loader, cursor, cache, or replay merge.
            continue
        decorated.append((_group_key(ex), dms, idx, vec, ex))

    # Per group, sort by (decision_ms, original_index) so windows are time-ordered
    # and strictly causal.
    by_group: dict[tuple[str, str], list[tuple[float, int, tuple[float, ...], Any]]] = {}
    for group, dms, idx, vec, ex in decorated:
        by_group.setdefault(group, []).append((dms, idx, vec, ex))
    for rows in by_group.values():
        rows.sort(key=lambda r: (r[0], r[1]))

    # Build windows keyed by original index so we can restore input order.
    windows_by_idx: dict[int, WindowedExample] = {}
    for rows in by_group.values():
        vectors = [vec for _dms, _idx, vec, _ex in rows]
        decision_times = [dms for dms, _idx, _vec, _ex in rows]
        for position, (target_dms, original_idx, _vec, ex) in enumerate(rows):
            start = max(0, position - seq_len + 1)
            real = vectors[start: position + 1]
            # The sorted prefix is causal; retain an explicit invariant so a
            # future refactor cannot admit a newer frame into this decision.
            if any(frame_dms > target_dms for frame_dms in decision_times[start: position + 1]):
                raise ValueError("TEMPORAL_WINDOW_CONTAINS_FUTURE_FRAME")
            real_count = len(real)
            if real_count < seq_len:
                # Left-pad by repeating the oldest real frame.
                pad = [real[0]] * (seq_len - real_count)
                frames = pad + real
                pad_mask = tuple([0] * (seq_len - real_count) + [1] * real_count)
            else:
                frames = real
                pad_mask = tuple([1] * seq_len)
            windows_by_idx[original_idx] = WindowedExample(
                example=ex,
                window=tuple(frames),
                pad_mask=pad_mask,
                real_frame_count=real_count,
            )

    return [windows_by_idx[i] for i in sorted(windows_by_idx)]


def build_window_lookup(examples: Sequence[Any], *, seq_len: int = DEFAULT_SEQ_LEN) -> dict[int, tuple[tuple[float, ...], ...]]:
    """Map id(example) -> its no-lookahead window, for building batched tensors.

    Keyed by ``id`` because TrainingExample is a frozen dataclass with an
    unhashable dict field. Each caller builds a lookup from its OWN row set so
    the window is self-consistent and strictly causal within that set.
    """
    return {id(w.example): w.window for w in build_example_windows(examples, seq_len=seq_len)}


def model_batch_tensor(
    torch_module: Any,
    rows: Sequence[Any],
    *,
    temporal: bool,
    seq_len: int,
    window_lookup: dict[int, tuple[tuple[float, ...], ...]] | None,
    device: str = "cpu",
) -> Any:
    """Build the model input batch: 2D (B, F) single-frame, or 3D (B, T, F) window.

    The SINGLE place that decides frame-vs-window, so every training/eval/predict
    path stays consistent. When ``temporal`` is off (or no lookup) it returns the
    exact 2D tensor the single-frame model always used. When on, each row must
    have a window built from a parseable decision_time. A missing lookup fails
    closed instead of silently degrading to single-frame training.
    """
    import numpy as np  # noqa: PLC0415

    if temporal:
        if window_lookup is None:
            raise ValueError("TEMPORAL_WINDOW_LOOKUP_MISSING")
        # Build via numpy (C-level) -- a nested Python list of B*T*F floats +
        # torch.tensor() is pathologically slow for large eval batches.
        frames: list[Any] = []
        for r in rows:
            window = window_lookup.get(id(r))
            if window is None:
                raise ValueError("TEMPORAL_WINDOW_MISSING_PARSEABLE_DECISION_TIME")
            frames.append(np.asarray(window, dtype=np.float32))
        arr = np.stack(frames)  # (B, T, F)
        return torch_module.from_numpy(arr).to(device)
    arr = np.asarray(
        [np.asarray(r.tensor.model_vector, dtype=np.float32) for r in rows],
        dtype=np.float32,
    )
    return torch_module.from_numpy(arr).to(device)
