"""
Automatic generation: expand outward from center in a spiral pattern.

Given a bounding box, creates an in-memory grid, queries the DB for
existing quadrants, and generates outward from the center rectangle
in spiral order: top, right, bottom, left.

Usage:
    python -m sprite_nyc.e2e_generation.auto_generate \
        --generation-dir generations/manhattan/ \
        --top-left "40.73,-74.01" \
        --bottom-right "40.70,-73.99" \
        --dry-run
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import click

from sprite_nyc.e2e_generation.generate_omni import (
    load_grid_from_db,
    run_generation_for_quadrants,
)
from sprite_nyc.e2e_generation.infill_template import QuadrantState


def find_quadrants_in_bounds(
    db_path: Path,
    top_left: tuple[float, float],
    bottom_right: tuple[float, float],
) -> list[tuple[int, int]]:
    """Find all quadrant (x,y) coords within the given lat/lng bounds."""
    tl_lat, tl_lng = top_left
    br_lat, br_lng = bottom_right

    min_lat = min(tl_lat, br_lat)
    max_lat = max(tl_lat, br_lat)
    min_lng = min(tl_lng, br_lng)
    max_lng = max(tl_lng, br_lng)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        """
        SELECT x, y FROM quadrants
        WHERE lat >= ? AND lat <= ? AND lng >= ? AND lng <= ?
        ORDER BY y, x
        """,
        (min_lat, max_lat, min_lng, max_lng),
    )
    coords = [(row[0], row[1]) for row in cursor]
    conn.close()
    return coords


def spiral_order(
    coords: list[tuple[int, int]],
) -> list[list[tuple[int, int]]]:
    """
    Order coordinates in spiral expansion from center outward.

    Returns a list of "rings", where each ring is a list of coordinates.
    The first ring is the center rectangle, subsequent rings expand
    outward.
    """
    if not coords:
        return []

    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Center point
    cx = (min_x + max_x) // 2
    cy = (min_y + max_y) // 2

    coord_set = set(coords)
    rings: list[list[tuple[int, int]]] = []

    # Start from center, expand outward
    max_radius = max(max_x - min_x, max_y - min_y) + 1
    assigned = set()

    for r in range(max_radius + 1):
        ring = []
        if r == 0:
            if (cx, cy) in coord_set:
                ring.append((cx, cy))
        else:
            # Top edge: left to right
            for x in range(cx - r, cx + r + 1):
                pos = (x, cy - r)
                if pos in coord_set and pos not in assigned:
                    ring.append(pos)

            # Right edge: top+1 to bottom
            for y in range(cy - r + 1, cy + r + 1):
                pos = (cx + r, y)
                if pos in coord_set and pos not in assigned:
                    ring.append(pos)

            # Bottom edge: right-1 to left
            for x in range(cx + r - 1, cx - r - 1, -1):
                pos = (x, cy + r)
                if pos in coord_set and pos not in assigned:
                    ring.append(pos)

            # Left edge: bottom-1 to top+1
            for y in range(cy + r - 1, cy - r, -1):
                pos = (cx - r, y)
                if pos in coord_set and pos not in assigned:
                    ring.append(pos)

        if ring:
            rings.append(ring)
            assigned.update(ring)

    return rings


def plan_generation_steps(
    coords: list[tuple[int, int]],
    grid_states: dict[tuple[int, int], QuadrantState],
    max_batch_size: int = 4,
) -> list[list[tuple[int, int]]]:
    """
    Plan generation steps respecting the constraint that each batch
    must have at least one generated neighbor (except the first).

    Processes in spiral order. Each step generates a small batch
    that is adjacent to already-generated quadrants.
    """
    rings = spiral_order(coords)
    generated = {k for k, v in grid_states.items() if v == QuadrantState.GENERATED}
    steps: list[list[tuple[int, int]]] = []

    for ring in rings:
        ungenerated = [c for c in ring if c not in generated]
        if not ungenerated:
            continue

        # Process ring in batches
        batch: list[tuple[int, int]] = []
        for coord in ungenerated:
            batch.append(coord)
            if len(batch) >= max_batch_size:
                steps.append(batch)
                generated.update(batch)
                batch = []

        if batch:
            steps.append(batch)
            generated.update(batch)

    return steps


def parse_coord(s: str) -> tuple[float, float]:
    parts = s.split(",")
    return float(parts[0].strip()), float(parts[1].strip())


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--top-left", required=True, help="Top-left as 'lat,lng'")
@click.option("--bottom-right", required=True, help="Bottom-right as 'lat,lng'")
@click.option("--api-key", envvar="OXEN_INFILL_V02_API_KEY", default="")
@click.option("--max-batch-size", default=4, type=int)
@click.option("--dry-run", is_flag=True, help="Plan only, don't generate")
def main(
    generation_dir: str,
    top_left: str,
    bottom_right: str,
    api_key: str,
    max_batch_size: int,
    dry_run: bool,
) -> None:
    """Auto-generate quadrants in spiral order within bounds."""
    gd = Path(generation_dir)
    db_path = gd / "quadrants.db"

    tl = parse_coord(top_left)
    br = parse_coord(bottom_right)

    print(f"Finding quadrants in bounds {tl} → {br}")
    coords = find_quadrants_in_bounds(db_path, tl, br)
    print(f"Found {len(coords)} quadrants")

    if not coords:
        return

    # Load current state
    grid = load_grid_from_db(db_path)
    grid_states = {k: q.state for k, q in grid.items()}

    steps = plan_generation_steps(coords, grid_states, max_batch_size)
    print(f"Planned {len(steps)} generation steps")

    for i, step in enumerate(steps):
        print(f"\nStep {i + 1}/{len(steps)}: {step}")
        if dry_run:
            continue

        if not api_key:
            print("No API key — skipping generation")
            continue

        try:
            start = time.time()
            run_generation_for_quadrants(gd, step, api_key)
            elapsed = time.time() - start
            print(f"  Done in {elapsed:.1f}s")
        except Exception as e:
            print(f"  Error: {e}")
            print("  Stopping auto-generation")
            break


if __name__ == "__main__":
    main()
