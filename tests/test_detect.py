import cv2
import numpy as np
import pytest


def _jpeg_bytes():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    ret, jpeg = cv2.imencode(".jpg", img)
    return jpeg.tobytes()


class TestDetectEndpoint:
    def test_invalid_image_returns_400(self, client):
        resp = client.post("/detect", data=b"not_an_image", content_type="image/jpeg")
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "invalid image"}

    def test_no_detection_returns_empty(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = []
        resp = client.post("/detect", data=_jpeg_bytes(), content_type="image/jpeg")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_valid_plate_detected(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = [("ABC1A23", 0.92)]
        resp = client.post("/detect", data=_jpeg_bytes(), content_type="image/jpeg")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["plate_text"] == "ABC1A23"
        assert data[0]["confidence"] == 0.92

    def test_invalid_plate_filtered_out(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = [("INVALID", 0.92)]
        resp = client.post("/detect", data=_jpeg_bytes(), content_type="image/jpeg")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_mixed_valid_and_invalid(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = [("ABC1A23", 0.95), ("12345", 0.80), ("XYZ-9999", 0.90)]
        resp = client.post("/detect", data=_jpeg_bytes(), content_type="image/jpeg")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        texts = [d["plate_text"] for d in data]
        assert "ABC1A23" in texts
        assert "XYZ-9999" in texts

    def test_confidence_threshold_filters_low_conf(
        self, client, mock_alpr, mock_db_session
    ):
        mock_alpr._plates = [("ABC1A23", 0.50)]
        import webapp.config as cfg

        cfg._CACHE["confidence_threshold"] = ("0.70", "")

        resp = client.post("/detect", data=_jpeg_bytes(), content_type="image/jpeg")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestDetectDedup:
    def test_same_plate_deduped(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = [("ABC1A23", 0.92)]
        data = _jpeg_bytes()

        r1 = client.post("/detect", data=data, content_type="image/jpeg")
        assert len(r1.get_json()) == 1

        r2 = client.post("/detect", data=data, content_type="image/jpeg")
        assert len(r2.get_json()) == 1

        from webapp.webapp import _seen

        key = ("ABC1A23", "0")
        assert key in _seen

    def test_different_cameras_independent_dedup(
        self, client, mock_alpr, mock_db_session
    ):
        mock_alpr._plates = [("ABC1A23", 0.92)]
        data = _jpeg_bytes()

        r1 = client.post(
            "/detect",
            data=data,
            content_type="image/jpeg",
            headers={"X-Camera-Id": "cam-1"},
        )
        assert len(r1.get_json()) == 1

        r2 = client.post(
            "/detect",
            data=data,
            content_type="image/jpeg",
            headers={"X-Camera-Id": "cam-2"},
        )
        assert len(r2.get_json()) == 1

        from webapp.webapp import _seen

        assert ("ABC1A23", "cam-1") in _seen
        assert ("ABC1A23", "cam-2") in _seen

    def test_different_plates_not_deduped(self, client, mock_alpr, mock_db_session):
        mock_alpr._plates = [("ABC1A23", 0.92)]
        data = _jpeg_bytes()

        r1 = client.post("/detect", data=data, content_type="image/jpeg")
        assert len(r1.get_json()) == 1

        mock_alpr._plates = [("XYZ-9999", 0.90)]
        r2 = client.post("/detect", data=data, content_type="image/jpeg")
        assert len(r2.get_json()) == 1
