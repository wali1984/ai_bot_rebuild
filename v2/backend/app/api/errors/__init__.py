"""Error envelope and closed taxonomy."""

from app.api.errors.envelope import ErrorBody, ResponseEnvelope
from app.api.errors.taxonomy import (
    ERROR_CLASS_NAMES,
    ERROR_CLASSES,
    ERROR_GROUPS,
    ErrorClass,
    lookup,
)

__all__ = [
    "ERROR_CLASSES",
    "ERROR_CLASS_NAMES",
    "ERROR_GROUPS",
    "ErrorBody",
    "ErrorClass",
    "ResponseEnvelope",
    "lookup",
]
