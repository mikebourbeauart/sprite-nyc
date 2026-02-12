"""
Direct Oxen.ai API wrapper for tile generation.

Lower-level than generate_tile.py — accepts an image path or URL
directly and returns the generation result.

Usage:
    python -m sprite_nyc.generate_tile_oxen \
        --image template.png \
        --output generation.png
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import click
import requests
from PIL import Image

from sprite_nyc.gcs_upload import upload_file, upload_pil_image


OXEN_API_URL = "https://hub.oxen.ai/api/images/edit"
OXEN_MODEL = "mike804-nice-aqua-muskox"
NUM_INFERENCE_STEPS = 28
PROMPT = "Convert to <isometric nyc pixel art>"


def generate_from_url(
    image_url: str, api_key: str, prompt: str = PROMPT
) -> Image.Image:
    """Call Oxen API with an image URL and return the result."""
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": OXEN_MODEL,
        "input_image": image_url,
        "prompt": prompt,
        "num_inference_steps": NUM_INFERENCE_STEPS,
    }

    resp = requests.post(OXEN_API_URL, json=payload, headers=headers, timeout=300)
    resp.raise_for_status()
    result = resp.json()

    # Response may have url at top level or nested under images[0].url
    result_url = result.get("url") or result.get("image_url")
    if not result_url and result.get("images"):
        result_url = result["images"][0].get("url")
    if not result_url:
        raise ValueError(f"No result URL in API response: {result}")

    img_resp = requests.get(result_url, timeout=60)
    img_resp.raise_for_status()
    return Image.open(io.BytesIO(img_resp.content)).convert("RGBA")


def generate_from_file(
    image_path: str | Path,
    api_key: str,
    gcs_bucket: str = "sprite-nyc-assets",
    prompt: str = PROMPT,
) -> Image.Image:
    """Upload a local image to GCS, then call Oxen API."""
    public_url = upload_file(image_path, bucket_name=gcs_bucket)
    return generate_from_url(public_url, api_key, prompt)


def generate_from_pil(
    image: Image.Image,
    api_key: str,
    gcs_bucket: str = "sprite-nyc-assets",
    prompt: str = PROMPT,
) -> Image.Image:
    """Upload a PIL Image to GCS, then call Oxen API."""
    public_url = upload_pil_image(image, bucket_name=gcs_bucket)
    return generate_from_url(public_url, api_key, prompt)


@click.command()
@click.option("--image", required=True, help="Input image path or URL")
@click.option("--output", default="generation.png", help="Output path")
@click.option("--api-key", envvar="OXEN_INFILL_V02_API_KEY", required=True)
@click.option("--gcs-bucket", default="sprite-nyc-assets")
def main(image: str, output: str, api_key: str, gcs_bucket: str) -> None:
    """Generate pixel art from an infill template."""
    start = time.time()

    if image.startswith("http://") or image.startswith("https://"):
        print(f"Using URL: {image}")
        result = generate_from_url(image, api_key)
    else:
        print(f"Uploading {image} to GCS…")
        result = generate_from_file(image, api_key, gcs_bucket)

    elapsed = time.time() - start
    print(f"Generation took {elapsed:.1f}s")

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
