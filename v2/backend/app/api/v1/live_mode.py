"""Live-mode endpoints. Default-deny; L5 approval required.

No handler bodies in scaffold. All future routes here must be guarded by the
live-block guard and the step-up MFA middleware.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/live-mode", tags=["live-mode"])