import logging
import os

from flask import Response, jsonify

from webapp import database
from webapp.database import Detection

logger = logging.getLogger(__name__)

_MAX_PER_PAGE = int(os.getenv("DETECTIONS_MAX_PER_PAGE", "200"))


class DetectionService:

    @staticmethod
    def list_all(page, per_page, q, camera_id, sort_by, sort_order):
        per_page = min(per_page, _MAX_PER_PAGE)
        allowed_sort = {"detected_at", "plate_text", "confidence"}
        if sort_by not in allowed_sort:
            sort_by = "detected_at"
        sort_col = getattr(Detection, sort_by)
        sort_col = sort_col.asc() if sort_order == "asc" else sort_col.desc()

        session = database.get_session()
        query = session.query(Detection)

        if q:
            query = query.filter(Detection.plate_text.ilike(f"%{q}%"))
        if camera_id:
            query = query.filter(Detection.camera_id == camera_id)

        total = query.count()
        detections = (
            query.order_by(sort_col)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        session.close()

        return {
            "detections": [
                {
                    "id": d.id,
                    "plate_text": d.plate_text,
                    "confidence": d.confidence,
                    "camera_id": d.camera_id,
                    "camera_name": d.camera_name,
                    "detected_at": d.detected_at.isoformat() if d.detected_at else None,
                    "has_image": d.image is not None,
                }
                for d in detections
            ],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def list_cameras():
        session = database.get_session()
        rows = (
            session.query(Detection.camera_id, Detection.camera_name)
            .distinct()
            .order_by(Detection.camera_name, Detection.camera_id)
            .all()
        )
        session.close()
        return [
            {"camera_id": r.camera_id, "camera_name": r.camera_name or r.camera_id}
            for r in rows
        ]

    @staticmethod
    def get_image(detection_id):
        session = database.get_session()
        det = session.query(Detection).filter_by(id=detection_id).first()
        session.close()
        if det is None or det.image is None:
            return None
        return Response(det.image, mimetype="image/jpeg")
