"""Database engine and session factory."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "salesos_lite.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def get_db():
    """Yield a SQLAlchemy session (FastAPI dependency)."""
    with Session(engine) as session:
        yield session
