from sqlmodel import Session, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from .config import settings
import os

# Sync engine for migrations/simple tasks
engine = create_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)

# Async engine for API requests - configure pool size for concurrent workers
# Workers: SUMMARIZE_WORKERS (default 2) + trans-worker (1) + queue-depth (1) + API requests
# Pool size 10 with overflow 20 gives genoeg ruimte voor pieken zonder timeout
_pool_size = int(os.environ.get("DB_POOL_SIZE", "10"))
_max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
_pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
_pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "3600"))  # Recycle na 1 uur

async_engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_timeout=_pool_timeout,
    pool_recycle=_pool_recycle,
    pool_pre_ping=True,  # Check connectie voordat we 'm gebruiken
)


def get_session():
    with Session(engine) as session:
        yield session


async def get_async_session():
    async with AsyncSession(async_engine) as session:
        yield session


def async_session_maker():
    """Standalone async session ctx-manager (use outside Depends)."""
    return AsyncSession(async_engine)

