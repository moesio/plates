import os

from sqlalchemy import Boolean, create_engine, Column, Integer, String, Float, DateTime, LargeBinary, Text
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
    camera_id = Column(String(200), nullable=False)
    camera_name = Column(String(100))
    image = Column(LargeBinary, nullable=True)
    detected_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Config(Base):
    __tablename__ = "config"

    key = Column(String(50), primary_key=True)
    value = Column(String(255), nullable=False)
    description = Column(Text)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RtspCamera(Base):
    __tablename__ = "rtsp_cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=554)
    username = Column(String(100))
    password = Column(String(100))
    path = Column(String(255), default="/")
    name = Column(String(100))
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "host": self.host,
            "port": self.port if self.port is not None else 554,
            "username": self.username or "",
            "password": self.password or "",
            "path": self.path or "/",
            "name": self.name or "",
            "enabled": self.enabled if self.enabled is not None else True,
        }


def get_session():
    return SessionLocal()
