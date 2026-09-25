"""Tests for local SVD image-to-video generation pipeline and task wiring (#102).

Tests:
1. Mock string elimination scan across production code.
2. Safe imports: app.ml.video imports cleanly without torch/diffusers installed.
3. Filename generator: build_video_filename() produces nanosecond timestamped pure-digit filenames.
4. Monotonic progress mapping: video_progress stays within 0..99 across denoise (0..79%) and encode (80..99%).
5. Degraded refusal: VRAM guard refusal (no GPU / insufficient VRAM) returns degraded contract for 'svd'.
6. Image validation: unreadable/corrupt conditioning image raises ValueError.
7. Pipeline execution: mock diffusers pipeline generates frames, encodes via ffmpeg, uploads MP4, persists MediaAsset.
8. Celery task dispatch: process_gpu_task dispatches image_to_video op, executes progress_cb, updates Celery/Redis/DB.
9. Endpoint validation: POST /api/generate/video rejects path traversals, missing source, corrupt images, out-of-bounds num_frames/fps with 400.
10. Endpoint dispatch: POST /api/generate/video returns Celery task_id with PENDING status.
"""

import io
import json
from pathlib import Path
import re
import tempfile
import time
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.ml.contracts import DegradedReason, FallbackTier
from app.ml.guard import InsufficientVRAMError, NoGPUError, vram_guard
from app.ml.registry import model_registry
from app.models import MediaAsset, Task

REPO_ROOT = Path(__file__).resolve().parents[2]


def create_test_png_bytes(width: int = 64, height: int = 64, color: tuple = (255, 0, 0)) -> bytes:
    """Helper to generate valid PNG bytes for conditioning image tests."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestMockStringElimination:
    def test_mock_strings_absent_from_codebase(self):
        """Ensure no forbidden mock strings exist in backend/app."""
        forbidden_strings = [
            "Mock " + "local flux generated image bytes",
            "Mock " + "elevenlabs generated audio bytes",
            "Mock " + "svd generated video bytes",
        ]
        app_dir = REPO_ROOT / "backend" / "app"

        found = []
        for path in app_dir.rglob("*.py"):
            try:
                content = path.read_text(encoding="utf-8")
                for s in forbidden_strings:
                    if s in content:
                        found.append((str(path.relative_to(REPO_ROOT)), s))
            except (OSError, UnicodeDecodeError):
                continue

        assert not found, f"Forbidden mock strings found in production files: {found}"


class TestVideoImportAndHelpers:
    def test_video_module_imports_without_torch(self, monkeypatch):
        """app.ml.video must import cleanly even when torch and diffusers are unavailable."""
        import importlib
        import sys

        saved = sys.modules.pop("app.ml.video", None)
        saved_parent = getattr(sys.modules.get("app.ml"), "video", None)

        try:
            monkeypatch.setitem(sys.modules, "torch", None)
            monkeypatch.setitem(sys.modules, "diffusers", None)

            mod = importlib.import_module("app.ml.video")
            assert hasattr(mod, "run_local_image_to_video")
            assert hasattr(mod, "build_video_filename")
            assert hasattr(mod, "video_progress")
        finally:
            if saved is not None:
                sys.modules["app.ml.video"] = saved
            if "app.ml" in sys.modules and saved_parent is not None:
                setattr(sys.modules["app.ml"], "video", saved_parent)

    def test_build_video_filename_pure_digits(self):
        """build_video_filename must match gen_video_<digits>.mp4 for frontend regex compatibility."""
        from app.ml.video import build_video_filename

        filename1 = build_video_filename()
        assert re.match(r"^gen_video_\d+\.mp4$", filename1)

        time.sleep(0.001)
        filename2 = build_video_filename()
        assert filename1 != filename2, "Nanosecond timestamps should not collide"


class TestVideoProgressMapping:
    def test_video_progress_ranges_and_monotonicity(self):
        """video_progress must stay within 0..99 and be monotonic across denoise -> encode handoff."""
        from app.ml.video import video_progress

        total_denoise_steps = 25
        denoise_percents = []
        for step in range(1, total_denoise_steps + 1):
            pct, status_text = video_progress("denoise", step, total_denoise_steps)
            assert 0 <= pct <= 79, f"Denoise percent {pct} out of bounds 0..79"
            assert f"denoising step {step}/{total_denoise_steps}" in status_text
            denoise_percents.append(pct)

        # Monotonicity during denoise
        assert denoise_percents == sorted(denoise_percents)
        assert denoise_percents[-1] == 79

        total_encode_frames = 14
        encode_percents = []
        for frame in range(1, total_encode_frames + 1):
            pct, status_text = video_progress("encode", frame, total_encode_frames)
            assert 80 <= pct <= 99, f"Encode percent {pct} out of bounds 80..99"
            assert f"Encoding frame {frame}/{total_encode_frames}" in status_text
            encode_percents.append(pct)

        # Monotonicity during encode
        assert encode_percents == sorted(encode_percents)
        assert encode_percents[-1] == 99

        # Monotonic across handoff
        assert denoise_percents[-1] < encode_percents[0]


class TestLocalVideoRefusal:
    def test_degraded_refusal_when_no_gpu(self, monkeypatch):
        """When host has no CUDA GPU, run_local_image_to_video returns degraded response."""
        from app.ml.video import run_local_image_to_video

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": False,
                "device_name": None,
                "total_bytes": 0,
                "free_bytes": 0,
                "used_bytes": 0,
                "total_gb": 0.0,
                "free_gb": 0.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            },
        )

        source_bytes = create_test_png_bytes()
        res = run_local_image_to_video(source_bytes, num_frames=14, fps=7)

        assert res.get("degraded") is True
        assert res.get("reason") == DegradedReason.NO_GPU.value
        assert "no cuda gpu" in res.get("message", "").lower()
        assert res.get("fallback_tier") == FallbackTier.REFUSAL.value

    def test_degraded_refusal_when_insufficient_vram(self, monkeypatch):
        """When free VRAM cannot accommodate SVD even with offload (8 GB floor), return insufficient_vram."""
        from app.ml.video import run_local_image_to_video

        total_bytes = int(16.0 * (1024 ** 3))
        free_bytes = int(4.0 * (1024 ** 3))  # 4 GB free, SVD offload requires 8 GB + 1 GB overhead

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4080",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 16.0,
                "free_gb": 4.0,
                "used_gb": 12.0,
                "vram_percent": 75.0,
            },
        )

        source_bytes = create_test_png_bytes()
        res = run_local_image_to_video(source_bytes, num_frames=14, fps=7)

        assert res.get("degraded") is True
        assert res.get("reason") == DegradedReason.INSUFFICIENT_VRAM.value
        assert res.get("model_id") == "svd"


class TestVideoPipelineExecution:
    def test_unreadable_source_image_raises_value_error(self, monkeypatch):
        """Corrupt or unreadable conditioning image must raise ValueError (distinguishable from load_failed)."""
        from app.ml.video import run_local_image_to_video

        monkeypatch.setattr(
            vram_guard,
            "check_vram",
            lambda model_id, **kwargs: {"admitted": True, "model_id": "svd", "mode": "offload"},
        )

        with pytest.raises(ValueError, match="unreadable|invalid|corrupt"):
            run_local_image_to_video(b"not-a-valid-image", num_frames=14, fps=7)

    def test_successful_video_generation_and_encoding(self, monkeypatch, db_session, stub_storage):
        """Full pipeline execution with mocked SVD model and real ffmpeg encode."""
        from app.ml.video import run_local_image_to_video

        monkeypatch.setattr(
            vram_guard,
            "check_vram",
            lambda model_id, **kwargs: {"admitted": True, "model_id": "svd", "mode": "offload"},
        )

        # Mock model pipeline returning PIL frames
        mock_pipe = MagicMock()
        pil_frames = [Image.new("RGB", (64, 64), color=(i * 10, i * 10, i * 10)) for i in range(14)]

        class MockPipeOutput:
            frames = [pil_frames]

        def fake_pipe_call(*args, **kwargs):
            # Fire callback if present
            cb = kwargs.get("callback_on_step_end")
            if cb:
                for step_idx in range(25):
                    cb(mock_pipe, step_idx, None, {})
            return MockPipeOutput()

        mock_pipe.side_effect = fake_pipe_call
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **kwargs: mock_pipe)

        progress_calls = []
        def tracking_cb(pct, status):
            progress_calls.append((pct, status))

        source_bytes = create_test_png_bytes()
        res = run_local_image_to_video(
            source_bytes,
            num_frames=14,
            fps=7,
            progress_cb=tracking_cb,
            db=db_session,
            source_name="conditioning.png",
        )

        assert res.get("status") == "COMPLETED"
        assert res.get("type") == "video"
        assert res.get("num_frames") == 14
        assert res.get("fps") == 7
        assert re.match(r"^gen_video_\d+\.mp4$", res.get("filename", ""))

        # Check progress events occurred
        assert len(progress_calls) > 0
        denoise_calls = [p for p in progress_calls if "denoising" in p[1]]
        encode_calls = [p for p in progress_calls if "Encoding" in p[1]]
        assert len(denoise_calls) == 25
        assert len(encode_calls) > 0

        # Check MediaAsset persisted
        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == res["filename"]).first()
        assert asset is not None
        assert "Local SVD:" in asset.title
        assert asset.content_type == "video/mp4"
        assert asset.duration == round(14 / 7.0, 2)

    def test_ffmpeg_encoding_failure_returns_load_failed(self, monkeypatch, db_session):
        """When ffmpeg encoding fails, run_local_image_to_video returns degraded response with load_failed."""
        from app.ml.video import run_local_image_to_video, VideoEncodingError

        monkeypatch.setattr(
            vram_guard,
            "check_vram",
            lambda model_id, **kwargs: {"admitted": True, "model_id": "svd", "mode": "offload"},
        )

        mock_pipe = MagicMock()
        pil_frames = [Image.new("RGB", (64, 64)) for _ in range(14)]
        mock_pipe.return_value = MagicMock(frames=[pil_frames])
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **kwargs: mock_pipe)

        def failing_encode(frames, fps, progress_cb=None):
            raise VideoEncodingError("FFmpeg encoding failed with exit code 1")

        monkeypatch.setattr("app.ml.video.encode_frames_to_mp4", failing_encode)

        source_bytes = create_test_png_bytes()
        res = run_local_image_to_video(source_bytes, num_frames=14, fps=7, db=db_session)

        assert res.get("degraded") is True
        assert res.get("reason") == DegradedReason.LOAD_FAILED.value
        assert "failed to encode video frames" in res.get("message", "").lower()


class TestTasksProcessGpuTaskDispatch:
    def test_process_gpu_task_image_to_video_dispatch(self, monkeypatch, db_session, stub_storage):
        """process_gpu_task handles op=image_to_video, resolves source, and wires progress_cb."""
        import app.tasks as tasks_module
        from app.tasks import process_gpu_task

        # Put a test image in storage
        test_source = "uploads/cond_image.png"
        test_bytes = create_test_png_bytes()
        stub_storage["uploaded"][test_source] = {"data": test_bytes, "content_type": "image/png"}

        # Mock run_local_image_to_video
        recorded_progress = []
        def fake_run_video(source, *, num_frames, fps, progress_cb=None, db=None, source_name=None):
            assert source == test_bytes
            assert num_frames == 14
            assert fps == 7
            if progress_cb:
                progress_cb(50, "Generating video: denoising step 16/25")
                progress_cb(90, "Encoding frame 7/14")
            return {
                "status": "COMPLETED",
                "type": "video",
                "filename": "gen_video_12345.mp4",
                "url": "http://test/gen_video_12345.mp4",
                "num_frames": num_frames,
                "fps": fps,
            }

        import app.ml.video as vid_mod
        monkeypatch.setattr(vid_mod, "run_local_image_to_video", fake_run_video)
        monkeypatch.setattr("app.ml.video.run_local_image_to_video", fake_run_video, raising=False)

        states = []
        def fake_update_state(state, meta):
            states.append((state, meta))

        monkeypatch.setattr(process_gpu_task, "update_state", fake_update_state)

        published_redis = []
        monkeypatch.setattr(
            tasks_module.redis_client,
            "publish",
            lambda channel, msg: published_redis.append((channel, json.loads(msg))),
        )

        process_gpu_task.push_request(id="test-celery-video-task")
        try:
            res = process_gpu_task.run(
                "svd",
                payload={"op": "image_to_video", "source": test_source, "num_frames": 14, "fps": 7},
            )
        finally:
            process_gpu_task.pop_request()

        assert res.get("status") == "COMPLETED"
        assert res.get("filename") == "gen_video_12345.mp4"

        # Check update_state calls have percent and status keys
        assert len(states) >= 2
        for state, meta in states:
            assert state == "PROGRESS"
            assert "percent" in meta
            assert "status" in meta
            assert isinstance(meta["percent"], int)
            assert isinstance(meta["status"], str)

        # Check Redis updates
        redis_updates = [msg for chan, msg in published_redis if chan == "task_updates"]
        assert len(redis_updates) >= 2
        assert redis_updates[0]["progress"] == 50
        assert redis_updates[1]["progress"] == 90

        # Check DB task row
        db_task = db_session.query(Task).filter(Task.task_id == "test-celery-video-task").first()
        assert db_task is not None
        assert db_task.progress in (90, 100)

    def test_process_gpu_task_guard_refusal_returns_degraded_contract(self, monkeypatch, stub_storage):
        """VRAM guard refusal inside process_gpu_task returns degraded response with SUCCESS state."""
        from app.tasks import process_gpu_task

        test_bytes = create_test_png_bytes()
        stub_storage["uploaded"]["test.png"] = {"data": test_bytes, "content_type": "image/png"}

        monkeypatch.setattr(
            vram_guard,
            "check_vram",
            lambda model_id, **kwargs: (_ for _ in ()).throw(NoGPUError(model_id="svd")),
        )

        process_gpu_task.push_request(id="test-refusal-task")
        try:
            res = process_gpu_task.run(
                "svd",
                payload={"op": "image_to_video", "source": "test.png", "num_frames": 14, "fps": 7},
            )
        finally:
            process_gpu_task.pop_request()

        assert isinstance(res, dict)
        assert res.get("degraded") is True
        assert res.get("reason") == DegradedReason.NO_GPU.value


class TestGenerateVideoEndpoint:
    def test_validation_path_traversals(self, client):
        """POST /api/generate/video rejects path traversals and absolute paths with 400."""
        for bad_source in [
            "../secret.png",
            "/absolute/path.png",
            "dir/../../escaped.png",
            "escaped\\backslash.png",
            "",
            "   ",
        ]:
            res = client.post(f"/api/generate/video?source={bad_source}")
            assert res.status_code == 400, f"Expected 400 for bad source '{bad_source}'"

    def test_validation_missing_source_in_storage(self, client, stub_storage):
        """POST /api/generate/video returns 400 when source file does not exist in storage."""
        res = client.post("/api/generate/video?source=nonexistent.png")
        assert res.status_code == 400
        assert "not found" in res.json().get("detail", "").lower()

    def test_validation_corrupt_source_image_in_storage(self, client, stub_storage):
        """POST /api/generate/video returns 400 when source file is unreadable/corrupt."""
        stub_storage["uploaded"]["corrupt.png"] = {"data": b"not-image-data-corrupted", "content_type": "image/png"}
        res = client.post("/api/generate/video?source=corrupt.png")
        assert res.status_code == 400
        assert "unreadable or corrupt" in res.json().get("detail", "").lower()

    def test_validation_num_frames_bounds(self, client, stub_storage):
        """POST /api/generate/video validates num_frames in range 2..25."""
        stub_storage["uploaded"]["input.png"] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        res_low = client.post("/api/generate/video?source=input.png&num_frames=1")
        assert res_low.status_code == 400
        assert "num_frames" in res_low.json().get("detail", "")

        res_high = client.post("/api/generate/video?source=input.png&num_frames=26")
        assert res_high.status_code == 400
        assert "num_frames" in res_high.json().get("detail", "")

    def test_validation_fps_bounds(self, client, stub_storage):
        """POST /api/generate/video validates fps in range 1..30."""
        stub_storage["uploaded"]["input.png"] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        res_low = client.post("/api/generate/video?source=input.png&fps=0")
        assert res_low.status_code == 400
        assert "fps" in res_low.json().get("detail", "")

        res_high = client.post("/api/generate/video?source=input.png&fps=31")
        assert res_high.status_code == 400
        assert "fps" in res_high.json().get("detail", "")

    def test_endpoint_dispatch_returns_task_id(self, client, stub_storage, monkeypatch):
        """POST /api/generate/video dispatches to process_gpu_task and returns Celery task_id."""
        stub_storage["uploaded"]["input.png"] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        delay_calls = []
        class MockCeleryResult:
            id = "celery-video-task-456"

        def fake_delay(model_id, payload):
            delay_calls.append((model_id, payload))
            return MockCeleryResult()

        import app.tasks as tasks_module
        monkeypatch.setattr(tasks_module.process_gpu_task, "delay", fake_delay)

        res = client.post("/api/generate/video?source=input.png&num_frames=14&fps=7")
        assert res.status_code == 200
        body = res.json()

        assert body["task_id"] == "celery-video-task-456"
        assert body["status"] == "PENDING"
        assert body["type"] == "video"
        assert body["source"] == "input.png"
        assert body["num_frames"] == 14
        assert body["fps"] == 7

        assert len(delay_calls) == 1
        assert delay_calls[0][0] == "svd"
        assert delay_calls[0][1]["op"] == "image_to_video"
        assert delay_calls[0][1]["source"] == "input.png"

    def test_endpoint_routes_to_colab_when_connected(self, client, stub_storage, monkeypatch):
        """POST /api/generate/video routes to Colab when Colab worker is connected."""
        stub_storage["uploaded"]["input.png"] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        import app.routers.generate as gen_router
        monkeypatch.setattr(gen_router, "is_colab_connected", lambda: True)

        dispatched = []
        def fake_dispatch(task_type, parameters, db, **kwargs):
            dispatched.append((task_type, parameters))
            return {
                "status": "COMPLETED",
                "colab": True,
                "task_id": "colab_video_task_789",
            }

        monkeypatch.setattr(gen_router, "dispatch_gen_to_colab", fake_dispatch)

        res = client.post("/api/generate/video?source=input.png&num_frames=14&fps=7")
        assert res.status_code == 200
        body = res.json()
        assert body["colab"] is True
        assert len(dispatched) == 1
        assert dispatched[0][0] == "video_generation"
        assert dispatched[0][1]["source"] == "input.png"
        assert dispatched[0][1]["num_frames"] == 14
        assert dispatched[0][1]["fps"] == 7
