from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from src.db.session import close_db, init_db
from src.modules.voice.dependencies import close_voice_dependencies
from src.modules.profiles.repository import get_profile_repository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up Kira API...")
    await init_db()
    get_profile_repository()
    logger.info("Application dependencies initialized successfully")
    yield
    await close_voice_dependencies()
    await close_db()
    logger.info("Shutting down Kira API...")
    logger.info("Cleanup completed successfully")
