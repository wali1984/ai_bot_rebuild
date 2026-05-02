"""Passive discovery endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/discovery", tags=["discovery"])