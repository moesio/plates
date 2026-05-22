import re
import sys
import time
from pathlib import Path

import cv2
from flask import Flask, jsonify, render_template, Response
from fast_alpr import ALPR

sys.path.insert(0, str(Path(__file__).resolve().parent))
import database

app = Flask(__name__)
alpr = ALPR()

FRAME_DELAY = 0.03
V4L_BASE = Path("/sys/class/video4linux")
DEDUP_SECONDS = 60


def get_camera_name(index):
    name_path = V4L_BASE / f"video{index}" / "name"
    if name_path.exists():
        return name_path.read_text().strip()
    return f"Câmera {index}"


def list_cameras():
    available = []

    indices = set()
    for dev in Path("/dev").glob("video*"):
        m = re.match(r"video(\d+)", dev.name)
        if m:
            indices.add(int(m.group(1)))

    for i in sorted(indices):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret is not None and ret:
                name = get_camera_name(i)
                available.append({
                    "id": i,
                    "label": name,
                    "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    "virtual": "virtual" in name.lower(),
                })
            cap.release()
    return available


def generate_frames(camera_id):
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        return

    cam_name = get_camera_name(camera_id)
    last_logged = {}

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = alpr.predict(frame)
            for result in results:
                if result.ocr is None:
                    continue
                bbox = result.detection.bounding_box
                x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
                text = result.ocr.text
                conf = result.ocr.confidence
                if isinstance(conf, list):
                    conf = sum(conf) / len(conf) if conf else 0.0

                cv2.rectangle(
                    frame, (x1, y1), (x2, y2), (0, 255, 0), 2
                )
                label = f"{text} ({conf:.2f})" if conf else text
                cv2.putText(
                    frame, label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
                )

                now = time.time()
                if text not in last_logged or now - last_logged[text] > DEDUP_SECONDS:
                    last_logged[text] = now
                    try:
                        session = database.get_session()
                        det = database.Detection(
                            plate_text=text,
                            confidence=round(conf, 4),
                            camera_id=camera_id,
                            camera_name=cam_name,
                        )
                        session.add(det)
                        session.commit()
                        print(f"Saved: {text} ({conf:.2f})")
                    except Exception as e:
                        print(f"DB error: {e}")
                    finally:
                        session.close()

            ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ret:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
            )
            time.sleep(FRAME_DELAY)
    finally:
        cap.release()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/cameras")
def cameras():
    return jsonify(list_cameras())


@app.route("/video/<int:camera_id>")
def video(camera_id):
    return Response(
        generate_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
