from __future__ import annotations


class ObservationCollectorError(Exception):
    def __init__(self, code: str, *, field: str | None = None) -> None:
        self.code = code
        self.field = field
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.field is None:
            return self.code
        return f"{self.code} ({self.field})"
