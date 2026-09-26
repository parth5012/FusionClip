"""Tests for batch asset select + zip export with derivatives (Wayfinder ticket #106)."""

import io
import zipfile
import pytest
from app.models import MediaAsset, Task


class _FakeAsyncResult:
    def __init__(self, task_id="export-test-123", status="PENDING"):
        self.id = task_id
        self.status = status


class _FakeCeleryTask:
    def __init__(self, task_id="export-task-celery"):
        self.request = type("Req", (), {"id": task_id})()

    def update_state(self, *args, **kwargs):
        pass


class TestBatchExportApi:
    def test_empty_asset_ids_returns_400(self, client):
        res = client.post("/api/export/batch", json={"asset_ids": []})
        assert res.status_code == 400
        assert "empty" in res.json()["detail"].lower() or "no assets" in res.json()["detail"].lower()

    def test_missing_asset_ids_field_returns_400(self, client):
        res = client.post("/api/export/batch", json={})
        assert res.status_code == 400

    def test_unknown_asset_id_returns_400(self, client, db_session):
        asset = MediaAsset(
            title="Real Asset",
            file_path="real.png",
            file_size=100,
            content_type="image/png",
        )
        db_session.add(asset)
        db_session.commit()

        res = client.post("/api/export/batch", json={"asset_ids": [asset.id, 99999]})
        assert res.status_code == 400
        assert "99999" in res.json()["detail"] or "not found" in res.json()["detail"].lower()

    def test_asset_ids_over_100_rejected_with_400(self, client):
        oversized = list(range(1, 102))  # 101 items
        res = client.post("/api/export/batch", json={"asset_ids": oversized})
        assert res.status_code == 400

    def test_valid_asset_ids_enqueues_task_and_creates_db_record(
        self, client, db_session, monkeypatch
    ):
        asset1 = MediaAsset(
            title="Asset 1",
            file_path="assets/a1.mp4",
            file_size=1024,
            content_type="video/mp4",
        )
        asset2 = MediaAsset(
            title="Asset 2",
            file_path="assets/a2.jpg",
            file_size=512,
            content_type="image/jpeg",
        )
        db_session.add_all([asset1, asset2])
        db_session.commit()

        dispatched = {}

        def _fake_apply_async(args=None, kwargs=None, task_id=None):
            dispatched["args"] = args
            dispatched["kwargs"] = kwargs
            dispatched["task_id"] = task_id
            return _FakeAsyncResult(task_id=task_id)

        monkeypatch.setattr(
            "app.tasks.export_assets_zip.apply_async",
            _fake_apply_async,
            raising=False,
        )

        res = client.post(
            "/api/export/batch",
            json={"asset_ids": [asset1.id, asset2.id], "include_derivatives": True},
        )
        assert res.status_code == 200
        data = res.json()
        assert "task_id" in data
        assert data["status"] == "PENDING"

        task_id = data["task_id"]
        # Verify Task record in DB
        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task is not None
        assert db_task.name == "batch_export"
        assert db_task.status == "PENDING"
        assert db_task.progress == 0


class TestBatchExportCeleryTask:
    def test_export_assets_zip_collects_originals_and_derivatives(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        # Create parent asset
        parent = MediaAsset(
            title="Hero Image",
            file_path="images/hero.png",
            file_size=2000,
            content_type="image/png",
        )
        db_session.add(parent)
        db_session.commit()

        # Create derivative asset pointing to parent
        derivative = MediaAsset(
            title="Hero Upscaled 4x",
            file_path="upscaled/hero_4x.png",
            file_size=8000,
            content_type="image/png",
            source_path="images/hero.png",
        )
        db_session.add(derivative)

        # Create Task DB record
        task_id = "test-export-task-1"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add(db_task)
        db_session.commit()

        # Populate stub storage
        stub_storage["uploaded"]["images/hero.png"] = {
            "data": b"hero-original-bytes",
            "content_type": "image/png",
        }
        stub_storage["uploaded"]["upscaled/hero_4x.png"] = {
            "data": b"hero-upscaled-bytes",
            "content_type": "image/png",
        }

        # Run celery task synchronously
        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[parent.id],
            include_derivatives=True,
        )

        assert result["count"] == 2
        assert result["filename"] == f"export_{task_id}.zip"
        assert "url" in result

        # Check uploaded archive in storage
        export_key = f"exports/export_{task_id}.zip"
        assert export_key in stub_storage["uploaded"]
        zip_data = stub_storage["uploaded"][export_key]["data"]
        archive = zipfile.ZipFile(io.BytesIO(zip_data))
        namelist = archive.namelist()
        assert len(namelist) == 2
        # Check files are inside archive
        names_str = " ".join(namelist)
        assert "hero.png" in names_str
        assert "hero_4x.png" in names_str

        # Check DB task status
        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "COMPLETED"
        assert db_task.progress == 100

    def test_export_assets_zip_without_derivatives_flag(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        parent = MediaAsset(
            title="Parent Image",
            file_path="images/parent.png",
            file_size=1000,
            content_type="image/png",
        )
        db_session.add(parent)
        db_session.commit()

        derivative = MediaAsset(
            title="Derivative Image",
            file_path="upscaled/deriv.png",
            file_size=4000,
            content_type="image/png",
            source_path="images/parent.png",
        )
        task_id = "test-export-no-deriv"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add_all([derivative, db_task])
        db_session.commit()

        stub_storage["uploaded"]["images/parent.png"] = {
            "data": b"parent-data",
            "content_type": "image/png",
        }
        stub_storage["uploaded"]["upscaled/deriv.png"] = {
            "data": b"deriv-data",
            "content_type": "image/png",
        }

        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[parent.id],
            include_derivatives=False,
        )

        assert result["count"] == 1
        export_key = f"exports/export_{task_id}.zip"
        archive = zipfile.ZipFile(io.BytesIO(stub_storage["uploaded"][export_key]["data"]))
        assert archive.namelist() == ["parent.png"]

    def test_export_assets_zip_handles_zero_byte_entry_safely(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        asset = MediaAsset(
            title="Zero Byte File",
            file_path="empty/zero.txt",
            file_size=0,
            content_type="text/plain",
        )
        task_id = "test-export-zero-byte"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add_all([asset, db_task])
        db_session.commit()

        stub_storage["uploaded"]["empty/zero.txt"] = {
            "data": b"",
            "content_type": "text/plain",
        }

        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[asset.id],
            include_derivatives=False,
        )

        assert result["count"] == 1
        export_key = f"exports/export_{task_id}.zip"
        archive = zipfile.ZipFile(io.BytesIO(stub_storage["uploaded"][export_key]["data"]))
        assert archive.namelist() == ["zero.txt"]
        assert archive.read("zero.txt") == b""

    def test_export_assets_zip_skips_missing_derivative_without_failing(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        parent = MediaAsset(
            title="Video Clip",
            file_path="videos/clip.mp4",
            file_size=5000,
            content_type="video/mp4",
        )
        db_session.add(parent)
        db_session.commit()

        # Derivative exists in DB but not in storage
        missing_deriv = MediaAsset(
            title="Missing Upscale",
            file_path="upscaled/missing.mp4",
            file_size=10000,
            content_type="video/mp4",
            source_path="videos/clip.mp4",
        )
        db_session.add(missing_deriv)

        task_id = "test-export-task-missing"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add(db_task)
        db_session.commit()

        stub_storage["uploaded"]["videos/clip.mp4"] = {
            "data": b"clip-bytes",
            "content_type": "video/mp4",
        }
        # missing.mp4 is intentionally NOT in stub_storage

        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[parent.id],
            include_derivatives=True,
        )

        # Parent is zipped; missing derivative is skipped and noted
        assert result["count"] == 1
        assert len(result.get("skipped", [])) == 1

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "COMPLETED"

    def test_export_assets_zip_handles_storage_upload_failure(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        parent = MediaAsset(
            title="Audio",
            file_path="audio/track.mp3",
            file_size=100,
            content_type="audio/mpeg",
        )
        task_id = "test-export-fail"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add_all([parent, db_task])
        db_session.commit()

        stub_storage["uploaded"]["audio/track.mp3"] = {
            "data": b"mp3-bytes",
            "content_type": "audio/mpeg",
        }

        # Mock upload_object to return False (storage failure)
        def _failing_upload(*args, **kwargs):
            return False

        monkeypatch.setattr("app.tasks.upload_object", _failing_upload)

        raw = export_assets_zip.run.__func__
        with pytest.raises(Exception):
            raw(
                _FakeCeleryTask(task_id=task_id),
                asset_ids=[parent.id],
                include_derivatives=False,
            )

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "FAILED"
        assert db_task.error is not None
        assert db_task.traceback is not None

    def test_export_assets_zip_sanitizes_zip_slip_and_windows_paths(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        # Path with traversal tokens
        malicious = MediaAsset(
            title="Evil Asset",
            file_path="uploads/../../evil.sh",
            file_size=100,
            content_type="application/x-sh",
        )
        # Windows-style path with backslashes
        win_asset = MediaAsset(
            title="Windows Asset",
            file_path="sub\\dir\\nested\\test.txt",
            file_size=50,
            content_type="text/plain",
        )
        task_id = "test-zip-slip-task"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add_all([malicious, win_asset, db_task])
        db_session.commit()

        stub_storage["uploaded"]["uploads/../../evil.sh"] = {
            "data": b"echo evil",
            "content_type": "text/plain",
        }
        stub_storage["uploaded"]["sub\\dir\\nested\\test.txt"] = {
            "data": b"hello windows",
            "content_type": "text/plain",
        }

        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[malicious.id, win_asset.id],
            include_derivatives=False,
        )

        assert result["count"] == 2
        export_key = f"exports/export_{task_id}.zip"
        archive = zipfile.ZipFile(io.BytesIO(stub_storage["uploaded"][export_key]["data"]))
        namelist = archive.namelist()
        for name in namelist:
            assert ".." not in name
            assert "\\" not in name
            assert not name.startswith("/")
        assert "evil.sh" in namelist
        assert "test.txt" in namelist

    def test_export_assets_zip_excludes_duplicate_when_parent_and_child_both_selected(
        self, db_session, stub_storage, stub_redis, monkeypatch
    ):
        from app.tasks import export_assets_zip

        parent = MediaAsset(
            title="Parent Image",
            file_path="images/orig.png",
            file_size=1000,
            content_type="image/png",
        )
        db_session.add(parent)
        db_session.commit()

        derivative = MediaAsset(
            title="Child Image",
            file_path="upscaled/child.png",
            file_size=4000,
            content_type="image/png",
            source_path="images/orig.png",
        )
        task_id = "test-dup-task"
        db_task = Task(
            task_id=task_id,
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add_all([derivative, db_task])
        db_session.commit()

        stub_storage["uploaded"]["images/orig.png"] = {
            "data": b"orig-data",
            "content_type": "image/png",
        }
        stub_storage["uploaded"]["upscaled/child.png"] = {
            "data": b"child-data",
            "content_type": "image/png",
        }

        # Select BOTH parent and derivative explicitly
        raw = export_assets_zip.run.__func__
        result = raw(
            _FakeCeleryTask(task_id=task_id),
            asset_ids=[parent.id, derivative.id],
            include_derivatives=True,
        )

        # Count must be exactly 2 (not 3!)
        assert result["count"] == 2
        export_key = f"exports/export_{task_id}.zip"
        archive = zipfile.ZipFile(io.BytesIO(stub_storage["uploaded"][export_key]["data"]))
        assert len(archive.namelist()) == 2


class TestExportStatusAndDownload:
    def test_status_returns_404_for_unknown_task(self, client):
        res = client.get("/api/export/nonexistent-task")
        assert res.status_code == 404

    def test_status_returns_progress_for_in_progress_task(self, client, db_session):
        task = Task(
            task_id="export-prog-1",
            name="batch_export",
            status="PROCESSING",
            progress=45,
        )
        db_session.add(task)
        db_session.commit()

        res = client.get("/api/export/export-prog-1")
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"] == "export-prog-1"
        assert data["status"] == "PROCESSING"
        assert data["progress"] == 45
        assert data["download_url"] is None

    def test_status_returns_presigned_url_when_completed(self, client, db_session):
        task = Task(
            task_id="export-done-1",
            name="batch_export",
            status="COMPLETED",
            progress=100,
        )
        db_session.add(task)
        db_session.commit()

        res = client.get("/api/export/export-done-1")
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"] == "export-done-1"
        assert data["status"] == "COMPLETED"
        assert data["progress"] == 100
        assert data["download_url"] is not None
        assert "export_export-done-1.zip" in data["download_url"]

    def test_download_endpoint_returns_404_for_unknown_task(self, client):
        res = client.get("/api/export/download/unknown-id")
        assert res.status_code == 404

    def test_download_endpoint_returns_400_for_uncompleted_task(self, client, db_session):
        task = Task(
            task_id="export-pending-1",
            name="batch_export",
            status="PENDING",
            progress=0,
        )
        db_session.add(task)
        db_session.commit()

        res = client.get("/api/export/download/export-pending-1")
        assert res.status_code == 400
        assert "not completed" in res.json()["detail"].lower()

    def test_download_endpoint_returns_url_for_completed_task(self, client, db_session):
        task = Task(
            task_id="export-ready-1",
            name="batch_export",
            status="COMPLETED",
            progress=100,
        )
        db_session.add(task)
        db_session.commit()

        res = client.get("/api/export/download/export-ready-1")
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"] == "export-ready-1"
        assert "export_export-ready-1.zip" in data["download_url"]
