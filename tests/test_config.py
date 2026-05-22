import time
from unittest.mock import MagicMock, patch

import pytest

from webapp import config as cfg
from webapp.database import Config


class TestConfigDefaults:
    def test_get_default_string(self):
        cfg._CACHE = {"dedup_seconds": ("60", "desc")}
        val = cfg.get("dedup_seconds")
        assert val == "60"

    def test_get_default_int(self):
        cfg._CACHE = {"dedup_seconds": ("60", "desc")}
        val = cfg.get_int("dedup_seconds")
        assert val == 60

    def test_get_float(self):
        cfg._CACHE = {"confidence_threshold": ("0.85", "desc")}
        val = cfg.get_float("confidence_threshold")
        assert val == 0.85

    def test_get_nonexistent_returns_default(self):
        cfg._CACHE = {}
        val = cfg.get("nonexistent", "fallback")
        assert val == "fallback"

    def test_get_int_nonexistent(self):
        cfg._CACHE = {}
        val = cfg.get_int("nonexistent", 42)
        assert val == 42

    def test_get_float_nonexistent(self):
        cfg._CACHE = {}
        val = cfg.get_float("nonexistent", 3.14)
        assert val == 3.14

    def test_get_bad_int_returns_default(self):
        cfg._CACHE = {"some_key": ("not_a_number", "")}
        val = cfg.get_int("some_key", 99)
        assert val == 99


class TestConfigCache:
    def test_cache_uses_existing(self, mocker):
        mock_load = mocker.patch.object(cfg, "_load")
        cfg._CACHE = {"dedup_seconds": ("60", "desc")}
        cfg._CACHE_TIME = time.time()

        val = cfg.get("dedup_seconds")
        assert val == "60"
        mock_load.assert_not_called()

    def test_cache_expires_and_reloads(self, mocker):
        mock_load = mocker.patch.object(cfg, "_load")
        cfg._CACHE = {"dedup_seconds": ("60", "desc")}
        cfg._CACHE_TIME = time.time() - 20  # expired (TTL is 10)

        cfg.get("dedup_seconds")
        mock_load.assert_called_once()

    def test_reload_clears_cache(self, mocker):
        mock_load = mocker.patch.object(cfg, "_load")
        cfg.reload()
        mock_load.assert_called_once()


class TestConfigSeed:
    def test_seed_inserts_defaults(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None

        cfg.seed(session)

        assert session.add.call_count == 3
        session.commit.assert_called_once()

    def test_seed_skips_existing(self):
        session = MagicMock()
        existing = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = existing

        cfg.seed(session)

        session.add.assert_not_called()
        session.commit.assert_called_once()


class TestConfigLoadFromDb:
    def test_load_overrides_defaults(self, mocker):
        mock_rows = [
            Config(key="dedup_seconds", value="120", description="custom"),
        ]
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = mock_rows
        mocker.patch("webapp.config.database.get_session", return_value=mock_session)

        cfg._load()

        assert cfg._CACHE["dedup_seconds"] == ("120", "custom")
        assert cfg._CACHE["cleanup_interval"] == (
            "20",
            "Frequência de limpeza do cache (a cada N saves)",
        )

    def test_load_db_failure_falls_back_to_defaults(self, mocker):
        mocker.patch(
            "webapp.config.database.get_session",
            side_effect=Exception("DB down"),
        )

        cfg._load()

        assert cfg._CACHE["dedup_seconds"] == ("60", "Janela de deduplicação em segundos")
