"""Risk gateway endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/risk", tags=["risk"])