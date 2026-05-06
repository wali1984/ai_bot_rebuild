from __future__ import annotations


class PaperExecutionLedgerCompositionError(Exception):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "PaperExecutionLedgerCompositionError("
            f"code={self.code!r}, field={self.field!r})"
        )
