"""Domain-specific exception types for trainer parity records."""

from __future__ import annotations


class TrainerParityLineageError(ValueError):
    """Raised when a trainer parity lineage or explainability invariant is violated."""

    __slots__ = ("reason", "field")

    def __init__(self, reason: str, *, field: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.field = field
