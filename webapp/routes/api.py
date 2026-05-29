import logging
from urllib.parse import unquote

import cv2
import numpy as np
from flask import Blueprint, jsonify, request

from webapp import config as cfg, database
from webapp.database import Config
from webapp.detection import _process_alpr_results
from webapp.services.camera_service import CameraService
from webapp.services.detection_service import DetectionService

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.route("/detect", methods=["POST"])
def detect():
    from webapp.alpr import alpr

    image_bytes = request.get_data()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "invalid image"}), 400

    results = alpr.predict(frame)

    cam_id = request.headers.get("X-Camera-Id", "0")
    cam_name_raw = request.headers.get("X-Camera-Name", "Browser Camera")
    cam_name = unquote(cam_name_raw)

    detections = _process_alpr_results(results, frame, cam_id, cam_name, include_bbox=True)
    return jsonify(detections)


@api_bp.route("/config", methods=["GET"])
def list_config():
    items = []
    for key in sorted(cfg._DEFAULTS):
        val = cfg.get(key, "")
        desc = cfg._DEFAULTS[key][1] if key in cfg._DEFAULTS else ""
        items.append({"key": key, "value": val, "description": desc})
    return jsonify(items)


@api_bp.route("/config/<key>", methods=["PUT"])
def update_config(key):
    data = request.get_json()
    if not data or "value" not in data:
        return jsonify({"error": "value is required"}), 400
    session = database.get_session()
    row = session.query(Config).filter_by(key=key).first()
    if row is None:
        session.close()
        return jsonify({"error": "config key not found"}), 404
    row.value = str(data["value"])
    session.commit()
    new_value = row.value
    session.close()
    cfg.reload()
    return jsonify({"key": key, "value": new_value})


@api_bp.route("/cameras", methods=["GET"])
def list_cameras():
    return jsonify(CameraService.list_all())


@api_bp.route("/cameras", methods=["POST"])
def create_camera():
    data = request.get_json()
    if not data or "host" not in data:
        return jsonify({"error": "host is required"}), 400
    result = CameraService.create(data)
    return jsonify(result), 201


@api_bp.route("/cameras/<int:camera_id>", methods=["PUT"])
def update_camera(camera_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400
    result = CameraService.update(camera_id, data)
    if result is None:
        return jsonify({"error": "camera not found"}), 404
    return jsonify(result)


@api_bp.route("/cameras/<int:camera_id>", methods=["DELETE"])
def delete_camera(camera_id):
    if not CameraService.delete(camera_id):
        return jsonify({"error": "camera not found"}), 404
    return jsonify({"message": "camera deleted"}), 200


@api_bp.route("/detections", methods=["GET"])
def list_detections():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    q = request.args.get("q", "")
    camera_id = request.args.get("camera_id", "")
    sort_by = request.args.get("sort_by", "detected_at")
    sort_order = request.args.get("sort_order", "desc")
    result = DetectionService.list_all(page, per_page, q, camera_id, sort_by, sort_order)
    return jsonify(result)


@api_bp.route("/detections/cameras", methods=["GET"])
def list_detection_cameras():
    return jsonify(DetectionService.list_cameras())


@api_bp.route("/detections/<int:detection_id>/image")
def detection_image(detection_id):
    result = DetectionService.get_image(detection_id)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return result
