"""Trainer prediction endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/predictions", tags=["predictions"])