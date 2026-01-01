"""Database connection management."""

import logging
import os
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from .models import Base


def get_database_url():
    """Get database URL from environment variables."""
    # Try DATABASE_URL first (full connection string)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    
    # Build from individual components
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "saloonbot")
    user = os.getenv("POSTGRES_USER", "saloonbot")
    password = os.getenv("POSTGRES_PASSWORD", "saloonbot")
    
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


_engine = None
_SessionLocal = None


def get_engine(pool_size=5, max_overflow=10, retries=5, retry_delay=2):
    """Get or create the database engine with connection pooling."""
    global _engine
    
    if _engine is None:
        database_url = get_database_url()
        logging.info(f"Connecting to database at {database_url.split('@')[1] if '@' in database_url else 'unknown'}")
        
        for attempt in range(retries):
            try:
                _engine = create_engine(
                    database_url,
                    pool_size=pool_size,
                    max_overflow=max_overflow,
                    pool_pre_ping=True,  # Verify connections before using
                    echo=os.getenv("SALOONBOT_DEBUG_SQL") is not None
                )
                
                # Test the connection
                with _engine.connect() as conn:
                    conn.execute("SELECT 1")
                
                logging.info("Database connection established successfully")
                break
            except Exception as e:
                if attempt < retries - 1:
                    logging.warning(f"Database connection attempt {attempt + 1} failed: {e}")
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    logging.error(f"Failed to connect to database after {retries} attempts")
                    raise
    
    return _engine


def init_db():
    """Initialize the database by creating all tables."""
    engine = get_engine()
    logging.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logging.info("Database tables created successfully")


def get_session():
    """Get a new database session."""
    global _SessionLocal
    
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    return _SessionLocal()


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
