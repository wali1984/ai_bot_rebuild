from __future__ import annotations


class PaperModeServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "PaperModeServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
