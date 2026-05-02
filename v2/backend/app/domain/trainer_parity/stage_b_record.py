"""Stage B trainer-signal publication record dataclass."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TrainerParityLineageError

_ALLOWED_ACTIONS: frozenset[str] = frozenset({"buy", "sell", "hold", "close"})
_ALLOWED_ACTION_TYPES: frozenset[str] = frozenset(
    {"open_long", "open_short", "close_long", "close_short", "hold"}
)


@dataclass(frozen=True, slots=True)
class StageBTrainerRecord:
    """Trainer-signal publication record (Stage B) for V2 GPU parity."""

    signal_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    action: str
    action_type: str
    confidence: float
    signal_ts_ms: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("signal_id", self.signal_id),
            ("prediction_id", self.prediction_id),
            ("feature_snapshot_id", self.feature_snapshot_id),
            ("symbol", self.symbol),
            ("action", self.action),
            ("action_type", self.action_type),
        ):
            if not value:
                raise TrainerParityLineageError(
                    f"stage_b.{field_name} must be non-empty",
                    field=f"stage_b.{field_name}",
                )

        if not 0.0 <= self.confidence <= 1.0:
            raise TrainerParityLineageError(
                "stage_b.confidence must be in [0.0, 1.0]",
                field="stage_b.confidence",
            )
        if self.signal_ts_ms < 0:
            raise TrainerParityLineageError(
                "stage_b.signal_ts_ms must be >= 0",
                field="stage_b.signal_ts_ms",
            )
        if self.action not in _ALLOWED_ACTIONS:
            raise TrainerParityLineageError(
                f"stage_b.action {self.action!r} not in allowed set",
                field="stage_b.action",
            )
        if self.action_type not in _ALLOWED_ACTION_TYPES:
            raise TrainerParityLineageError(
                f"stage_b.action_type {self.action_type!r} not in allowed set",
                field="stage_b.action_type",
            )
