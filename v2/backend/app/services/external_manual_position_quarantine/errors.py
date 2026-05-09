from __future__ import annotations


class ExternalManualPositionQuarantineServiceError(ValueError):
    def __init__(self, code: str, *, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__(f"{code} ({field})")

    def __repr__(self) -> str:
        return (
            "ExternalManualPositionQuarantineServiceError("
            f"code={self.code!r}, field={self.field!r})"
        )
