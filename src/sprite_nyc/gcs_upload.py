"""
Upload images to Google Cloud Storage for use with the Oxen API.

The Oxen API needs publicly-accessible image URLs. This module uploads
PIL Images or local files to a GCS bucket and returns the public URL.

Requires GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service
account key file, or Application Default Credentials.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

from google.cloud import storage
from PIL import Image


DEFAULT_BUCKET = "sprite-nyc-assets"
DEFAULT_PREFIX = "infill-images/"


def get_client() -> storage.Client:
    """Create a GCS client from environment credentials."""
    return storage.Client(project="isometric-nyc-486920")


def upload_pil_image(
    image: Image.Image,
    bucket_name: str = DEFAULT_BUCKET,
    prefix: str = DEFAULT_PREFIX,
    name: str | None = None,
) -> str:
    """
    Upload a PIL Image to GCS and return its public URL.

    If *name* is not provided, a content-based hash is used.
    """
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()

    if name is None:
        h = hashlib.sha256(data).hexdigest()[:16]
        name = f"{h}.png"

    blob_path = f"{prefix}{name}"
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type="image/png")
    blob.make_public()

    return blob.public_url


def upload_file(
    path: str | Path,
    bucket_name: str = DEFAULT_BUCKET,
    prefix: str = DEFAULT_PREFIX,
    name: str | None = None,
) -> str:
    """Upload a local file to GCS and return its public URL."""
    path = Path(path)
    if name is None:
        name = path.name

    blob_path = f"{prefix}{name}"
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(path), content_type="image/png")
    blob.make_public()

    return blob.public_url
