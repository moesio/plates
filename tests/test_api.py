from unittest.mock import MagicMock

import pytest


class TestRtspCameraModel:
    def test_to_dict(self):
        from webapp.database import RtspCamera
        from datetime import datetime

        cam = RtspCamera(
            id=1, host="10.0.0.1", port=554, username="admin", password="secret",
            path="/live", name="Portaria", enabled=True, detect_enabled=True,
        )
        d = cam.to_dict()
        assert d["id"] == 1
        assert d["host"] == "10.0.0.1"
        assert d["port"] == 554
        assert d["username"] == "admin"
        assert d["password"] == "secret"
        assert d["path"] == "/live"
        assert d["name"] == "Portaria"
        assert d["enabled"] is True
        assert d["detect_enabled"] is True

    def test_to_dict_defaults(self):
        from webapp.database import RtspCamera

        cam = RtspCamera(id=2, host="10.0.0.2")
        d = cam.to_dict()
        assert d["host"] == "10.0.0.2"
        assert d["port"] == 554
        assert d["username"] == ""
        assert d["password"] == ""
        assert d["path"] == "/"
        assert d["name"] == ""
        assert d["enabled"] is True
        assert d["detect_enabled"] is True

    def test_to_dict_enabled_none_defaults_true(self):
        from webapp.database import RtspCamera

        cam = RtspCamera(id=3, host="10.0.0.3", enabled=None)
        d = cam.to_dict()
        assert d["enabled"] is True

    def test_to_dict_detect_enabled_none_defaults_true(self):
        from webapp.database import RtspCamera

        cam = RtspCamera(id=4, host="10.0.0.4", detect_enabled=None)
        d = cam.to_dict()
        assert d["detect_enabled"] is True


class TestConfigAPI:
    def test_list_config_uses_cache(self, client):
        import webapp.config as cfg
        cfg._CACHE = {
            "dedup_seconds": ("99", "custom window"),
            "cleanup_interval": ("10", ""),
            "confidence_threshold": ("0.5", ""),
        }

        resp = client.get("/config")
        data = resp.get_json()
        items = {item["key"]: item["value"] for item in data}
        assert items["dedup_seconds"] == "99"
        assert items["cleanup_interval"] == "10"
        assert items["confidence_threshold"] == "0.5"

    def test_list_config_returns_defaults(self, client):
        import webapp.config as cfg
        cfg._CACHE = dict(cfg._DEFAULTS)

        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 4
        keys = [item["key"] for item in data]
        assert "dedup_seconds" in keys
        assert "cleanup_interval" in keys
        assert "confidence_threshold" in keys

    def test_update_config(self, client, mock_db_session):
        import webapp.config as cfg
        from webapp.database import Config

        cfg._CACHE = {"dedup_seconds": ("60", "")}
        existing = Config(key="dedup_seconds", value="60")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = existing

        resp = client.put("/config/dedup_seconds", json={"value": "120"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["key"] == "dedup_seconds"
        assert data["value"] == "120"
        assert existing.value == "120"

    def test_update_nonexistent_returns_404(self, client, mock_db_session):
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None

        resp = client.put("/config/nonexistent", json={"value": "1"})
        assert resp.status_code == 404

    def test_update_without_value_returns_400(self, client, mock_db_session):
        resp = client.put("/config/dedup_seconds", json={})
        assert resp.status_code == 400

    def test_create_camera(self, client, mock_db_session, mocker):
        from webapp.database import RtspCamera

        mock_start = mocker.patch("webapp.services.camera_service._start_rtsp_threads")

        resp = client.post("/cameras", json={"host": "10.0.0.1", "port": 554})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["host"] == "10.0.0.1"
        assert data["port"] == 554

        added = mock_db_session.add.call_args[0][0]
        assert isinstance(added, RtspCamera)
        assert added.host == "10.0.0.1"
        assert added.detect_enabled is True
        mock_start.assert_called_once()

    def test_create_camera_with_detect_disabled(self, client, mock_db_session, mocker):
        from webapp.database import RtspCamera

        mocker.patch("webapp.services.camera_service._start_rtsp_threads")

        resp = client.post("/cameras", json={"host": "10.0.0.1", "detect_enabled": False})
        assert resp.status_code == 201

        added = mock_db_session.add.call_args[0][0]
        assert isinstance(added, RtspCamera)
        assert added.detect_enabled is False

    def test_create_camera_missing_host(self, client):
        resp = client.post("/cameras", json={"port": 554})
        assert resp.status_code == 400

    def test_list_cameras(self, client, mock_db_session):
        from webapp.database import RtspCamera

        cams = [
            RtspCamera(id=1, host="10.0.0.1", port=554, name="Cam 1"),
            RtspCamera(id=2, host="10.0.0.2", port=554, name="Cam 2",
                       detect_enabled=False),
        ]
        mock_db_session.query.return_value.order_by.return_value.all.return_value = cams

        resp = client.get("/cameras")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["host"] == "10.0.0.1"
        assert data[0]["detect_enabled"] is True
        assert data[1]["host"] == "10.0.0.2"
        assert data[1]["detect_enabled"] is False

    def test_update_camera(self, client, mock_db_session, mocker):
        from webapp.database import RtspCamera

        mock_start = mocker.patch("webapp.services.camera_service._start_rtsp_threads")
        cam = RtspCamera(id=1, host="10.0.0.1", port=554, name="Old Name")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = cam

        resp = client.put("/cameras/1", json={"name": "New Name"})
        assert resp.status_code == 200
        assert cam.name == "New Name"
        mock_start.assert_called_once()

    def test_update_camera_toggles_detect_enabled(self, client, mock_db_session, mocker):
        from webapp.database import RtspCamera

        mock_start = mocker.patch("webapp.services.camera_service._start_rtsp_threads")
        cam = RtspCamera(id=1, host="10.0.0.1", port=554, detect_enabled=True)
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = cam

        resp = client.put("/cameras/1", json={"detect_enabled": False})
        assert resp.status_code == 200
        assert cam.detect_enabled is False
        mock_start.assert_called_once()

    def test_update_camera_not_found(self, client, mock_db_session):
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None

        resp = client.put("/cameras/999", json={"name": "Nope"})
        assert resp.status_code == 404

    def test_update_camera_empty_body(self, client):
        resp = client.put("/cameras/1", json={})
        assert resp.status_code == 400

    def test_delete_camera(self, client, mock_db_session, mocker):
        from webapp.database import RtspCamera

        mock_start = mocker.patch("webapp.services.camera_service._start_rtsp_threads")
        cam = RtspCamera(id=1, host="10.0.0.1", port=554)
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = cam

        resp = client.delete("/cameras/1")
        assert resp.status_code == 200
        mock_db_session.delete.assert_called_once_with(cam)
        mock_start.assert_called_once()

    def test_delete_camera_not_found(self, client, mock_db_session):
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None

        resp = client.delete("/cameras/999")
        assert resp.status_code == 404


class TestCameraLiveEndpoints:
    def test_frame_camera_missing_404(self, client, mock_db_session):
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None

        resp = client.get("/cameras/999/frame")
        assert resp.status_code == 404

    def test_frame_no_signal_404(self, client, mock_db_session):
        from webapp.rtsp import _RTSP_LATEST

        _RTSP_LATEST.pop("rtsp:1", None)
        resp = client.get("/cameras/1/frame")
        assert resp.status_code == 404

    def test_frame_returns_latest_jpeg(self, client, mock_db_session):
        from webapp.rtsp import _clear_latest_frame, _set_latest_frame

        _set_latest_frame("rtsp:1", b"\xff\xd8jpegdata")
        try:
            resp = client.get("/cameras/1/frame")
            assert resp.status_code == 200
            assert resp.mimetype == "image/jpeg"
            assert resp.data.startswith(b"\xff\xd8")
        finally:
            _clear_latest_frame("rtsp:1")

    def test_stream_camera_missing_404(self, client, mock_db_session):
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = None

        resp = client.get("/cameras/999/stream")
        assert resp.status_code == 404

    def test_stream_returns_mjpeg(self, client, mock_db_session):
        from webapp.rtsp import _clear_latest_frame, _set_latest_frame

        _set_latest_frame("rtsp:1", b"jpegdata")
        try:
            resp = client.get("/cameras/1/stream")
            assert resp.status_code == 200
            assert "multipart/x-mixed-replace" in resp.content_type
        finally:
            _clear_latest_frame("rtsp:1")


class TestSeedOnFirstRequest:
    def test_seed_runs_once(self, client, mocker):
        mock_seed = mocker.patch("webapp.app.cfg.seed")
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        client.application._config_seeded = False

        client.get("/config")
        mock_seed.assert_called_once_with(mock_session)

        client.get("/config")
        assert mock_seed.call_count == 1

    def test_seed_skipped_if_already_seeded(self, client, mocker):
        mock_seed = mocker.patch("webapp.app.cfg.seed")
        mocker.patch("webapp.database.get_session")

        client.application._config_seeded = True

        client.get("/config")
        mock_seed.assert_not_called()
