"""
Batch CLI for tile generation — processes quadrants directly or from
a JSON plan file.

Usage:
    # Direct quadrants:
    python -m sprite_nyc.e2e_generation.generate_tiles_omni \
        --generation-dir generations/manhattan/ \
        --quadrants "0,0" "1,0"

    # From plan file:
    python -m sprite_nyc.e2e_generation.generate_tiles_omni \
        --generation-dir generations/manhattan/ \
        --plan-file generate_strip_plan.json
"""

from __future__ import annotations

import json
import time
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
@click.option("--plan-file", default=None, help="JSON plan file with generation steps")
@click.option("--dry-run", is_flag=True)
@click.argument("quadrants", nargs=-1)
def main(
    generation_dir: str,
    api_key: str,
    gcs_bucket: str,
    tile_size: int,
    plan_file: str | None,
    dry_run: bool,
    quadrants: tuple[str, ...],
) -> None:
    """Batch generate tiles from quadrant list or plan file."""
    gd = Path(generation_dir)

    if plan_file:
        _run_from_plan(gd, plan_file, api_key, gcs_bucket, tile_size, dry_run)
    elif quadrants:
        coords = [parse_quadrant_tuple(q) for q in quadrants]
        run_generation_for_quadrants(gd, coords, api_key, gcs_bucket, tile_size, dry_run)
    else:
        raise click.ClickException("Provide --plan-file or quadrant arguments")


def _run_from_plan(
    generation_dir: Path,
    plan_file: str,
    api_key: str,
    gcs_bucket: str,
    tile_size: int,
    dry_run: bool,
) -> None:
    """Execute a JSON plan file with multiple generation steps."""
    with open(plan_file) as f:
        plan = json.load(f)

    steps = plan.get("steps", [])
    print(f"Plan has {len(steps)} steps")

    for i, step in enumerate(steps):
        status = step.get("status", "pending")
        if status == "done":
            print(f"Step {i + 1}/{len(steps)}: already done, skipping")
            continue
        if status == "error":
            print(f"Step {i + 1}/{len(steps)}: previous error, skipping")
            continue

        coords = [tuple(c) for c in step["quadrants"]]
        print(f"\nStep {i + 1}/{len(steps)}: generating {len(coords)} quadrant(s)")

        try:
            start = time.time()
            run_generation_for_quadrants(
                generation_dir, coords, api_key, gcs_bucket, tile_size, dry_run
            )
            elapsed = time.time() - start
            step["status"] = "done"
            step["elapsed_seconds"] = round(elapsed, 1)
            print(f"Step {i + 1} done in {elapsed:.1f}s")
        except Exception as e:
            step["status"] = "error"
            step["error"] = str(e)
            print(f"Step {i + 1} failed: {e}")

        # Save progress
        with open(plan_file, "w") as f:
            json.dump(plan, f, indent=2)


if __name__ == "__main__":
    main()
