"""
Model artifacts (autoencoder.keras, scaler.joblib, isolation_forest.joblib,
metadata.json) live in Blob Storage, not on the Function App's local disk --
the Consumption plan's filesystem is ephemeral/read-only in places, so we
can't rely on a persistent local "models/" folder between invocations or
after a retrain swaps in new files.

Layout in blob storage:
    models/latest/autoencoder.keras
    models/latest/scaler.joblib
    models/latest/isolation_forest.joblib
    models/latest/metadata.json
    models/archive/2026-09-16T02-00-00/...   (previous versions, kept for rollback)

The retrain function writes a new "latest/" on each run (after archiving the
old one); the scoring function downloads "latest/" into /tmp at cold start
and caches it there for the lifetime of the instance.
"""

import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

STORAGE_ACCOUNT_URL = os.environ["MODEL_STORAGE_ACCOUNT_URL"]  # e.g. https://thinkixmodels.blob.core.windows.net
CONTAINER_NAME = os.environ.get("MODEL_CONTAINER_NAME", "anomaly-models")
LOCAL_CACHE_DIR = "/tmp/models"

MODEL_FILES = ["autoencoder.keras", "scaler.joblib", "isolation_forest.joblib", "metadata.json"]


def _client() -> BlobServiceClient:
    credential = DefaultAzureCredential()
    return BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=credential)


def download_latest(force: bool = False) -> str:
    """Downloads models/latest/* into LOCAL_CACHE_DIR, returns the local path.
    Skips re-download if already cached, unless force=True."""
    cache_path = Path(LOCAL_CACHE_DIR)
    marker = cache_path / ".cached"

    if marker.exists() and not force:
        return str(cache_path)

    cache_path.mkdir(parents=True, exist_ok=True)
    service = _client()
    container = service.get_container_client(CONTAINER_NAME)

    for filename in MODEL_FILES:
        blob_path = f"latest/{filename}"
        local_path = cache_path / filename
        with open(local_path, "wb") as f:
            f.write(container.download_blob(blob_path).readall())

    marker.touch()
    return str(cache_path)


def upload_new_version(local_model_dir: str, version_tag: str) -> None:
    """Archives the current 'latest/' under archive/<version_tag>/, then
    uploads local_model_dir's contents as the new 'latest/'."""
    service = _client()
    container = service.get_container_client(CONTAINER_NAME)

    # archive current latest, if it exists
    for filename in MODEL_FILES:
        src_blob = container.get_blob_client(f"latest/{filename}")
        if src_blob.exists():
            dest_blob = container.get_blob_client(f"archive/{version_tag}/{filename}")
            dest_blob.start_copy_from_url(src_blob.url)

    # upload new version as latest
    for filename in MODEL_FILES:
        local_file = Path(local_model_dir) / filename
        with open(local_file, "rb") as f:
            container.upload_blob(name=f"latest/{filename}", data=f, overwrite=True)
