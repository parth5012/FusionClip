"""Subtitle processing, validation, conversion, and extraction services (#109).

Handles:
- Validation of uploaded .vtt and .srt sidecar subtitle files (size cap, format, header checks)
- In-memory lossless SRT -> WebVTT conversion
- Probing embedded subtitle tracks via ffprobe
- Extracting embedded subtitle tracks via ffmpeg to WebVTT
- Graceful degradation on missing ffmpeg or unsupported bitmap codecs (e.g. PGS)
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import MediaAsset, SubtitleTrack
from app.scratchpad import scratchpad
from app.storage import download_bytes, get_object_bytes, upload_object

logger = logging.getLogger(__name__)

MAX_SUBTITLE_SIZE = 2 * 1024 * 1024  # 2MB cap for subtitle text files
ALLOWED_EXTENSIONS = {".vtt", ".srt"}

# Bitmap or unsupported subtitle codecs that cannot be directly transcoded to WebVTT
UNSUPPORTED_BITMAP_CODECS = {
    "hdmv_pgs_subtitle",
    "pgssub",
    "dvd_subtitle",
    "dvdsub",
    "dvb_subtitle",
    "dvb_teletext",
    "xsub",
}

SRT_TIMESTAMP_PATTERN = re.compile(
    r"(\d{1,2}:\d{2}:\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2})[,.](\d{3})"
)


def validate_and_prepare_subtitle(filename: str, file_bytes: bytes) -> tuple[str, str]:
    """Validate subtitle file extension, size, and content.

    Returns:
        tuple[vtt_content, format]: The cleaned WebVTT text and format ("vtt").
    Raises:
        HTTPException(400): If validation fails.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid subtitle format '{ext}'. Only .vtt and .srt files are supported.",
        )

    if len(file_bytes) > MAX_SUBTITLE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Subtitle file exceeds maximum allowed size ({MAX_SUBTITLE_SIZE // (1024 * 1024)}MB)",
        )

    # Attempt to decode text
    text_content = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text_content = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text_content is None:
        raise HTTPException(
            status_code=400,
            detail="Corrupt or unreadable subtitle file: failed to decode text encoding.",
        )

    stripped = text_content.strip()
    if not stripped:
        raise HTTPException(
            status_code=400,
            detail="Corrupt or empty subtitle file: file contains no content.",
        )

    if ext == ".vtt":
        # Check WEBVTT header
        if not (stripped.startswith("WEBVTT") or stripped.startswith("\ufeffWEBVTT")):
            raise HTTPException(
                status_code=400,
                detail="Corrupt or invalid WebVTT file: missing WEBVTT header.",
            )
        return text_content, "vtt"
    elif ext == ".srt":
        # Validate that SRT contains timestamp cue arrows
        if "-->" not in stripped or not SRT_TIMESTAMP_PATTERN.search(stripped):
            raise HTTPException(
                status_code=400,
                detail="Corrupt or invalid SRT file: no valid subtitle timing cues found.",
            )
        vtt_content = convert_srt_to_vtt(text_content)
        return vtt_content, "vtt"

    raise HTTPException(status_code=400, detail="Unsupported subtitle format.")


def convert_srt_to_vtt(srt_text: str) -> str:
    """Convert SRT formatted subtitle text to WebVTT format."""
    # Replace SRT timestamp comma with WebVTT period
    # e.g., 00:00:01,000 --> 00:00:04,000 -> 00:00:01.000 --> 00:00:04.000
    converted = SRT_TIMESTAMP_PATTERN.sub(r"\1.\2 --> \3.\4", srt_text)

    # Normalize line endings
    lines = converted.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"WEBVTT\n\n{lines}\n"


def probe_subtitle_streams(file_path: str) -> List[dict]:
    """Probe media file for embedded subtitle streams using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "s",
            "-show_entries", "stream=index,codec_name:stream_tags=language,title",
            "-of", "json",
            str(file_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        out = []
        for i, s in enumerate(streams):
            tags = s.get("tags") or {}
            lang = tags.get("language")
            title = tags.get("title")
            label = title or (f"Track {i+1} ({lang})" if lang else f"Track {i+1}")
            out.append({
                "index": s.get("index", i),
                "codec_name": (s.get("codec_name") or "").lower(),
                "language": lang,
                "label": label,
            })
        return out
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe timed out after 30s while probing {file_path}")
        return []
    except FileNotFoundError:
        logger.warning("ffprobe not found on system; skipping embedded subtitle probing")
        return []
    except Exception as e:
        logger.error(f"Failed to probe subtitle streams for {file_path}: {e}")
        return []


def extract_track_to_vtt(input_path: str, stream_info: dict, output_path: str) -> bool:
    """Extract one embedded subtitle stream to WebVTT using ffmpeg."""
    codec = stream_info.get("codec_name", "").lower()
    if codec in UNSUPPORTED_BITMAP_CODECS:
        logger.warning(
            "Skipping subtitle stream %s: codec '%s' is bitmap-based and cannot be converted to WebVTT text",
            stream_info.get("index"),
            codec,
        )
        return False

    try:
        stream_index = stream_info["index"]
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-map", f"0:{stream_index}",
            "-c:s", "webvtt",
            str(output_path),
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            logger.warning(
                "ffmpeg failed to extract subtitle stream %s: %s",
                stream_index,
                res.stderr,
            )
            return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
        return False
    except subprocess.TimeoutExpired:
        logger.warning(
            "ffmpeg timed out after 60s extracting subtitle stream %s from %s",
            stream_info.get("index"),
            input_path,
        )
        return False
    except FileNotFoundError:
        logger.warning("ffmpeg not found on system; skipping subtitle extraction")
        return False
    except Exception as e:
        logger.error(f"Error extracting subtitle stream {stream_info}: {e}")
        return False


def extract_and_save_embedded_subtitles(
    db: Session,
    asset: MediaAsset,
    video_bytes: Optional[bytes] = None,
) -> List[SubtitleTrack]:
    """Detect and extract embedded subtitle streams for a MediaAsset, uploading to MinIO."""
    temp_in = scratchpad.get_temp_path(suffix="_sub_in.tmp")
    created_tracks: List[SubtitleTrack] = []

    try:
        # Write bytes or download from S3
        if video_bytes:
            with open(temp_in, "wb") as f:
                f.write(video_bytes)
        else:
            try:
                data = get_object_bytes(asset.file_path)
            except Exception:
                data = download_bytes(asset.file_path)
            if not data:
                logger.warning(f"Could not read asset {asset.file_path} for subtitle extraction")
                return []
            with open(temp_in, "wb") as f:
                f.write(data)

        streams = probe_subtitle_streams(str(temp_in))
        if not streams:
            logger.info("No embedded subtitle streams found for asset %s", asset.id)
            return []

        for stream in streams:
            stream_idx = stream["index"]
            temp_vtt = scratchpad.get_temp_path(suffix=f"_sub_{stream_idx}.vtt")
            try:
                success = extract_track_to_vtt(str(temp_in), stream, str(temp_vtt))
                if not success:
                    continue

                with open(temp_vtt, "rb") as vf:
                    vtt_bytes = vf.read()

                lang_tag = stream["language"] or f"track_{stream_idx}"
                s3_key = f"subtitles/{asset.id}/embedded_{stream_idx}_{lang_tag}.vtt"
                uploaded = upload_object(vtt_bytes, s3_key, content_type="text/vtt")
                if not uploaded:
                    logger.error(f"Failed to upload extracted subtitle to {s3_key}")
                    continue

                existing = (
                    db.query(SubtitleTrack)
                    .filter(
                        SubtitleTrack.asset_id == asset.id,
                        SubtitleTrack.file_path == s3_key,
                    )
                    .first()
                )
                if existing:
                    existing.label = stream["label"]
                    existing.language = stream["language"]
                    existing.format = "vtt"
                    existing.track_type = "embedded"
                    track = existing
                else:
                    track = SubtitleTrack(
                        asset_id=asset.id,
                        label=stream["label"],
                        language=stream["language"],
                        file_path=s3_key,
                        format="vtt",
                        track_type="embedded",
                    )
                    db.add(track)
                created_tracks.append(track)
            finally:
                scratchpad.remove_path(temp_vtt)

        if created_tracks:
            db.commit()
            for t in created_tracks:
                db.refresh(t)

        return created_tracks
    except Exception as e:
        logger.error(f"Failed extracting embedded subtitles for asset {asset.id}: {e}")
        return []
    finally:
        scratchpad.remove_path(temp_in)
