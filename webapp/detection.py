import logging

import cv2

from webapp import config as cfg
from webapp import database
from webapp import dedup
from webapp.plate import _is_valid_plate

logger = logging.getLogger(__name__)

_CONFIDENCE_PRECISION = 4


def _process_alpr_results(results, frame, cam_id, cam_name, include_bbox=False):
    min_conf = cfg.get_float("confidence_threshold", 0.0)
    valid = []

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

        entry = {"plate_text": text, "confidence": round(conf, _CONFIDENCE_PRECISION)}
        if include_bbox:
            bbox = result.detection.bounding_box
            entry.update({
                "x1": bbox.x1,
                "y1": bbox.y1,
                "x2": bbox.x2,
                "y2": bbox.y2,
            })
        valid.append(entry)

    if not valid:
        return []

    _, jpeg_buf = cv2.imencode(".jpg", frame)
    image_bytes = jpeg_buf.tobytes()

    for d in valid:
        if not dedup._check_dedup(d["plate_text"], cam_id):
            continue

        session = database.get_session()
        try:
            det = database.Detection(
                plate_text=d["plate_text"],
                confidence=d["confidence"],
                camera_id=cam_id,
                camera_name=cam_name,
                image=image_bytes,
            )
            session.add(det)
            session.commit()
            logger.info("Saved plate %s from %s", d["plate_text"], cam_id)

            dedup._save_counter += 1
            cleanup_every = cfg.get_int("cleanup_interval", 20)
            if dedup._save_counter % cleanup_every == 0:
                dedup._cleanup_stale()
        except Exception as e:
            logger.error("DB error saving %s: %s", d["plate_text"], e)
            session.rollback()
        finally:
            session.close()

    return valid
