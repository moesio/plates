from unittest.mock import MagicMock

import pytest


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

    def test_update_rtsp_cameras_triggers_threads(self, client, mock_db_session, mocker):
        from webapp.database import Config
        from webapp import webapp

        webapp._RTSP_THREADS.clear()
        mock_start = mocker.patch.object(webapp, "_start_rtsp_threads")
        existing = Config(key="rtsp_cameras", value="[]")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = existing

        resp = client.put(
            "/config/rtsp_cameras",
            json={"value": '[{"host":"10.0.0.1","port":554}]'},
        )
        assert resp.status_code == 200
        mock_start.assert_called_once()


class TestSeedOnFirstRequest:
    def test_seed_runs_once(self, client, mocker):
        mock_seed = mocker.patch("webapp.webapp.cfg.seed")
        mock_session = MagicMock()
        mocker.patch("webapp.database.get_session", return_value=mock_session)

        client.application._config_seeded = False

        client.get("/config")
        mock_seed.assert_called_once_with(mock_session)

        client.get("/config")
        assert mock_seed.call_count == 1

    def test_seed_skipped_if_already_seeded(self, client, mocker):
        mock_seed = mocker.patch("webapp.webapp.cfg.seed")
        mocker.patch("webapp.database.get_session")

        client.application._config_seeded = True

        client.get("/config")
        mock_seed.assert_not_called()
