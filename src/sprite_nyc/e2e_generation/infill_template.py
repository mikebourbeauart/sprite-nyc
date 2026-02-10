"""
Infill template creation and quadrant management for the E2E pipeline.

Defines the QuadrantState enum, QuadrantPosition with neighbor utilities,
validation rules for legal generation configurations, and functions for
creating infill template images and extracting generated quadrants.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from PIL import Image, ImageDraw


# ── Enums & data classes ──────────────────────────────────────────────

class QuadrantState(enum.Enum):
    EMPTY = "empty"
    GENERATED = "generated"
    SELECTED = "selected"  # currently being generated


@dataclass
class QuadrantPosition:
    """A quadrant in the generation grid with neighbor awareness."""
    x: int
    y: int
    state: QuadrantState = QuadrantState.EMPTY
    image: Image.Image | None = None

    @property
    def key(self) -> tuple[int, int]:
        return (self.x, self.y)

    def neighbor_keys(self) -> dict[str, tuple[int, int]]:
        """Return the (x, y) keys of all 8 neighbors."""
        return {
            "top": (self.x, self.y - 1),
            "bottom": (self.x, self.y + 1),
            "left": (self.x - 1, self.y),
            "right": (self.x + 1, self.y),
            "top_left": (self.x - 1, self.y - 1),
            "top_right": (self.x + 1, self.y - 1),
            "bottom_left": (self.x - 1, self.y + 1),
            "bottom_right": (self.x + 1, self.y + 1),
        }

    def cardinal_neighbor_keys(self) -> dict[str, tuple[int, int]]:
        """Return only the 4 cardinal neighbor keys."""
        return {
            "top": (self.x, self.y - 1),
            "bottom": (self.x, self.y + 1),
            "left": (self.x - 1, self.y),
            "right": (self.x + 1, self.y),
        }


# ── Validation ────────────────────────────────────────────────────────

def validate_generation_config(
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
) -> list[str]:
    """
    Validate that a set of selected quadrants forms a legal generation
    configuration. Returns a list of error messages (empty = valid).

    Rules:
      1. Selected quadrants must form a connected group.
      2. At least one selected quadrant must have a generated neighbor
         (unless this is the very first generation).
      3. Selected quadrants must not already be generated.
    """
    errors: list[str] = []

    if not selected:
        errors.append("No quadrants selected")
        return errors

    # Rule 3: none already generated
    for q in selected:
        if q.state == QuadrantState.GENERATED:
            errors.append(f"Quadrant ({q.x}, {q.y}) is already generated")

    # Rule 1: connected
    if len(selected) > 1:
        selected_keys = {q.key for q in selected}
        visited = set()
        stack = [selected[0].key]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            cx, cy = current
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (cx + dx, cy + dy)
                if nb in selected_keys and nb not in visited:
                    stack.append(nb)
        if visited != selected_keys:
            errors.append("Selected quadrants are not connected")

    # Rule 2: at least one neighbor is generated (or no generated tiles exist yet)
    has_any_generated = any(
        q.state == QuadrantState.GENERATED for q in grid.values()
    )
    if has_any_generated:
        has_generated_neighbor = False
        for q in selected:
            for nb_key in q.cardinal_neighbor_keys().values():
                nb = grid.get(nb_key)
                if nb and nb.state == QuadrantState.GENERATED:
                    has_generated_neighbor = True
                    break
            if has_generated_neighbor:
                break
        if not has_generated_neighbor:
            errors.append("No selected quadrant has a generated neighbor")

    return errors


# ── Template image creation ───────────────────────────────────────────

BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH = 1
TILE_SIZE = 1024  # default tile size in pixels


def create_template_image(
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
    render_lookup: dict[tuple[int, int], Image.Image],
    tile_size: int = TILE_SIZE,
) -> Image.Image:
    """
    Create the infill template image for a set of selected quadrants.

    The template shows:
      - Generated neighbors as pixel art (context)
      - Selected quadrants as renders with red borders (to fill)
      - Empty quadrants left black/transparent

    The output image is sized to encompass all selected quadrants plus
    one ring of neighbor context, at tile_size resolution per quadrant.
    """
    if not selected:
        raise ValueError("No quadrants selected")

    # Find bounding box of selected + 1 ring of neighbors
    all_keys = set()
    for q in selected:
        all_keys.add(q.key)
        for nb_key in q.neighbor_keys().values():
            all_keys.add(nb_key)

    min_x = min(k[0] for k in all_keys)
    max_x = max(k[0] for k in all_keys)
    min_y = min(k[1] for k in all_keys)
    max_y = max(k[1] for k in all_keys)

    cols = max_x - min_x + 1
    rows = max_y - min_y + 1

    # Create the composite image
    img_w = cols * tile_size
    img_h = rows * tile_size
    template = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(template)

    selected_keys = {q.key for q in selected}

    for key in all_keys:
        q = grid.get(key)
        px = (key[0] - min_x) * tile_size
        py = (key[1] - min_y) * tile_size

        if key in selected_keys:
            # Show the render for selected quadrants
            render = render_lookup.get(key)
            if render:
                resized = render.resize((tile_size, tile_size), Image.LANCZOS)
                template.paste(resized, (px, py))

            # Red border
            for i in range(BORDER_WIDTH):
                draw.rectangle(
                    [px + i, py + i, px + tile_size - 1 - i, py + tile_size - 1 - i],
                    outline=BORDER_COLOR,
                )

        elif q and q.state == QuadrantState.GENERATED and q.image:
            # Show the generated pixel art for context
            resized = q.image.resize((tile_size, tile_size), Image.LANCZOS)
            template.paste(resized, (px, py))

    return template


def extract_generated_quadrants(
    result_image: Image.Image,
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
    tile_size: int = TILE_SIZE,
) -> dict[tuple[int, int], Image.Image]:
    """
    Extract individual quadrant images from a generation result.

    The result image should match the template layout. This function
    crops out each selected quadrant's region.
    """
    all_keys = set()
    for q in selected:
        all_keys.add(q.key)
        for nb_key in q.neighbor_keys().values():
            all_keys.add(nb_key)

    min_x = min(k[0] for k in all_keys)
    min_y = min(k[1] for k in all_keys)

    results = {}
    for q in selected:
        px = (q.x - min_x) * tile_size
        py = (q.y - min_y) * tile_size
        crop = result_image.crop((px, py, px + tile_size, py + tile_size))
        results[q.key] = crop

    return results
