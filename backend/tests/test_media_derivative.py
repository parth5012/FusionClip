import io
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError

from app.models import MediaAsset
from app.services.media_derivative import (
    MediaDerivativeService,
    DerivativeResult,
    build_derivative_key,
    sanitize_stem,
    record_derivative,
)


class TestMediaDerivativeService:
    def test_sanitize_stem(self):
        """Stem sanitization converts unsafe characters and preserves safe alphanumeric tokens."""
        assert sanitize_stem("uploads/photo.png") == "photo"
        assert sanitize_stem("uploads/photo..v2.png") == "photo_v2"
        assert sanitize_stem("uploads/my portrait (1).png") == "my_portrait_1"
        assert sanitize_stem("../../evil.png") == "evil"
        assert sanitize_stem("..") == "asset"
        assert sanitize_stem("$$$.png") == "asset"
        assert sanitize_stem("uploads/folder/special_name-2026.jpg") == "special_name-2026"

    def test_build_derivative_key_formatting(self):
        """Constructs keys following the standardized pipeline folder and token structure."""
        key = build_derivative_key(
            source_path="uploads/photo.jpg",
            pipeline="skin_enhance",
            token="123456abcdef",
        )
        assert key == "skin_enhanced/photo_123456abcdef.png"

        upscale_key = build_derivative_key(
            source_path="uploads/photo.jpg",
            pipeline="upscale",
            qualifier="4x",
            token="123456abcdef",
        )
        assert upscale_key == "upscaled/photo_4x_123456abcdef.png"

        bg_key = build_derivative_key(
            source_path="uploads/hero.png",
            pipeline="bgremove",
            token="123456abcdef",
        )
        assert bg_key == "bg_removed/hero_123456abcdef.png"

        editor_key = build_derivative_key(
            source_path="uploads/graphic.png",
            pipeline="editor",
            qualifier="v2",
            token="123456abcdef",
        )
        assert editor_key == "edited/graphic_v2_123456abcdef.png"

    def test_record_derivative_success(self, db_session, monkeypatch):
        """Normal execution stores object, commits catalog row with lineage, and returns presigned URL."""
        fake_storage = {}
        monkeypatch.setattr(
            "app.services.media_derivative.upload_object",
            lambda data, name, content_type: fake_storage.setdefault(name, data) is not None or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.generate_url",
            lambda key: f"http://storage.local/{key}",
        )
        monkeypatch.setattr(
            "app.services.media_derivative.get_embedding",
            lambda text: [0.1] * 384,
        )

        dummy_bytes = b"\x89PNG\r\n\x1a\nfakeimagebytes"
        source = "uploads/source_image.png"

        result = record_derivative(
            db=db_session,
            source_path=source,
            file_data=dummy_bytes,
            pipeline="skin_enhance",
            task_token="aabbcc112233",
            qualifier="faithful",
        )

        assert isinstance(result, DerivativeResult)
        assert result.output_path == "skin_enhanced/source_image_faithful_aabbcc112233.png"
        assert result.source_path == source
        assert result.url == f"http://storage.local/{result.output_path}"
        assert result.file_size == len(dummy_bytes)

        # Assert MediaAsset row in database
        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == result.output_path).first()
        assert asset is not None
        assert asset.source_path == source
        assert asset.content_type == "image/png"
        assert asset.file_size == len(dummy_bytes)
        assert asset.embedding is not None

    def test_record_derivative_integrates_with_conftest_stub_storage(self, db_session, stub_storage, monkeypatch):
        """Verify that app.services.media_derivative is properly captured by the stub_storage fixture."""
        monkeypatch.setattr("app.services.media_derivative.get_embedding", lambda text: [0.1] * 384)
        payload = b"binary_data_for_stub_test"
        res = record_derivative(
            db=db_session,
            source_path="uploads/source.png",
            file_data=payload,
            pipeline="editor",
            task_token="tok999",
        )
        assert res.output_path in stub_storage["uploaded"]
        assert stub_storage["uploaded"][res.output_path]["data"] == payload

    def test_record_derivative_atomic_rollback_on_commit_failure(self, db_session, monkeypatch):
        """When db.commit() fails, uploaded storage object is deleted synchronously and error re-raised."""
        deleted_keys = []
        uploaded_keys = []

        monkeypatch.setattr(
            "app.services.media_derivative.upload_object",
            lambda data, name, content_type: uploaded_keys.append(name) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.delete_object",
            lambda key: deleted_keys.append(key) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.get_embedding",
            lambda text: [0.0] * 384,
        )

        # Force commit failure
        monkeypatch.setattr(
            db_session,
            "commit",
            MagicMock(side_effect=SQLAlchemyError("Simulated DB connection drop")),
        )

        dummy_bytes = b"sample_bytes"
        with pytest.raises(SQLAlchemyError, match="Simulated DB connection drop"):
            record_derivative(
                db=db_session,
                source_path="uploads/test.png",
                file_data=dummy_bytes,
                pipeline="upscale",
                task_token="testtoken123",
            )

        assert "upscaled/test_testtoken123.png" in uploaded_keys
        assert "upscaled/test_testtoken123.png" in deleted_keys

    def test_record_derivative_no_session_rollback_when_auto_commit_false(self, db_session, monkeypatch):
        """When auto_commit=False, session rollback is deferred to caller but storage rollback executes."""
        deleted_keys = []
        uploaded_keys = []

        monkeypatch.setattr(
            "app.services.media_derivative.upload_object",
            lambda data, name, content_type: uploaded_keys.append(name) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.delete_object",
            lambda key: deleted_keys.append(key) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.get_embedding",
            lambda text: [0.0] * 384,
        )

        rollback_called = False

        def mock_rollback():
            nonlocal rollback_called
            rollback_called = True

        monkeypatch.setattr(db_session, "rollback", mock_rollback)
        monkeypatch.setattr(
            db_session,
            "flush",
            MagicMock(side_effect=SQLAlchemyError("Flush failure")),
        )

        with pytest.raises(SQLAlchemyError, match="Flush failure"):
            record_derivative(
                db=db_session,
                source_path="uploads/test.png",
                file_data=b"sample_bytes",
                pipeline="upscale",
                task_token="testtoken123",
                auto_commit=False,
            )

        assert "upscaled/test_testtoken123.png" in uploaded_keys
        assert "upscaled/test_testtoken123.png" in deleted_keys
        assert not rollback_called, "db.rollback() should not be called when auto_commit=False"

    def test_record_derivative_sidecar_rollback_on_commit_failure(self, db_session, monkeypatch):
        """Failure to commit cleans up both main derivative and auxiliary sidecars."""
        deleted_keys = []
        uploaded_keys = []

        monkeypatch.setattr(
            "app.services.media_derivative.upload_object",
            lambda data, name, content_type: uploaded_keys.append(name) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.delete_object",
            lambda key: deleted_keys.append(key) or True,
        )
        monkeypatch.setattr(
            "app.services.media_derivative.get_embedding",
            lambda text: [0.0] * 384,
        )

        monkeypatch.setattr(
            db_session,
            "commit",
            MagicMock(side_effect=SQLAlchemyError("Transaction serialization failure")),
        )

        sidecars = {
            "editor_recipes/test_recipe_v1.json": b'{"exposure": 10}',
        }

        with pytest.raises(SQLAlchemyError):
            record_derivative(
                db=db_session,
                source_path="uploads/test.png",
                file_data=b"imagebytes",
                pipeline="editor",
                task_token="editortok123",
                sidecars=sidecars,
            )

        assert "edited/test_editortok123.png" in uploaded_keys
        assert "editor_recipes/test_recipe_v1.json" in uploaded_keys
        assert "edited/test_editortok123.png" in deleted_keys
        assert "editor_recipes/test_recipe_v1.json" in deleted_keys

    def test_record_derivative_sidecar_upload_failure_compensating_delete(self, db_session, monkeypatch):
        """If sidecar upload fails, already-uploaded main derivative is deleted before raising."""
        deleted_keys = []
        uploaded_keys = []

        def fake_upload(data, name, content_type):
            if name.endswith(".json"):
                return False  # Simulate sidecar upload failure
            uploaded_keys.append(name)
            return True

        monkeypatch.setattr("app.services.media_derivative.upload_object", fake_upload)
        monkeypatch.setattr("app.services.media_derivative.delete_object", lambda k: deleted_keys.append(k) or True)

        sidecars = {"editor_recipes/test_recipe.json": b'{"settings": 1}'}

        with pytest.raises(RuntimeError, match="Failed to upload sidecar"):
            record_derivative(
                db=db_session,
                source_path="uploads/test.png",
                file_data=b"bytes",
                pipeline="editor",
                task_token="tok456",
                sidecars=sidecars,
            )

        assert "edited/test_tok456.png" in uploaded_keys
        assert "edited/test_tok456.png" in deleted_keys

    def test_record_derivative_custom_title_and_embedding_honored(self, db_session, monkeypatch):
        """Custom title and pre-computed embedding are saved without recomputing."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")
        embed_mock = MagicMock()
        monkeypatch.setattr("app.services.media_derivative.get_embedding", embed_mock)

        custom_emb = [0.42] * 384
        res = record_derivative(
            db=db_session,
            source_path="uploads/flower.png",
            file_data=b"dummy",
            pipeline="upscale",
            title="Custom Flower 8k",
            embedding=custom_emb,
        )

        assert res.asset.title == "Custom Flower 8k"
        assert res.asset.embedding == custom_emb
        embed_mock.assert_not_called()

    def test_record_derivative_without_db(self, monkeypatch):
        """When db is None, uploads and returns DerivativeResult without catalog insertion."""
        uploaded = []
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda d, n, **k: uploaded.append(n) or True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")

        res = record_derivative(
            db=None,
            source_path="uploads/flower.png",
            file_data=io.BytesIO(b"file_like_stream"),
            pipeline="bgremove",
            task_token="streamtok123",
        )

        assert res.asset is None
        assert res.file_size == len(b"file_like_stream")
        assert res.output_path == "bg_removed/flower_streamtok123.png"
        assert uploaded == ["bg_removed/flower_streamtok123.png"]

    def test_record_derivative_upload_failure_raises(self, db_session, monkeypatch):
        """Initial derivative upload failure raises RuntimeError and skips DB operation."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: False)

        with pytest.raises(RuntimeError, match="Failed to upload derivative"):
            record_derivative(
                db=db_session,
                source_path="uploads/flower.png",
                file_data=b"dummy",
                pipeline="upscale",
            )

    def test_path_traversal_sanitization_and_validation(self, monkeypatch):
        """Path traversal characters in qualifiers, output_paths, or sidecars are sanitized or rejected."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        key = build_derivative_key("uploads/photo.jpg", "upscale", qualifier="../../traversal", token="123456abcdef")
        assert ".." not in key
        assert key == "upscaled/photo_traversal_123456abcdef.png"

        with pytest.raises(ValueError, match="Insecure or invalid storage key"):
            record_derivative(
                db=None,
                source_path="uploads/photo.jpg",
                file_data=b"data",
                pipeline="upscale",
                output_path="../../etc/passwd",
            )

        with pytest.raises(ValueError, match="Insecure or invalid storage key"):
            record_derivative(
                db=None,
                source_path="uploads/photo.jpg",
                file_data=b"data",
                pipeline="editor",
                sidecars={"../sidecar.json": b"{}"},
            )

    def test_post_commit_refresh_failure_does_not_delete_storage(self, db_session, monkeypatch):
        """If db.commit() succeeds but refresh raises, the committed storage object is NOT deleted."""
        deleted_keys = []
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        monkeypatch.setattr("app.services.media_derivative.delete_object", lambda k: deleted_keys.append(k) or True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")
        monkeypatch.setattr(db_session, "refresh", MagicMock(side_effect=SQLAlchemyError("Post-commit refresh error")))

        res = record_derivative(
            db=db_session,
            source_path="uploads/photo.jpg",
            file_data=b"bytes",
            pipeline="skin_enhance",
            task_token="tok123",
        )
        assert len(deleted_keys) == 0
        assert res.output_path == "skin_enhanced/photo_tok123.png"

    def test_eof_stream_handling_and_empty_rejection(self, monkeypatch):
        """A seekable stream positioned at EOF is read completely, and empty data raises ValueError."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")

        buf = io.BytesIO()
        buf.write(b"encoded_png_bytes")
        assert buf.tell() == len(b"encoded_png_bytes")

        res = record_derivative(
            db=None,
            source_path="uploads/photo.jpg",
            file_data=buf,
            pipeline="bgremove",
        )
        assert res.file_size == len(b"encoded_png_bytes")

    def test_seekable_stream_without_getvalue_rewinds_from_eof(self, monkeypatch):
        """Streams without getvalue() but supporting seekable/seek are rewound from EOF."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")

        class CustomSeekableStream:
            def __init__(self, data: bytes):
                self._stream = io.BytesIO(data)
                self._stream.seek(len(data))  # Position at EOF

            def read(self, *a, **k):
                return self._stream.read(*a, **k)

            def seek(self, *a, **k):
                return self._stream.seek(*a, **k)

            def seekable(self):
                return True

        stream = CustomSeekableStream(b"stream_payload_bytes")
        res = record_derivative(db=None, source_path="test.png", file_data=stream, pipeline="upscale")
        assert res.file_size == len(b"stream_payload_bytes")

    def test_record_derivative_sidecar_success(self, db_session, monkeypatch):
        """Sidecar files are uploaded and recorded in DerivativeResult.sidecar_paths."""
        uploaded = {}
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda d, n, **k: uploaded.setdefault(n, d) is not None or True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://storage/{k}")
        monkeypatch.setattr("app.services.media_derivative.get_embedding", lambda text: [0.0] * 384)

        sidecars = {"recipes/adjust.json": (b'{"bright": 5}', "application/json")}
        res = record_derivative(
            db=db_session,
            source_path="photo.png",
            file_data=b"img",
            pipeline="editor",
            task_token="tok1",
            sidecars=sidecars,
        )
        assert "recipes/adjust.json" in uploaded
        assert "recipes/adjust.json" in res.sidecar_paths
        assert res.sidecar_paths["recipes/adjust.json"] == "http://storage/recipes/adjust.json"

    def test_record_derivative_empty_data_raises(self):
        """Empty data raises ValueError."""
        with pytest.raises(ValueError, match="file_data cannot be empty"):
            record_derivative(
                db=None,
                source_path="uploads/photo.jpg",
                file_data=b"",
                pipeline="bgremove",
            )

    def test_auto_commit_false_flushes_id(self, db_session, monkeypatch):
        """When auto_commit=False, db.flush() is called and asset.id is assigned without committing."""
        monkeypatch.setattr("app.services.media_derivative.upload_object", lambda *a, **k: True)
        monkeypatch.setattr("app.services.media_derivative.generate_url", lambda k: f"http://{k}")

        res = record_derivative(
            db=db_session,
            source_path="uploads/photo.jpg",
            file_data=b"bytes",
            pipeline="editor",
            auto_commit=False,
        )
        assert res.asset is not None
        assert res.asset.id is not None
        db_session.rollback()

    def test_derivative_result_cleanup(self, monkeypatch):
        """DerivativeResult exposes uploaded_keys and cleanup helper deletes them."""
        deleted = []
        res = DerivativeResult(
            output_path="test/output.png",
            url="http://storage/test/output.png",
            source_path="test.png",
            file_size=100,
            uploaded_keys=["test/output.png", "recipes/test.json"],
        )
        res.cleanup(delete_fn=lambda k: deleted.append(k) or True)
        assert deleted == ["test/output.png", "recipes/test.json"]



