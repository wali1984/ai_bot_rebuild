from __future__ import annotations

from .errors import DegradedStateFailClosedGatesServiceError
from .service import assemble_degraded_state_record


__all__ = [
    "DegradedStateFailClosedGatesServiceError",
    "assemble_degraded_state_record",
]
