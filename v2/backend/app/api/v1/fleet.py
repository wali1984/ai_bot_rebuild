"""Trader fleet endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/fleet", tags=["fleet"])