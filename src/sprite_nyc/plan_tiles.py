"""
Plan a grid of overlapping isometric tiles.

Given a center lat/lng and an m×n grid, this script creates a directory of
tile folders, each containing its own view.json. Tiles overlap by 50%
horizontally and vertically so that neighboring tiles share half their
content for seamless stitching.

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


# ── Isometric frustum size ────────────────────────────────────────────

def tile_ground_footprint(cfg: dict) -> tuple[float, float]:
    """
    Return the (east, north) extent in metres of one tile's ground
    coverage, taking into account the orthographic view height and
    aspect ratio.

    For an ortho camera the visible ground width/height in metres
    equals the camera frustum size projected onto the ground plane.
    At a 45° elevation the vertical frustum dimension maps to
    ground_north = view_height / sin(45°). The horizontal dimension
    maps similarly, scaled by the aspect ratio.
    """
    vh = cfg["view_height_meters"]
    aspect = cfg["width"] / cfg["height"]
    el = abs(cfg["elevation"])
    az = abs(cfg["azimuth"])

    sin_el = math.sin(math.radians(el))
    cos_az = math.cos(math.radians(az))
    sin_az = math.sin(math.radians(az))

    # Ground extent along north and east for the vertical camera axis
    north_extent = vh / sin_el
    east_extent = vh * aspect / sin_el

    # Rotate by azimuth to get axis-aligned extents
    ground_east = abs(east_extent * cos_az) + abs(north_extent * sin_az)
    ground_north = abs(east_extent * sin_az) + abs(north_extent * cos_az)

    return ground_east, ground_north


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

    Tiles overlap by 50% — each step moves half the tile footprint.
    The (0, 0) tile is centred on the provided coordinates; negative
    indices extend left/up.
    """
    east_extent, north_extent = tile_ground_footprint(cfg)

    # 50% overlap → step = half the extent
    step_east = east_extent / 2
    step_north = north_extent / 2

    tiles: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            # Offsets from center of the grid
            offset_c = c - (cols - 1) / 2
            offset_r = r - (rows - 1) / 2

            east_m = offset_c * step_east
            north_m = -offset_r * step_north  # rows go south

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
