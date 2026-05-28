import logging
import sys
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request
from fast_alpr import ALPR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp import database
from webapp import config as cfg
from webapp import dedup
from webapp.plate import _is_valid_plate
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
    detections = []
    min_conf = cfg.get_float("confidence_threshold", 0.0)

    for result in results:
        if result.ocr is None:
            continue
        bbox = result.detection.bounding_box
        text = result.ocr.text
        conf = result.ocr.confidence
        if isinstance(conf, list):
            conf = sum(conf) / len(conf) if conf else 0.0
        if conf < min_conf:
            continue

        detections.append({
            "plate_text": text,
            "confidence": round(conf, 4),
            "x1": bbox.x1,
            "y1": bbox.y1,
            "x2": bbox.x2,
            "y2": bbox.y2,
        })

    before = len(detections)
    detections = [d for d in detections if _is_valid_plate(d["plate_text"])]
    invalid = before - len(detections)

    cam_id = request.headers.get("X-Camera-Id", "0")
    cam_name_raw = request.headers.get("X-Camera-Name", "Browser Camera")
    cam_name = unquote(cam_name_raw)

    app.logger.info(
        "Detected %d plate(s), %d invalid, image size: %d bytes",
        len(detections), invalid, len(image_bytes),
    )

    saved = 0
    skipped = 0

    for d in detections:
        if not dedup._check_dedup(d["plate_text"], cam_id):
            skipped += 1
            continue

        try:
            session = database.get_session()
            det = database.Detection(
                plate_text=d["plate_text"],
                confidence=d["confidence"],
                camera_id=cam_id,
                camera_name=cam_name,
                image=image_bytes,
            )
            session.add(det)
            session.commit()
            saved += 1
            app.logger.info("Saved plate %s to DB", d["plate_text"])
        except Exception as e:
            app.logger.error("DB error saving %s: %s", d["plate_text"], e)
        finally:
            session.close()

    dedup._save_counter += 1
    window = cfg.get_int("dedup_seconds", 60)
    cleanup_every = cfg.get_int("cleanup_interval", 20)
    if dedup._save_counter % cleanup_every == 0:
        dedup._cleanup_stale()

    app.logger.info("Plates: %d saved, %d skipped (dedup window: %ds)", saved, skipped, window)

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
