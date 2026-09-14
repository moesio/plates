import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def reset_rtsp_state():
    from webapp import rtsp

    rtsp._stop_all_rtsp_threads()
    rtsp._RTSP_LATEST.clear()
    rtsp._RTSP_FRAME_EVENTS.clear()
    rtsp._RTSP_DETECT_FRAMES.clear()
    rtsp._RTSP_DETECT_EVENTS.clear()
    yield
    rtsp._stop_all_rtsp_threads()
    rtsp._RTSP_LATEST.clear()
    rtsp._RTSP_FRAME_EVENTS.clear()
    rtsp._RTSP_DETECT_FRAMES.clear()
    rtsp._RTSP_DETECT_EVENTS.clear()


class TestBuildRtspUrl:
    def test_basic_host_port(self):
        from webapp.rtsp import _build_rtsp_url

        url = _build_rtsp_url({"host": "192.168.1.100", "port": 8080})
        assert url == "rtsp://192.168.1.100:8080/"

    def test_with_auth(self):
        from webapp.rtsp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "10.0.0.50",
            "port": 554,
            "username": "admin",
            "password": "secret",
        })
        assert url == "rtsp://admin:secret@10.0.0.50:554/"

    def test_with_path(self):
        from webapp.rtsp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "192.168.1.100",
            "port": 554,
            "path": "/Streaming/Channels/101",
        })
        assert url == "rtsp://192.168.1.100:554/Streaming/Channels/101"

    def test_without_username_skips_auth(self):
        from webapp.rtsp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "192.168.1.100",
            "port": 8080,
            "password": "secret",
        })
        assert url == "rtsp://192.168.1.100:8080/"

    def test_default_port(self):
        from webapp.rtsp import _build_rtsp_url

        url = _build_rtsp_url({"host": "10.0.0.1"})
        assert url == "rtsp://10.0.0.1:554/"


class TestStartRtspThreads:
    def test_empty_config_does_nothing(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp

        rtsp._RTSP_THREADS.clear()
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        rtsp._start_rtsp_threads([])

    def test_starts_thread(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp
        from webapp.database import RtspCamera

        mock_thread = mocker.patch.object(rtsp.threading, "Thread")
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        cam = RtspCamera(id=1, host="10.0.0.1", port=554)
        rtsp._start_rtsp_threads([cam])

        assert mock_thread.call_count == 2
        for call in mock_thread.call_args_list:
            kwargs = call.kwargs
            assert kwargs["daemon"] is True
            assert kwargs["name"].startswith("rtsp:1")

    def test_starts_thread_with_full_config(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp
        from webapp.database import RtspCamera

        mock_thread = mocker.patch.object(rtsp.threading, "Thread")
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        cam = RtspCamera(id=2, host="10.0.0.2", port=8080, username="admin",
                         password="secret", path="/live", name="Garagem")
        rtsp._start_rtsp_threads([cam])

        calls = mock_thread.call_args_list
        assert len(calls) == 2
        for call in calls:
            assert call.kwargs["name"].startswith("rtsp:2")
        cam_dict = calls[0].kwargs["args"][1]
        assert cam_dict["host"] == "10.0.0.2"
        assert cam_dict["port"] == 8080
        assert cam_dict["username"] == "admin"
        assert cam_dict["password"] == "secret"
        assert cam_dict["path"] == "/live"
        assert cam_dict["name"] == "Garagem"

    def test_skips_disabled_cameras(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp

        rtsp._RTSP_THREADS.clear()
        mock_thread = mocker.patch.object(rtsp.threading, "Thread")
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        rtsp._start_rtsp_threads([])

        mock_thread.assert_not_called()

    def test_orphan_thread_removed(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp
        from webapp.database import RtspCamera

        mock_orphan = MagicMock()
        mock_orphan.is_alive.return_value = True
        rtsp._RTSP_THREADS["rtsp:99"] = mock_orphan
        rtsp._RTSP_CAMERAS["rtsp:99"] = MagicMock()

        mock_thread = mocker.patch.object(rtsp.threading, "Thread")
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        cam = RtspCamera(id=1, host="10.0.0.1", port=554)
        rtsp._start_rtsp_threads([cam])

        assert "rtsp:99" not in rtsp._RTSP_THREADS
        assert "rtsp:99" not in rtsp._RTSP_CAMERAS

    def test_restarts_threads(self, mocker):
        import webapp.config as cfg
        from webapp import rtsp
        from webapp.database import RtspCamera

        mock_thread = mocker.patch.object(rtsp.threading, "Thread")
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        cam = RtspCamera(id=1, host="10.0.0.1", port=554)
        rtsp._start_rtsp_threads([cam])
        rtsp._start_rtsp_threads([cam])

        assert mock_thread.call_count == 4

    def test_bad_db_does_not_crash(self):
        from webapp import rtsp
        import webapp.config as cfg

        rtsp._RTSP_THREADS.clear()
        cfg._CACHE["confidence_threshold"] = ("0.0", "")
        rtsp._start_rtsp_threads([])


class TestLatestFrame:
    def _clear_state(self):
        from webapp.rtsp import _RTSP_FRAME_EVENTS, _RTSP_LATEST

        _RTSP_LATEST.clear()
        _RTSP_FRAME_EVENTS.clear()

    def test_set_and_get_latest_frame(self):
        from webapp.rtsp import _set_latest_frame, get_latest_frame

        self._clear_state()
        _set_latest_frame("rtsp:1", b"jpegdata")
        assert get_latest_frame("rtsp:1") == b"jpegdata"

    def test_clear_latest_frame(self):
        from webapp.rtsp import _clear_latest_frame, _set_latest_frame, get_latest_frame

        self._clear_state()
        _set_latest_frame("rtsp:1", b"jpegdata")
        _clear_latest_frame("rtsp:1")
        assert get_latest_frame("rtsp:1") is None

    def test_wait_for_frame_returns_pending_frame(self):
        from webapp.rtsp import _set_latest_frame, wait_for_frame

        self._clear_state()
        _set_latest_frame("rtsp:1", b"jpegdata")
        assert wait_for_frame("rtsp:1", timeout=0.2) == b"jpegdata"

    def test_wait_for_frame_blocks_until_new_frame(self):
        from threading import Thread

        import webapp.rtsp as rtsp

        self._clear_state()
        results = []

        def waiter():
            results.append(rtsp.wait_for_frame("rtsp:1", timeout=1.0))

        t = Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        rtsp._set_latest_frame("rtsp:1", b"later")
        t.join(timeout=2.0)
        assert results == [b"later"]

    def test_stream_frames_yields_latest_jpeg(self):
        from webapp.rtsp import _set_latest_frame, stream_frames

        self._clear_state()
        _set_latest_frame("rtsp:1", b"\xff\xd8jpegdata")
        gen = stream_frames("rtsp:1", timeout=0.5)
        first = next(gen)
        assert b"\xff\xd8jpegdata" in first
        gen.close()

    def test_stream_frames_ends_when_offline(self):
        import webapp.rtsp as rtsp

        self._clear_state()
        old_poll = rtsp._POLL_INTERVAL
        rtsp._POLL_INTERVAL = 0.02
        try:
            parts = list(rtsp.stream_frames("rtsp:1", timeout=0.05))
        finally:
            rtsp._POLL_INTERVAL = old_poll
        assert parts == []


class TestRtspCaptureLoop:
    def _make_result(self, plate_text, confidence):
        from fast_alpr.alpr import ALPRResult
        from open_image_models.detection.core.base import DetectionResult, BoundingBox
        from fast_alpr.base import OcrResult

        bbox = BoundingBox(x1=0, y1=0, x2=100, y2=50)
        det = DetectionResult(label="license_plate", confidence=confidence, bounding_box=bbox)
        ocr = OcrResult(text=plate_text, confidence=confidence)
        return ALPRResult(detection=det, ocr=ocr)

    def _setup_mocks(self, mocker, plates, mock_cap=None, clear_state=True):
        """Configure mocks for a single-frame RTSP loop."""
        from webapp.dedup import _seen
        from webapp.rtsp import (
            _RTSP_CAMERAS,
            _RTSP_DETECT_EVENTS,
            _RTSP_DETECT_FRAMES,
            _RTSP_FRAME_EVENTS,
            _RTSP_LATEST,
            _RTSP_STOP_EVENTS,
            _RTSP_THREADS,
        )

        if clear_state:
            _seen.clear()
            _RTSP_CAMERAS.clear()
            _RTSP_THREADS.clear()
            _RTSP_LATEST.clear()
            _RTSP_FRAME_EVENTS.clear()
            _RTSP_DETECT_FRAMES.clear()
            _RTSP_DETECT_EVENTS.clear()
            _RTSP_STOP_EVENTS.clear()

        mock_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        if mock_cap is None:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.side_effect = [(True, mock_frame), (False, None)]
            mocker.patch("cv2.VideoCapture", return_value=mock_cap)

        alpr_mock = mocker.patch("webapp.alpr.alpr.predict")
        alpr_mock.return_value = [self._make_result(*p) for p in plates]
        return mock_cap

    def _start_loops(self, cam_id, cam_config):
        from webapp.rtsp import _rtsp_capture_loop, _rtsp_detection_loop

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=(cam_id, cam_config),
            daemon=True,
        )
        t.start()
        td = threading.Thread(
            target=_rtsp_detection_loop,
            args=(cam_id, cam_config),
            daemon=True,
        )
        td.start()

    def test_saves_detection(self, mocker):
        self._setup_mocks(mocker, [("ABC1234", 0.95)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        self._start_loops("rtsp:cam1", {"host": "10.0.0.1", "port": 554, "name": "Test Cam"})
        time.sleep(0.3)

        mock_session.add.assert_called_once()
        det = mock_session.add.call_args[0][0]
        assert det.plate_text == "ABC1234"
        assert det.camera_id == "rtsp:cam1"
        assert det.camera_name == "Test Cam"

    def test_skips_low_confidence(self, mocker):
        self._setup_mocks(mocker, [("ABC1234", 0.3)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.5", "")

        self._start_loops("rtsp:cam2", {"host": "10.0.0.2", "port": 554})
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_skips_invalid_plate(self, mocker):
        self._setup_mocks(mocker, [("INVALID", 0.95)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        self._start_loops("rtsp:cam3", {"host": "10.0.0.3", "port": 554})
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_dedup_blocks_duplicate(self, mocker):
        from webapp.dedup import _seen

        _seen.clear()
        _seen[("ABC1234", "rtsp:cam4")] = time.time()

        self._setup_mocks(mocker, [("ABC1234", 0.95)], clear_state=False)
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")
        cfg._CACHE["dedup_seconds"] = ("60", "")

        self._start_loops("rtsp:cam4", {"host": "10.0.0.4", "port": 554})
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_reconnects_on_read_failure(self, mocker):
        from webapp.dedup import _seen
        from webapp.rtsp import _RTSP_CAMERAS, _rtsp_capture_loop

        _seen.clear()
        _RTSP_CAMERAS.clear()

        first_cap = MagicMock()
        first_cap.isOpened.return_value = True
        first_cap.read.return_value = (False, None)

        second_cap = MagicMock()
        second_cap.isOpened.return_value = False

        mocker.patch("cv2.VideoCapture", side_effect=[first_cap, second_cap])
        mocker.patch("webapp.alpr.alpr.predict", return_value=[])
        mocker.patch("cv2.imencode", return_value=(True, MagicMock()))

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=("rtsp:cam5", {"host": "10.0.0.5", "port": 554}),
            daemon=True,
        )
        t.start()
        time.sleep(0.5)

        assert first_cap.release.called
