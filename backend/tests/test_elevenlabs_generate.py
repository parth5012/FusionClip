"""Offline tests for the real-ElevenLabs generation endpoints.

The elevenlabs SDK is never invoked; ``app.services.elevenlabs`` helpers are
monkeypatched so no network call is ever made. An ElevenLabs key is only
considered configured when a test stores one via the secret store (or sends the
``X-ElevenLabs-Key`` header).
"""

from app import tasks
from app.models import Configuration, MediaAsset
from app.services import elevenlabs as elevenlabs_service
from app.services import secrets as secret_store
from app.services.elevenlabs import DEFAULT_MODEL, DEFAULT_VOICE_ID


class TestGenerateAudioNoKey:
    def test_no_key_returns_mock_fallback(self, client, stub_storage, db_session):
        res = client.post("/api/generate/audio?prompt=Hello+world&type=tts")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "type", "filename", "url"}
        assert body["status"] == "COMPLETED"
        assert body["filename"].startswith("gen_audio_")
        assert body["filename"] in stub_storage["uploaded"]

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "audio/mpeg"


class TestGenerateAudioElevenLabs:
    def test_voice_clone_success(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        # Mock clone_voice
        mock_voice_id = "cloned-voice-123"
        def mock_clone(*args, **kwargs):
            return mock_voice_id
        monkeypatch.setattr(elevenlabs_service, "clone_voice", mock_clone)
        # Prepare test file
        test_file = ("test.mp3", b"dummy audio", "audio/mpeg")
        form_data = {
            "file": test_file,
            "voice_name": "TestVoice",
        }
        response = client.post("/api/generate/voice-clone", files=form_data)
        assert response.status_code == 200
        assert response.json()["voice_id"] == mock_voice_id
        # Verify Configuration entry
        config = db_session.query(Configuration).filter_by(key="elevenlabs.voice.TestVoice").first()
        assert config.value == str(mock_voice_id)

    def test_voice_clone_no_key_is_503(self, client):
        test_file = ("test.mp3", b"dummy audio", "audio/mpeg")
        response = client.post(
            "/api/generate/voice-clone", files={"file": test_file, "voice_name": "NoKey"}
        )
        assert response.status_code == 503

    def test_voice_clone_invalid_format(self, client, db_session):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        test_file = ("test.jpg", b"dummy image", "image/jpeg")
        response = client.post(
            "/api/generate/voice-clone", files={"file": test_file, "voice_name": "BadVoice"}
        )
        assert response.status_code == 400
        assert "Invalid audio" in response.json()["detail"]

    def test_voice_clone_too_long(self, client, db_session, monkeypatch, tmp_path):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        # Mock parse_duration to return 70 seconds
        monkeypatch.setattr("app.routers.generate.parse_duration", lambda x: 70.0)
        test_file = ("long.mp3", b"long audio", "audio/mpeg")
        response = client.post(
            "/api/generate/voice-clone", files={"file": test_file, "voice_name": "LongVoice"}
        )
        assert response.status_code == 400
        assert "exceeds 1 minute" in response.json()["detail"]

    def test_stored_key_calls_real_elevenlabs(self, client, db_session, stub_storage, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured["api_key"] = api_key
            captured["text"] = text
            captured["voice_id"] = voice_id
            captured["stability"] = stability
            captured["clarity"] = clarity
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        res = client.post("/api/generate/audio?prompt=hello+elevenlabs&type=tts")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "type", "filename", "url"}
        assert body["status"] == "COMPLETED"
        assert body["type"] == "tts"
        assert body["filename"].startswith("gen_audio_")
        assert body["filename"].endswith(".mp3")
        assert body["url"].startswith("http://test-minio/")
        assert body["filename"] in stub_storage["uploaded"]
        assert captured == {
            "api_key": "xi-stored-key-0001",
            "text": "hello elevenlabs",
            "voice_id": DEFAULT_VOICE_ID,
            "stability": 0.5,
            "clarity": 0.75,
        }

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "audio/mpeg"

    def test_header_key_used_when_nothing_stored(self, client, monkeypatch):
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured["api_key"] = api_key
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        res = client.post(
            "/api/generate/audio?prompt=hi",
            headers={"X-ElevenLabs-Key": "xi-header-key-0002"},
        )
        assert res.status_code == 200
        assert captured["api_key"] == "xi-header-key-0002"

    def test_stored_key_precedes_header(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0003", db=db_session)
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured["api_key"] = api_key
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        client.post(
            "/api/generate/audio?prompt=hi",
            headers={"X-ElevenLabs-Key": "xi-header-key-0002"},
        )
        assert captured["api_key"] == "xi-stored-key-0003"

    def test_voice_and_settings_passthrough(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured.update(voice_id=voice_id, stability=stability, clarity=clarity)
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        client.post(
            "/api/generate/audio?prompt=hi&voice_id=ExsVoice123&stability=0.3&clarity=0.9"
        )
        assert captured == {"voice_id": "ExsVoice123", "stability": 0.3, "clarity": 0.9}

    def test_synthesis_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            raise RuntimeError("quota exceeded")

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        res = client.post("/api/generate/audio?prompt=boom")
        assert res.status_code == 502


class TestGenerateTts:
    def test_no_key_returns_mock_fallback(self, client, stub_storage, db_session):
        res = client.post("/api/generate/tts?text=Hello+world")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "voice_id", "model", "stability", "clarity", "filename", "url", "content_type"}
        assert body["status"] == "COMPLETED"
        assert body["voice_id"] == DEFAULT_VOICE_ID
        assert body["filename"].startswith("gen_audio_")
        assert body["url"].startswith("http://test-minio/")
        assert body["filename"] in stub_storage["uploaded"]

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "audio/mpeg"

    def test_stored_key_calls_real_elevenlabs(self, client, db_session, stub_storage, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured.update(api_key=api_key, text=text, voice_id=voice_id, stability=stability, clarity=clarity, model=model)
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        res = client.post("/api/generate/tts?text=hello+there&voice_id=ExsVoice123")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["voice_id"] == "ExsVoice123"
        assert body["model"] == DEFAULT_MODEL
        assert body["stability"] == 0.5
        assert body["clarity"] == 0.75
        assert body["filename"].startswith("gen_tts_")
        assert body["filename"].endswith(".mp3")
        assert body["content_type"] == "audio/mpeg"
        assert body["url"].startswith("http://test-minio/")
        assert body["filename"] in stub_storage["uploaded"]
        assert captured == {
            "api_key": "xi-stored-key-0001",
            "text": "hello there",
            "voice_id": "ExsVoice123",
            "stability": 0.5,
            "clarity": 0.75,
            "model": DEFAULT_MODEL,
        }

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "audio/mpeg"

    def test_default_voice_used_when_omitted(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured["voice_id"] = voice_id
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        client.post("/api/generate/tts?text=hi")
        assert captured["voice_id"] == DEFAULT_VOICE_ID

    def test_header_key_used_when_nothing_stored(self, client, monkeypatch):
        captured = {}

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            captured["api_key"] = api_key
            return b"ID3-fake-mp3-bytes"

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        client.post("/api/generate/tts?text=hi", headers={"X-ElevenLabs-Key": "xi-header-key-0002"})
        assert captured["api_key"] == "xi-header-key-0002"

    def test_synthesis_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)

        def fake_synthesize(api_key, text, voice_id=DEFAULT_VOICE_ID, stability=0.5, clarity=0.75, model=DEFAULT_MODEL):
            raise RuntimeError("synthesis failed")

        monkeypatch.setattr("app.services.elevenlabs.synthesize", fake_synthesize)

        res = client.post("/api/generate/tts?text=boom")
        assert res.status_code == 502


class TestGenerateVoiceList:
    def test_no_key_is_503(self, client):
        res = client.get("/api/generate/voice-list")
        assert res.status_code == 503

    def test_stored_key_returns_voices(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)
        captured = {}

        def fake_list_voices(api_key):
            captured["api_key"] = api_key
            return [
                {"voice_id": "ExsVoice123", "name": "Rachel", "labels": {"accent": "american"}, "category": "premade", "preview_url": "https://example.com/rachel.mp3"},
                {"voice_id": "ExsVoice456", "name": "Drew", "labels": {}, "category": "premade", "preview_url": None},
            ]

        monkeypatch.setattr("app.services.elevenlabs.list_voices", fake_list_voices)

        res = client.get("/api/generate/voice-list")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert len(body["voices"]) == 2
        assert body["voices"][0]["voice_id"] == "ExsVoice123"
        assert body["voices"][0]["name"] == "Rachel"
        assert body["voices"][0]["labels"]["accent"] == "american"
        assert captured["api_key"] == "xi-stored-key-0001"

    def test_header_key_used_when_nothing_stored(self, client, monkeypatch):
        captured = {}

        def fake_list_voices(api_key):
            captured["api_key"] = api_key
            return []

        monkeypatch.setattr("app.services.elevenlabs.list_voices", fake_list_voices)

        client.get("/api/generate/voice-list", headers={"X-ElevenLabs-Key": "xi-header-key-0002"})
        assert captured["api_key"] == "xi-header-key-0002"

    def test_list_failure_returns_502(self, client, db_session, monkeypatch):
        secret_store.set_secret("elevenlabs", "xi-stored-key-0001", db=db_session)

        def fake_list_voices(api_key):
            raise RuntimeError("unauthorized")

        monkeypatch.setattr("app.services.elevenlabs.list_voices", fake_list_voices)

        res = client.get("/api/generate/voice-list")
        assert res.status_code == 502
