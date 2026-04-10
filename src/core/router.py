from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.core.config import get_settings
from src.db.session import check_db_health
from src.modules.conversations.router import router as conversations_router
from src.modules.voice.dependencies import get_voice_metrics, get_voice_session_store
from src.modules.voice.integrations.retell.router import router as retell_router
from src.modules.voice.metrics import VoiceMetrics
from src.modules.voice.session_store import VoiceSessionStore


def setup_routers() -> APIRouter:
    """
    Create and configure all application routers.
    
    Returns:
        APIRouter: Main router with all sub-routers included
    """
    settings = get_settings()
    
    # Create main router
    main_router = APIRouter()
    
    # Include module routers with API prefix
    api_router = APIRouter()
    api_router.include_router(conversations_router, tags=["conversations"])
    
    # Include API routes with prefix
    main_router.include_router(api_router, prefix=settings.api_prefix)
    main_router.include_router(retell_router)
    
    # Health check endpoint
    @main_router.get("/health", tags=["health"])
    async def health_check(
        session_store: VoiceSessionStore = Depends(get_voice_session_store),
        voice_metrics: VoiceMetrics = Depends(get_voice_metrics),
    ):
        db_healthy = await check_db_health()
        voice_store_health = await session_store.check_health()
        voice_metrics_snapshot = voice_metrics.snapshot()
        overall_healthy = db_healthy and voice_store_health.status == "healthy"
        return JSONResponse(
            status_code=200 if overall_healthy else 503,
            content={
                "status": "healthy" if overall_healthy else "unhealthy",
                "app_name": settings.app_name,
                "app_version": settings.app_version,
                "environment": settings.environment,
                "components": {
                    "database": {"status": "healthy" if db_healthy else "unhealthy"},
                    "voice_session_store": voice_store_health.model_dump(),
                },
                "voice_metrics": voice_metrics_snapshot,
            }
        )
    
    # Root endpoint
    @main_router.get("/", tags=["root"])
    async def root():
        response_content = {
            "message": f"Welcome to {settings.app_name}",
            "version": settings.app_version,
            "health_url": "/health",
            "api_prefix": settings.api_prefix,
        }
        
        # Only include docs URLs in development environment
        if settings.environment == "development":
            response_content.update({
                "docs_url": "/docs",
                "redoc_url": "/redoc"
            })
        
        return JSONResponse(content=response_content)
    
    return main_router
