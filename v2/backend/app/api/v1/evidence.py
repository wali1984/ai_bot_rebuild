"""Evidence packet endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/evidence", tags=["evidence"])