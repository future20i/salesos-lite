import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://salesos:salesos_dev@localhost:5432/salesos_lite"
)
TEST_DATABASE_URL = DATABASE_URL.replace("salesos_lite", "salesos_lite_test")

# Connection pool settings
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
DB_POOL_HEALTH_THRESHOLD = 0.8   # 80% → degrade AI
DB_POOL_CRITICAL_THRESHOLD = 0.95  # 95% → 503
