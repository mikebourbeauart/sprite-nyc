"""
Create infill templates for tile generation.

An infill template composites:
  - The current tile's 3D render (whitebox or render)
  - Neighboring tiles' already-generated pixel art (if available)
  - A red border around the region to be generated

Supports two modes:
  - **Guided** (with neighbors): Some quadrants show existing pixel art,
    the target quadrant shows the render with a red border.
  - **Unguided** (from scratch): The entire tile is the render with
    a red border — no neighbor context.
"""

from __future__ import annotations

from PIL import Image, ImageDraw


BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH = 1


def create_guided_template(
    render: Image.Image,
    neighbors: dict[str, Image.Image | None],
    target_quadrant: str = "full",
) -> Image.Image:
    """
    Create a guided infill template.

    Parameters
    ----------
    render : Image
        The 3D render of the current tile.
    neighbors : dict
        Mapping of position → generated Image for neighboring tiles.
        Keys: "top", "bottom", "left", "right", "top_left", "top_right",
              "bottom_left", "bottom_right". Values may be None.
    target_quadrant : str
        Which region to fill: "full", "tl", "tr", "bl", "br",
        "top_half", "bottom_half", "left_half", "right_half".

    Returns
    -------
    Image
        The composited infill template.
    """
    w, h = render.size
    hw, hh = w // 2, h // 2

    # Start with the render
    template = render.copy().convert("RGBA")

    # Overlay neighboring generated tiles where they overlap (50% overlap)
    # The overlap region depends on which neighbor and the tile step
    _composite_neighbors(template, neighbors, w, h)

    # Draw the red border around the target region
    draw = ImageDraw.Draw(template)
    box = _get_target_box(target_quadrant, w, h)
    for i in range(BORDER_WIDTH):
        draw.rectangle(
            [box[0] + i, box[1] + i, box[2] - 1 - i, box[3] - 1 - i],
            outline=BORDER_COLOR,
        )

    return template


def create_unguided_template(render: Image.Image) -> Image.Image:
    """
    Create an unguided template — just the render with a border.
    """
    w, h = render.size
    template = render.copy().convert("RGBA")
    draw = ImageDraw.Draw(template)
    for i in range(BORDER_WIDTH):
        draw.rectangle(
            [i, i, w - 1 - i, h - 1 - i],
            outline=BORDER_COLOR,
        )
    return template


def _composite_neighbors(
    template: Image.Image,
    neighbors: dict[str, Image.Image | None],
    w: int,
    h: int,
) -> None:
    """
    Overlay the overlapping portions of neighbor tiles.

    With 50% overlap, each neighbor's relevant half is pasted onto
    the corresponding edge of the template.
    """
    hw, hh = w // 2, h // 2

    # Right neighbor: its left half overlaps our right half
    if neighbors.get("right"):
        nb = neighbors["right"]
        region = nb.crop((0, 0, hw, h))
        template.paste(region, (hw, 0), region)

    # Left neighbor: its right half overlaps our left half
    if neighbors.get("left"):
        nb = neighbors["left"]
        region = nb.crop((hw, 0, w, h))
        template.paste(region, (0, 0), region)

    # Bottom neighbor: its top half overlaps our bottom half
    if neighbors.get("bottom"):
        nb = neighbors["bottom"]
        region = nb.crop((0, 0, w, hh))
        template.paste(region, (0, hh), region)

    # Top neighbor: its bottom half overlaps our top half
    if neighbors.get("top"):
        nb = neighbors["top"]
        region = nb.crop((0, hh, w, h))
        template.paste(region, (0, 0), region)

    # Corner neighbors — their quadrant overlaps our corresponding corner
    corner_map = {
        "top_left": ((hw, hh, w, h), (0, 0)),
        "top_right": ((0, hh, hw, h), (hw, 0)),
        "bottom_left": ((hw, 0, w, hh), (0, hh)),
        "bottom_right": ((0, 0, hw, hh), (hw, hh)),
    }
    for key, (crop_box, paste_pos) in corner_map.items():
        if neighbors.get(key):
            nb = neighbors[key]
            region = nb.crop(crop_box)
            template.paste(region, paste_pos, region)


def _get_target_box(
    quadrant: str, w: int, h: int
) -> tuple[int, int, int, int]:
    hw, hh = w // 2, h // 2
    boxes = {
        "full": (0, 0, w, h),
        "tl": (0, 0, hw, hh),
        "tr": (hw, 0, w, hh),
        "bl": (0, hh, hw, h),
        "br": (hw, hh, w, h),
        "top_half": (0, 0, w, hh),
        "bottom_half": (0, hh, w, h),
        "left_half": (0, 0, hw, h),
        "right_half": (hw, 0, w, h),
    }
    return boxes.get(quadrant, (0, 0, w, h))
