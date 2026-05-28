import logging
import sys
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request
from fast_alpr import ALPR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp import database
from webapp import config as cfg
from webapp.detection import _process_alpr_results
from webapp.rtsp import _start_rtsp_threads, _stop_all_rtsp_threads

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
alpr = ALPR()


@app.before_request
def _seed_config():
    if not getattr(app, "_config_seeded", False):
        try:
            session = database.get_session()
            cfg.seed(session)
            cameras = session.query(database.RtspCamera).filter_by(enabled=True).all()
            session.close()
            if cameras:
                _start_rtsp_threads(cameras)
            else:
                _stop_all_rtsp_threads()
        except Exception:
            pass
        app._config_seeded = True


_seed_config()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/detect", methods=["POST"])
def detect():
    image_bytes = request.get_data()
    app.logger.info("Received %d bytes", len(image_bytes))

    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        app.logger.warning("Invalid image data")
        return jsonify({"error": "invalid image"}), 400

    results = alpr.predict(frame)

    cam_id = request.headers.get("X-Camera-Id", "0")
    cam_name_raw = request.headers.get("X-Camera-Name", "Browser Camera")
    cam_name = unquote(cam_name_raw)

    detections = _process_alpr_results(results, frame, cam_id, cam_name, include_bbox=True)

    app.logger.info(
        "Detected %d plate(s), image size: %d bytes",
        len(detections), len(image_bytes),
    )

    return jsonify(detections)


@app.route("/config", methods=["GET"])
def list_config():
    items = []
    for key in sorted(cfg._DEFAULTS):
        val = cfg.get(key, "")
        desc = cfg._DEFAULTS[key][1] if key in cfg._DEFAULTS else ""
        items.append({"key": key, "value": val, "description": desc})
    return jsonify(items)


@app.route("/config/<key>", methods=["PUT"])
def update_config(key):
    data = request.get_json()
    if not data or "value" not in data:
        return jsonify({"error": "value is required"}), 400
    session = database.get_session()
    row = session.query(database.Config).filter_by(key=key).first()
    if row is None:
        session.close()
        return jsonify({"error": "config key not found"}), 404
    row.value = str(data["value"])
    session.commit()
    new_value = row.value
    session.close()
    cfg.reload()
    return jsonify({"key": key, "value": new_value})


@app.route("/cameras", methods=["GET"])
def list_cameras():
    session = database.get_session()
    cameras = session.query(database.RtspCamera).order_by(database.RtspCamera.id).all()
    session.close()
    return jsonify([cam.to_dict() for cam in cameras])


@app.route("/cameras", methods=["POST"])
def create_camera():
    data = request.get_json()
    if not data or "host" not in data:
        return jsonify({"error": "host is required"}), 400
    session = database.get_session()
    cam = database.RtspCamera(
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
    session = database.get_session()
    cameras = session.query(database.RtspCamera).filter_by(enabled=True).all()
    session.close()
    if cameras:
        _start_rtsp_threads(cameras)
    else:
        _stop_all_rtsp_threads()
    return jsonify(cam.to_dict()), 201


@app.route("/cameras/<int:camera_id>", methods=["PUT"])
def update_camera(camera_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400
    session = database.get_session()
    cam = session.query(database.RtspCamera).filter_by(id=camera_id).first()
    if cam is None:
        session.close()
        return jsonify({"error": "camera not found"}), 404
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
    session = database.get_session()
    cameras = session.query(database.RtspCamera).filter_by(enabled=True).all()
    session.close()
    if cameras:
        _start_rtsp_threads(cameras)
    else:
        _stop_all_rtsp_threads()
    return jsonify(cam.to_dict())


@app.route("/cameras/<int:camera_id>", methods=["DELETE"])
def delete_camera(camera_id):
    session = database.get_session()
    cam = session.query(database.RtspCamera).filter_by(id=camera_id).first()
    if cam is None:
        session.close()
        return jsonify({"error": "camera not found"}), 404
    session.delete(cam)
    session.commit()
    session.close()
    session = database.get_session()
    cameras = session.query(database.RtspCamera).filter_by(enabled=True).all()
    session.close()
    if cameras:
        _start_rtsp_threads(cameras)
    else:
        _stop_all_rtsp_threads()
    return jsonify({"message": "camera deleted"}), 200


@app.route("/admin/cameras")
def admin_cameras():
    return render_template("admin_cameras.html")


@app.route("/admin/config")
def admin_config():
    return render_template("admin_config.html")


@app.route("/admin/detections")
def admin_detections():
    return render_template("detections.html")


@app.route("/detections", methods=["GET"])
def list_detections():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(per_page, 200)
    q = request.args.get("q", "")
    camera_id = request.args.get("camera_id", "")
    sort_by = request.args.get("sort_by", "detected_at")
    sort_order = request.args.get("sort_order", "desc")

    allowed_sort = {"detected_at", "plate_text", "confidence"}
    if sort_by not in allowed_sort:
        sort_by = "detected_at"
    sort_col = getattr(database.Detection, sort_by)
    if sort_order == "asc":
        sort_col = sort_col.asc()
    else:
        sort_col = sort_col.desc()

    session = database.get_session()
    query = session.query(database.Detection)

    if q:
        query = query.filter(database.Detection.plate_text.ilike(f"%{q}%"))
    if camera_id:
        query = query.filter(database.Detection.camera_id == camera_id)

    total = query.count()
    detections = (
        query.order_by(sort_col)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    session.close()

    return jsonify({
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
    })


@app.route("/detections/cameras", methods=["GET"])
def list_detection_cameras():
    session = database.get_session()
    rows = (
        session.query(
            database.Detection.camera_id,
            database.Detection.camera_name,
        )
        .distinct()
        .order_by(database.Detection.camera_name, database.Detection.camera_id)
        .all()
    )
    session.close()
    return jsonify([
        {"camera_id": r.camera_id, "camera_name": r.camera_name or r.camera_id}
        for r in rows
    ])


@app.route("/detections/<int:detection_id>/image")
def detection_image(detection_id):
    session = database.get_session()
    det = session.query(database.Detection).filter_by(id=detection_id).first()
    session.close()
    if det is None or det.image is None:
        return jsonify({"error": "not found"}), 404
    return Response(det.image, mimetype="image/jpeg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
