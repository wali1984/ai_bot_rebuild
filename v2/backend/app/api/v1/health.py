"""Health endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])