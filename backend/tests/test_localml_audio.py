"""Tests for local audio generation endpoint, zero-shot voice cloning, and MusicGen (#101).

Tests:
1. Complete removal of legacy placeholder string 'Mock elevenlabs generated audio bytes'.
2. Degraded refusal contract (HTTP 200 with degraded: true + reason) when no GPU is available.
3. Degraded refusal when free VRAM is insufficient for xtts-v2 or musicgen.
4. Model selection: tts/voice/voice_clone -> xtts-v2, sfx/music -> musicgen.
5. Voice cloning: type=voice_clone requires reference (400 if missing/invalid), forwards reference on success.
6. Clone markers: voice_clone includes marker at 0.0 with kind="voice_clone"; other types return empty markers list.
7. MediaAsset contract: title prefix 'Voice Clone: ' for cloned output, content_type 'audio/wav', duration recorded.
8. Real audio bytes uploaded to storage with content_type 'audio/wav' and filename gen_audio_{time_ns}.wav.
9. Runtime load failure handling: returns degraded envelope with reason 'load_failed'.
10. ElevenLabs cloud path preservation: tts/sfx routes reach ElevenLabs when key is configured.
11. Safe imports: app.ml.audio imports cleanly without torch/transformers/TTS installed.
"""

from pathlib import Path
import re
import pytest

from app.ml.contracts import DegradedReason, FallbackTier
from app.ml.guard import vram_guard
from app.ml.registry import model_registry
from app.models import MediaAsset
from app.services.secrets import set_secret


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestMockStringElimination:
    def test_mock_string_completely_removed_from_codebase(self):
        """Binding Decision #3: The string 'Mock elevenlabs generated audio bytes'
        must no longer exist in any production python file.
        """
        forbidden = "Mock elevenlabs generated audio bytes"
        app_dir = REPO_ROOT / "backend" / "app"

        found_in = []
        for path in app_dir.rglob("*.py"):
            try:
                content = path.read_text(encoding="utf-8")
                if forbidden in content:
                    found_in.append(str(path.relative_to(REPO_ROOT)))
            except (OSError, UnicodeDecodeError):
                continue

        assert not found_in, (
            f"Forbidden mock payload string '{forbidden}' found in production files: {found_in}"
        )


class TestLocalAudioRefusal:
    def test_degraded_refusal_when_no_gpu(self, client, monkeypatch):
        """When host has no CUDA GPU, local audio generation returns degraded contract."""
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

        res = client.post("/api/generate/audio?prompt=A+serene+voice&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.NO_GPU.value
        assert "no cuda gpu" in body["message"].lower()
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value
        assert "Mock" not in body["message"]

    def test_degraded_refusal_when_insufficient_vram(self, client, monkeypatch):
        """When GPU free VRAM is insufficient for xtts-v2 (4GB + 1GB overhead),
        returns degraded contract with reason 'insufficient_vram'.
        """
        total_bytes = int(16.0 * (1024 ** 3))
        free_bytes = int(2.0 * (1024 ** 3))  # 2 GB free, xtts-v2 needs 5 GB
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
                "free_gb": 2.0,
                "used_gb": 14.0,
                "vram_percent": 87.5,
            },
        )

        res = client.post("/api/generate/audio?prompt=A+spoken+dialogue&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.INSUFFICIENT_VRAM.value
        assert body["model_id"] == "xtts-v2"
        assert body["vram_available_gb"] == 2.0
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value
        assert "Mock" not in body["message"]

    def test_degraded_refusal_when_insufficient_vram_for_musicgen(self, client, monkeypatch):
        """When GPU free VRAM is insufficient for musicgen (10.4GB + 1GB overhead = 11.4GB),
        returns degraded contract with model_id 'musicgen'.
        """
        total_bytes = int(16.0 * (1024 ** 3))
        free_bytes = int(8.0 * (1024 ** 3))  # 8 GB free, musicgen needs 11.4 GB
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
                "free_gb": 8.0,
                "used_gb": 8.0,
                "vram_percent": 50.0,
            },
        )

        res = client.post("/api/generate/audio?prompt=Synthwave+beat&type=music&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.INSUFFICIENT_VRAM.value
        assert body["model_id"] == "musicgen"


class TestModelSelectionAndExecution:
    @pytest.fixture(autouse=True)
    def stub_sufficient_gpu(self, monkeypatch):
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

    def test_model_selection_routes_tts_to_xtts_v2(self, client, monkeypatch, stub_storage, db_session):
        guard_candidates = []
        orig_select = vram_guard.select_fitting_model

        def fake_select(candidate_ids, **kw):
            guard_candidates.append(list(candidate_ids))
            return orig_select(candidate_ids, **kw)

        monkeypatch.setattr(vram_guard, "select_fitting_model", fake_select)
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFfake-xtts-wav-bytes",
        )

        res = client.post("/api/generate/audio?prompt=Hello+there&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "tts"
        assert guard_candidates == [["xtts-v2"]]
        assert body["markers"] == []

    def test_model_selection_routes_voice_to_xtts_v2(self, client, monkeypatch, stub_storage, db_session):
        guard_candidates = []
        orig_select = vram_guard.select_fitting_model

        def fake_select(candidate_ids, **kw):
            guard_candidates.append(list(candidate_ids))
            return orig_select(candidate_ids, **kw)

        monkeypatch.setattr(vram_guard, "select_fitting_model", fake_select)
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFfake-xtts-wav-bytes",
        )

        res = client.post("/api/generate/audio?prompt=Spoken+audio&type=voice&provider=local")
        assert res.status_code == 200
        assert guard_candidates == [["xtts-v2"]]

    def test_model_selection_routes_sfx_and_music_to_musicgen(
        self, client, monkeypatch, stub_storage, db_session
    ):
        guard_candidates = []
        orig_select = vram_guard.select_fitting_model

        def fake_select(candidate_ids, **kw):
            guard_candidates.append(list(candidate_ids))
            return orig_select(candidate_ids, **kw)

        monkeypatch.setattr(vram_guard, "select_fitting_model", fake_select)
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFfake-musicgen-wav-bytes",
        )

        res_sfx = client.post("/api/generate/audio?prompt=Explosion&type=sfx&provider=local")
        assert res_sfx.status_code == 200
        assert res_sfx.json()["type"] == "sfx"

        res_music = client.post("/api/generate/audio?prompt=Epic+orchestral&type=music&provider=local")
        assert res_music.status_code == 200
        assert res_music.json()["type"] == "music"

        assert guard_candidates == [["musicgen"], ["musicgen"]]

    def test_real_bytes_uploaded_and_media_asset_persisted(
        self, client, monkeypatch, stub_storage, db_session
    ):
        fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: fake_wav,
        )

        res = client.post("/api/generate/audio?prompt=Orchestral+theme&type=music&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["filename"].startswith("gen_audio_")
        assert body["filename"].endswith(".wav")
        assert body["url"]

        # Check stub storage
        assert body["filename"] in stub_storage["uploaded"]
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_wav
        assert stub_storage["uploaded"][body["filename"]]["content_type"] == "audio/wav"

        # Check MediaAsset in DB
        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .first()
        )
        assert asset is not None
        assert "MusicGen" in asset.title
        assert asset.content_type == "audio/wav"
        assert asset.file_size == len(fake_wav)


class TestVoiceCloningAndMarkers:
    @pytest.fixture(autouse=True)
    def stub_sufficient_gpu(self, monkeypatch):
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

    def test_voice_clone_without_reference_returns_400(self, client):
        """voice_clone requires a reference file parameter."""
        res = client.post("/api/generate/audio?prompt=Clone+this+voice&type=voice_clone&provider=local")
        assert res.status_code == 400
        detail = res.json()["detail"].lower()
        assert "reference" in detail

    def test_voice_clone_with_empty_or_whitespace_reference_returns_400(self, client):
        res = client.post("/api/generate/audio?prompt=Clone&type=voice_clone&reference=&provider=local")
        assert res.status_code == 400
        assert "reference" in res.json()["detail"].lower()

    def test_voice_clone_rejects_path_traversal_reference(self, client):
        for bad_ref in ("../secret.wav", "foo/../../bar.wav", "..\\evil.wav", "ref;rm -rf"):
            res = client.post(
                f"/api/generate/audio?prompt=Clone&type=voice_clone&reference={bad_ref}&provider=local"
            )
            assert res.status_code == 400, f"Expected 400 for bad reference {bad_ref!r}"

    def test_voice_clone_with_valid_reference_produces_markers_and_title(
        self, client, monkeypatch, stub_storage, db_session
    ):
        passed_kwargs = {}

        def fake_runner(**kw):
            passed_kwargs.update(kw)
            return b"RIFFfake-voice-clone-wav"

        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: fake_runner,
        )

        ref_file = "speaker_sample_01.wav"
        stub_storage["uploaded"][ref_file] = {
            "data": b"RIFFfake-ref-audio",
            "content_type": "audio/wav",
        }
        prompt = "Hello from cloned speaker"
        res = client.post(
            f"/api/generate/audio?prompt={prompt.replace(' ', '+')}&type=voice_clone&reference={ref_file}&provider=local"
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "voice_clone"
        assert body["filename"].endswith(".wav")

        # Markers contract: list of {time: float, label: str, kind: str}
        assert "markers" in body
        assert len(body["markers"]) == 1
        marker = body["markers"][0]
        assert marker["time"] == 0.0
        assert marker["kind"] == "voice_clone"
        assert ref_file in marker["label"]

        # Reference forwarded to loader execution
        assert passed_kwargs.get("reference") == ref_file

        # MediaAsset title prefix contract: 'Voice Clone: <prompt[:30]>...'
        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .first()
        )
        assert asset is not None
        assert asset.title.startswith(f"Voice Clone: {prompt[:30]}")
        assert asset.content_type == "audio/wav"

    def test_plain_tts_has_empty_markers(self, client, monkeypatch, stub_storage):
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFfake-tts-wav",
        )
        res = client.post("/api/generate/audio?prompt=Hello&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["markers"] == []


class TestLoadFailedEnvelope:
    def test_load_failed_returns_degraded_contract(self, client, monkeypatch):
        """When model loading raises an exception, return degraded contract with reason 'load_failed'."""
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: (_ for _ in ()).throw(RuntimeError("Checkpoint not found or corrupt")),
        )

        res = client.post("/api/generate/audio?prompt=A+voice&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert body["model_id"] == "xtts-v2"
        assert "Checkpoint not found or corrupt" in body["message"]
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value


class TestCloudElevenLabsPreservation:
    def test_elevenlabs_tts_reached_when_key_configured(self, client, db_session, monkeypatch, stub_storage):
        """When ElevenLabs key is present and provider is not 'local', route uses ElevenLabs API."""
        set_secret("elevenlabs", "test-eleven-key", db_session)

        called_tts = []

        def fake_tts(api_key, text, voice_id="21m00Tcm4TlvDq8ikWAM", model_id="eleven_multilingual_v2"):
            called_tts.append((api_key, text, voice_id))
            return b"fake-elevenlabs-mp3-bytes"

        monkeypatch.setattr("app.routers.generate.call_elevenlabs_tts", fake_tts)

        res = client.post("/api/generate/audio?prompt=Welcome+speech&type=tts")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "tts"
        assert len(called_tts) == 1
        assert called_tts[0][0] == "test-eleven-key"
        assert called_tts[0][1] == "Welcome speech"

    def test_elevenlabs_sfx_reached_when_key_configured(self, client, db_session, monkeypatch, stub_storage):
        """When ElevenLabs key is present and type is 'sfx', route uses ElevenLabs SFX API."""
        set_secret("elevenlabs", "test-eleven-key", db_session)

        called_sfx = []

        def fake_sfx(api_key, text, duration_seconds=5.0):
            called_sfx.append((api_key, text, duration_seconds))
            return b"fake-elevenlabs-sfx-mp3-bytes"

        monkeypatch.setattr("app.routers.generate.call_elevenlabs_sfx", fake_sfx)

        res = client.post("/api/generate/audio?prompt=Thunder+sound&type=sfx&duration=4.5")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["type"] == "sfx"
        assert len(called_sfx) == 1
        assert called_sfx[0][0] == "test-eleven-key"
        assert called_sfx[0][1] == "Thunder sound"
        assert called_sfx[0][2] == 4.5


class TestAudioModuleSafetyAndFilenames:
    def test_audio_module_imports_without_torch(self, monkeypatch):
        """FIX 8: app.ml.audio must import cleanly in an environment without torch installed."""
        import sys
        import importlib

        saved = sys.modules.pop("app.ml.audio", None)
        saved_parent = getattr(sys.modules.get("app.ml"), "audio", None)
        try:
            monkeypatch.setitem(sys.modules, "torch", None)
            monkeypatch.setitem(sys.modules, "transformers", None)
            monkeypatch.setitem(sys.modules, "TTS", None)

            mod = importlib.import_module("app.ml.audio")
            assert hasattr(mod, "run_local_audio_generation")
            assert hasattr(mod, "SUPPORTED_AUDIO_TYPES")
            assert hasattr(mod, "build_audio_filename")
            assert hasattr(mod, "make_audio_loader")
        finally:
            if saved is not None:
                sys.modules["app.ml.audio"] = saved
            if "app.ml" in sys.modules and saved_parent is not None:
                setattr(sys.modules["app.ml"], "audio", saved_parent)

    def test_generated_audio_filenames_do_not_collide(self):
        """Nanosecond-resolution filenames ensure no collisions on concurrent requests."""
        from app.ml.audio import build_audio_filename

        names = {build_audio_filename() for _ in range(200)}
        assert len(names) == 200, "filename collision detected"
        for n in names:
            assert re.fullmatch(r"gen_audio_\d+\.wav", n), n

    def test_make_audio_loader_unknown_model_raises_valueerror(self):
        from app.ml.audio import make_audio_loader

        loader = make_audio_loader("unknown-audio-model")
        with pytest.raises(ValueError, match="No audio loader configured"):
            loader()


class TestFix1ElevenlabsRouting:
    """FIX 1: ElevenLabs only serves tts/voice/sfx. voice_clone and music go local."""

    def test_voice_clone_and_music_bypass_elevenlabs_when_key_exists(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """When an ElevenLabs key is configured, voice_clone and music must NOT be sent to ElevenLabs."""
        set_secret("elevenlabs", "test-eleven-key", db_session)

        called_elevenlabs = []
        monkeypatch.setattr(
            "app.routers.generate.call_elevenlabs_tts",
            lambda *a, **k: called_elevenlabs.append("tts"),
        )
        monkeypatch.setattr(
            "app.routers.generate.call_elevenlabs_sfx",
            lambda *a, **k: called_elevenlabs.append("sfx"),
        )

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFfake-audio-bytes",
        )

        ref_file = "uploads/speaker.wav"
        stub_storage["uploaded"][ref_file] = {
            "data": b"RIFFsample",
            "content_type": "audio/wav",
        }

        # 1. voice_clone -> must go local pipeline, NOT ElevenLabs TTS
        res_clone = client.post(
            f"/api/generate/audio?prompt=Clone+speech&type=voice_clone&reference={ref_file}"
        )
        assert res_clone.status_code == 200
        body_clone = res_clone.json()
        assert body_clone["type"] == "voice_clone"
        assert body_clone["status"] == "COMPLETED"
        assert len(body_clone.get("markers", [])) == 1

        # 2. music -> must go local pipeline, NOT ElevenLabs TTS
        res_music = client.post(
            "/api/generate/audio?prompt=Guitar+riff&type=music"
        )
        assert res_music.status_code == 200
        body_music = res_music.json()
        assert body_music["type"] == "music"
        assert body_music["status"] == "COMPLETED"

        assert called_elevenlabs == [], f"ElevenLabs was unexpectedly called: {called_elevenlabs}"

    def test_tts_and_sfx_still_use_elevenlabs_when_key_exists(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """tts and sfx types continue to use ElevenLabs when key is configured."""
        set_secret("elevenlabs", "test-eleven-key", db_session)

        monkeypatch.setattr(
            "app.routers.generate.call_elevenlabs_tts",
            lambda *a, **k: b"eleven-tts-bytes",
        )
        monkeypatch.setattr(
            "app.routers.generate.call_elevenlabs_sfx",
            lambda *a, **k: b"eleven-sfx-bytes",
        )

        res_tts = client.post("/api/generate/audio?prompt=Hello&type=tts")
        assert res_tts.status_code == 200
        assert res_tts.json()["filename"].startswith("eleven_tts_")

        res_sfx = client.post("/api/generate/audio?prompt=Bang&type=sfx")
        assert res_sfx.status_code == 200
        assert res_sfx.json()["filename"].startswith("eleven_sfx_")

    def test_colab_keeps_priority_for_voice_clone_and_music(
        self, client, monkeypatch, stub_storage, stub_redis, db_session
    ):
        """When Colab is connected, voice_clone and music dispatch to Colab."""
        stub_redis.set("colab:connected", "true")
        set_secret("elevenlabs", "test-eleven-key", db_session)

        dispatched = []

        def mock_dispatch(task_type, parameters, db, **kwargs):
            dispatched.append((task_type, parameters))
            return {
                "status": "DISPATCHED",
                "colab": True,
                "task_id": "colab_gen_audio_123",
            }

        monkeypatch.setattr("app.routers.generate.dispatch_gen_to_colab", mock_dispatch)

        res_clone = client.post(
            "/api/generate/audio?prompt=Clone+speech&type=voice_clone&reference=uploads/speaker.wav"
        )
        assert res_clone.status_code == 200
        body = res_clone.json()
        assert body["status"] == "DISPATCHED"
        assert len(dispatched) == 1
        assert dispatched[0][0] == "audio_generation"
        assert dispatched[0][1]["type"] == "voice_clone"

        # Also test music
        res_music = client.post(
            "/api/generate/audio?prompt=Rock+track&type=music"
        )
        assert res_music.status_code == 200
        assert len(dispatched) == 2
        assert dispatched[1][1]["type"] == "music"


class TestFix3ReferenceResolutionAndValidation:
    """FIX 3: Reference is resolved to real file or returns 400; validation allows relative paths with '/'."""

    def test_missing_reference_in_storage_returns_400(self, client, monkeypatch):
        """Missing reference in storage returns 400 with actionable message."""
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        res = client.post(
            "/api/generate/audio?prompt=Clone&type=voice_clone&reference=uploads/nonexistent.wav&provider=local"
        )
        assert res.status_code == 400
        detail = res.json()["detail"].lower()
        assert "not found" in detail or "unreadable" in detail

    def test_reference_validation_rejects_traversal_and_accepts_slashes(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """Path traversal/absolute paths are rejected; valid slash paths are accepted."""
        for bad in ("../etc/passwd", "/etc/passwd", "..\\evil.wav", "", "   "):
            res = client.post(
                f"/api/generate/audio?prompt=Clone&type=voice_clone&reference={bad}&provider=local"
            )
            assert res.status_code == 400, f"Expected 400 for bad reference: {bad!r}"

        valid_ref = "uploads/speaker.wav"
        stub_storage["uploaded"][valid_ref] = {
            "data": b"RIFFsample-wav-data",
            "content_type": "audio/wav",
        }
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFcloned-audio",
        )

        res = client.post(
            f"/api/generate/audio?prompt=Clone&type=voice_clone&reference={valid_ref}&provider=local"
        )
        assert res.status_code == 200
        assert res.json()["status"] == "COMPLETED"


class TestFix4MusicgenLargePrecision:
    """FIX 4: Model identity facebook/musicgen-large, fp16 on CUDA, torch.inference_mode()."""

    def test_musicgen_loader_uses_large_model_and_fp16_on_cuda(self, monkeypatch):
        import sys
        import types
        from unittest.mock import MagicMock
        from app.ml.audio import make_audio_loader

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.float16 = "fp16-marker"

        mock_transformers = types.ModuleType("transformers")
        mock_proc_cls = MagicMock()
        mock_model_cls = MagicMock()
        mock_transformers.AutoProcessor = mock_proc_cls
        mock_transformers.MusicgenForConditionalGeneration = mock_model_cls

        monkeypatch.setitem(sys.modules, "torch", mock_torch)
        monkeypatch.setitem(sys.modules, "transformers", mock_transformers)

        loader = make_audio_loader("musicgen")
        pipeline = loader()

        mock_proc_cls.from_pretrained.assert_called_once_with("facebook/musicgen-large")
        mock_model_cls.from_pretrained.assert_called_once_with(
            "facebook/musicgen-large", torch_dtype="fp16-marker"
        )

    def test_musicgen_pipeline_runs_in_inference_mode(self, monkeypatch):
        import sys
        from unittest.mock import MagicMock
        from app.ml.audio import MusicgenPipeline

        inference_mode_active = []

        class FakeInferenceMode:
            def __enter__(self):
                inference_mode_active.append(True)
                return self

            def __exit__(self, *args):
                inference_mode_active.append(False)

        mock_torch = MagicMock()
        mock_torch.inference_mode.side_effect = FakeInferenceMode
        monkeypatch.setitem(sys.modules, "torch", mock_torch)

        mock_model = MagicMock()
        mock_values = MagicMock()
        mock_values.__getitem__.return_value.cpu.return_value.numpy.return_value = MagicMock(ndim=1)
        mock_model.generate.return_value = mock_values

        mock_processor = MagicMock()
        mock_processor.return_value = {"input_ids": MagicMock()}

        pipeline = MusicgenPipeline(model=mock_model, processor=mock_processor, device="cpu")
        monkeypatch.setattr("scipy.io.wavfile.write", lambda buf, rate, data: None)

        pipeline("Test prompt", duration=2.0)
        assert inference_mode_active == [True, False], "inference_mode context was not entered and exited"


class TestFix6DurationValidation:
    """FIX 6: Duration bounded between 0.5 and 30.0 seconds."""

    def test_duration_boundary_validation(self, client, monkeypatch, stub_storage):
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: b"RIFFaudio",
        )

        # 0.49 -> 400
        res = client.post("/api/generate/audio?prompt=test&duration=0.49&provider=local")
        assert res.status_code == 400
        assert "duration" in res.json()["detail"].lower()

        # 30.01 -> 400
        res = client.post("/api/generate/audio?prompt=test&duration=30.01&provider=local")
        assert res.status_code == 400
        assert "duration" in res.json()["detail"].lower()

        # 0.5 -> 200
        res = client.post("/api/generate/audio?prompt=test&duration=0.5&provider=local")
        assert res.status_code == 200

        # 30.0 -> 200
        res = client.post("/api/generate/audio?prompt=test&duration=30.0&provider=local")
        assert res.status_code == 200


class TestFix7XTTSCallingConvention:
    """FIX 7: Real tts_to_file stub exercises speaker_wav resolution and cleanup."""

    def test_xtts_calling_convention_with_real_tts_to_file_stub(
        self, client, monkeypatch, stub_storage, db_session
    ):
        import os

        captured_calls = []

        class StubXTTSModel:
            speakers = ["DefaultSpeaker"]

            def tts_to_file(self, text, file_path, **kwargs):
                captured_calls.append({"text": text, "file_path": file_path, "kwargs": kwargs})
                if "speaker_wav" in kwargs:
                    spk_path = kwargs["speaker_wav"]
                    assert os.path.exists(spk_path), f"speaker_wav path {spk_path} must exist during call"
                    with open(spk_path, "rb") as sf:
                        assert sf.read() == b"RIFFreference-wav-bytes"
                with open(file_path, "wb") as f:
                    f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

        stub_model = StubXTTSModel()
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: stub_model)
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        # 1. Voice clone with reference
        ref_file = "uploads/speaker_voice.wav"
        stub_storage["uploaded"][ref_file] = {
            "data": b"RIFFreference-wav-bytes",
            "content_type": "audio/wav",
        }

        res = client.post(
            f"/api/generate/audio?prompt=Hello+world&type=voice_clone&reference={ref_file}&provider=local"
        )
        assert res.status_code == 200
        assert len(captured_calls) == 1
        clone_call = captured_calls[0]
        assert "speaker_wav" in clone_call["kwargs"]
        temp_speaker_wav = clone_call["kwargs"]["speaker_wav"]
        assert temp_speaker_wav != ref_file
        assert temp_speaker_wav.endswith(".wav")
        # Ensure temp file was cleaned up afterwards
        assert not os.path.exists(temp_speaker_wav)

        # 2. Plain TTS without reference
        captured_calls.clear()
        res_tts = client.post(
            "/api/generate/audio?prompt=Plain+TTS&type=tts&provider=local"
        )
        assert res_tts.status_code == 200
        assert len(captured_calls) == 1
        tts_call = captured_calls[0]
        assert "speaker_wav" not in tts_call["kwargs"], "speaker_wav must NOT be passed when no reference is given"


class TestCodeRabbitFixesAudio:
    """Tests for CodeRabbit PR #130 review findings (B1, B2)."""

    def test_b1_plain_tts_supplies_deterministic_default_speaker_when_speakers_present(
        self, client, monkeypatch, stub_storage
    ):
        """B1: Plain TTS with model exposing speakers supplies first/lowest-index speaker as default."""
        captured_calls = []

        class StubModelWithSpeakers:
            speakers = ["FirstSpeaker", "SecondSpeaker"]

            def tts_to_file(self, text, file_path, **kwargs):
                captured_calls.append(kwargs)
                with open(file_path, "wb") as f:
                    f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

        stub_model = StubModelWithSpeakers()
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: stub_model)
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        res = client.post("/api/generate/audio?prompt=Hello+default+speaker&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert len(captured_calls) == 1
        assert captured_calls[0].get("speaker") == "FirstSpeaker"
        assert "speaker_wav" not in captured_calls[0]

    def test_b1_plain_tts_refuses_before_inference_when_no_speakers_and_no_reference(
        self, client, monkeypatch
    ):
        """B1: When model has no speakers and request has no reference, refuse before inference with LOAD_FAILED."""
        tts_called = []

        class StubModelNoSpeakers:
            speakers = []

            def tts_to_file(self, text, file_path, **kwargs):
                tts_called.append(True)

        stub_model = StubModelNoSpeakers()
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: stub_model)
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        res = client.post("/api/generate/audio?prompt=Hello+no+speaker&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body.get("degraded") is True
        assert body.get("reason") == DegradedReason.LOAD_FAILED.value
        assert "speaker" in body.get("message", "").lower() or "reference" in body.get("message", "").lower()
        assert len(tts_called) == 0, "tts_to_file must not be called when refused before inference"

    def test_b2_upload_failure_returns_degraded_response_and_does_not_persist(
        self, client, monkeypatch, db_session
    ):
        """B2: Forced upload_object -> False must return degraded failure, not COMPLETED, and not persist MediaAsset."""
        fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

        class StubModel:
            speakers = ["Speaker1"]

            def tts_to_file(self, text, file_path, **kwargs):
                with open(file_path, "wb") as f:
                    f.write(fake_wav)

        stub_model = StubModel()
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: stub_model)
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        import app.ml.audio as audio_mod
        monkeypatch.setattr(audio_mod, "upload_object", lambda *args, **kwargs: False)

        initial_count = db_session.query(MediaAsset).count()
        res = client.post("/api/generate/audio?prompt=Hello+upload+fail&type=tts&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") != "COMPLETED", "Upload failure must not report COMPLETED"
        assert body.get("degraded") is True
        assert body.get("reason") == DegradedReason.LOAD_FAILED.value
        assert "storage" in body.get("message", "").lower() or "upload" in body.get("message", "").lower()
        assert db_session.query(MediaAsset).count() == initial_count, "MediaAsset must not be persisted on upload failure"

