from __future__ import annotations


class TrainerPredictionOutputCompositionError(Exception):
    def __init__(self, code: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.field is not None:
            return f"{self.code} ({self.field})"
        return self.code
