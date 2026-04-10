from typing import AsyncGenerator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker, create_async_engine)

from src.core.config import get_settings

# Global variables for database session management
engine = None
SessionLocal = None


async def init_db() -> None:
    global engine, SessionLocal

    settings = get_settings()

    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if SessionLocal is None:
        await init_db()

    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")


async def check_db_health() -> bool:
    if SessionLocal is None:
        await init_db()

    async with SessionLocal() as session:
        try:
            await session.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Database health check failed")
            return False
