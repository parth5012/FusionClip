"""MinIO / S3 object storage endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset
from app.storage import (
    delete_object,
    generate_url,
    list_workspace_files,
    upload_object,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["storage"])


@router.post("/api/storage/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Query("", description="Folder directory location to upload into"),
    db: Session = Depends(get_db),
):
    """Upload media binary content directly into local MinIO storage."""
    file_bytes = await file.read()

    # Clean the folder path and append filename
    folder_prefix = folder.strip("/")
    if folder_prefix:
        object_name = f"{folder_prefix}/{file.filename}"
    else:
        object_name = file.filename

    logger.info(f"Uploading file {file.filename} to S3 Key: {object_name}")

    # Upload binary content using helper
    success = upload_object(file_bytes, object_name, content_type=file.content_type)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to upload file to Minio storage")

    # Record in database
    try:
        asset = MediaAsset(
            title=file.filename,
            file_path=object_name,
            file_size=len(file_bytes),
            content_type=file.content_type,
            duration=0.0,
        )
        db.add(asset)
        db.commit()
        try:
            from app.tasks import generate_media_embedding
            generate_media_embedding.delay(asset.id)
        except Exception as celery_err:
            logger.error(f"Failed to schedule embedding task for asset {asset.id}: {celery_err}")
    except Exception as e:
        logger.error(f"Failed to save asset to db: {e}")
        db.rollback()

    return {
        "message": "File uploaded successfully",
        "filename": file.filename,
        "path": object_name,
        "url": generate_url(object_name),
    }


@router.get("/api/storage/list")
def list_files(prefix: Optional[str] = Query("", description="Directory folder path to inspect")):
    """Retrieve full catalog list of objects (files and directories) inside S3 bucket."""
    return list_workspace_files(prefix)


@router.delete("/api/storage/delete")
def delete_file(path: str = Query(..., description="Absolute key of the object to delete")):
    """Delete an object from MinIO."""
    success = delete_object(path)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete object from S3 storage")
    return {"message": f"Successfully deleted object matching key: {path}"}


@router.post("/api/storage/create-folder")
def create_folder(
    folder_path: str = Query(..., description="Virtual directory structure path to create")
):
    """Simulate filemanager folder creation by creating an empty directory suffix object."""
    clean_path = folder_path.strip("/")
    if not clean_path:
        raise HTTPException(status_code=400, detail="Invalid folder path")

    # S3 folders are virtual and represented by keys ending in '/'
    dir_key = f"{clean_path}/"
    success = upload_object(b"", dir_key, content_type="application/x-directory")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create directory folder structure")

    return {"message": "Folder directory structure created successfully", "path": dir_key}
