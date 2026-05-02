"""Ollama local assistant endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/ollama", tags=["ollama"])