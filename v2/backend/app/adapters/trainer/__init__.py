"""Public trainer subprocess adapter API for Phase 2E1.A.

Phase 2E1.A spec (`02_PHASE_2E1A_SUBPROCESS_ADAPTER_SPEC.md`) restricts
the package public surface to the five names below. Other adapter
symbols remain accessible via their submodules:
`v2.backend.app.adapters.trainer.modes`,
`v2.backend.app.adapters.trainer.errors`,
`v2.backend.app.adapters.trainer.audit_emitter`,
`v2.backend.app.adapters.trainer.subprocess_adapter`,
`v2.backend.app.adapters.trainer.default_runner`.
"""

from .audit_emitter import TrainerSubprocessAuditEvent
from .errors import (
    TrainerSubprocessSafetyError,
    TrainerSubprocessTimeoutError,
)
from .modes import TrainerSubprocessMode
from .subprocess_adapter import SubprocessTrainerAdapter

__all__ = [
    "SubprocessTrainerAdapter",
    "TrainerSubprocessAuditEvent",
    "TrainerSubprocessMode",
    "TrainerSubprocessSafetyError",
    "TrainerSubprocessTimeoutError",
]
