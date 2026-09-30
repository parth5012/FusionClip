import pytest
from unittest.mock import MagicMock, patch
from app.models import Task

@patch("app.routers.tasks.process_upscale_task.apply_async")
def test_upscale_endpoint_dispatches(mock_apply_async, client, db_session):
    response = client.post(
        "/api/upscale?path=test_image.png",
        json={
            "denoising_strength": 0.4,
            "controlnet_weight": 1.2,
            "preset": "Portraits",
            "preview": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Upscale task initiated successfully"
    assert "task_id" in data
    assert data["status"] == "PROCESSING"
    
    # Verify task database record exists
    task_id = data["task_id"]
    db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
    assert db_task is not None
    assert db_task.name == "upscale"
    assert db_task.status == "PROCESSING"
    
    # Verify Celery apply_async params
    mock_apply_async.assert_called_once_with(
        args=[task_id, "test_image.png", {
            "denoising_strength": 0.4,
            "controlnet_weight": 1.2,
            "preset": "Portraits",
            "preview": False
        }],
        task_id=task_id
    )


# --------------------------------------------------------------------------- #
# Precision mode request contract (#123-d8/d10/d11, #124)
# --------------------------------------------------------------------------- #

def _body(**overrides):
    body = {"image_path": "contract.png", "scale": 4}
    body.update(overrides)
    return body


class TestPrecisionRequestContract:
    def test_creative_mode_rejects_precision_fields(self, client):
        """d11: engine/sharpness/grain are 422 when mode='creative' — no silent ignoring."""
        for field, value in (("engine", "hat"), ("sharpness", 10), ("grain", 5)):
            res = client.post("/api/upscale", json=_body(**{field: value}))
            assert res.status_code == 422, f"{field} must be rejected in creative mode"

    def test_precision_mode_rejects_creative_sliders(self, client):
        """d8: Creativity/Resemblance/Fractality/HDR stay Creative-only."""
        for field, value in (
            ("creativity", 5),
            ("resemblance", -3),
            ("fractality", 2),
            ("hdr", 1),
        ):
            res = client.post("/api/upscale", json=_body(mode="precision", **{field: value}))
            assert res.status_code == 422, f"{field} must be rejected in precision mode"

    def test_precision_defaults_to_hat_and_echoes_mode(self, client):
        res = client.post("/api/upscale", json=_body(mode="precision"))
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "precision"
        assert data["engine"] == "hat"  # d10: default hat, manual pick
        assert data["parameters"]["sharpness"] == 0
        assert data["parameters"]["grain"] == 0

    def test_precision_echoes_explicit_engine_and_sliders(self, client):
        res = client.post(
            "/api/upscale",
            json=_body(mode="precision", engine="scunet", sharpness=40, grain=25),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "precision"
        assert data["engine"] == "scunet"
        assert data["parameters"]["sharpness"] == 40
        assert data["parameters"]["grain"] == 25

    def test_creative_response_echoes_mode_and_no_engine(self, client):
        res = client.post("/api/upscale", json=_body())
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "creative"
        assert data["engine"] is None

    def test_stub_engine_is_not_user_selectable(self, client):
        """d9: the deterministic PIL path is CI-only, never an API value."""
        res = client.post("/api/upscale", json=_body(mode="precision", engine="stub"))
        assert res.status_code == 422

    def test_unknown_engine_rejected(self, client):
        res = client.post("/api/upscale", json=_body(mode="precision", engine="giga"))
        assert res.status_code == 422

    @pytest.mark.parametrize(
        "field,value",
        [("sharpness", 101), ("sharpness", -1), ("grain", 101), ("grain", -1)],
    )
    def test_precision_slider_bounds_rejected(self, client, field, value):
        res = client.post("/api/upscale", json=_body(mode="precision", **{field: value}))
        assert res.status_code == 422

    def test_invalid_mode_rejected(self, client):
        res = client.post("/api/upscale", json=_body(mode="turbo"))
        assert res.status_code == 422

    def test_legacy_celery_path_rejects_precision_controls(self, client):
        """The ?path= Celery dispatch is creative-only — precision there would be
        silently dropped, which d11 forbids."""
        res = client.post(
            "/api/upscale?path=legacy.png",
            json={"preset": "Portraits", "mode": "precision"},
        )
        assert res.status_code == 422

        res2 = client.post(
            "/api/upscale?path=legacy.png",
            json={"preset": "Portraits", "engine": "hat"},
        )
        assert res2.status_code == 422
