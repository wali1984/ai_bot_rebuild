"""Feature flow / freshness endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/features", tags=["features"])