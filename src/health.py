from fastapi import HTTPException
from src.database import engine
from src.config import DB_POOL_HEALTH_THRESHOLD, DB_POOL_CRITICAL_THRESHOLD

# Global degradation flag
ai_degraded = False


async def check_pool_health():
    """Called by background task every 30s."""
    global ai_degraded
    pool = engine.pool
    if hasattr(pool, "size"):
        used = pool.size() - pool.freesize() if hasattr(pool, "freesize") else 0
        ratio = used / pool.size() if pool.size() > 0 else 0
        if ratio > DB_POOL_CRITICAL_THRESHOLD:
            raise HTTPException(status_code=503, detail="Database overloaded")
        ai_degraded = ratio > DB_POOL_HEALTH_THRESHOLD


async def health_endpoint():
    pool = engine.pool
    status = {"status": "healthy"}
    if hasattr(pool, "size") and hasattr(pool, "freesize"):
        status["pool_used"] = pool.size() - pool.freesize()
        status["pool_total"] = pool.size()
    return status
