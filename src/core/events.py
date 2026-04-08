from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from loguru import logger

from src.db.session import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up Atom API...")
    
    """
    Create database tables
    https://docs.sqlalchemy.org/en/13/core/metadata.html#creating-and-dropping-database-tables
    This method will issue queries that first check for the existence of each individual table, and if not found will issue the CREATE statements.
    """
    await create_tables()
    logger.info("Database tables created successfully")
    
    yield
    
    logger.info("Shutting down Atom API...")
    logger.info("Cleanup completed successfully")