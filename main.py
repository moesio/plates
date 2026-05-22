import csv
import time
from pathlib import Path

import cv2
import numpy as np
from fast_alpr import ALPR

# --- CONFIG ---
CAMERA_INDEX = 10
PROCESS_WIDTH = 640
ANGLES = [-5, 0, 5]
CONFIRM_FRAMES = 3
CONF_THRESHOLD = 0.5
PROCESS_EVERY_N = 3
ROI_MARGIN = 0.10
CSV_PATH = "plate_log.csv"

alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v1-global-model",
)

cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

tracks = {}
confirmed = set()
frame_count = 0
proc_frame_count = 0

csv_file = open(CSV_PATH, "a", newline="")
csv_writer = csv.writer(csv_file)
if not Path(CSV_PATH).exists() or Path(CSV_PATH).stat().st_size == 0:
    csv_writer.writerow(["timestamp", "plate", "confidence"])


def rotate_image(image, angle):
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, matrix


def inverse_rotate_bbox(x1, y1, x2, y2, matrix):
    inv = cv2.invertAffineTransform(matrix)
    a, b, c = inv[0, 0], inv[0, 1], inv[0, 2]
    d, e, f = inv[1, 0], inv[1, 1], inv[1, 2]

    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    xs, ys = [], []
    for px, py in corners:
        xs.append(a * px + b * py + c)
        ys.append(d * px + e * py + f)

    return min(xs), min(ys), max(xs), max(ys)


def enhance(image):
    kernel = np.array([
        [0, -1, 0],
        [-1, 5, -1],
        [0, -1, 0]
    ])
    return cv2.filter2D(image, -1, kernel)


def compute_iou(box_a, box_b):
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / (union + 1e-6)


def is_in_roi(x1, y1, x2, y2, frame_w, frame_h):
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    roi_x1 = frame_w * ROI_MARGIN
    roi_y1 = frame_h * ROI_MARGIN
    roi_x2 = frame_w * (1 - ROI_MARGIN)
    roi_y2 = frame_h * (1 - ROI_MARGIN)
    return roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2


def update_tracks(detections, proc_count):
    global tracks, confirmed
    iou_threshold = 0.3

    for t in tracks.values():
        t["matched"] = False

    for det_plate, det_box, det_conf in detections:
        best_track = None
        best_iou = iou_threshold

        for text, t in tracks.items():
            if text == det_plate:
                iou = compute_iou(det_box, t["box"])
                if iou > best_iou:
                    best_iou = iou
                    best_track = text

        if best_track is not None:
            t = tracks[best_track]
            t["box"] = det_box
            t["conf_sum"] += det_conf
            t["count"] += 1
            t["last_seen"] = proc_count
            t["matched"] = True

            if t["count"] >= CONFIRM_FRAMES and best_track not in confirmed:
                confirmed.add(best_track)
                avg_conf = t["conf_sum"] / t["count"]
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                csv_writer.writerow([ts, best_track, f"{avg_conf:.3f}"])
                csv_file.flush()
                print(f"CONFIRMED: {best_track}")
        else:
            tracks[det_plate] = {
                "box": det_box,
                "count": 1,
                "conf_sum": det_conf,
                "first_seen": proc_count,
                "last_seen": proc_count,
                "matched": True,
            }

    stale = [text for text, t in tracks.items()
             if not t["matched"] or proc_count - t["last_seen"] > 10]
    for text in stale:
        confirmed.discard(text)
        del tracks[text]


def process_frame(frame):
    h_disp, w_disp = frame.shape[:2]
    scale = PROCESS_WIDTH / w_disp
    proc_h = int(h_disp * scale)
    proc = cv2.resize(frame, (PROCESS_WIDTH, proc_h))
    proc = enhance(proc)

    frame_detections = {}

    for angle in ANGLES:
        rotated, rot_matrix = rotate_image(proc, angle)
        try:
            alpr_results = alpr.predict(rotated)
        except Exception as e:
            print(f"ALPR error: {e}")
            continue

        for result in alpr_results:
            if result.ocr is None or not result.ocr.text:
                continue

            bbox = result.detection.bounding_box
            ox1, oy1, ox2, oy2 = inverse_rotate_bbox(
                bbox.x1, bbox.y1, bbox.x2, bbox.y2, rot_matrix
            )

            inv_scale = w_disp / PROCESS_WIDTH
            dx1 = max(0, int(ox1 * inv_scale))
            dy1 = max(0, int(oy1 * inv_scale))
            dx2 = min(w_disp, int(ox2 * inv_scale))
            dy2 = min(h_disp, int(oy2 * inv_scale))

            if not is_in_roi(dx1, dy1, dx2, dy2, w_disp, h_disp):
                continue

            text = result.ocr.text.strip()
            conf = result.ocr.confidence
            if isinstance(conf, list):
                conf = sum(conf) / len(conf)
            if conf < CONF_THRESHOLD:
                continue

            if text not in frame_detections or conf > frame_detections[text][2]:
                frame_detections[text] = (text, (dx1, dy1, dx2, dy2), conf)

    return list(frame_detections.values())


while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    h_disp, w_disp = frame.shape[:2]

    rx1 = int(w_disp * ROI_MARGIN)
    ry1 = int(h_disp * ROI_MARGIN)
    rx2 = int(w_disp * (1 - ROI_MARGIN))
    ry2 = int(h_disp * (1 - ROI_MARGIN))
    cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (255, 255, 0), 1)

    if frame_count % PROCESS_EVERY_N == 0:
        proc_frame_count += 1
        detections = process_frame(frame)
        update_tracks(detections, proc_frame_count)

    for text, t in tracks.items():
        x1, y1, x2, y2 = t["box"]
        if text in confirmed:
            avg_conf = t["conf_sum"] / t["count"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame, f"{text} ({avg_conf:.2f})", (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
            )
        else:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 1)

    cv2.putText(
        frame, f"Confirmed: {len(confirmed)} | Tracking: {len(tracks)}",
        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )

    cv2.imshow("ALPR", frame)
    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()
csv_file.close()
