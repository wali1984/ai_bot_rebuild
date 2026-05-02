"""Live-readiness endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/live-readiness", tags=["live-readiness"])