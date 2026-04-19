from sqlmodel import Session, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from .config import settings

# Sync engine for migrations/simple tasks
engine = create_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)

# Async engine for API requests
async_engine = create_async_engine(settings.ASYNC_DATABASE_URL, echo=settings.SQL_ECHO)


def get_session():
    with Session(engine) as session:
        yield session


async def get_async_session():
    async with AsyncSession(async_engine) as session:
        yield session

