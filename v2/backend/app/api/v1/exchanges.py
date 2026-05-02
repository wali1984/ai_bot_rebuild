"""Exchange manager endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/exchanges", tags=["exchanges"])