import json
import threading
import time
from unittest.mock import MagicMock

import pytest


class TestBuildRtspUrl:
    def test_basic_host_port(self):
        from webapp.webapp import _build_rtsp_url

        url = _build_rtsp_url({"host": "192.168.1.100", "port": 8080})
        assert url == "rtsp://192.168.1.100:8080/"

    def test_with_auth(self):
        from webapp.webapp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "10.0.0.50",
            "port": 554,
            "username": "admin",
            "password": "secret",
        })
        assert url == "rtsp://admin:secret@10.0.0.50:554/"

    def test_with_path(self):
        from webapp.webapp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "192.168.1.100",
            "port": 554,
            "path": "/Streaming/Channels/101",
        })
        assert url == "rtsp://192.168.1.100:554/Streaming/Channels/101"

    def test_without_username_skips_auth(self):
        from webapp.webapp import _build_rtsp_url

        url = _build_rtsp_url({
            "host": "192.168.1.100",
            "port": 8080,
            "password": "secret",
        })
        assert url == "rtsp://192.168.1.100:8080/"

    def test_default_port(self):
        from webapp.webapp import _build_rtsp_url

        url = _build_rtsp_url({"host": "10.0.0.1"})
        assert url == "rtsp://10.0.0.1:554/"


class TestStartRtspThreads:
    def test_empty_config_does_nothing(self):
        import webapp.config as cfg
        from webapp.webapp import _start_rtsp_threads

        cfg._CACHE["rtsp_cameras"] = ("[]", "")
        _start_rtsp_threads()

    def test_starts_thread(self, mocker):
        import webapp.config as cfg
        from webapp import webapp

        webapp._RTSP_THREADS.clear()
        mock_thread = mocker.patch.object(webapp.threading, "Thread")
        cfg._CACHE["rtsp_cameras"] = (
            json.dumps([{"host": "10.0.0.1", "port": 554}]),
            "",
        )

        webapp._start_rtsp_threads()

        mock_thread.assert_called_once()
        _, kwargs = mock_thread.call_args
        assert kwargs["name"] == "rtsp:10.0.0.1:554"
        assert kwargs["daemon"] is True

    def test_thread_only_starts_once(self, mocker):
        import webapp.config as cfg
        from webapp import webapp

        webapp._RTSP_THREADS.clear()
        mock_thread = mocker.patch.object(webapp.threading, "Thread")
        cfg._CACHE["rtsp_cameras"] = (
            json.dumps([{"host": "10.0.0.1", "port": 554}]),
            "",
        )

        webapp._start_rtsp_threads()
        webapp._start_rtsp_threads()

        mock_thread.assert_called_once()

    def test_bad_json_does_not_crash(self):
        import webapp.config as cfg
        from webapp.webapp import _start_rtsp_threads

        cfg._CACHE["rtsp_cameras"] = ("not-json", "")
        _start_rtsp_threads()


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
        from webapp.webapp import _seen, _RTSP_CAMERAS

        if clear_state:
            _seen.clear()
            _RTSP_CAMERAS.clear()

        mock_frame = MagicMock()
        if mock_cap is None:
            mock_cap = MagicMock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.side_effect = [(True, mock_frame), (False, None)]
            mocker.patch("cv2.VideoCapture", return_value=mock_cap)

        mocker.patch("cv2.imencode", return_value=(True, MagicMock()))

        alpr_mock = mocker.patch("webapp.webapp.alpr.predict")
        alpr_mock.return_value = [self._make_result(*p) for p in plates]
        return mock_cap

    def test_saves_detection(self, mocker):
        from webapp.webapp import _rtsp_capture_loop

        self._setup_mocks(mocker, [("ABC1234", 0.95)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=("rtsp:cam1", {"host": "10.0.0.1", "port": 554, "name": "Test Cam"}),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)

        mock_session.add.assert_called_once()
        det = mock_session.add.call_args[0][0]
        assert det.plate_text == "ABC1234"
        assert det.camera_id == "rtsp:cam1"
        assert det.camera_name == "Test Cam"

    def test_skips_low_confidence(self, mocker):
        from webapp.webapp import _rtsp_capture_loop

        self._setup_mocks(mocker, [("ABC1234", 0.3)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.5", "")

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=("rtsp:cam2", {"host": "10.0.0.2", "port": 554}),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_skips_invalid_plate(self, mocker):
        from webapp.webapp import _rtsp_capture_loop

        self._setup_mocks(mocker, [("INVALID", 0.95)])
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=("rtsp:cam3", {"host": "10.0.0.3", "port": 554}),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_dedup_blocks_duplicate(self, mocker):
        from webapp.webapp import _rtsp_capture_loop, _seen, _RTSP_CAMERAS

        _seen.clear()
        _RTSP_CAMERAS.clear()
        _seen[("ABC1234", "rtsp:cam4")] = time.time()

        self._setup_mocks(mocker, [("ABC1234", 0.95)], clear_state=False)
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        import webapp.config as cfg
        cfg._CACHE["confidence_threshold"] = ("0.0", "")
        cfg._CACHE["dedup_seconds"] = ("60", "")

        t = threading.Thread(
            target=_rtsp_capture_loop,
            args=("rtsp:cam4", {"host": "10.0.0.4", "port": 554}),
            daemon=True,
        )
        t.start()
        time.sleep(0.3)

        mock_session.add.assert_not_called()

    def test_reconnects_on_read_failure(self, mocker):
        from webapp.webapp import _rtsp_capture_loop, _seen, _RTSP_CAMERAS

        _seen.clear()
        _RTSP_CAMERAS.clear()

        first_cap = MagicMock()
        first_cap.isOpened.return_value = True
        first_cap.read.return_value = (False, None)

        second_cap = MagicMock()
        second_cap.isOpened.return_value = False

        mocker.patch("cv2.VideoCapture", side_effect=[first_cap, second_cap])
        mocker.patch("webapp.webapp.alpr.predict", return_value=[])
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
