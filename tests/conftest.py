import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock

from webapp.webapp import app as _app


@pytest.fixture
def app():
    _app.config.update({"TESTING": True})
    _app._config_seeded = True
    yield _app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset config cache before each test to prevent DB access."""
    import webapp.config as cfg

    cfg._CACHE = dict(cfg._DEFAULTS)
    cfg._CACHE_TIME = time.time()
    yield
    cfg._CACHE = None
    cfg._CACHE_TIME = 0


@pytest.fixture
def mock_db_session(mocker):
    """Mock database session to avoid real DB."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock()
    mocker.patch("webapp.database.get_session", return_value=mock_session)
    mocker.patch("webapp.database.SessionLocal", return_value=mock_session)
    return mock_session


@pytest.fixture
def mock_alpr(mocker):
    """Mock ALPR predictions."""
    from fast_alpr.alpr import ALPRResult
    from open_image_models.detection.core.base import DetectionResult, BoundingBox
    from fast_alpr.base import OcrResult

    def make_results(plates):
        results = []
        for text, conf in plates:
            bbox = BoundingBox(x1=50, y1=100, x2=200, y2=150)
            det = DetectionResult(
                label="license_plate", confidence=conf, bounding_box=bbox
            )
            ocr = OcrResult(text=text, confidence=conf)
            results.append(ALPRResult(detection=det, ocr=ocr))
        return results

    mock = mocker.patch("webapp.webapp.alpr.predict")
    mock.side_effect = lambda frame: make_results(mock._plates or [])
    mock._plates = []
    return mock
