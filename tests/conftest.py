import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from src.config import DATABASE_URL, TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh test DB with all tables for each test."""
    # Drop and recreate test database
    engine = create_async_engine(
        DATABASE_URL.replace("salesos_lite", "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    async with engine.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS salesos_lite_test"))
        await conn.execute(text("CREATE DATABASE salesos_lite_test"))
    await engine.dispose()

    # Create tables
    from src.models.base import Base
    test_engine = create_async_engine(TEST_DATABASE_URL)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Yield session
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await test_engine.dispose()
