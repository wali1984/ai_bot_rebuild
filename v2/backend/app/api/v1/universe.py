"""Universe endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/universe", tags=["universe"])