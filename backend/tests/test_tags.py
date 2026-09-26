"""Tests for Tag schema, CRUD API endpoints, and AND-filter semantics on MediaAsset (#105)."""

import pytest
from app.models import MediaAsset, Tag


def _create_asset(db, title, file_path="test.png", content_type="image/png", file_size=1024):
    asset = MediaAsset(
        title=title,
        file_path=file_path,
        file_size=file_size,
        content_type=content_type,
        duration=0.0,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def test_tag_model_and_association(db_session):
    """Verify Tag model and many-to-many relationship with MediaAsset."""
    asset = _create_asset(db_session, "Aerial Beach View", "aerial.mp4", "video/mp4")
    tag1 = Tag(name="drone")
    tag2 = Tag(name="sunset")
    db_session.add_all([tag1, tag2])
    db_session.commit()

    asset.tags.append(tag1)
    asset.tags.append(tag2)
    db_session.commit()
    db_session.refresh(asset)

    assert len(asset.tags) == 2
    tag_names = {t.name for t in asset.tags}
    assert tag_names == {"drone", "sunset"}
    assert asset in tag1.assets

    # Deleting an asset should cascade from association table without deleting Tag
    db_session.delete(asset)
    db_session.commit()
    assert db_session.query(Tag).filter(Tag.name == "drone").first() is not None


def test_get_tags_empty_and_list(client, db_session):
    """GET /api/tags should return empty list, then all created tags."""
    res = client.get("/api/tags")
    assert res.status_code == 200
    assert res.json() == []

    tag1 = Tag(name="nature")
    tag2 = Tag(name="action")
    db_session.add_all([tag1, tag2])
    db_session.commit()

    res = client.get("/api/tags")
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 2
    # Alphabetical order
    assert [t["name"] for t in tags] == ["action", "nature"]


def test_create_tag_endpoint(client, db_session):
    """POST /api/tags creates or retrieves existing tag, rejects empty names."""
    # Blank name rejected
    res = client.post("/api/tags", json={"name": "   "})
    assert res.status_code == 400

    # Create tag
    res = client.post("/api/tags", json={"name": "cinematic"})
    assert res.status_code in (200, 201)
    data = res.json()
    assert data["name"] == "cinematic"
    assert "id" in data

    # Idempotent create
    res2 = client.post("/api/tags", json={"name": "cinematic"})
    assert res2.status_code in (200, 201)
    assert res2.json()["id"] == data["id"]
    assert db_session.query(Tag).count() == 1


def test_add_and_remove_tag_on_asset(client, db_session):
    """POST and DELETE /api/media/{asset_id}/tags endpoints."""
    asset = _create_asset(db_session, "Mountain Sunset", "mountain.jpg")

    # Add tag
    res = client.post(f"/api/media/{asset.id}/tags", json={"name": "sunset"})
    assert res.status_code in (200, 201)
    data = res.json()
    assert any(t["name"] == "sunset" for t in data["tags"])

    # Verify GET /api/media/{asset_id}/tags
    res = client.get(f"/api/media/{asset.id}/tags")
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 1
    assert tags[0]["name"] == "sunset"
    tag_id = tags[0]["id"]

    # Verify GET /api/media includes tags in serialized asset
    res = client.get("/api/media")
    assert res.status_code == 200
    catalog = res.json()
    matched = next(a for a in catalog if a["id"] == asset.id)
    assert len(matched["tags"]) == 1
    assert matched["tags"][0]["name"] == "sunset"

    # Remove tag
    res = client.delete(f"/api/media/{asset.id}/tags/{tag_id}")
    assert res.status_code == 200
    assert len(res.json()["tags"]) == 0

    # Asset now has 0 tags
    res = client.get(f"/api/media/{asset.id}/tags")
    assert res.status_code == 200
    assert res.json() == []


def test_put_asset_tags_bulk(client, db_session):
    """PUT /api/media/{asset_id}/tags replaces all tags on the asset."""
    asset = _create_asset(db_session, "Forest River", "river.jpg")

    res = client.put(f"/api/media/{asset.id}/tags", json={"tags": ["forest", "water", "nature"]})
    assert res.status_code == 200
    tags = [t["name"] for t in res.json()["tags"]]
    assert set(tags) == {"forest", "water", "nature"}

    # Replace with single tag
    res = client.put(f"/api/media/{asset.id}/tags", json={"tags": ["landscape"]})
    assert res.status_code == 200
    tags = [t["name"] for t in res.json()["tags"]]
    assert tags == ["landscape"]


def test_filter_media_by_tags_and_semantics(client, db_session):
    """GET /api/media?tag=A&tag=B must enforce AND semantics across tags."""
    # Asset 1: sunset, drone
    a1 = _create_asset(db_session, "Sunset Drone", "a1.mp4")
    # Asset 2: sunset, beach
    a2 = _create_asset(db_session, "Sunset Beach", "a2.jpg")
    # Asset 3: drone, city
    a3 = _create_asset(db_session, "City Drone", "a3.mp4")
    # Asset 4: untagged
    a4 = _create_asset(db_session, "Untagged File", "a4.png")

    client.put(f"/api/media/{a1.id}/tags", json={"tags": ["sunset", "drone"]})
    client.put(f"/api/media/{a2.id}/tags", json={"tags": ["sunset", "beach"]})
    client.put(f"/api/media/{a3.id}/tags", json={"tags": ["drone", "city"]})

    # Filter by single tag "sunset" -> a1, a2
    res = client.get("/api/media?tag=sunset")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id, a2.id}

    # Filter by single tag "drone" -> a1, a3
    res = client.get("/api/media?tag=drone")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id, a3.id}

    # Filter by BOTH "sunset" AND "drone" (multi-param) -> ONLY a1
    res = client.get("/api/media?tag=sunset&tag=drone")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id}

    # Filter by comma-separated tags -> ONLY a1
    res = client.get("/api/media?tags=sunset,drone")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id}

    # Filter by tags that no single asset satisfies -> empty list
    res = client.get("/api/media?tag=sunset&tag=city")
    assert res.status_code == 200
    assert res.json() == []

    # Case-insensitive tag matching
    res = client.get("/api/media?tag=SUNSET&tag=DRONE")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id}


def test_delete_tag_endpoint(client, db_session):
    """DELETE /api/tags/{tag_id} deletes tag and cascades from asset_tags."""
    asset = _create_asset(db_session, "Test Asset", "t.png")
    res = client.post(f"/api/media/{asset.id}/tags", json={"name": "temporary"})
    tag_id = res.json()["tags"][0]["id"]

    # Delete tag
    res = client.delete(f"/api/tags/{tag_id}")
    assert res.status_code == 200

    # Tag no longer exists
    assert db_session.query(Tag).filter(Tag.id == tag_id).first() is None
    # Asset has 0 tags
    res = client.get(f"/api/media/{asset.id}/tags")
    assert res.status_code == 200
    assert res.json() == []


def test_search_media_with_tag_filters(client, db_session):
    """GET /api/media/search should filter search results by tags."""
    a1 = _create_asset(db_session, "Mountain Lake Morning", "lake.jpg")
    a2 = _create_asset(db_session, "Mountain Forest Sunset", "forest.jpg")
    client.put(f"/api/media/{a1.id}/tags", json={"tags": ["nature", "lake"]})
    client.put(f"/api/media/{a2.id}/tags", json={"tags": ["nature", "sunset"]})

    # Search query "Mountain" with tag "lake"
    res = client.get("/api/media/search?query=Mountain&tag=lake")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id}

    # Search query "Mountain" with tag "sunset"
    res = client.get("/api/media/search?query=Mountain&tag=sunset")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a2.id}

    # Search query "Mountain" with tag "nature"
    res = client.get("/api/media/search?query=Mountain&tag=nature")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert ids == {a1.id, a2.id}
