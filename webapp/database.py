from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import Session as SASession
from sqlalchemy.sql import func

db = SQLAlchemy()


class Detection(db.Model):
    __tablename__ = "detections"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    plate_text = db.Column(db.String(20), nullable=False, index=True)
    confidence = db.Column(db.Float, nullable=False)
    camera_id = db.Column(db.String(200), nullable=False)
    camera_name = db.Column(db.String(100))
    image = db.Column(db.LargeBinary, nullable=True)
    detected_at = db.Column(
        db.DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Config(db.Model):
    __tablename__ = "config"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RtspCamera(db.Model):
    __tablename__ = "rtsp_cameras"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=554)
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))
    path = db.Column(db.String(255), default="/")
    name = db.Column(db.String(100))
    enabled = db.Column(db.Boolean, default=True)
    detect_enabled = db.Column(db.Boolean, default=True)
    detect_grid = db.Column(db.String(10), default="1x1")
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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
            "detect_enabled": self.detect_enabled if self.detect_enabled is not None else True,
            "detect_grid": self.detect_grid or "1x1",
        }


def get_session():
    return SASession(db.engine)
