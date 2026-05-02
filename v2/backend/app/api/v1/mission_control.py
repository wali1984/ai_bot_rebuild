"""Mission Control endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/mission-control", tags=["mission-control"])