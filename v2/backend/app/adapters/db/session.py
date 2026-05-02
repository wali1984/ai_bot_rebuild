"""SQLAlchemy session factory for AI BOT V2.

No I/O at import. Sessions are constructed only when callers invoke
:func:`make_sessionmaker`. The factory returns a configured
:class:`sessionmaker`; callers are responsible for the session
lifecycle (open/close, commit/rollback) at the service boundary.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    """Return a :class:`sessionmaker` bound to ``engine``.

    Defaults are conservative for control-plane usage:
    ``autoflush=False``, ``autocommit=False``, ``expire_on_commit=False``.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
