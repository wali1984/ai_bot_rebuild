from __future__ import annotations


class TrainerWorkerHealthServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field

    def __str__(self) -> str:
        return f"{self.code} ({self.field})"

    def __repr__(self) -> str:
        return f"TrainerWorkerHealthServiceError(code={self.code!r}, field={self.field!r})"
