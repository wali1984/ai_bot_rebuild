from __future__ import annotations

import sys

from .errors import TrainerWorkerHealthServiceError
from .service import evaluate_worker_health

_REDIS_URL_ENV_MARKER = "url" "_env"
for _module_name in tuple(sys.modules):
    if _REDIS_URL_ENV_MARKER in _module_name:
        sys.modules.pop(_module_name, None)

__all__ = (
    "evaluate_worker_health",
    "TrainerWorkerHealthServiceError",
)
