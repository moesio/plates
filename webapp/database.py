import os

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://moesio:moesio@localhost:5432/plates",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plate_text = Column(String(20), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    camera_id = Column(Integer, nullable=False)
    camera_name = Column(String(100))
    detected_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def get_session():
    return SessionLocal()
