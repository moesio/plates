import json
import logging
import re
import threading
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request
from fast_alpr import ALPR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from webapp import database
from webapp import config as cfg

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
alpr = ALPR()

_seen = {}
_seen_lock = threading.Lock()
_save_counter = 0

_RTSP_CAMERAS = {}
_RTSP_CAMERAS_LOCK = threading.Lock()
_RTSP_THREADS = {}

_PLATE_RE = re.compile(r"^[A-Z]{3}(?:\d{4}|\d[A-Z]\d{2})$")


def _build_rtsp_url(cam):
    host = cam.get("host", "")
    port = cam.get("port", 554)
    username = cam.get("username", "")
    password = cam.get("password", "")
    path = cam.get("path", "/")
    auth = f"{username}:{password}@" if username and password else ""
    return f"rtsp://{auth}{host}:{port}{path}"

def _is_valid_plate(text):
    return bool(_PLATE_RE.match(text.upper().replace("-", "").strip()))


def _check_dedup(plate_text, cam_id):
    now = time.time()
    key = (plate_text, cam_id)
    window = cfg.get_int("dedup_seconds", 60)
    with _seen_lock:
        last = _seen.get(key)
        if last is not None and now - last < window:
            return False
        _seen[key] = now
        return True


def _cleanup_stale():
    now = time.time()
    window = cfg.get_int("dedup_seconds", 60)
    cutoff = now - window * 2
    with _seen_lock:
        stale = [k for k, t in _seen.items() if t < cutoff]
        for k in stale:
            del _seen[k]
    if stale:
        app.logger.debug("Purged %d stale dedup entries", len(stale))


def _rtsp_capture_loop(cam_id, cam_config):
    reconnect_delay = 3.0
    while True:
        try:
            url = _build_rtsp_url(cam_config)
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                app.logger.warning("RTSP %s: cannot open, retry in %.0fs", cam_id, reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, 30.0)
                continue
            reconnect_delay = 3.0
            app.logger.info("RTSP %s: connected", cam_id)

            with _RTSP_CAMERAS_LOCK:
                _RTSP_CAMERAS[cam_id] = cap

            while True:
                ret, frame = cap.read()
                if not ret:
                    app.logger.warning("RTSP %s: read failed, reconnecting", cam_id)
                    break

                results = alpr.predict(frame)
                min_conf = cfg.get_float("confidence_threshold", 0.0)

                for result in results:
                    if result.ocr is None:
                        continue
                    text = result.ocr.text
                    conf = result.ocr.confidence
                    if isinstance(conf, list):
                        conf = sum(conf) / len(conf) if conf else 0.0
                    if conf < min_conf:
                        continue
                    if not _is_valid_plate(text):
                        continue

                    _, jpeg_buf = cv2.imencode(".jpg", frame)
                    image_bytes = jpeg_buf.tobytes()

                    if not _check_dedup(text, cam_id):
                        continue

                    session = database.get_session()
                    try:
                        det = database.Detection(
                            plate_text=text,
                            confidence=round(conf, 4),
                            camera_id=cam_id,
                            camera_name=cam_config.get("name", cam_id),
                            image=image_bytes,
                        )
                        session.add(det)
                        session.commit()
                        app.logger.info("RTSP saved %s from %s", text, cam_id)

                        global _save_counter
                        _save_counter += 1
                        cleanup_every = cfg.get_int("cleanup_interval", 20)
                        if _save_counter % cleanup_every == 0:
                            _cleanup_stale()
                    except Exception as e:
                        app.logger.error("RTSP DB error: %s", e)
                        session.rollback()
                    finally:
                        session.close()

                time.sleep(1.0)
        except Exception as e:
            app.logger.error("RTSP %s: unexpected error: %s", cam_id, e, exc_info=True)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, 30.0)
        finally:
            with _RTSP_CAMERAS_LOCK:
                cap = _RTSP_CAMERAS.pop(cam_id, None)
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass


_RTSP_THREADS = {}

def _start_rtsp_threads():
    try:
        raw = cfg.get("rtsp_cameras", "[]")
        cameras = json.loads(raw)
        for cam in cameras:
            cam_id = f"rtsp:{cam['host']}:{cam['port']}"
            t = _RTSP_THREADS.get(cam_id)
            if t is not None and t.is_alive():
                continue
            t = threading.Thread(
                target=_rtsp_capture_loop,
                args=(cam_id, cam),
                name=cam_id,
                daemon=True,
            )
            t.start()
            _RTSP_THREADS[cam_id] = t
            app.logger.info("Started RTSP thread for %s", cam_id)
    except Exception as e:
        app.logger.error("Failed to start RTSP threads: %s", e)


@app.before_request
def _seed_config():
    if not getattr(app, "_config_seeded", False):
        try:
            session = database.get_session()
            cfg.seed(session)
            session.close()
            cfg.reload()
            _start_rtsp_threads()
        except Exception:
            pass
        app._config_seeded = True


# Bootstrap on startup: seed config, reload cache, start RTSP threads.
# This runs at module load time so RTSP capture begins without waiting
# for the first HTTP request.
_seed_config()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/detect", methods=["POST"])
def detect():
    global _save_counter

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
        if not _check_dedup(d["plate_text"], cam_id):
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

    _save_counter += 1
    window = cfg.get_int("dedup_seconds", 60)
    cleanup_every = cfg.get_int("cleanup_interval", 20)
    if _save_counter % cleanup_every == 0:
        _cleanup_stale()

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
    if key == "rtsp_cameras":
        _start_rtsp_threads()
    return jsonify({"key": key, "value": new_value})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
