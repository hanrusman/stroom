
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings

# Sync engine for migrations/simple tasks
engine = create_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)

# Async engine for API requests - configure pool size for concurrent workers
# Workers: SUMMARIZE_WORKERS (default 2) + trans-worker (1) + queue-depth (1) + API requests
# Pool size 10 with overflow 20 gives genoeg ruimte voor pieken zonder timeout
_pool_size = settings.DB_POOL_SIZE
_max_overflow = settings.DB_MAX_OVERFLOW
_pool_timeout = settings.DB_POOL_TIMEOUT
_pool_recycle = settings.DB_POOL_RECYCLE  # Recycle na 1 uur

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

