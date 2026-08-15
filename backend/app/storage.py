import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from app.config import settings
import logging
from typing import Generator

logger = logging.getLogger(__name__)

# Internal S3 client (used for backend container-to-container calls)
s3_client = boto3.client(
    "s3",
    endpoint_url=f"http://{settings.MINIO_ENDPOINT}" if not settings.MINIO_USE_SSL else f"https://{settings.MINIO_ENDPOINT}",
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1"
)

# External S3 client (used to sign URLs that client browsers will run on localhost)
s3_external_client = boto3.client(
    "s3",
    endpoint_url=settings.MINIO_EXTERNAL_ENDPOINT,
    aws_access_key_id=settings.MINIO_ROOT_USER,
    aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1"
)

def init_storage():
    """Create bucket if it doesn't already exist."""
    try:
        s3_client.head_bucket(Bucket=settings.MINIO_BUCKET_NAME)
        logger.info(f"MinIO Bucket '{settings.MINIO_BUCKET_NAME}' already exists.")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ["404", "NoSuchBucket"]:
            try:
                s3_client.create_bucket(Bucket=settings.MINIO_BUCKET_NAME)
                logger.info(f"Created MinIO Bucket '{settings.MINIO_BUCKET_NAME}'.")
            except Exception as create_err:
                logger.error(f"Error creating bucket: {create_err}")
        else:
            logger.error(f"Error checking bucket existence: {e}")

def upload_object(file_data, object_name: str, content_type: str = "application/octet-stream") -> bool:
    """Upload dynamic binary files to S3 bucket."""
    try:
        s3_client.put_object(
            Bucket=settings.MINIO_BUCKET_NAME,
            Key=object_name,
            Body=file_data,
            ContentType=content_type
        )
        return True
    except Exception as e:
        logger.error(f"Failed to upload object {object_name} to MinIO: {e}")
        return False

def generate_url(object_name: str, expires_in: int = 3600) -> str:
    """Generate pre-signed S3 URL for web playback/download."""
    try:
        url = s3_external_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.MINIO_BUCKET_NAME, "Key": object_name},
            ExpiresIn=expires_in
        )
        return url
    except Exception as e:
        logger.error(f"Failed to generate presigned URL for {object_name}: {e}")
        return ""

def delete_object(object_name: str) -> bool:
    """Delete object from S3."""
    try:
        s3_client.delete_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
        return True
    except Exception as e:
        logger.error(f"Failed to delete object {object_name}: {e}")
        return False

def list_workspace_files(prefix: str = ""):
    """List S3 bucket directory content support directories hierarchy."""
    # Ensure prefix ends with '/' if it represents a folder
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    try:
        # Fetch S3 files filtering by prefix and collapsing sub-folders using Delimiter='/'
        response = s3_client.list_objects_v2(
            Bucket=settings.MINIO_BUCKET_NAME,
            Prefix=prefix,
            Delimiter="/"
        )
        
        directories = []
        # CommonPrefixes contains directories under this folder
        if "CommonPrefixes" in response:
            for item in response["CommonPrefixes"]:
                # strip out the base path prefix
                full_dir = item["Prefix"]
                dir_name = full_dir[len(prefix):].rstrip("/")
                directories.append({
                    "name": dir_name,
                    "path": full_dir,
                    "type": "directory"
                })

        files = []
        if "Contents" in response:
            for item in response["Contents"]:
                key = item["Key"]
                # Skip the directory folder placeholder object itself if it exists
                if key == prefix:
                    continue
                    
                file_name = key[len(prefix):]
                if not file_name:
                    continue

                files.append({
                    "name": file_name,
                    "path": key,
                    "type": "file",
                    "size": item["Size"],
                    "last_modified": item["LastModified"].isoformat(),
                    "url": generate_url(key)
                })

        return {
            "current_dir": prefix,
            "directories": directories,
            "files": files
        }
    except Exception as e:
        logger.error(f"Failed to list objects in MinIO under prefix '{prefix}': {e}")
        return {"current_dir": prefix, "directories": [], "files": []}

def generate_presigned_upload_url(object_name: str, content_type: str = "application/octet-stream", expires_in: int = 3600) -> str:
    """Generate a pre-signed S3 URL for client-side uploads."""
    try:
        url = s3_external_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.MINIO_BUCKET_NAME,
                "Key": object_name,
                "ContentType": content_type
            },
            ExpiresIn=expires_in
        )
        return url
    except Exception as e:
        logger.error(f"Failed to generate presigned upload URL {object_name}: {e}")
        return ""

def download_bytes(object_name: str) -> bytes:
    """Fetch the full contents of an object as bytes."""
    try:
        response = s3_client.get_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
        return response["Body"].read()
    except Exception as e:
        logger.error(f"Failed to download object {object_name} from MinIO: {e}")
        return b""


def get_object_stream(object_name: str) -> Generator:
    """Stream an S3 object chunk by chunk."""
    try:
        response = s3_client.get_object(Bucket=settings.MINIO_BUCKET_NAME, Key=object_name)
        body = response.get("Body")
        if body:
            for chunk in body.iter_chunks(chunk_size=1024 * 64):
                yield chunk
    except Exception as e:
        logger.error(f"Error streaming object {object_name} from MinIO: {e}")
        yield b""
