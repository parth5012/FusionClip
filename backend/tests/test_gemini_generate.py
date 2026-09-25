"""Offline tests for the real-Gemini generation endpoints.

The google-genai SDK is never invoked; ``app.services.gemini`` helpers are
monkeypatched so no network call is ever made. A Gemini key is only considered
configured when a test stores one via the secret store (or sends the
``X-Gemini-Key`` header).
"""

from app.models import MediaAsset
from app.services import secrets as secret_store

TEXT_MODEL = "gemini-2.0-flash"


class TestGenerateTextNoKey:
    def test_no_key_returns_mock_fallback(self, client, db_session):
        res = client.post("/api/generate/text?prompt=Hello+world")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "output"}
        assert body["status"] == "COMPLETED"
        assert "Hello world" in body["output"]

    def test_no_key_with_files_still_falls_back(self, client):
        res = client.post(
            "/api/generate/text?prompt=",
            files={"files": ("clip.mp4", b"fake-video-bytes", "video/mp4")},
        )
        assert res.status_code == 200
        assert set(res.json()) == {"status", "output"}


class TestGenerateTextGemini:
    def test_stored_key_calls_real_gemini(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)
        captured = {}

        def fake_generate_text(api_key, prompt, model=TEXT_MODEL):
            captured["api_key"] = api_key
            captured["prompt"] = prompt
            captured["model"] = model
            return "A real Gemini answer."

        monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)

        res = client.post("/api/generate/text?prompt=hello+gemini")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "output"}
        assert body["output"] == "A real Gemini answer."
        assert captured == {"api_key": "AIza-fake-key-0001", "prompt": "hello gemini", "model": TEXT_MODEL}

    def test_header_key_used_when_nothing_stored(self, client, monkeypatch):
        captured = {}

        def fake_generate_text(api_key, prompt, model=TEXT_MODEL):
            captured["api_key"] = api_key
            return "Header-key answer."

        monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)

        res = client.post(
            "/api/generate/text?prompt=hi",
            headers={"X-Gemini-Key": "AIza-header-key-0002"},
        )
        assert res.status_code == 200
        assert captured["api_key"] == "AIza-header-key-0002"

    def test_stored_key_precedes_header(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-stored-key-0003", db=db_session)
        captured = {}

        def fake_generate_text(api_key, prompt, model=TEXT_MODEL):
            captured["api_key"] = api_key
            return "Stored-key answer."

        monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)

        client.post(
            "/api/generate/text?prompt=hi",
            headers={"X-Gemini-Key": "AIza-header-key-0002"},
        )
        assert captured["api_key"] == "AIza-stored-key-0003"

    def test_gemini_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_text(api_key, prompt, model=TEXT_MODEL):
            raise RuntimeError("quota exceeded")

        monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)

        res = client.post("/api/generate/text?prompt=boom")
        assert res.status_code == 502

    def test_empty_prompt_without_files_is_400(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_text(api_key, prompt, model=TEXT_MODEL):
            raise AssertionError("should not be called")

        monkeypatch.setattr("app.services.gemini.generate_text", fake_generate_text)
        assert client.post("/api/generate/text?prompt=").status_code == 400


class TestGenerateMultimodal:
    def test_files_trigger_analysis_pipeline(self, client, db_session, stub_storage, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)
        captured = {}

        def fake_analyze_media(api_key, data, mime_type, filename, instruction, model=TEXT_MODEL):
            captured["mime_type"] = mime_type
            captured["filename"] = filename
            captured["data"] = data
            return (
                '{"transcript": "hello", "summary": "a clip", "metadata": {}}',
                {
                    "gemini_file": "files/abc123",
                    "gemini_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc123",
                    "mime_type": mime_type,
                },
            )

        monkeypatch.setattr("app.services.gemini.analyze_media", fake_analyze_media)

        res = client.post(
            "/api/generate/text?prompt=Summarize+this",
            files={"files": ("clip.mp4", b"fake-video-bytes", "video/mp4")},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["output"] == '{"transcript": "hello", "summary": "a clip", "metadata": {}}'
        assert body["metadata"]["files_analyzed"] == 1
        assert len(body["analyzed_files"]) == 1
        entry = body["analyzed_files"][0]
        assert entry["original_name"] == "clip.mp4"
        assert entry["content_type"] == "video/mp4"
        assert entry["gemini_uri"].startswith("https://generativelanguage.googleapis.com")
        assert entry["filename"] in stub_storage["uploaded"]
        assert captured["data"] == b"fake-video-bytes"

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == entry["filename"])
            .one()
        )
        assert asset.content_type == "video/mp4"

    def test_multiple_files_analyzed_in_order(self, client, db_session, stub_storage, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_analyze_media(api_key, data, mime_type, filename, instruction, model=TEXT_MODEL):
            return f"analysis-of-{filename}", {"gemini_file": "files/x", "gemini_uri": "uri", "mime_type": mime_type}

        monkeypatch.setattr("app.services.gemini.analyze_media", fake_analyze_media)

        res = client.post(
            "/api/generate/text?prompt=",
            files=[
                ("files", ("a.mp3", b"audio-bytes", "audio/mpeg")),
                ("files", ("b.png", b"image-bytes", "image/png")),
            ],
        )
        assert res.status_code == 200
        body = res.json()
        assert body["metadata"]["files_analyzed"] == 2
        assert body["output"] == "analysis-of-a.mp3\n\nanalysis-of-b.png"
        assert [e["original_name"] for e in body["analyzed_files"]] == ["a.mp3", "b.png"]

    def test_analysis_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_analyze_media(api_key, data, mime_type, filename, instruction, model=TEXT_MODEL):
            raise RuntimeError("file too large")

        monkeypatch.setattr("app.services.gemini.analyze_media", fake_analyze_media)

        res = client.post(
            "/api/generate/text?prompt=",
            files={"files": ("big.mp4", b"x" * 64, "video/mp4")},
        )
        assert res.status_code == 502


class TestGenerateGeminiImage:
    def test_no_key_is_503(self, client):
        res = client.post("/api/generate/gemini/image?prompt=cat")
        assert res.status_code == 503

    def test_generates_and_persists_image(self, client, db_session, stub_storage, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)
        captured = {}

        def fake_generate_image(api_key, prompt, model="imagen-3.0-generate-002"):
            captured["api_key"] = api_key
            return b"\x89PNG-fake-image", "image/png"

        monkeypatch.setattr("app.services.gemini.generate_image", fake_generate_image)

        res = client.post("/api/generate/gemini/image?prompt=a+cat")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["prompt"] == "a cat"
        assert body["content_type"] == "image/png"
        assert body["filename"].startswith("gen_gemini_image_")
        assert body["url"].startswith("http://test-minio/")
        assert body["filename"] in stub_storage["uploaded"]
        assert captured["api_key"] == "AIza-fake-key-0001"

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "image/png"

    def test_generation_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_image(api_key, prompt, model="imagen-3.0-generate-002"):
            raise RuntimeError("safety filter")

        monkeypatch.setattr("app.services.gemini.generate_image", fake_generate_image)
        assert client.post("/api/generate/gemini/image?prompt=dog").status_code == 502


class TestGenerateGeminiVideo:
    def test_no_key_is_503(self, client):
        res = client.post("/api/generate/gemini/video?prompt=cat+running")
        assert res.status_code == 503

    def test_completed_video(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_video(api_key, prompt, model="veo-3.0-generate-001", timeout=300):
            return {
                "status": "COMPLETED",
                "operation_name": "operations/veo-123",
                "uri": "https://storage.googleapis.com/generativeai-downloads/video.mp4",
                "metadata": {"mime_type": "video/mp4"},
            }

        monkeypatch.setattr("app.services.gemini.generate_video", fake_generate_video)

        res = client.post("/api/generate/gemini/video?prompt=cat+running")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["url"] == "https://storage.googleapis.com/generativeai-downloads/video.mp4"
        assert body["filename"].startswith("gen_gemini_video_")
        assert body["metadata"]["operation_name"] == "operations/veo-123"

    def test_processing_video(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_video(api_key, prompt, model="veo-3.0-generate-001", timeout=300):
            return {"status": "PROCESSING", "operation_name": "operations/veo-456"}

        monkeypatch.setattr("app.services.gemini.generate_video", fake_generate_video)

        body = client.post("/api/generate/gemini/video?prompt=slow+scene&timeout=1").json()
        assert body["status"] == "PROCESSING"
        assert body["url"] == ""
        assert body["metadata"]["operation_name"] == "operations/veo-456"
        assert body["filename"] is None

    def test_failed_video(self, client, db_session, monkeypatch):
        secret_store.set_secret("gemini", "AIza-fake-key-0001", db=db_session)

        def fake_generate_video(api_key, prompt, model="veo-3.0-generate-001", timeout=300):
            return {
                "status": "FAILED",
                "operation_name": "operations/veo-789",
                "error": "content policy violation",
            }

        monkeypatch.setattr("app.services.gemini.generate_video", fake_generate_video)

        body = client.post("/api/generate/gemini/video?prompt=bad+scene").json()
        assert body["status"] == "FAILED"
        assert body["metadata"]["error"] == "content policy violation"
