"""Public trainer subprocess adapter API for Phase 2E1.A."""

from .audit_emitter import TrainerSubprocessAuditEvent, to_dict
from .default_runner import DefaultSubprocessRunner
from .errors import (
    TrainerSubprocessConfigError,
    TrainerSubprocessSafetyError,
    TrainerSubprocessTimeoutError,
)
from .modes import ALLOWED_MODES, TrainerSubprocessMode
from .subprocess_adapter import (
    SubprocessRunResult,
    SubprocessRunner,
    SubprocessTrainerAdapter,
)

__all__ = [
    "ALLOWED_MODES",
    "DefaultSubprocessRunner",
    "SubprocessRunResult",
    "SubprocessRunner",
    "SubprocessTrainerAdapter",
    "TrainerSubprocessAuditEvent",
    "TrainerSubprocessConfigError",
    "TrainerSubprocessMode",
    "TrainerSubprocessSafetyError",
    "TrainerSubprocessTimeoutError",
    "to_dict",
]
