import logging
import threading
import time

import cv2

from webapp import config as cfg
from webapp import database
from webapp import dedup
from webapp.plate import _is_valid_plate

logger = logging.getLogger(__name__)

_RTSP_CAMERAS = {}
_RTSP_CAMERAS_LOCK = threading.Lock()
_RTSP_THREADS = {}


def _build_rtsp_url(cam):
    host = cam.get("host", "")
    port = cam.get("port", 554)
    username = cam.get("username", "")
    password = cam.get("password", "")
    path = cam.get("path", "/")
    auth = f"{username}:{password}@" if username and password else ""
    return f"rtsp://{auth}{host}:{port}{path}"


def _rtsp_capture_loop(cam_id, cam_config):
    from webapp.webapp import alpr

    reconnect_delay = 3.0
    while True:
        try:
            url = _build_rtsp_url(cam_config)
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                logger.warning("RTSP %s: cannot open, retry in %.0fs", cam_id, reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, 30.0)
                continue
            reconnect_delay = 3.0
            logger.info("RTSP %s: connected", cam_id)

            with _RTSP_CAMERAS_LOCK:
                _RTSP_CAMERAS[cam_id] = cap

            while True:
                ret, frame = cap.read()
                if not ret:
                    logger.warning("RTSP %s: read failed, reconnecting", cam_id)
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

                    if not dedup._check_dedup(text, cam_id):
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
                        logger.info("RTSP saved %s from %s", text, cam_id)

                        dedup._save_counter += 1
                        cleanup_every = cfg.get_int("cleanup_interval", 20)
                        if dedup._save_counter % cleanup_every == 0:
                            dedup._cleanup_stale()
                    except Exception as e:
                        logger.error("RTSP DB error: %s", e)
                        session.rollback()
                    finally:
                        session.close()

                time.sleep(1.0)
        except Exception as e:
            logger.error("RTSP %s: unexpected error: %s", cam_id, e, exc_info=True)
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


def _stop_orphan_threads(active_ids):
    for cam_id in list(_RTSP_THREADS):
        if cam_id not in active_ids:
            t = _RTSP_THREADS.pop(cam_id, None)
            if t is not None:
                logger.info("Removed orphan RTSP thread reference for %s", cam_id)
            with _RTSP_CAMERAS_LOCK:
                cap = _RTSP_CAMERAS.pop(cam_id, None)
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass


def _start_rtsp_threads():
    try:
        session = database.get_session()
        cameras = session.query(database.RtspCamera).filter_by(enabled=True).all()
        session.close()

        active_ids = set()
        for cam in cameras:
            cam_id = f"rtsp:{cam.id}"
            active_ids.add(cam_id)

            t = _RTSP_THREADS.get(cam_id)
            if t is not None and t.is_alive():
                continue

            cam_dict = {
                "host": cam.host,
                "port": cam.port,
                "username": cam.username or "",
                "password": cam.password or "",
                "path": cam.path or "/",
                "name": cam.name or "",
            }
            t = threading.Thread(
                target=_rtsp_capture_loop,
                args=(cam_id, cam_dict),
                name=cam_id,
                daemon=True,
            )
            t.start()
            _RTSP_THREADS[cam_id] = t
            logger.info("Started RTSP thread for rtsp:%s (host=%s)", cam.id, cam.host)

        _stop_orphan_threads(active_ids)
    except Exception as e:
        logger.error("Failed to start RTSP threads: %s", e)
