from __future__ import annotations


class TrainerParityServiceError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.code} ({self.field})"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, field={self.field!r})"
