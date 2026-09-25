"""Tests for real pgvector/semantic search, 384-dim embeddings, and backfill (#80)."""

import pytest
from app.models import MediaAsset
from app.services.embedding import (
    EMBEDDING_DIM,
    get_embedding,
    get_model,
    backfill_media_embeddings,
    compute_cosine_distance,
)


def test_embedding_dimensions_and_consistency():
    """Real embedder must produce exactly 384-dimensional normalized vectors."""
    if get_model() is None:
        pytest.skip("embedding model is unavailable")
    assert EMBEDDING_DIM == 384
    vec1 = get_embedding("ocean waves crashing on shore")
    assert isinstance(vec1, list)
    assert len(vec1) == 384
    assert all(isinstance(x, float) for x in vec1)

    vec2 = get_embedding("ocean waves crashing on shore")
    # Deterministic / consistent
    assert pytest.approx(vec1, rel=1e-5) == vec2

    # Different text produces different vectors
    vec3 = get_embedding("corporate finance budget spreadsheets")
    assert vec1 != vec3
    dist_similar = compute_cosine_distance(vec1, get_embedding("sea water coast"))
    dist_different = compute_cosine_distance(vec1, vec3)
    assert dist_similar < dist_different


def test_semantic_search_meaningfully_ranked(client, db_session, stub_storage):
    """Semantic search must rank conceptually relevant media ahead of irrelevant media,

    even when words do not overlap with the search query.
    """
    if get_model() is None:
        pytest.skip("embedding model is unavailable")
    assets = [
        MediaAsset(
            title="sea_water_coast_timelapse.mp4",
            file_path="sea_water.mp4",
            file_size=1024,
            content_type="video/mp4",
            duration=10.0,
            embedding=get_embedding("sea water coast timelapse"),
        ),
        MediaAsset(
            title="downtown_traffic_night.mp4",
            file_path="traffic.mp4",
            file_size=2048,
            content_type="video/mp4",
            duration=12.0,
            embedding=get_embedding("downtown traffic night"),
        ),
        MediaAsset(
            title="financial_earnings_spreadsheet.pdf",
            file_path="finance.pdf",
            file_size=512,
            content_type="application/pdf",
            duration=0.0,
            embedding=get_embedding("financial earnings spreadsheet"),
        ),
    ]
    db_session.add_all(assets)
    db_session.commit()

    # Query: "marine ocean surf" — zero word overlap with "sea_water_coast_timelapse.mp4"
    res = client.get("/api/media/search?query=marine+ocean+surf&limit=3")
    assert res.status_code == 200
    results = res.json()
    assert len(results) >= 1
    # Most semantically relevant asset should be first
    assert results[0]["title"] == "sea_water_coast_timelapse.mp4"


def test_backfill_media_embeddings(db_session):
    """Backfill should compute and assign 384-dim embeddings to rows missing them."""
    assets = [
        MediaAsset(
            title="mountain_drone_footage.mp4",
            file_path="mountain.mp4",
            file_size=1024,
            content_type="video/mp4",
            duration=5.0,
            embedding=None,
        ),
        MediaAsset(
            title="forest_birds_audio.wav",
            file_path="birds.wav",
            file_size=512,
            content_type="audio/wav",
            duration=3.0,
            embedding=None,
        ),
    ]
    db_session.add_all(assets)
    db_session.commit()

    count = backfill_media_embeddings(db_session)
    assert count == 2

    # Query back from DB
    updated = db_session.query(MediaAsset).filter(
        MediaAsset.title.in_(["mountain_drone_footage.mp4", "forest_birds_audio.wav"])
    ).all()
    for asset in updated:
        assert asset.embedding is not None
        assert len(asset.embedding) == 384


def test_ilike_fallback_when_no_embeddings_exist(client, db_session, stub_storage):
    """When assets have no embeddings, search falls back cleanly to ILIKE text match."""
    asset = MediaAsset(
        title="Unembedded special clip.mp4",
        file_path="unembedded.mp4",
        file_size=1024,
        content_type="video/mp4",
        duration=1.0,
        embedding=None,
    )
    db_session.add(asset)
    db_session.commit()

    res = client.get("/api/media/search?query=special")
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 1
    assert results[0]["title"] == "Unembedded special clip.mp4"


def test_backfill_endpoint(client, db_session, stub_storage):
    """POST /api/media/backfill-embeddings triggers backfill and returns count."""
    asset = MediaAsset(
        title="new_uploaded_file.mp4",
        file_path="new_uploaded_file.mp4",
        file_size=1024,
        content_type="video/mp4",
        duration=1.0,
        embedding=None,
    )
    db_session.add(asset)
    db_session.commit()

    res = client.post("/api/media/backfill-embeddings")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "backfilled": 1}

    refetched = db_session.query(MediaAsset).filter_by(title="new_uploaded_file.mp4").first()
    assert refetched.embedding is not None
    assert len(refetched.embedding) == 384


def test_backfill_endpoint_caps_rows_per_request(client, db_session, stub_storage):
    """max_rows bounds how many NULL-embedding rows a single request re-embeds."""
    for i in range(3):
        db_session.add(
            MediaAsset(
                title=f"cap_{i}.mp4",
                file_path=f"cap_{i}.mp4",
                file_size=1,
                content_type="video/mp4",
                duration=1.0,
                embedding=None,
            )
        )
    db_session.commit()

    res = client.post("/api/media/backfill-embeddings?max_rows=2")
    assert res.status_code == 200
    assert res.json()["backfilled"] == 2
    remaining = (
        db_session.query(MediaAsset)
        .filter(MediaAsset.embedding.is_(None))
        .count()
    )
    assert remaining == 1

    bad = client.post("/api/media/backfill-embeddings?max_rows=0")
    assert bad.status_code == 400
