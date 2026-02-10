"""
Generate pixel art for specific quadrant coordinates using the omni model.

Usage:
    python -m sprite_nyc.e2e_generation.generate_tile_omni \
        --generation-dir generations/manhattan/ \
        --quadrants "0,0" "1,0" "0,1"
"""

from __future__ import annotations

from pathlib import Path

import click

from sprite_nyc.e2e_generation.generate_omni import (
    parse_quadrant_tuple,
    run_generation_for_quadrants,
)


@click.command()
@click.option("--generation-dir", required=True, help="Generation directory")
@click.option("--api-key", envvar="OXEN_INFILL_V02_API_KEY", required=True)
@click.option("--gcs-bucket", default="sprite-nyc-assets")
@click.option("--tile-size", default=1024, type=int)
@click.option("--dry-run", is_flag=True, help="Create template only")
@click.argument("quadrants", nargs=-1, required=True)
def main(
    generation_dir: str,
    api_key: str,
    gcs_bucket: str,
    tile_size: int,
    dry_run: bool,
    quadrants: tuple[str, ...],
) -> None:
    """Generate pixel art for quadrant coordinates (e.g. '0,0' '1,0')."""
    gd = Path(generation_dir)
    coords = [parse_quadrant_tuple(q) for q in quadrants]

    print(f"Generating {len(coords)} quadrant(s): {coords}")
    results = run_generation_for_quadrants(
        gd, coords, api_key, gcs_bucket, tile_size, dry_run
    )

    if results:
        print(f"Successfully generated {len(results)} quadrant(s)")
    elif not dry_run:
        print("No results returned")


if __name__ == "__main__":
    main()
