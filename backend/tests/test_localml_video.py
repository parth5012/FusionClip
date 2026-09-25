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

    def test_make_video_loader_picks_dtype_by_device(self, monkeypatch):
        """make_video_loader selects float32 on CPU and float16 on GPU (F1)."""
        import sys
        from app.ml.video import make_video_loader

        mock_torch = MagicMock()
        mock_torch.float16 = "mock_float16"
        mock_torch.float32 = "mock_float32"

        mock_pipe = MagicMock()
        mock_diffusers = MagicMock()
        mock_diffusers.StableVideoDiffusionPipeline.from_pretrained.return_value = mock_pipe

        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        monkeypatch.setitem(sys.modules, "diffusers", mock_diffusers)

        # 1. On CPU (cuda=False) -> must select float32
        mock_torch.cuda.is_available.return_value = False
        loader_cpu = make_video_loader("svd")
        pipe_cpu = loader_cpu()
        mock_diffusers.StableVideoDiffusionPipeline.from_pretrained.assert_called_with(
            "stabilityai/stable-video-diffusion-img2vid-xt",
            torch_dtype="mock_float32",
        )
        pipe_cpu.to.assert_called_with("cpu")

        # 2. On GPU (cuda=True) -> must select float16 and enable offload
        mock_torch.cuda.is_available.return_value = True
        loader_gpu = make_video_loader("svd")
        pipe_gpu = loader_gpu()
        mock_diffusers.StableVideoDiffusionPipeline.from_pretrained.assert_called_with(
            "stabilityai/stable-video-diffusion-img2vid-xt",
            torch_dtype="mock_float16",
        )
        pipe_gpu.enable_model_cpu_offload.assert_called_once()



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

    def test_encode_frames_to_mp4_real_ffmpeg_failure_captures_exit_code_and_stderr(self):
        """Genuine ffmpeg failure raises VideoEncodingError with exit code and stderr lines (F9)."""
        from app.ml.video import encode_frames_to_mp4, VideoEncodingError

        frames = [Image.new("RGB", (64, 64))]
        # framerate 0 is an invalid video rate in ffmpeg and causes immediate non-zero exit
        with pytest.raises(VideoEncodingError) as exc_info:
            encode_frames_to_mp4(frames, fps=0)

        err = exc_info.value
        assert err.returncode is not None and err.returncode != 0
        assert f"exit code {err.returncode}" in str(err)
        assert err.stderr is not None
        assert "Unable to parse option value" in err.stderr or "Error" in err.stderr

    def test_encode_frames_to_mp4_timeout_raises_encoding_error(self, monkeypatch):
        """When ffmpeg stalls or exceeds bounded timeout, VideoEncodingError is raised and child killed (F4)."""
        import subprocess
        from app.ml.video import encode_frames_to_mp4, VideoEncodingError

        frames = [Image.new("RGB", (64, 64))]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.returncode = None
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.fileno.return_value = 999
        mock_proc.stderr.read.return_value = ""

        # Make select return empty (timeout)
        monkeypatch.setattr("select.select", lambda r, w, x, t: ([], [], []))
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        with pytest.raises(VideoEncodingError, match="timed out"):
            encode_frames_to_mp4(frames, fps=7, timeout=0.01)

        mock_proc.kill.assert_called_once()
        mock_proc.stderr.close.assert_called_once()

    def test_encode_frames_to_mp4_cleans_up_child_on_callback_exception(self, monkeypatch):
        """When progress_cb raises an exception, the child process is killed and stderr closed (F4)."""
        import subprocess
        from app.ml.video import encode_frames_to_mp4

        frames = [Image.new("RGB", (64, 64))]

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.returncode = None
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.fileno.return_value = 999
        # Simulate frame progress output
        mock_proc.stderr.read.side_effect = ["f", "r", "a", "m", "e", "=", " ", "1", "\n", ""]

        monkeypatch.setattr("select.select", lambda r, w, x, t: ([mock_proc.stderr], [], []))
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        def exploding_cb(pct, status):
            raise RuntimeError("Progress callback crashed")

        with pytest.raises(RuntimeError, match="Progress callback crashed"):
            encode_frames_to_mp4(frames, fps=7, progress_cb=exploding_cb)

        mock_proc.kill.assert_called_once()
        mock_proc.stderr.close.assert_called_once()



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

    def test_process_gpu_task_guard_refusal_returns_degraded_contract(self, monkeypatch, stub_storage, stub_redis):
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

    def test_process_gpu_task_exception_records_failed_in_db_and_publishes(
        self, monkeypatch, db_session, stub_storage
    ):
        """Unexpected exceptions in process_gpu_task mark DB Task FAILED and publish terminal event (F3a)."""
        import app.tasks as tasks_module
        from app.tasks import process_gpu_task

        test_source = "uploads/corrupt.png"
        stub_storage["uploaded"][test_source] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        # Simulate unexpected inference crash
        def crashing_run(*args, **kwargs):
            raise RuntimeError("Unexpected GPU inference kernel crash")

        import app.ml.video as vid_mod
        monkeypatch.setattr(vid_mod, "run_local_image_to_video", crashing_run)
        monkeypatch.setattr("app.ml.video.run_local_image_to_video", crashing_run, raising=False)

        published_redis = []
        monkeypatch.setattr(
            tasks_module.redis_client,
            "publish",
            lambda channel, msg: published_redis.append((channel, json.loads(msg))),
        )

        task_id = "test-gpu-crash-task"
        process_gpu_task.push_request(id=task_id)
        try:
            with pytest.raises(RuntimeError, match="Unexpected GPU inference kernel crash"):
                process_gpu_task.run(
                    "svd",
                    payload={"op": "image_to_video", "source": test_source, "num_frames": 14, "fps": 7},
                )
        finally:
            process_gpu_task.pop_request()

        # 1. DB Task row must exist and be FAILED, not PROCESSING
        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task is not None
        assert db_task.status == "FAILED"
        assert "Unexpected GPU inference kernel crash" in db_task.error

        # 2. Redis task_updates must have received terminal FAILED event
        failed_events = [
            msg for chan, msg in published_redis
            if chan == "task_updates" and msg.get("task_id") == task_id and msg.get("status") == "FAILED"
        ]
        assert len(failed_events) >= 1
        assert "Unexpected GPU inference kernel crash" in failed_events[0]["error"]

    def test_process_gpu_task_degraded_publishes_terminal_event_and_updates_db(
        self, monkeypatch, db_session, stub_storage
    ):
        """Degraded responses from local video inference update DB Task to FAILED and publish terminal event (F3b)."""
        import app.tasks as tasks_module
        from app.tasks import process_gpu_task

        test_source = "uploads/refused.png"
        stub_storage["uploaded"][test_source] = {"data": create_test_png_bytes(), "content_type": "image/png"}

        # Simulate degraded response from run_local_image_to_video
        def degraded_run(*args, **kwargs):
            return {
                "degraded": True,
                "reason": "no_gpu",
                "message": "No CUDA GPU detected on host",
                "fallback_tier": "refusal",
            }

        import app.ml.video as vid_mod
        monkeypatch.setattr(vid_mod, "run_local_image_to_video", degraded_run)
        monkeypatch.setattr("app.ml.video.run_local_image_to_video", degraded_run, raising=False)

        published_redis = []
        monkeypatch.setattr(
            tasks_module.redis_client,
            "publish",
            lambda channel, msg: published_redis.append((channel, json.loads(msg))),
        )

        task_id = "test-gpu-degraded-task"
        process_gpu_task.push_request(id=task_id)
        try:
            res = process_gpu_task.run(
                "svd",
                payload={"op": "image_to_video", "source": test_source, "num_frames": 14, "fps": 7},
            )
        finally:
            process_gpu_task.pop_request()

        assert res.get("degraded") is True

        # 1. DB Task must not be PROCESSING or COMPLETED
        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task is not None
        assert db_task.status == "FAILED"
        assert "No CUDA GPU detected on host" in (db_task.error or "")

        # 2. Redis task_updates must have received terminal FAILED event
        terminal_events = [
            msg for chan, msg in published_redis
            if chan == "task_updates" and msg.get("task_id") == task_id and msg.get("status") == "FAILED"
        ]
        assert len(terminal_events) == 1
        assert terminal_events[0]["degraded"] is True



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

    def test_validation_local_disk_fallback_removed_rejects_disk_files(self, client, stub_storage):
        """Local disk files not in storage must NOT be read (F7 storage isolation)."""
        disk_path = Path("test_disk_isolate.png")
        try:
            disk_path.write_bytes(create_test_png_bytes())
            # Ensure it is NOT in stub_storage
            stub_storage["uploaded"].pop(str(disk_path), None)

            res = client.post(f"/api/generate/video?source={disk_path.name}")
            # Must return 400 because it should not read from host disk
            assert res.status_code == 400
            assert "not found or unreadable in storage" in res.json().get("detail", "").lower()
        finally:
            if disk_path.exists():
                disk_path.unlink()



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
