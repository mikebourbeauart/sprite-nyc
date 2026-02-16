"""
Infill template creation and quadrant management for the E2E pipeline.

Defines the QuadrantState enum, QuadrantPosition with neighbor utilities,
validation rules for legal generation configurations, and functions for
creating infill template images and extracting generated quadrants.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

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

def _has_generated_on_side(
    grid: dict[tuple[int, int], QuadrantPosition],
    side: str,
    bbox: tuple[int, int, int, int],
) -> bool:
    """Check if ANY cell along a side of the bounding box has a GENERATED neighbor.

    bbox is (min_x, min_y, max_x, max_y) inclusive.
    """
    min_x, min_y, max_x, max_y = bbox
    if side == "top":
        for x in range(min_x, max_x + 1):
            nb = grid.get((x, min_y - 1))
            if nb and nb.state == QuadrantState.GENERATED:
                return True
    elif side == "bottom":
        for x in range(min_x, max_x + 1):
            nb = grid.get((x, max_y + 1))
            if nb and nb.state == QuadrantState.GENERATED:
                return True
    elif side == "left":
        for y in range(min_y, max_y + 1):
            nb = grid.get((min_x - 1, y))
            if nb and nb.state == QuadrantState.GENERATED:
                return True
    elif side == "right":
        for y in range(min_y, max_y + 1):
            nb = grid.get((max_x + 1, y))
            if nb and nb.state == QuadrantState.GENERATED:
                return True
    return False


def validate_seam_rules(
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
) -> list[str]:
    """Validate seam prevention rules for a selection.

    Prevents the model from being asked to seamlessly blend with
    pre-existing pixel art on all sides simultaneously, which produces
    visible seams.

    Rules by selection shape:
      - 1×1: max 3 generated cardinal neighbors (not all 4)
      - 1×2 (tall): no generated on BOTH left AND right simultaneously
      - 2×1 (wide): no generated on BOTH top AND bottom simultaneously
      - 2×2: no generated cardinal neighbors at all
    """
    errors: list[str] = []
    if not selected:
        return errors

    # Compute bounding box of selection
    xs = [q.x for q in selected]
    ys = [q.y for q in selected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x + 1
    h = max_y - min_y + 1

    # Must be rectangular and fit within 2×2
    if w > 2 or h > 2:
        errors.append(f"Selection bounding box {w}×{h} exceeds max 2×2")
        return errors

    if len(selected) != w * h:
        errors.append("Selection must be rectangular (fill the bounding box)")
        return errors

    bbox = (min_x, min_y, max_x, max_y)

    if w == 1 and h == 1:
        # 1×1: max 3 generated cardinal neighbors
        gen_sides = sum(
            1
            for side in ("top", "bottom", "left", "right")
            if _has_generated_on_side(grid, side, bbox)
        )
        if gen_sides >= 4:
            errors.append(
                "1×1 selection has generated neighbors on all 4 sides — "
                "would cause seams"
            )
    elif w == 1 and h == 2:
        # 1×2 (tall): no generated on BOTH left AND right
        if _has_generated_on_side(grid, "left", bbox) and _has_generated_on_side(
            grid, "right", bbox
        ):
            errors.append(
                "1×2 selection has generated neighbors on both left and right — "
                "would cause seams"
            )
    elif w == 2 and h == 1:
        # 2×1 (wide): no generated on BOTH top AND bottom
        if _has_generated_on_side(grid, "top", bbox) and _has_generated_on_side(
            grid, "bottom", bbox
        ):
            errors.append(
                "2×1 selection has generated neighbors on both top and bottom — "
                "would cause seams"
            )
    elif w == 2 and h == 2:
        # 2×2: no generated cardinal neighbors at all
        for side in ("top", "bottom", "left", "right"):
            if _has_generated_on_side(grid, side, bbox):
                errors.append(
                    f"2×2 selection has generated neighbor on {side} — "
                    "would cause seams"
                )

    return errors


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

    # Seam prevention rules
    errors.extend(validate_seam_rules(selected, grid))

    return errors


# ── Template image creation ───────────────────────────────────────────

BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH = 1
TILE_SIZE = 1024  # default tile size in pixels
CELL_SIZE = 512   # each cell in the 2×2 template


def _best_corner_for_single(
    q: QuadrantPosition,
    grid: dict[tuple[int, int], QuadrantPosition],
) -> tuple[int, int]:
    """Pick the best corner (col, row) in a 2×2 grid for a 1×1 selection.

    Scores each corner by counting generated neighbors that would be
    visible in that 2×2 layout.  Cardinal neighbors get weight 2,
    diagonal weight 1.

    Returns (col_offset, row_offset) where each is 0 or 1.
    """
    best_corner = (0, 0)
    best_score = -1

    for col_off in (0, 1):
        for row_off in (0, 1):
            # The 2×2 grid origin in world coords if target is at (col_off, row_off)
            origin_x = q.x - col_off
            origin_y = q.y - row_off
            score = 0
            for dc in range(2):
                for dr in range(2):
                    if dc == col_off and dr == row_off:
                        continue  # skip the target cell
                    wx = origin_x + dc
                    wy = origin_y + dr
                    nb = grid.get((wx, wy))
                    if nb and nb.state == QuadrantState.GENERATED:
                        # Cardinal if shares row or col with target
                        if dc == col_off or dr == row_off:
                            score += 2
                        else:
                            score += 1
            if score > best_score:
                best_score = score
                best_corner = (col_off, row_off)

    return best_corner


def _compute_2x2_layout(
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
) -> dict[tuple[int, int], tuple[int, int]]:
    """Compute grid_coord → (col, row) mapping for the 2×2 template.

    Returns a dict mapping world (x, y) to template cell (col, row),
    where col and row are each 0 or 1.
    """
    xs = [q.x for q in selected]
    ys = [q.y for q in selected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    w = max_x - min_x + 1
    h = max_y - min_y + 1

    layout: dict[tuple[int, int], tuple[int, int]] = {}

    if w == 1 and h == 1:
        q = selected[0]
        col_off, row_off = _best_corner_for_single(q, grid)
        origin_x = q.x - col_off
        origin_y = q.y - row_off
        for dc in range(2):
            for dr in range(2):
                layout[(origin_x + dc, origin_y + dr)] = (dc, dr)

    elif w == 1 and h == 2:
        # Tall 1×2: selected fills one column, pick best column position
        # Try placing selected in col 0 vs col 1
        best_col = 0
        best_score = -1
        for col in (0, 1):
            other_col = 1 - col
            origin_x = min_x - col
            score = 0
            for dy in range(2):
                wx = origin_x + other_col
                wy = min_y + dy
                nb = grid.get((wx, wy))
                if nb and nb.state == QuadrantState.GENERATED:
                    score += 2
            if score > best_score:
                best_score = score
                best_col = col
        origin_x = min_x - best_col
        for dc in range(2):
            for dr in range(2):
                layout[(origin_x + dc, min_y + dr)] = (dc, dr)

    elif w == 2 and h == 1:
        # Wide 2×1: selected fills one row, pick best row position
        best_row = 0
        best_score = -1
        for row in (0, 1):
            other_row = 1 - row
            origin_y = min_y - row
            score = 0
            for dx in range(2):
                wx = min_x + dx
                wy = origin_y + other_row
                nb = grid.get((wx, wy))
                if nb and nb.state == QuadrantState.GENERATED:
                    score += 2
            if score > best_score:
                best_score = score
                best_row = row
        origin_y = min_y - best_row
        for dc in range(2):
            for dr in range(2):
                layout[(min_x + dc, origin_y + dr)] = (dc, dr)

    elif w == 2 and h == 2:
        # All 4 selected fill the grid directly
        for dc in range(2):
            for dr in range(2):
                layout[(min_x + dc, min_y + dr)] = (dc, dr)

    return layout


def create_template_image(
    selected: list[QuadrantPosition],
    grid: dict[tuple[int, int], QuadrantPosition],
    render_lookup: dict[tuple[int, int], Image.Image],
    tile_size: int = TILE_SIZE,
) -> tuple[Image.Image, dict[tuple[int, int], tuple[int, int]]]:
    """
    Create a 2×2 infill template at 1024×1024 with 512×512 cells.

    The template shows:
      - Selected quadrants as renders (downscaled to 512×512) with red borders
      - Generated neighbors as pixel art context (downscaled to 512×512)
      - Empty cells left black

    Returns (template_image, layout) where layout maps grid coords to
    (col, row) positions in the 2×2 grid.
    """
    if not selected:
        raise ValueError("No quadrants selected")

    layout = _compute_2x2_layout(selected, grid)
    selected_keys = {q.key for q in selected}

    template = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 255))
    draw = ImageDraw.Draw(template)

    for world_key, (col, row) in layout.items():
        px = col * CELL_SIZE
        py = row * CELL_SIZE

        if world_key in selected_keys:
            # Paste downscaled render
            render = render_lookup.get(world_key)
            if render:
                resized = render.resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
                template.paste(resized, (px, py))

            # Red border around this cell
            for i in range(BORDER_WIDTH):
                draw.rectangle(
                    [px + i, py + i, px + CELL_SIZE - 1 - i, py + CELL_SIZE - 1 - i],
                    outline=BORDER_COLOR,
                )

        else:
            # Neighbor cell — show generated pixel art if available
            q = grid.get(world_key)
            if q and q.state == QuadrantState.GENERATED and q.image:
                resized = q.image.resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
                template.paste(resized, (px, py))

    return template, layout


def extract_generated_quadrants(
    result_image: Image.Image,
    selected: list[QuadrantPosition],
    layout: dict[tuple[int, int], tuple[int, int]],
) -> dict[tuple[int, int], Image.Image]:
    """
    Extract individual quadrant images from a generation result.

    Crops each selected quadrant's 512×512 cell from the 1024×1024 result
    and upscales it to 1024×1024 (the standard tile size).
    """
    results = {}
    for q in selected:
        col, row = layout[q.key]
        px = col * CELL_SIZE
        py = row * CELL_SIZE
        crop = result_image.crop((px, py, px + CELL_SIZE, py + CELL_SIZE))
        # Upscale from 512×512 to 1024×1024
        upscaled = crop.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
        results[q.key] = upscaled

    return results
