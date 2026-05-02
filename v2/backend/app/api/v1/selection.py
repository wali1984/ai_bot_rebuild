"""Adaptive selection endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/selection", tags=["selection"])