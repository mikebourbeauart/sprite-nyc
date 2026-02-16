"""
Plan a grid of non-overlapping isometric tiles.

Given a center lat/lng and an m×n grid, this script creates a directory of
tile folders, each containing its own view.json. Tiles are placed edge-to-edge
with no overlap, matching the original author's quadrant approach.

Usage:
    python -m sprite_nyc.plan_tiles \
        --center-lat 40.7128 --center-lng -74.006 \
        --rows 3 --cols 3 \
        --config view.json \
        --output-dir tiles/
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import click


# ── Geo helpers ───────────────────────────────────────────────────────

EARTH_RADIUS_M = 6_378_137.0  # WGS-84 semi-major axis


def meters_per_degree_lat(lat_deg: float) -> float:
    """Approximate metres per degree of latitude at *lat_deg*."""
    return (math.pi / 180) * EARTH_RADIUS_M


def meters_per_degree_lng(lat_deg: float) -> float:
    """Approximate metres per degree of longitude at *lat_deg*."""
    return (math.pi / 180) * EARTH_RADIUS_M * math.cos(math.radians(lat_deg))


def offset_lat_lng(
    lat: float, lng: float, east_m: float, north_m: float
) -> tuple[float, float]:
    """Shift a lat/lng by the given east/north offsets in metres."""
    dlat = north_m / meters_per_degree_lat(lat)
    dlng = east_m / meters_per_degree_lng(lat)
    return lat + dlat, lng + dlng


# ── Isometric frustum stepping ────────────────────────────────────────

def tile_step_vectors(cfg: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Return camera-aligned step vectors for non-overlapping tiling.

    The orthographic camera is rotated by azimuth and tilted by
    elevation.  Steps move by the full tile width/height along the
    camera's own axes so adjacent tiles are non-overlapping.

    Returns
    -------
    col_step : (east_m, north_m)
        Ground shift that moves the image content by the full tile
        width (one column to the right).
    row_step : (east_m, north_m)
        Ground shift that moves the image content by the full tile
        height (one row downward).
    """
    vh = cfg["view_height_meters"]
    aspect = cfg["width"] / cfg["height"]
    el_rad = math.radians(abs(cfg["elevation"]))
    az_rad = math.radians(cfg["azimuth"])

    full_w = vh * aspect  # camera frustum full width in metres
    full_h = vh           # camera frustum full height in metres

    # The camera is positioned at (azimuth from North, elevation above
    # horizon) and looks back toward the center.  In this isometric view
    # the camera's right axis in ENU is (-cos(az), sin(az), 0) — roughly
    # westward for az = -15°.  "Right in the image" therefore corresponds
    # to westward on the ground.
    #
    # Column step: shift the camera by full_w along camera-right so the
    # image content scrolls left by 1024 px (= next column to the right).
    col_step_east = -full_w * math.cos(az_rad)
    col_step_north = full_w * math.sin(az_rad)

    # Row step: shift the camera so the image content scrolls up by
    # 1024 px (= next row downward).  The ground distance is stretched
    # by 1/sin(elevation) due to the oblique view angle.
    ground_h = full_h / math.sin(el_rad)
    row_step_east = ground_h * math.sin(az_rad)
    row_step_north = ground_h * math.cos(az_rad)

    return (col_step_east, col_step_north), (row_step_east, row_step_north)


# ── Main planning logic ──────────────────────────────────────────────

def plan_tile_grid(
    center_lat: float,
    center_lng: float,
    rows: int,
    cols: int,
    cfg: dict,
) -> list[dict]:
    """
    Return a list of tile descriptors: dicts with
    ``row``, ``col``, and a copy of *cfg* with an adjusted ``center``.

    Tiles are non-overlapping — each step moves the full camera frustum
    along the camera's image axes.  Both column and row steps have
    east *and* north components due to the azimuth rotation.
    """
    col_step, row_step = tile_step_vectors(cfg)

    tiles: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            # Offsets from center of the grid
            offset_c = c - (cols - 1) / 2
            offset_r = r - (rows - 1) / 2

            east_m = offset_c * col_step[0] + offset_r * row_step[0]
            north_m = offset_c * col_step[1] + offset_r * row_step[1]

            tile_lat, tile_lng = offset_lat_lng(
                center_lat, center_lng, east_m, north_m
            )

            tile_cfg = {**cfg, "center": {"lat": tile_lat, "lng": tile_lng}}
            tiles.append(
                {
                    "row": r,
                    "col": c,
                    "config": tile_cfg,
                }
            )

    return tiles


def write_tile_grid(tiles: list[dict], output_dir: Path) -> None:
    """Write each tile's view.json into ``output_dir/tile_R_C/``."""
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for tile in tiles:
        r, c = tile["row"], tile["col"]
        tile_dir = output_dir / f"tile_{r}_{c}"
        tile_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = tile_dir / "view.json"
        with open(cfg_path, "w") as f:
            json.dump(tile["config"], f, indent=2)

        manifest.append(
            {
                "row": r,
                "col": c,
                "dir": str(tile_dir),
                "center": tile["config"]["center"],
            }
        )

    # Write manifest for downstream use
    with open(output_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Planned {len(tiles)} tiles in {output_dir}")


# ── CLI ───────────────────────────────────────────────────────────────

@click.command()
@click.option("--center-lat", type=float, required=True, help="Center latitude")
@click.option("--center-lng", type=float, required=True, help="Center longitude")
@click.option("--rows", type=int, default=3, help="Number of rows")
@click.option("--cols", type=int, default=3, help="Number of columns")
@click.option("--config", default="view.json", help="Base view.json")
@click.option("--output-dir", default="tiles", help="Output directory")
def main(
    center_lat: float,
    center_lng: float,
    rows: int,
    cols: int,
    config: str,
    output_dir: str,
) -> None:
    """Plan a grid of overlapping isometric tiles."""
    with open(config) as f:
        cfg = json.load(f)

    tiles = plan_tile_grid(center_lat, center_lng, rows, cols, cfg)
    write_tile_grid(tiles, Path(output_dir))


if __name__ == "__main__":
    main()
