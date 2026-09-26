"""Tests for subtitle extraction, sidecar upload, and API endpoints (#109).

Covers:
- Embedded-track extraction with ffprobe and ffmpeg to WebVTT
- Unsupported codec handling (PGS bitmap subtitles skipped gracefully)
- Missing/failing ffmpeg/ffprobe graceful degradation (no 500 error)
- Zero embedded tracks handling
- Sidecar upload validation (.vtt, .srt conversion, size cap, reject corrupt/unreadable)
- Subtitle listing and deletion APIs
- Presigned URL generation for tracks
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models import MediaAsset, SubtitleTrack


SAMPLE_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Hello world, this is a test caption.

2
00:00:05.000 --> 00:00:08.000
Second subtitle line here.
"""

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:04,000
Hello world, this is a test caption.

2
00:00:05,000 --> 00:00:08,000
Second subtitle line here.
"""


@pytest.fixture()
def sample_video_asset(db_session):
    asset = MediaAsset(
        title="test_clip.mp4",
        file_path="uploads/test_clip.mp4",
        file_size=1024 * 1024,
        content_type="video/mp4",
        duration=12.5,
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return asset


class TestSidecarUploadValidation:
    def test_upload_valid_vtt_success(self, client, db_session, sample_video_asset, stub_storage):
        files = {"file": ("captions.vtt", SAMPLE_VTT.encode("utf-8"), "text/vtt")}
        data = {"label": "English", "language": "en"}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files, data=data)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["asset_id"] == sample_video_asset.id
        assert body["label"] == "English"
        assert body["language"] == "en"
        assert body["format"] == "vtt"
        assert body["track_type"] == "sidecar"
        assert body["url"] == f"/api/media/{sample_video_asset.id}/subtitles/{body['id']}/content"
        assert body["file_path"].endswith(".vtt")

    def test_upload_valid_srt_converted_to_vtt(self, client, db_session, sample_video_asset, stub_storage):
        files = {"file": ("french.srt", SAMPLE_SRT.encode("utf-8"), "application/x-subrip")}
        data = {"label": "French", "language": "fr"}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files, data=data)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["asset_id"] == sample_video_asset.id
        assert body["label"] == "French"
        assert body["format"] == "vtt"
        # Stored content must be WebVTT
        stored_bytes = stub_storage["uploaded"][body["file_path"]]["data"]
        assert stored_bytes.startswith(b"WEBVTT")
        assert b"00:00:01.000 --> 00:00:04.000" in stored_bytes

    def test_upload_rejects_unsupported_file_extension(self, client, sample_video_asset):
        files = {"file": ("subtitles.txt", b"plain text content", "text/plain")}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files)
        assert res.status_code == 400
        assert "Only .vtt and .srt files are supported" in res.json()["detail"]

    def test_upload_rejects_oversized_file(self, client, sample_video_asset):
        large_content = b"WEBVTT\n\n" + b"0" * (3 * 1024 * 1024)
        files = {"file": ("giant.vtt", large_content, "text/vtt")}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files)
        assert res.status_code == 400
        assert "exceeds maximum allowed size" in res.json()["detail"]

    def test_upload_rejects_corrupt_vtt_missing_header(self, client, sample_video_asset):
        corrupt = b"This is not a webvtt file at all."
        files = {"file": ("corrupt.vtt", corrupt, "text/vtt")}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files)
        assert res.status_code == 400
        assert "missing WEBVTT header" in res.json()["detail"]

    def test_upload_rejects_corrupt_srt_no_cues(self, client, sample_video_asset):
        corrupt = b"Random string without any timecodes or cue structure."
        files = {"file": ("corrupt.srt", corrupt, "application/x-subrip")}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files)
        assert res.status_code == 400
        assert "no valid subtitle timing cues" in res.json()["detail"]

    def test_upload_derives_label_from_filename_when_omitted(self, client, sample_video_asset, stub_storage):
        files = {"file": ("spanish_dialogue.vtt", SAMPLE_VTT.encode("utf-8"), "text/vtt")}
        res = client.post(f"/api/media/{sample_video_asset.id}/subtitles", files=files)
        assert res.status_code == 200
        assert res.json()["label"] == "spanish_dialogue"

    def test_upload_to_nonexistent_asset_returns_404(self, client):
        files = {"file": ("test.vtt", SAMPLE_VTT.encode("utf-8"), "text/vtt")}
        res = client.post("/api/media/99999/subtitles", files=files)
        assert res.status_code == 404


class TestSubtitleListAndDeletion:
    def test_list_subtitles_empty(self, client, sample_video_asset):
        res = client.get(f"/api/media/{sample_video_asset.id}/subtitles")
        assert res.status_code == 200
        assert res.json() == []

    def test_list_subtitles_returns_all_tracks(self, client, db_session, sample_video_asset, stub_storage):
        t1 = SubtitleTrack(
            asset_id=sample_video_asset.id,
            label="English",
            language="en",
            file_path=f"subtitles/{sample_video_asset.id}/en.vtt",
            format="vtt",
            track_type="embedded",
        )
        t2 = SubtitleTrack(
            asset_id=sample_video_asset.id,
            label="Spanish Commentary",
            language="es",
            file_path=f"subtitles/{sample_video_asset.id}/es.vtt",
            format="vtt",
            track_type="sidecar",
        )
        db_session.add_all([t1, t2])
        db_session.commit()

        res = client.get(f"/api/media/{sample_video_asset.id}/subtitles")
        assert res.status_code == 200
        tracks = res.json()
        assert len(tracks) == 2
        labels = [t["label"] for t in tracks]
        assert "English" in labels
        assert "Spanish Commentary" in labels
        for t in tracks:
            assert t["url"] == f"/api/media/{sample_video_asset.id}/subtitles/{t['id']}/content"

    def test_list_subtitles_for_nonexistent_asset_returns_404(self, client):
        res = client.get("/api/media/99999/subtitles")
        assert res.status_code == 404

    def test_delete_subtitle_track(self, client, db_session, sample_video_asset, stub_storage):
        t = SubtitleTrack(
            asset_id=sample_video_asset.id,
            label="To Delete",
            language="en",
            file_path=f"subtitles/{sample_video_asset.id}/delete.vtt",
            format="vtt",
            track_type="sidecar",
        )
        db_session.add(t)
        db_session.commit()
        db_session.refresh(t)

        del_res = client.delete(f"/api/media/{sample_video_asset.id}/subtitles/{t.id}")
        assert del_res.status_code == 200
        assert del_res.json()["message"] == "Subtitle track deleted successfully"

        # Verify gone
        list_res = client.get(f"/api/media/{sample_video_asset.id}/subtitles")
        assert list_res.json() == []


class TestEmbeddedTrackExtraction:
    def test_probe_embedded_subtitle_tracks_finds_streams(self):
        from app.services.subtitles import probe_subtitle_streams

        ffprobe_output = json.dumps({
            "streams": [
                {
                    "index": 2,
                    "codec_name": "subrip",
                    "tags": {"language": "eng", "title": "English Dialogue"}
                },
                {
                    "index": 3,
                    "codec_name": "webvtt",
                    "tags": {"language": "spa", "title": "Spanish"}
                }
            ]
        })

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ffprobe_output, stderr="", returncode=0)
            streams = probe_subtitle_streams("/fake/path.mp4")
            assert len(streams) == 2
            assert streams[0]["index"] == 2
            assert streams[0]["codec_name"] == "subrip"
            assert streams[0]["language"] == "eng"
            assert streams[0]["label"] == "English Dialogue"
            assert streams[1]["language"] == "spa"

    def test_probe_handles_missing_tags(self):
        from app.services.subtitles import probe_subtitle_streams

        ffprobe_output = json.dumps({
            "streams": [
                {"index": 1, "codec_name": "mov_text"}
            ]
        })

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ffprobe_output, stderr="", returncode=0)
            streams = probe_subtitle_streams("/fake/path.mp4")
            assert len(streams) == 1
            assert streams[0]["label"] == "Track 1"
            assert streams[0]["language"] is None

    def test_probe_handles_no_subtitle_streams(self):
        from app.services.subtitles import probe_subtitle_streams

        ffprobe_output = json.dumps({"streams": []})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=ffprobe_output, stderr="", returncode=0)
            streams = probe_subtitle_streams("/fake/path.mp4")
            assert streams == []

    def test_extract_skips_unsupported_pgs_codec(self):
        from app.services.subtitles import extract_track_to_vtt

        # hdmv_pgs_subtitle is bitmap; conversion to text WebVTT is unsupported
        stream_info = {
            "index": 2,
            "codec_name": "hdmv_pgs_subtitle",
            "language": "eng",
            "label": "English PGS",
        }
        result = extract_track_to_vtt("/fake/in.mkv", stream_info, "/fake/out.vtt")
        assert result is False, "Bitmap PGS subtitles should be skipped gracefully"

    def test_extract_degrades_gracefully_when_ffmpeg_missing(self):
        from app.services.subtitles import extract_track_to_vtt

        stream_info = {
            "index": 2,
            "codec_name": "subrip",
            "language": "eng",
            "label": "English",
        }
        with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            result = extract_track_to_vtt("/fake/in.mp4", stream_info, "/fake/out.vtt")
            assert result is False

    def test_extract_on_demand_endpoint(self, client, db_session, sample_video_asset, stub_storage):
        from app.services import subtitles

        probe_mock = [
            {"index": 2, "codec_name": "subrip", "language": "eng", "label": "English"}
        ]

        def fake_extract(input_path, stream_info, output_path):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_VTT)
            return True

        stub_storage["uploaded"][sample_video_asset.file_path] = {
            "data": b"fake video data",
            "content_type": "video/mp4",
        }

        with patch.object(subtitles, "probe_subtitle_streams", return_value=probe_mock), \
             patch.object(subtitles, "extract_track_to_vtt", side_effect=fake_extract):
            res = client.post(f"/api/media/{sample_video_asset.id}/subtitles/extract")
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["extracted_count"] == 1
            assert len(data["tracks"]) == 1
            assert data["tracks"][0]["label"] == "English"
            assert data["tracks"][0]["track_type"] == "embedded"

    def test_extract_on_demand_empty_when_no_embedded_tracks(self, client, sample_video_asset, stub_storage):
        from app.services import subtitles

        stub_storage["uploaded"][sample_video_asset.file_path] = {
            "data": b"fake video data",
            "content_type": "video/mp4",
        }

        with patch.object(subtitles, "probe_subtitle_streams", return_value=[]):
            res = client.post(f"/api/media/{sample_video_asset.id}/subtitles/extract")
            assert res.status_code == 200
            assert res.json()["extracted_count"] == 0
            assert res.json()["tracks"] == []

    def test_get_subtitle_content_endpoint(self, client, db_session, sample_video_asset, stub_storage):
        vtt_path = f"subtitles/{sample_video_asset.id}/stream.vtt"
        stub_storage["uploaded"][vtt_path] = {
            "data": SAMPLE_VTT.encode("utf-8"),
            "content_type": "text/vtt",
        }
        track = SubtitleTrack(
            asset_id=sample_video_asset.id,
            label="Streaming VTT",
            language="en",
            file_path=vtt_path,
            format="vtt",
            track_type="sidecar",
        )
        db_session.add(track)
        db_session.commit()
        db_session.refresh(track)

        res = client.get(f"/api/media/{sample_video_asset.id}/subtitles/{track.id}/content")
        assert res.status_code == 200
        assert "text/vtt" in res.headers["content-type"]
        assert "WEBVTT" in res.text

    def test_delete_nonexistent_subtitle_returns_404(self, client, sample_video_asset):
        res = client.delete(f"/api/media/{sample_video_asset.id}/subtitles/9999")
        assert res.status_code == 404

    def test_extract_twice_idempotency(self, client, db_session, sample_video_asset, stub_storage):
        from app.services import subtitles

        probe_mock = [
            {"index": 2, "codec_name": "subrip", "language": "eng", "label": "English"}
        ]

        def fake_extract(input_path, stream_info, output_path):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_VTT)
            return True

        stub_storage["uploaded"][sample_video_asset.file_path] = {
            "data": b"fake video data",
            "content_type": "video/mp4",
        }

        with patch.object(subtitles, "probe_subtitle_streams", return_value=probe_mock), \
             patch.object(subtitles, "extract_track_to_vtt", side_effect=fake_extract):
            res1 = client.post(f"/api/media/{sample_video_asset.id}/subtitles/extract")
            assert res1.status_code == 200
            assert res1.json()["extracted_count"] == 1

            # Run a second time
            res2 = client.post(f"/api/media/{sample_video_asset.id}/subtitles/extract")
            assert res2.status_code == 200
            assert res2.json()["extracted_count"] == 1

            # Assert DB has exactly one row for this asset
            rows = db_session.query(SubtitleTrack).filter(SubtitleTrack.asset_id == sample_video_asset.id).all()
            assert len(rows) == 1
            assert rows[0].label == "English"

    def test_video_upload_dispatches_celery_task_and_does_not_block(self, client, stub_storage):
        with patch("app.tasks.extract_media_subtitles.delay") as mock_delay:
            res = client.post(
                "/api/storage/upload",
                files={"file": ("fast_upload.mp4", b"dummy video bytes", "video/mp4")},
            )
            assert res.status_code == 200
            assert mock_delay.called
            # Verify passed asset id as integer, NOT raw bytes
            args, _ = mock_delay.call_args
            assert isinstance(args[0], int)

    def test_celery_task_extract_media_subtitles(self, db_session, sample_video_asset, stub_storage):
        from app.services import subtitles
        from app.tasks import extract_media_subtitles

        probe_mock = [
            {"index": 2, "codec_name": "subrip", "language": "eng", "label": "English"}
        ]

        def fake_extract(input_path, stream_info, output_path):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(SAMPLE_VTT)
            return True

        stub_storage["uploaded"][sample_video_asset.file_path] = {
            "data": b"fake video data",
            "content_type": "video/mp4",
        }

        with patch.object(subtitles, "probe_subtitle_streams", return_value=probe_mock), \
             patch.object(subtitles, "extract_track_to_vtt", side_effect=fake_extract):
            # Run celery task synchronously via apply()
            res = extract_media_subtitles.apply(args=(sample_video_asset.id,))
            assert res.successful()
            track_ids = res.result
            assert len(track_ids) == 1

    def test_subprocess_timeout_handled_gracefully(self):
        from app.services.subtitles import probe_subtitle_streams, extract_track_to_vtt

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)):
            streams = probe_subtitle_streams("/fake/path.mp4")
            assert streams == []

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)):
            success = extract_track_to_vtt("/fake/in.mp4", {"index": 1, "codec_name": "subrip"}, "/fake/out.vtt")
            assert success is False
