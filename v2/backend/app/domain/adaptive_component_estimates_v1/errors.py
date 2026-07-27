from __future__ import annotations


class AdaptiveComponentEstimateDomainError(ValueError):
    """Raised when a shadow component-estimate record is not trustworthy."""

    def __init__(self, reason: str, *, field: str) -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"{field}:{reason}")


__all__ = ("AdaptiveComponentEstimateDomainError",)
