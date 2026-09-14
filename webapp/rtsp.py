import dataclasses
import logging
import os
import threading
import time

import cv2
import numpy as np

from webapp.detection import _process_alpr_results

logger = logging.getLogger(__name__)

_DEBUG_DIR = os.getenv(
    "RTSP_DEBUG_DIR",
    os.path.join(os.path.dirname(__file__), "..", "debug"),
)
_SAVE_INTERVAL = int(os.getenv("RTSP_DEBUG_SAVE_INTERVAL", "30"))
_JPEG_QUALITY = int(os.getenv("RTSP_JPEG_QUALITY", "70"))
_RECONNECT_DELAY_INITIAL = float(os.getenv("RTSP_RECONNECT_DELAY", "3.0"))
_RECONNECT_BACKOFF = float(os.getenv("RTSP_RECONNECT_BACKOFF", "1.5"))
_RECONNECT_DELAY_MAX = float(os.getenv("RTSP_RECONNECT_DELAY_MAX", "30.0"))
_DETECT_INTERVAL = float(os.getenv("RTSP_DETECT_INTERVAL", os.getenv("RTSP_FRAME_SLEEP", "1.0")))
_CAPTURE_FRAME_SLEEP = float(os.getenv("RTSP_CAPTURE_FRAME_SLEEP", "0.05"))
_POLL_INTERVAL = float(os.getenv("RTSP_POLL_INTERVAL", "0.10"))
_STREAM_TIMEOUT = float(os.getenv("RTSP_STREAM_TIMEOUT", "10.0"))
_RTSP_TRANSPORT = os.getenv("RTSP_TRANSPORT", "tcp").lower()
_DETECT_TILE_UPSCALE = float(os.getenv("RTSP_DETECT_TILE_UPSCALE", "2.0"))
_frame_counters = {}

_RTSP_CAMERAS = {}
_RTSP_CAMERAS_LOCK = threading.Lock()
_RTSP_THREADS = {}

_RTSP_LATEST = {}
_RTSP_LATEST_LOCK = threading.Lock()
_RTSP_FRAME_EVENTS = {}

_RTSP_DETECT_FRAMES = {}
_RTSP_DETECT_LOCK = threading.Lock()
_RTSP_DETECT_EVENTS = {}

_RTSP_STOP_EVENTS = {}
_RTSP_STOP_LOCK = threading.Lock()


def _build_rtsp_url(cam):
    host = cam.get("host", "")
    port = cam.get("port", 554)
    username = cam.get("username", "")
    password = cam.get("password", "")
    path = cam.get("path", "/")
    auth = f"{username}:{password}@" if username and password else ""
    url = f"rtsp://{auth}{host}:{port}{path}"
    transport = (cam.get("transport") or _RTSP_TRANSPORT).lower()
    if transport:
        sep = "&" if "?" in path else "?"
        url += f"{sep}{transport}"
    return url


def _parse_grid(grid):
    """Parse a 'WxH' tile grid config; returns (cols, rows) or None."""
    if not grid:
        return None
    parts = str(grid).strip().lower().split("x")
    if len(parts) != 2:
        return None
    try:
        cols, rows = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if cols < 1 or rows < 1:
        return None
    return cols, rows


def _predict_frame(alpr, frame, cam_config):
    """Run plate detection, optionally tiling the frame for small/ distant plates.

    Returns the list of ALPR results with bounding boxes mapped back to
    full-frame coordinates.
    """
    grid = _parse_grid(cam_config.get("detect_grid"))
    h, w = frame.shape[:2]
    if grid is None or grid == (1, 1) or h < grid[1] or w < grid[0]:
        return alpr.predict(frame)
    cols, rows = grid
    tw, th = w // cols, h // rows
    results = []
    for r in range(rows):
        for c in range(cols):
            tile = frame[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
            if _DETECT_TILE_UPSCALE != 1.0:
                tile = cv2.resize(
                    tile, None,
                    fx=_DETECT_TILE_UPSCALE, fy=_DETECT_TILE_UPSCALE,
                    interpolation=cv2.INTER_CUBIC,
                )
            try:
                tile_results = alpr.predict(tile)
            except Exception:
                continue
            for res in tile_results:
                bb = getattr(getattr(res, "detection", None), "bounding_box", None)
                if bb is None:
                    continue
                new_bb = dataclasses.replace(
                    bb,
                    x1=bb.x1 / _DETECT_TILE_UPSCALE + c * tw,
                    y1=bb.y1 / _DETECT_TILE_UPSCALE + r * th,
                    x2=bb.x2 / _DETECT_TILE_UPSCALE + c * tw,
                    y2=bb.y2 / _DETECT_TILE_UPSCALE + r * th,
                )
                new_det = dataclasses.replace(res.detection, bounding_box=new_bb)
                results.append(dataclasses.replace(res, detection=new_det))
    return results


def _set_latest_frame(cam_id, jpeg):
    with _RTSP_LATEST_LOCK:
        _RTSP_LATEST[cam_id] = jpeg
        ev = _RTSP_FRAME_EVENTS.get(cam_id)
    if ev is not None:
        ev.set()


def _clear_latest_frame(cam_id):
    with _RTSP_LATEST_LOCK:
        _RTSP_LATEST.pop(cam_id, None)
        ev = _RTSP_FRAME_EVENTS.pop(cam_id, None)
    if ev is not None:
        ev.set()


def get_latest_frame(cam_id):
    with _RTSP_LATEST_LOCK:
        return _RTSP_LATEST.get(cam_id)


def wait_for_frame(cam_id, timeout=1.0):
    """Block until a new frame is signaled for cam_id, then return it (or None)."""
    with _RTSP_LATEST_LOCK:
        ev = _RTSP_FRAME_EVENTS.get(cam_id)
        if ev is None:
            ev = threading.Event()
            _RTSP_FRAME_EVENTS[cam_id] = ev
        ev.clear()
    ev.wait(timeout)
    with _RTSP_LATEST_LOCK:
        return _RTSP_LATEST.get(cam_id)


def stream_frames(cam_id, timeout=None):
    """Yield MJPEG parts for new frames of cam_id until none arrive for `timeout`."""
    if timeout is None:
        timeout = _STREAM_TIMEOUT
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    sent = None
    idle_since = time.time()
    while True:
        jpeg = get_latest_frame(cam_id)
        if jpeg is not None and jpeg != sent:
            idle_since = time.time()
            yield boundary + jpeg + b"\r\n"
            sent = jpeg
            continue
        if time.time() - idle_since > timeout:
            break
        time.sleep(_POLL_INTERVAL)


def _set_detect_frame(cam_id, jpeg):
    with _RTSP_DETECT_LOCK:
        _RTSP_DETECT_FRAMES[cam_id] = jpeg
        ev = _RTSP_DETECT_EVENTS.get(cam_id)
    if ev is not None:
        ev.set()


def _clear_detect_frame(cam_id):
    with _RTSP_DETECT_LOCK:
        _RTSP_DETECT_FRAMES.pop(cam_id, None)
        ev = _RTSP_DETECT_EVENTS.pop(cam_id, None)
    if ev is not None:
        ev.set()


def _get_detect_frame(cam_id):
    with _RTSP_DETECT_LOCK:
        return _RTSP_DETECT_FRAMES.get(cam_id)


def _make_stop_event(cam_id):
    with _RTSP_STOP_LOCK:
        ev = _RTSP_STOP_EVENTS.get(cam_id)
        if ev is None:
            ev = threading.Event()
            _RTSP_STOP_EVENTS[cam_id] = ev
        return ev


def _rtsp_capture_loop(cam_id, cam_config):
    stop = _make_stop_event(cam_id)
    reconnect_delay = _RECONNECT_DELAY_INITIAL
    cap = None
    while not stop.is_set():
        try:
            url = _build_rtsp_url(cam_config)
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                logger.warning("RTSP %s: cannot open, retry in %.0fs", cam_id, reconnect_delay)
                stop.wait(reconnect_delay)
                reconnect_delay = min(reconnect_delay * _RECONNECT_BACKOFF, _RECONNECT_DELAY_MAX)
                continue
            reconnect_delay = _RECONNECT_DELAY_INITIAL
            logger.info("RTSP %s: connected", cam_id)

            with _RTSP_CAMERAS_LOCK:
                _RTSP_CAMERAS[cam_id] = cap

            while not stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    logger.warning("RTSP %s: read failed, reconnecting", cam_id)
                    break

                success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
                if not success:
                    continue

                image_bytes = buffer.tobytes()
                _set_latest_frame(cam_id, image_bytes)
                _set_detect_frame(cam_id, image_bytes)
                if _CAPTURE_FRAME_SLEEP > 0:
                    stop.wait(_CAPTURE_FRAME_SLEEP)
        except Exception as e:
            logger.error("RTSP %s: unexpected error: %s", cam_id, e, exc_info=True)
            reconnect_delay = min(reconnect_delay * _RECONNECT_BACKOFF, _RECONNECT_DELAY_MAX)
            stop.wait(reconnect_delay)
        finally:
            _clear_latest_frame(cam_id)
            _clear_detect_frame(cam_id)
            with _RTSP_CAMERAS_LOCK:
                cap = _RTSP_CAMERAS.pop(cam_id, None)
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass


def _rtsp_detection_loop(cam_id, cam_config):
    from webapp.alpr import alpr

    stop = _make_stop_event(cam_id)
    last_processed = None
    last_time = 0.0
    while not stop.is_set():
        jpeg = _get_detect_frame(cam_id)
        now = time.time()
        if jpeg is not None and jpeg is not last_processed and now - last_time >= _DETECT_INTERVAL:
            last_processed = jpeg
            last_time = now
            np_arr = np.frombuffer(jpeg, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            results = _predict_frame(alpr, frame, cam_config)
            logger.info("RTSP %s: alpr.predict returned %d result(s)", cam_id, len(results))

            if logger.getEffectiveLevel() == logging.DEBUG:
                if len(results) == 0:
                    _frame_counters[cam_id] = _frame_counters.get(cam_id, 0) + 1
                    if _frame_counters[cam_id] % _SAVE_INTERVAL == 1:
                        os.makedirs(_DEBUG_DIR, exist_ok=True)
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        path = os.path.join(_DEBUG_DIR, f"rtsp_{cam_id}_{ts}.jpg")
                        cv2.imwrite(path, frame)
                        logger.info("RTSP %s: saved debug frame to %s", cam_id, path)

            _process_alpr_results(results, frame, cam_id, cam_config.get("name", cam_id), include_bbox=True)
        stop.wait(_DETECT_INTERVAL if jpeg is None else min(_DETECT_INTERVAL, 0.1))


def _stop_all_rtsp_threads():
    with _RTSP_STOP_LOCK:
        stops = dict(_RTSP_STOP_EVENTS)
        _RTSP_STOP_EVENTS.clear()
    for ev in stops.values():
        ev.set()
    for cam_id in list(_RTSP_THREADS):
        _RTSP_THREADS.pop(cam_id, None)
        _clear_latest_frame(cam_id)
        _clear_detect_frame(cam_id)
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
                "detect_grid": getattr(cam, "detect_grid", None) or "1x1",
            }
            capture = threading.Thread(
                target=_rtsp_capture_loop,
                args=(cam_id, cam_dict),
                name=f"{cam_id}:capture",
                daemon=True,
            )
            detect = None
            if getattr(cam, "detect_enabled", True) is not False:
                detect = threading.Thread(
                    target=_rtsp_detection_loop,
                    args=(cam_id, cam_dict),
                    name=f"{cam_id}:detect",
                    daemon=True,
                )
            capture.start()
            if detect is not None:
                detect.start()
            _RTSP_THREADS[cam_id] = (capture, detect)
            logger.info("Started RTSP threads for rtsp:%s (host=%s)", cam.id, cam.host)
    except Exception as e:
        logger.error("Failed to start RTSP threads: %s", e)
