"""SQLAlchemy declarative base for AI BOT V2.

No I/O at import. No models declared at this milestone; ``Base.metadata``
is intentionally empty so the Alembic harness round-trip is a true
no-op. ORM models are introduced in milestone C proper, one model per
review-bounded change, behind explicit approval.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all V2 ORM models."""
