from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    Database dependency for FastAPI.
    Creates a new database session for each request
    and closes it automatically.
    """

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()