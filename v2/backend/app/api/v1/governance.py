"""Governance / approval endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/governance", tags=["governance"])