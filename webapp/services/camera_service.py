import logging

from webapp.database import db, RtspCamera
from webapp.rtsp import _start_rtsp_threads, _stop_all_rtsp_threads, get_latest_frame

logger = logging.getLogger(__name__)


class CameraService:

    @staticmethod
    def list_all():
        cameras = db.session.query(RtspCamera).order_by(RtspCamera.id).all()
        result = []
        for cam in cameras:
            data = cam.to_dict()
            data["online"] = get_latest_frame(f"rtsp:{cam.id}") is not None
            result.append(data)
        return result

    @staticmethod
    def create(data):
        cam = RtspCamera(
            host=data["host"],
            port=data.get("port", 554),
            username=data.get("username", ""),
            password=data.get("password", ""),
            path=data.get("path", "/"),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
        )
        db.session.add(cam)
        db.session.commit()
        db.session.refresh(cam)
        CameraService._restart_rtsp()
        return cam.to_dict()

    @staticmethod
    def update(camera_id, data):
        cam = db.session.query(RtspCamera).filter_by(id=camera_id).first()
        if cam is None:
            return None
        cam.host = data.get("host", cam.host)
        cam.port = data.get("port", cam.port)
        cam.username = data.get("username", cam.username)
        cam.password = data.get("password", cam.password)
        cam.path = data.get("path", cam.path)
        cam.name = data.get("name", cam.name)
        cam.enabled = data.get("enabled", cam.enabled)
        db.session.commit()
        db.session.refresh(cam)
        CameraService._restart_rtsp()
        return cam.to_dict()

    @staticmethod
    def delete(camera_id):
        cam = db.session.query(RtspCamera).filter_by(id=camera_id).first()
        if cam is None:
            return False
        db.session.delete(cam)
        db.session.commit()
        CameraService._restart_rtsp()
        return True

    @staticmethod
    def _restart_rtsp():
        cameras = db.session.query(RtspCamera).filter_by(enabled=True).all()
        if cameras:
            _start_rtsp_threads(cameras)
        else:
            _stop_all_rtsp_threads()
