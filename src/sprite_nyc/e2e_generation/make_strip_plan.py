"""
Generate a JSON plan for strip-based tile generation.

Strips are rows or columns of quadrants that can be generated
sequentially. The plan handles different strategies based on depth:
  - Depth 1: Single quadrant per step
  - Depth 2: Pairs of quadrants
  - Depth 3: Triplets
  - Depth >3: Max 4 quadrants per step

Usage:
    python -m sprite_nyc.e2e_generation.make_strip_plan \
        --generation-dir generations/manhattan/ \
        --top-left "0,0" \
        --bottom-right "5,3" \
        --output generate_strip_0_0_5_3.json
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import click

from sprite_nyc.e2e_generation.generate_omni import load_grid_from_db
from sprite_nyc.e2e_generation.infill_template import QuadrantState


def make_strip_plan(
    grid_states: dict[tuple[int, int], QuadrantState],
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
) -> dict:
    """
    Create a strip-based generation plan.

    The plan scans left-to-right, top-to-bottom within the specified
    grid coordinates. Each step generates a column-strip of quadrants.
    """
    tl_x, tl_y = top_left
    br_x, br_y = bottom_right

    min_x = min(tl_x, br_x)
    max_x = max(tl_x, br_x)
    min_y = min(tl_y, br_y)
    max_y = max(tl_y, br_y)

    depth = max_y - min_y + 1  # rows per strip

    steps = []
    for x in range(min_x, max_x + 1):
        col_quads = []
        for y in range(min_y, max_y + 1):
            state = grid_states.get((x, y), QuadrantState.EMPTY)
            if state != QuadrantState.GENERATED:
                col_quads.append([x, y])

        if not col_quads:
            continue

        # Split column into batches based on depth strategy
        if depth <= 3:
            # Generate entire column at once
            steps.append({
                "quadrants": col_quads,
                "status": "pending",
            })
        else:
            # Split into chunks of 4
            for i in range(0, len(col_quads), 4):
                chunk = col_quads[i : i + 4]
                steps.append({
                    "quadrants": chunk,
                    "status": "pending",
                })

    plan = {
        "top_left": [tl_x, tl_y],
        "bottom_right": [br_x, br_y],
        "depth": depth,
        "total_steps": len(steps),
        "steps": steps,
    }

    return plan


def parse_grid_coord(s: str) -> tuple[int, int]:
    parts = s.split(",")
    return int(parts[0].strip()), int(parts[1].strip())


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--top-left", required=True, help="Top-left grid coord as 'x,y'")
@click.option("--bottom-right", required=True, help="Bottom-right grid coord as 'x,y'")
@click.option("--output", default=None, help="Output JSON path")
def main(
    generation_dir: str,
    top_left: str,
    bottom_right: str,
    output: str | None,
) -> None:
    """Generate a strip-based generation plan."""
    gd = Path(generation_dir)
    db_path = gd / "quadrants.db"

    tl = parse_grid_coord(top_left)
    br = parse_grid_coord(bottom_right)

    grid = load_grid_from_db(db_path)
    grid_states = {k: q.state for k, q in grid.items()}

    plan = make_strip_plan(grid_states, tl, br)

    if output is None:
        output = f"generate_strip_{tl[0]}_{tl[1]}_{br[0]}_{br[1]}.json"

    out_path = gd / output
    with open(out_path, "w") as f:
        json.dump(plan, f, indent=2)

    print(f"Plan: {plan['total_steps']} steps, depth {plan['depth']}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
