import logging

from webapp import database
from webapp.database import RtspCamera
from webapp.rtsp import _start_rtsp_threads, _stop_all_rtsp_threads

logger = logging.getLogger(__name__)


class CameraService:

    @staticmethod
    def list_all():
        session = database.get_session()
        cameras = session.query(RtspCamera).order_by(RtspCamera.id).all()
        session.close()
        return [cam.to_dict() for cam in cameras]

    @staticmethod
    def create(data):
        session = database.get_session()
        cam = RtspCamera(
            host=data["host"],
            port=data.get("port", 554),
            username=data.get("username", ""),
            password=data.get("password", ""),
            path=data.get("path", "/"),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
        )
        session.add(cam)
        session.commit()
        session.refresh(cam)
        session.close()
        CameraService._restart_rtsp()
        return cam.to_dict()

    @staticmethod
    def update(camera_id, data):
        session = database.get_session()
        cam = session.query(RtspCamera).filter_by(id=camera_id).first()
        if cam is None:
            session.close()
            return None
        cam.host = data.get("host", cam.host)
        cam.port = data.get("port", cam.port)
        cam.username = data.get("username", cam.username)
        cam.password = data.get("password", cam.password)
        cam.path = data.get("path", cam.path)
        cam.name = data.get("name", cam.name)
        cam.enabled = data.get("enabled", cam.enabled)
        session.commit()
        session.refresh(cam)
        session.close()
        CameraService._restart_rtsp()
        return cam.to_dict()

    @staticmethod
    def delete(camera_id):
        session = database.get_session()
        cam = session.query(RtspCamera).filter_by(id=camera_id).first()
        if cam is None:
            session.close()
            return False
        session.delete(cam)
        session.commit()
        session.close()
        CameraService._restart_rtsp()
        return True

    @staticmethod
    def _restart_rtsp():
        session = database.get_session()
        cameras = session.query(RtspCamera).filter_by(enabled=True).all()
        session.close()
        if cameras:
            _start_rtsp_threads(cameras)
        else:
            _stop_all_rtsp_threads()
