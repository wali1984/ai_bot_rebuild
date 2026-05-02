"""Monitor center endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/monitor", tags=["monitor"])