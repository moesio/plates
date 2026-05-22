import logging
import threading
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request
from fast_alpr import ALPR

sys.path.insert(0, str(Path(__file__).resolve().parent))
import database

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
alpr = ALPR()

DEDUP_SECONDS = 60
CLEANUP_INTERVAL = 20

_seen = {}
_seen_lock = threading.Lock()
_save_counter = 0


def _check_dedup(plate_text, cam_id):
    now = time.time()
    key = (plate_text, cam_id)
    with _seen_lock:
        last = _seen.get(key)
        if last is not None and now - last < DEDUP_SECONDS:
            return False
        _seen[key] = now
        return True


def _cleanup_stale():
    now = time.time()
    cutoff = now - DEDUP_SECONDS * 2
    with _seen_lock:
        stale = [k for k, t in _seen.items() if t < cutoff]
        for k in stale:
            del _seen[k]
    if stale:
        app.logger.debug("Purged %d stale dedup entries", len(stale))


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

    for result in results:
        if result.ocr is None:
            continue
        bbox = result.detection.bounding_box
        text = result.ocr.text
        conf = result.ocr.confidence
        if isinstance(conf, list):
            conf = sum(conf) / len(conf) if conf else 0.0

        detections.append({
            "plate_text": text,
            "confidence": round(conf, 4),
            "x1": bbox.x1,
            "y1": bbox.y1,
            "x2": bbox.x2,
            "y2": bbox.y2,
        })

    cam_id = request.headers.get("X-Camera-Id", "0")
    cam_name_raw = request.headers.get("X-Camera-Name", "Browser Camera")
    cam_name = unquote(cam_name_raw)

    app.logger.info("Detected %d plate(s), image size: %d bytes", len(detections), len(image_bytes))

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
    if _save_counter % CLEANUP_INTERVAL == 0:
        _cleanup_stale()

    app.logger.info("Plates: %d saved, %d skipped (dedup window: %ds)", saved, skipped, DEDUP_SECONDS)

    return jsonify(detections)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
