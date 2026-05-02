"""Execution intent endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/intents", tags=["intents"])