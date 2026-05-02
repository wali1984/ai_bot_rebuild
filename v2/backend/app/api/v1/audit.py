"""Audit ledger endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/audit", tags=["audit"])