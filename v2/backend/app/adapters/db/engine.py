"""SQLAlchemy engine factory for AI BOT V2.

Lazy: no I/O at import. Engines are constructed only when callers
invoke :func:`make_engine`. The factory is dialect-agnostic at this
layer; the caller supplies a fully-qualified SQLAlchemy URL. Production
callers must source the URL from ``Settings.DATABASE_URL`` and never
from a free-form input.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def make_engine(
    url: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
) -> Engine:
    """Create a SQLAlchemy :class:`Engine` from a URL.

    No connection is opened until the engine is first used. Raises
    :class:`ValueError` for an empty URL to fail fast at the boundary
    rather than producing an opaque dialect error later.
    """
    if not url:
        raise ValueError("DATABASE_URL is empty; refusing to construct engine")
    return create_engine(
        url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        future=True,
    )
