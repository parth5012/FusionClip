"""Unit tests for the export_batch_zip Celery task body (Wayfinder ticket #48)."""

import io
import zipfile


class _FakeSelf:
    request = type("Req", (), {"id": "task-abc"})()

    def update_state(self, *args, **kwargs):
        pass


class TestExportBatchZipTask:
    def test_task_zips_objects_and_uploads_archive(
        self, monkeypatch, stub_storage, stub_redis
    ):
        from app.tasks import export_batch_zip

        def _stream(object_name):
            yield b"content-of-" + object_name.encode()

        monkeypatch.setattr("app.storage.get_object_stream", _stream, raising=False)

        raw = export_batch_zip.run.__func__
        result = raw(_FakeSelf(), ["a.txt", "folder/b.txt"], "original")

        assert result["count"] == 2
        assert result["filename"] == "batch_task-abc.zip"
        assert result["url"] == "http://test-minio/exports/batch_task-abc.zip"

        uploaded = stub_storage["uploaded"]["exports/batch_task-abc.zip"]
        archive = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        assert set(archive.namelist()) == {"a.txt", "b.txt"}
        assert archive.read("a.txt") == b"content-of-a.txt"
        assert archive.read("b.txt") == b"content-of-folder/b.txt"

    def test_task_skips_missing_objects(
        self, monkeypatch, stub_storage, stub_redis
    ):
        from app.tasks import export_batch_zip

        def _stream(object_name):
            if object_name == "missing.bin":
                return
            yield b"data"

        monkeypatch.setattr("app.storage.get_object_stream", _stream, raising=False)

        raw = export_batch_zip.run.__func__
        result = raw(_FakeSelf(), ["ok.txt", "missing.bin"], "original")

        assert result["count"] == 1

    def test_task_keeps_original_when_conversion_unsupported(
        self, monkeypatch, stub_storage, stub_redis
    ):
        from app.tasks import export_batch_zip

        def _stream(object_name):
            yield b"raw-bytes"

        monkeypatch.setattr("app.storage.get_object_stream", _stream, raising=False)

        raw = export_batch_zip.run.__func__
        result = raw(_FakeSelf(), ["photo.png"], "image-webp")

        assert result["count"] == 1
        uploaded = stub_storage["uploaded"]["exports/batch_task-abc.zip"]
        archive = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        # Pillow is not guaranteed installed; falls back to original bytes
        assert archive.read("photo.png") == b"raw-bytes"
