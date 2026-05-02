"""Codex review center endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/codex-review", tags=["codex-review"])