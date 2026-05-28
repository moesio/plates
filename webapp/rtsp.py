import logging
import threading
import time

import cv2

from webapp.detection import _process_alpr_results

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
                _process_alpr_results(
                    results, frame, cam_id, cam_config.get("name", cam_id),
                )
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


def _stop_all_rtsp_threads():
    for cam_id in list(_RTSP_THREADS):
        _RTSP_THREADS.pop(cam_id, None)
        with _RTSP_CAMERAS_LOCK:
            cap = _RTSP_CAMERAS.pop(cam_id, None)
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass


def _start_rtsp_threads(cameras):
    try:
        _stop_all_rtsp_threads()

        for cam in cameras:
            cam_id = f"rtsp:{cam.id}"
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
    except Exception as e:
        logger.error("Failed to start RTSP threads: %s", e)
