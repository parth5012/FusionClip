"""Unit tests for real Gemini and ElevenLabs generation endpoints in generate.py (#85)."""

import base64
import pytest
import httpx
from app.services.secrets import set_secret
from app.models import MediaAsset


class TestRealGeminiGeneration:
    def test_gemini_text_real_api_success(self, client, db_session, monkeypatch):
        set_secret("gemini", "AIza-test-gemini-key", db=db_session)

        def mock_post(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            assert headers.get("x-goog-api-key") == "AIza-test-gemini-key"
            json_body = kwargs.get("json", {})
            assert json_body["contents"][0]["parts"][0]["text"] == "Write a sci-fi scene"

            response = httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "Neon lights reflected in the wet asphalt of Neo-Tokyo."}],
                                "role": "model",
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )
            return response

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/text?prompt=Write+a+sci-fi+scene")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["output"] == "Neon lights reflected in the wet asphalt of Neo-Tokyo."

    def test_gemini_text_auth_error_401(self, client, db_session, monkeypatch):
        set_secret("gemini", "AIza-bad-key", db=db_session)

        def mock_post(url, *args, **kwargs):
            return httpx.Response(
                401,
                json={"error": {"code": 401, "message": "API key not valid. Please pass a valid API key."}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/text?prompt=Hello")
        assert res.status_code == 401
        assert "Gemini authentication failed" in res.json()["detail"]

    def test_gemini_text_quota_error_429(self, client, db_session, monkeypatch):
        set_secret("gemini", "AIza-quota-exceeded", db=db_session)

        def mock_post(url, *args, **kwargs):
            return httpx.Response(
                429,
                json={"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota)."}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/text?prompt=Hello")
        assert res.status_code == 429
        assert "rate limit or quota exceeded" in res.json()["detail"]

    def test_gemini_image_real_api_success(self, client, db_session, stub_storage, monkeypatch):
        set_secret("gemini", "AIza-test-image-key", db=db_session)

        fake_png_bytes = b"\x89PNG\r\n\x1a\nfake-gemini-image-bytes"
        fake_b64 = base64.b64encode(fake_png_bytes).decode("ascii")

        def mock_post(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            assert headers.get("x-goog-api-key") == "AIza-test-image-key"
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": fake_b64,
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/image?prompt=Futuristic+cityscape")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["filename"].startswith("gemini_img_")
        assert body["filename"].endswith(".png")
        assert body["url"].startswith("http://test-minio/")
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_png_bytes

        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == body["filename"]).first()
        assert asset is not None
        assert asset.content_type == "image/png"


class TestRealElevenLabsGeneration:
    def test_elevenlabs_tts_real_api_success(self, client, db_session, stub_storage, monkeypatch):
        set_secret("elevenlabs", "xi-test-secret-key", db=db_session)
        fake_audio = b"\xff\xfb\x90\x00fake-tts-mp3-bytes"

        def mock_post(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            assert headers.get("xi-api-key") == "xi-test-secret-key"
            assert "text-to-speech" in url
            return httpx.Response(
                200,
                content=fake_audio,
                headers={"Content-Type": "audio/mpeg"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/audio?prompt=Welcome+to+FusionClip&type=tts")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "tts"
        assert body["filename"].startswith("eleven_tts_")
        assert body["filename"].endswith(".mp3")
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_audio

        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == body["filename"]).first()
        assert asset is not None
        assert asset.content_type == "audio/mpeg"

    def test_elevenlabs_sfx_real_api_success(self, client, db_session, stub_storage, monkeypatch):
        set_secret("elevenlabs", "xi-test-sfx-key", db=db_session)
        fake_sfx = b"\xff\xfb\x90\x00fake-sfx-mp3-bytes"

        def mock_post(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            assert headers.get("xi-api-key") == "xi-test-sfx-key"
            assert "sound-generation" in url
            return httpx.Response(
                200,
                content=fake_sfx,
                headers={"Content-Type": "audio/mpeg"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/audio?prompt=Deep+sub+drop+braam&type=sfx")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "sfx"
        assert body["filename"].startswith("eleven_sfx_")
        assert body["filename"].endswith(".mp3")
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_sfx

    def test_elevenlabs_auth_error_401(self, client, db_session, monkeypatch):
        set_secret("elevenlabs", "xi-invalid-key", db=db_session)

        def mock_post(url, *args, **kwargs):
            return httpx.Response(
                401,
                json={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/audio?prompt=Hello&type=tts")
        assert res.status_code == 401
        assert "ElevenLabs authentication failed" in res.json()["detail"]

    def test_elevenlabs_quota_error_429(self, client, db_session, monkeypatch):
        set_secret("elevenlabs", "xi-throttled-key", db=db_session)

        def mock_post(url, *args, **kwargs):
            return httpx.Response(
                429,
                json={"detail": {"status": "too_many_concurrent_requests", "message": "Concurrency limit reached"}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/audio?prompt=Hello&type=tts")
        assert res.status_code == 429
        assert "ElevenLabs concurrency or quota limit exceeded" in res.json()["detail"]


class TestUnconfiguredKeyMockFallback:
    def test_no_keys_configured_falls_back_to_mock(self, client):
        # Without any keys configured, should return legacy mock responses
        res_text = client.post("/api/generate/text?prompt=Mock+test")
        assert res_text.status_code == 200
        assert "mock Gemini response" in res_text.json()["output"]

        res_audio = client.post("/api/generate/audio?prompt=Mock+audio&type=tts")
        assert res_audio.status_code == 200
        assert res_audio.json()["status"] == "COMPLETED"

        res_image = client.post("/api/generate/image?prompt=Mock+image")
        assert res_image.status_code == 200
        assert res_image.json()["status"] == "COMPLETED"
