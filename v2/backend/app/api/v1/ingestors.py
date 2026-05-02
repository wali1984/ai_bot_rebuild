"""Ingestor manager endpoints. No handler bodies in scaffold."""

from fastapi import APIRouter

router = APIRouter(prefix="/ingestors", tags=["ingestors"])