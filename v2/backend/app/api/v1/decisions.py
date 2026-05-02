"""Orchestrator decision endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/decisions", tags=["decisions"])