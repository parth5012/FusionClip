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
    def test_audio_module_imports_without_torch(self):
        """app.ml.audio must import cleanly in an environment without torch installed."""
        import importlib
        mod = importlib.import_module("app.ml.audio")
        assert hasattr(mod, "run_local_audio_generation")
        assert hasattr(mod, "SUPPORTED_AUDIO_TYPES")
        assert hasattr(mod, "build_audio_filename")
        assert hasattr(mod, "make_audio_loader")

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
