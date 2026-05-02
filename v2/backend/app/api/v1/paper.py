"""Paper-trading endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/paper", tags=["paper"])