"""
Batch-generate pixel art for a grid of tiles using the Oxen.ai API.

Iterates tiles in spiral order from center outward so each tile has
neighbor context from previously generated tiles.  Creates 3×3
non-overlapping templates (matching the e2e pipeline's infill_template
format) where the target tile is 1/9 of the image with a red border.

Usage:
    python -m sprite_nyc.batch_generate \
        --tiles-dir output/test_grid \
        --api-key <key>
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import click
from PIL import Image, ImageDraw

from sprite_nyc.gcs_upload import upload_pil_image
from sprite_nyc.generate_tile_oxen import generate_from_url, PROMPT

BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH = 1


def _load_image(path: Path) -> Image.Image | None:
    if path.exists():
        return Image.open(path).convert("RGBA")
    return None


def _spiral_order(rows: int, cols: int) -> list[tuple[int, int]]:
    """Return (row, col) pairs in spiral order from center outward.

    Within each Chebyshev ring, cardinal neighbors (sharing a row or
    column with center) are processed before diagonal ones.
    """
    coords = [(r, c) for r in range(rows) for c in range(cols)]
    if not coords:
        return []

    cr = (rows - 1) / 2
    cc = (cols - 1) / 2

    def sort_key(rc: tuple[int, int]) -> tuple[float, int, int, int]:
        r, c = rc
        ring = max(abs(r - cr), abs(c - cc))
        is_diagonal = 1 if (abs(r - cr) > 0 and abs(c - cc) > 0) else 0
        return (ring, is_diagonal, r, c)

    coords.sort(key=sort_key)
    return coords


def _build_template(
    target_row: int,
    target_col: int,
    tiles_dir: Path,
    rows: int,
    cols: int,
    tile_w: int,
    tile_h: int,
) -> Image.Image:
    """Build a 3×3 non-overlapping template with the target at center.

    Matches the e2e pipeline's infill_template format:
      - 3×3 grid of tiles placed side-by-side (no overlap)
      - Target tile's render at center with red border
      - 8 surrounding tiles as context (pixel art if generated, else black)
      - Template size = 3 * tile_size (e.g. 3072×3072 for 1024 tiles)
    """
    comp_w = tile_w * 3
    comp_h = tile_h * 3
    template = Image.new("RGBA", (comp_w, comp_h), (0, 0, 0, 255))

    # Place target render at center
    target_dir = tiles_dir / f"tile_{target_row}_{target_col}"
    target_render = _load_image(target_dir / "render.png")
    cx, cy = tile_w, tile_h  # center position
    if target_render:
        template.paste(target_render, (cx, cy))

    # Place 8 neighbors around the target
    for dr in range(-1, 2):
        for dc in range(-1, 2):
            if dr == 0 and dc == 0:
                continue
            nr = target_row + dr
            nc = target_col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue
            tile_dir = tiles_dir / f"tile_{nr}_{nc}"
            # Only use generated pixel art for context (not renders)
            img = _load_image(tile_dir / "generation.png")
            if img is None:
                continue
            px = (dc + 1) * tile_w
            py = (dr + 1) * tile_h
            template.paste(img, (px, py), img)

    # Red border around the center tile
    draw = ImageDraw.Draw(template)
    for i in range(BORDER_WIDTH):
        draw.rectangle(
            [cx + i, cy + i, cx + tile_w - 1 - i, cy + tile_h - 1 - i],
            outline=BORDER_COLOR,
        )

    return template


def batch_generate(
    tiles_dir: Path,
    api_key: str,
    gcs_bucket: str,
    dry_run: bool,
) -> None:
    manifest_path = tiles_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {tiles_dir}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    max_row = max(t["row"] for t in manifest)
    max_col = max(t["col"] for t in manifest)
    rows = max_row + 1
    cols = max_col + 1

    # Get tile dimensions from first render
    first_dir = Path(manifest[0]["dir"])
    first_img = Image.open(first_dir / "render.png")
    tile_w, tile_h = first_img.size
    first_img.close()

    template_size = tile_w * 3
    target_pct = 100 / 9
    print(f"3×3 template: {template_size}×{template_size}, target tile: {tile_w}×{tile_h} ({target_pct:.0f}%)")

    order = _spiral_order(rows, cols)
    total = len(order)
    print(f"Generating {total} tiles in spiral order from center")

    for i, (r, c) in enumerate(order):
        tile_dir = tiles_dir / f"tile_{r}_{c}"
        gen_path = tile_dir / "generation.png"

        if gen_path.exists():
            print(f"\n[{i + 1}/{total}] tile_{r}_{c} — already generated, skipping")
            continue

        print(f"\n[{i + 1}/{total}] Generating tile_{r}_{c}…")

        render = _load_image(tile_dir / "render.png")
        if render is None:
            print(f"  No render.png in {tile_dir}, skipping")
            continue

        # Build 3×3 template with target at center + 8 neighbors
        template = _build_template(r, c, tiles_dir, rows, cols, tile_w, tile_h)
        print(f"  Template: {template.size[0]}×{template.size[1]}")

        # Save template for debugging
        template.save(tile_dir / "template.png")

        if dry_run:
            print("  Dry run — skipping API call")
            continue

        # Upload and generate
        print("  Uploading to GCS…")
        public_url = upload_pil_image(template, bucket_name=gcs_bucket)

        print("  Calling Oxen API…")
        start = time.time()
        result = generate_from_url(public_url, api_key, PROMPT)
        elapsed = time.time() - start
        print(f"  Generation took {elapsed:.1f}s, result: {result.size[0]}×{result.size[1]}")

        # API returns 1024×1024 (model resolution). Upscale to template
        # dimensions and crop center tile.
        if result.size != template.size:
            result = result.resize(template.size, Image.LANCZOS)
        generation = result.crop((tile_w, tile_h, tile_w * 2, tile_h * 2))
        generation.save(gen_path)
        print(f"  Saved {gen_path}")

    print(f"\nDone — generated {total} tiles")


@click.command()
@click.option("--tiles-dir", required=True, help="Tiles directory with manifest.json")
@click.option(
    "--api-key",
    envvar="OXEN_INFILL_V02_API_KEY",
    required=True,
    help="Oxen API key",
)
@click.option("--gcs-bucket", default="sprite-nyc-assets", help="GCS bucket name")
@click.option("--dry-run", is_flag=True, help="Save templates only, don't call API")
def main(tiles_dir: str, api_key: str, gcs_bucket: str, dry_run: bool) -> None:
    """Batch-generate pixel art tiles with neighbor context."""
    batch_generate(Path(tiles_dir), api_key, gcs_bucket, dry_run)


if __name__ == "__main__":
    main()
