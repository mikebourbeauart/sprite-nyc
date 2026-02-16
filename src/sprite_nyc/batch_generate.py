"""
Batch-generate pixel art for a grid of tiles using the Oxen.ai API.

Iterates tiles in spiral order from center outward so each tile has
neighbor context from previously generated tiles.  Creates 2×2
templates at 1024×1024 (model native resolution) with 512×512 cells,
where the target tile occupies one cell with a red border.

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
CELL_SIZE = 512
TEMPLATE_SIZE = 1024


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


def _best_corner(
    target_row: int,
    target_col: int,
    tiles_dir: Path,
    rows: int,
    cols: int,
) -> tuple[int, int]:
    """Pick the best corner (col_off, row_off) in the 2×2 grid for the target.

    Scores each corner by counting generated neighbors visible in that layout.
    Cardinal neighbors get weight 2, diagonal weight 1.
    """
    best = (0, 0)
    best_score = -1

    for col_off in (0, 1):
        for row_off in (0, 1):
            origin_r = target_row - row_off
            origin_c = target_col - col_off
            score = 0
            for dc in range(2):
                for dr in range(2):
                    if dc == col_off and dr == row_off:
                        continue
                    nr = origin_r + dr
                    nc = origin_c + dc
                    if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                        continue
                    tile_dir = tiles_dir / f"tile_{nr}_{nc}"
                    if (tile_dir / "generation.png").exists():
                        is_cardinal = dc == col_off or dr == row_off
                        score += 2 if is_cardinal else 1
            if score > best_score:
                best_score = score
                best = (col_off, row_off)

    return best


def _build_template(
    target_row: int,
    target_col: int,
    tiles_dir: Path,
    rows: int,
    cols: int,
) -> tuple[Image.Image, int, int]:
    """Build a 2×2 template at 1024×1024 with 512×512 cells.

    Returns (template, col_off, row_off) where col_off/row_off indicate
    the target's position in the 2×2 grid.
    """
    col_off, row_off = _best_corner(target_row, target_col, tiles_dir, rows, cols)
    origin_r = target_row - row_off
    origin_c = target_col - col_off

    template = Image.new("RGBA", (TEMPLATE_SIZE, TEMPLATE_SIZE), (0, 0, 0, 255))

    for dc in range(2):
        for dr in range(2):
            nr = origin_r + dr
            nc = origin_c + dc
            px = dc * CELL_SIZE
            py = dr * CELL_SIZE

            if dc == col_off and dr == row_off:
                # Target cell: paste downscaled render
                target_dir = tiles_dir / f"tile_{nr}_{nc}"
                render = _load_image(target_dir / "render.png")
                if render:
                    resized = render.resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
                    template.paste(resized, (px, py))

                # Red border
                draw = ImageDraw.Draw(template)
                for i in range(BORDER_WIDTH):
                    draw.rectangle(
                        [px + i, py + i, px + CELL_SIZE - 1 - i, py + CELL_SIZE - 1 - i],
                        outline=BORDER_COLOR,
                    )
            else:
                # Neighbor cell: use generated pixel art if available
                if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                    continue
                tile_dir = tiles_dir / f"tile_{nr}_{nc}"
                img = _load_image(tile_dir / "generation.png")
                if img is None:
                    continue
                resized = img.resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
                template.paste(resized, (px, py))

    return template, col_off, row_off


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

    print(f"2×2 template: {TEMPLATE_SIZE}×{TEMPLATE_SIZE}, cell: {CELL_SIZE}×{CELL_SIZE} (25%)")

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

        # Build 2×2 template with target at best corner
        template, col_off, row_off = _build_template(r, c, tiles_dir, rows, cols)
        print(f"  Template: {template.size[0]}×{template.size[1]}, target at ({col_off},{row_off})")

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

        # Crop target's 512×512 cell and upscale to 1024×1024
        assert result.size == (TEMPLATE_SIZE, TEMPLATE_SIZE), (
            f"Expected {TEMPLATE_SIZE}×{TEMPLATE_SIZE} result, got {result.size}"
        )
        px = col_off * CELL_SIZE
        py = row_off * CELL_SIZE
        crop = result.crop((px, py, px + CELL_SIZE, py + CELL_SIZE))
        generation = crop.resize((1024, 1024), Image.LANCZOS)
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
