#!/usr/bin/env python
"""CI audit: check all business tables have RLS enabled. Non-zero exit on failure."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sqlalchemy.ext.asyncio import create_async_engine
from src.rls import verify_rls
from src.config import DATABASE_URL


async def main():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        missing = await verify_rls(conn)
        if missing:
            print(f"\u274c RLS not enabled on: {missing}")
            sys.exit(1)
        print("\u2705 All business tables have RLS enabled")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
