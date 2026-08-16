"""Tests for MVV frame-by-frame video upscaling (map #62, ticket #64).

Covers the ffprobe helpers, the local ``run_video_upscale_task`` pipeline
(extract -> per-frame upscale -> re-encode -> upload), and the
``process_media_heavy`` routing for the ``video_upscale`` task type.
"""

import io
from pathlib import Path

import pytest
from PIL import Image

from app.models import MediaAsset
from app.upscaler import UpscaleParams

from app.tasks import (
    parse_duration,
    parse_frame_rate,
    probe_audio_codec,
    run_video_upscale_task,
    record_upscaled_asset,
    process_media_heavy,
    process_multimedia_task,
)


def _png_bytes(width=32, height=24, color=(80, 110, 180)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeSelf:
    request = type("Req", (), {"id": "video-task-1", "retries": 0})()

    def update_state(self, *args, **kwargs):
        pass


class TestFfprobeHelpers:
    def test_parse_frame_rate_rational(self, monkeypatch):
        class Result:
            stdout = "30000/1001\n"
            returncode = 0

        monkeypatch.setattr("app.tasks.subprocess.run", lambda *a, **k: Result())
        assert abs(parse_frame_rate("clip.mp4") - 29.97) < 0.01

    def test_parse_frame_rate_integer(self, monkeypatch):
        class Result:
            stdout = "30\n"
            returncode = 0

        monkeypatch.setattr("app.tasks.subprocess.run", lambda *a, **k: Result())
        assert parse_frame_rate("clip.mp4") == 30.0

    def test_parse_frame_rate_error_returns_zero(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("ffprobe missing")

        monkeypatch.setattr("app.tasks.subprocess.run", boom)
        assert parse_frame_rate("clip.mp4") == 0.0

    def test_probe_audio_codec_returns_codec(self, monkeypatch):
        class Result:
            stdout = "aac\n"
            returncode = 0

        monkeypatch.setattr("app.tasks.subprocess.run", lambda *a, **k: Result())
        assert probe_audio_codec("clip.mp4") == "aac"

    def test_probe_audio_codec_empty_when_no_audio(self, monkeypatch):
        class Result:
            stdout = ""
            returncode = 0

        monkeypatch.setattr("app.tasks.subprocess.run", lambda *a, **k: Result())
        assert probe_audio_codec("clip.mp4") == ""

    def test_probe_audio_codec_error_returns_empty(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("ffprobe missing")

        monkeypatch.setattr("app.tasks.subprocess.run", boom)
        assert probe_audio_codec("clip.mp4") == ""


class TestRecordUpscaledAssetVideo:
    def test_records_video_media_asset(self, db_session):
        asset = record_upscaled_asset(
            db_session,
            object_name="clips/short.mp4",
            processed_name="processed/video_upscaled_short.mp4",
            processed_url="http://test-minio/processed/video_upscaled_short.mp4",
            params=None,
            content_type="video/mp4",
            duration=12.5,
        )
        assert asset is not None
        assert asset.content_type == "video/mp4"
        assert asset.duration == 12.5
        assert asset.source_path == "clips/short.mp4"


class TestRunVideoUpscaleTask:
    def test_full_pipeline_uploads_video(self, monkeypatch, stub_storage, stub_redis, db_session):
        # Replace ffprobe/ffmpeg with fakes that simulate extraction + re-encode.
        calls = {"extract": 0, "encode": 0}

        def _fake_download(bucket, key, path):
            Path(path).write_bytes(b"fake-clip-bytes")

        def _fake_duration(path):
            return 1.0

        def _fake_fps(path):
            return 30.0

        def _fake_audio(path):
            return "aac"

        def _fake_ffmpeg(cmd, duration, task_id, celery_task=None):
            cmd_str = " ".join(cmd)
            if "-c:v png" in cmd_str:
                # Simulate frame extraction: write two PNGs into frames dir.
                out_template = cmd[-1]
                frames_dir = Path(out_template).parent
                for i in (1, 2):
                    (frames_dir / f"frame_{i:06d}.png").write_bytes(_png_bytes())
                calls["extract"] += 1
            else:
                # Simulate re-encode: write a fake mp4 to the last arg.
                Path(cmd[-1]).write_bytes(b"fake-upscaled-mp4")
                calls["encode"] += 1

        class _FakeS3:
            def download_file(self, bucket, key, path):
                _fake_download(bucket, key, path)

        monkeypatch.setattr("app.storage.s3_client", _FakeS3(), raising=False)
        monkeypatch.setattr("app.tasks.parse_duration", _fake_duration)
        monkeypatch.setattr("app.tasks.parse_frame_rate", _fake_fps)
        monkeypatch.setattr("app.tasks.probe_audio_codec", _fake_audio)
        monkeypatch.setattr("app.tasks.run_ffmpeg_with_progress", _fake_ffmpeg)

        params = UpscaleParams(denoise=0.4, hdr=0.5, fractality=0.2)
        result = run_video_upscale_task(
            "clips/short.mp4", params, task_id="video-task-1", scale=2.0
        )

        assert calls["extract"] == 1
        assert calls["encode"] == 1
        assert result["status"] == "COMPLETED"
        assert result["processed_name"] == "processed/video_upscaled_short.mp4"
        assert result["processed_url"].startswith("http://test-minio/")
        assert result["frames"] == 2
        assert result["duration"] == 1.0
        assert result["colab"] is False
        assert "processed/video_upscaled_short.mp4" in stub_storage["uploaded"]
        uploaded = stub_storage["uploaded"]["processed/video_upscaled_short.mp4"]
        assert uploaded["content_type"] == "video/mp4"

    def test_missing_source_raises(self, monkeypatch, stub_storage, stub_redis):
        def _no_download(bucket, key, path):
            raise FileNotFoundError("no such object")

        monkeypatch.setattr(
            "app.storage.s3_client",
            type("S", (), {"download_file": _no_download})(),
            raising=False,
        )
        monkeypatch.setattr("app.tasks.parse_duration", lambda p: 1.0)
        monkeypatch.setattr("app.tasks.parse_frame_rate", lambda p: 30.0)
        monkeypatch.setattr("app.tasks.probe_audio_codec", lambda p: "aac")
        with pytest.raises(Exception):
            run_video_upscale_task(
                "clips/missing.mp4", UpscaleParams(), task_id="video-task-2"
            )


class TestProcessMediaHeavyVideoRouting:
    def test_video_upscale_runs_local_task_and_records_asset(
        self, monkeypatch, stub_storage, stub_redis, db_session
    ):
        captured = {}

        def _fake_run_video(object_name, params, task_id=None, celery_task=None):
            captured["object_name"] = object_name
            captured["params"] = params
            return {
                "status": "COMPLETED",
                "task_id": task_id,
                "original_object": object_name,
                "processed_url": "http://test-minio/processed/video_upscaled_short.mp4",
                "processed_name": "processed/video_upscaled_short.mp4",
                "duration": 5.0,
                "frames": 150,
                "params": params.as_colab_parameters(),
                "colab": False,
            }

        monkeypatch.setattr("app.tasks.run_video_upscale_task", _fake_run_video)

        raw = process_media_heavy.run.__func__
        result = raw(
            _FakeSelf(),
            "clips/short.mp4",
            "video_upscale",
            denoise=0.5,
            hdr=0.3,
            fractality=0.1,
            prompt="smooth motion",
        )

        assert captured["object_name"] == "clips/short.mp4"
        assert captured["params"].denoise == 0.5
        assert captured["params"].hdr == 0.3
        assert captured["params"].prompt == "smooth motion"
        assert result["status"] == "COMPLETED"

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == "processed/video_upscaled_short.mp4")
            .first()
        )
        assert asset is not None
        assert asset.content_type == "video/mp4"
        assert asset.source_path == "clips/short.mp4"
        assert asset.duration == 5.0

    def test_multimedia_task_forwards_video_upscale_kwargs(self, monkeypatch, stub_redis):
        """The duplicate process_multimedia_task must not swallow upscale kwargs."""
        captured = {}

        def _fake_heavy(object_name, task_type, **kwargs):
            captured["object_name"] = object_name
            captured["task_type"] = task_type
            captured["kwargs"] = kwargs

        monkeypatch.setattr("app.tasks.process_media_heavy", _fake_heavy)

        raw = process_multimedia_task.run.__func__
        raw(_FakeSelf(), "clips/short.mp4", "video_upscale", denoise=0.6, fractality=0.4)

        assert captured["object_name"] == "clips/short.mp4"
        assert captured["task_type"] == "video_upscale"
        assert captured["kwargs"]["denoise"] == 0.6
        assert captured["kwargs"]["fractality"] == 0.4
