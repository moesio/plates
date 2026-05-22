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
alpr = ALPR()

DEDUP_SECONDS = 60


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/detect", methods=["POST"])
def detect():
    image_bytes = request.get_data()
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
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

    for d in detections:
        try:
            session = database.get_session()
            det = database.Detection(
                plate_text=d["plate_text"],
                confidence=d["confidence"],
                camera_id=int(cam_id),
                camera_name=cam_name,
            )
            session.add(det)
            session.commit()
        except Exception as e:
            print(f"DB error: {e}")
        finally:
            session.close()

    return jsonify(detections)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
