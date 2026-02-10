"""
Create the unified "omni" training dataset.

Merges full generation, quadrant infill, half infill, middle infill,
rectangle strip, and rectangle infill variants into a single dataset
with controlled distribution:

  Full generation:  20%
  Quadrant infill:  20%
  Half infill:      20%
  Middle infill:    15%
  Rect strips:      10%
  Rect infills:     15%

Usage:
    python -m sprite_nyc.synthetic_data.create_omni_dataset \
        --dataset-dir synthetic_data/datasets/v04/ \
        --output-dir synthetic_data/omni_v04/
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

import click
from PIL import Image, ImageDraw


BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH_INFILL = 1
BORDER_WIDTH_INPAINT = 2

PROMPT_TEMPLATE = (
    "Fill in the outlined section with the missing pixels "
    "corresponding to the <sprite nyc pixel art> style. "
    "The red border indicates the region to generate. "
    "Variant: {variant}."
)

# Target distribution weights
DISTRIBUTION = {
    "full": 0.20,
    "quadrant": 0.20,
    "half": 0.20,
    "middle": 0.15,
    "rect_strip": 0.10,
    "rect_infill": 0.15,
}


def _draw_border(draw: ImageDraw.ImageDraw, box: tuple, width: int) -> None:
    x0, y0, x1, y1 = box
    for i in range(width):
        draw.rectangle([x0 + i, y0 + i, x1 - 1 - i, y1 - 1 - i], outline=BORDER_COLOR)


def make_full_example(render: Image.Image, generation: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Full generation: entire render as input, entire generation as target."""
    w, h = render.size
    inp = render.copy().convert("RGBA")
    draw = ImageDraw.Draw(inp)
    _draw_border(draw, (0, 0, w, h), BORDER_WIDTH_INFILL)
    return inp, generation.copy().convert("RGBA")


def make_quadrant_example(
    render: Image.Image, generation: Image.Image, quadrant: int
) -> tuple[Image.Image, Image.Image]:
    """Single quadrant rendered, rest is generated."""
    w, h = render.size
    hw, hh = w // 2, h // 2
    boxes = [(0, 0, hw, hh), (hw, 0, w, hh), (0, hh, hw, h), (hw, hh, w, h)]

    result = generation.copy().convert("RGBA")
    box = boxes[quadrant]
    region = render.crop(box)
    result.paste(region, (box[0], box[1]))
    draw = ImageDraw.Draw(result)
    _draw_border(draw, box, BORDER_WIDTH_INFILL)
    return result, generation.copy().convert("RGBA")


def make_half_example(
    render: Image.Image, generation: Image.Image, half: str
) -> tuple[Image.Image, Image.Image]:
    """Half the image rendered."""
    w, h = render.size
    hw, hh = w // 2, h // 2
    halves = {
        "top": (0, 0, w, hh),
        "bottom": (0, hh, w, h),
        "left": (0, 0, hw, h),
        "right": (hw, 0, w, h),
    }
    box = halves[half]
    result = generation.copy().convert("RGBA")
    region = render.crop(box)
    result.paste(region, (box[0], box[1]))
    draw = ImageDraw.Draw(result)
    _draw_border(draw, box, BORDER_WIDTH_INFILL)
    return result, generation.copy().convert("RGBA")


def make_middle_example(
    render: Image.Image, generation: Image.Image
) -> tuple[Image.Image, Image.Image]:
    """Center region rendered."""
    w, h = render.size
    margin_x = w // 4
    margin_y = h // 4
    box = (margin_x, margin_y, w - margin_x, h - margin_y)
    result = generation.copy().convert("RGBA")
    region = render.crop(box)
    result.paste(region, (box[0], box[1]))
    draw = ImageDraw.Draw(result)
    _draw_border(draw, box, BORDER_WIDTH_INPAINT)
    return result, generation.copy().convert("RGBA")


def make_rect_strip_example(
    render: Image.Image, generation: Image.Image, orientation: str
) -> tuple[Image.Image, Image.Image]:
    """Full-width or full-height strip rendered."""
    w, h = render.size
    if orientation == "vertical":
        bw = random.randint(w // 6, w // 2)
        x0 = random.randint(0, w - bw)
        box = (x0, 0, x0 + bw, h)
    else:
        bh = random.randint(h // 6, h // 2)
        y0 = random.randint(0, h - bh)
        box = (0, y0, w, y0 + bh)

    result = generation.copy().convert("RGBA")
    region = render.crop(box)
    result.paste(region, (box[0], box[1]))
    draw = ImageDraw.Draw(result)
    _draw_border(draw, box, BORDER_WIDTH_INPAINT)
    return result, generation.copy().convert("RGBA")


def make_rect_infill_example(
    render: Image.Image, generation: Image.Image
) -> tuple[Image.Image, Image.Image]:
    """Random rectangle rendered."""
    w, h = render.size
    rw = random.randint(w // 5, int(w * 0.6))
    rh = random.randint(h // 5, int(h * 0.6))
    # Ensure < 50% area
    while rw * rh > w * h * 0.5:
        rw = int(rw * 0.9)
        rh = int(rh * 0.9)
    x0 = random.randint(0, w - rw)
    y0 = random.randint(0, h - rh)
    box = (x0, y0, x0 + rw, y0 + rh)

    result = generation.copy().convert("RGBA")
    region = render.crop(box)
    result.paste(region, (box[0], box[1]))
    draw = ImageDraw.Draw(result)
    _draw_border(draw, box, BORDER_WIDTH_INPAINT)
    return result, generation.copy().convert("RGBA")


def generate_examples_for_pair(
    render: Image.Image,
    generation: Image.Image,
    target_per_category: dict[str, int],
    seed: int,
) -> list[tuple[str, Image.Image, Image.Image]]:
    """Generate all variant examples for one pair."""
    random.seed(seed)
    examples: list[tuple[str, Image.Image, Image.Image]] = []

    # Full
    for _ in range(target_per_category["full"]):
        inp, tgt = make_full_example(render, generation)
        examples.append(("full", inp, tgt))

    # Quadrant
    for i in range(target_per_category["quadrant"]):
        inp, tgt = make_quadrant_example(render, generation, i % 4)
        examples.append(("quadrant", inp, tgt))

    # Half
    half_names = ["top", "bottom", "left", "right"]
    for i in range(target_per_category["half"]):
        inp, tgt = make_half_example(render, generation, half_names[i % 4])
        examples.append(("half", inp, tgt))

    # Middle
    for _ in range(target_per_category["middle"]):
        inp, tgt = make_middle_example(render, generation)
        examples.append(("middle", inp, tgt))

    # Rect strip
    for i in range(target_per_category["rect_strip"]):
        orient = "vertical" if i % 2 == 0 else "horizontal"
        inp, tgt = make_rect_strip_example(render, generation, orient)
        examples.append(("rect_strip", inp, tgt))

    # Rect infill
    for _ in range(target_per_category["rect_infill"]):
        inp, tgt = make_rect_infill_example(render, generation)
        examples.append(("rect_infill", inp, tgt))

    return examples


@click.command()
@click.option("--dataset-dir", required=True, help="Directory with renders/ and generations/")
@click.option("--output-dir", required=True, help="Output directory")
@click.option("--total-examples", default=200, type=int, help="Target total examples")
@click.option("--seed", default=42, type=int, help="Random seed")
def main(dataset_dir: str, output_dir: str, total_examples: int, seed: int) -> None:
    """Create unified omni training dataset."""
    ds = Path(dataset_dir)
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    renders_dir = ds / "renders"
    gens_dir = ds / "generations"
    render_files = {p.stem: p for p in renders_dir.glob("*.png")}
    gen_files = {p.stem: p for p in gens_dir.glob("*.png")}
    pairs = sorted(set(render_files) & set(gen_files))

    if not pairs:
        raise click.ClickException("No matching pairs found")

    n_pairs = len(pairs)
    per_pair = max(1, total_examples // n_pairs)

    # Compute per-category counts per pair
    target_per_cat = {}
    for cat, weight in DISTRIBUTION.items():
        target_per_cat[cat] = max(1, round(per_pair * weight))

    actual_per_pair = sum(target_per_cat.values())
    print(f"Found {n_pairs} pairs, ~{actual_per_pair} examples each")
    print(f"Distribution: {target_per_cat}")

    all_rows: list[dict] = []
    idx = 0
    for pair_idx, name in enumerate(pairs):
        render = Image.open(render_files[name]).convert("RGBA")
        generation = Image.open(gen_files[name]).convert("RGBA")

        examples = generate_examples_for_pair(
            render, generation, target_per_cat, seed=seed + pair_idx
        )

        for variant, inp, tgt in examples:
            inp_name = f"{name}_{variant}_{idx:04d}_input.png"
            tgt_name = f"{name}_{variant}_{idx:04d}_target.png"

            inp_path = od / "inputs" / inp_name
            tgt_path = od / "targets" / tgt_name
            inp_path.parent.mkdir(parents=True, exist_ok=True)
            tgt_path.parent.mkdir(parents=True, exist_ok=True)

            inp.save(inp_path)
            tgt.save(tgt_path)

            all_rows.append(
                {
                    "input": f"inputs/{inp_name}",
                    "target": f"targets/{tgt_name}",
                    "prompt": PROMPT_TEMPLATE.format(variant=variant),
                    "variant": variant,
                }
            )
            idx += 1

    # Write CSV
    csv_path = od / "omni_dataset.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["input", "target", "prompt", "variant"])
        writer.writeheader()
        writer.writerows(all_rows)

    # Stats
    from collections import Counter
    counts = Counter(r["variant"] for r in all_rows)
    print(f"\nWrote {len(all_rows)} total examples to {csv_path}")
    for cat, count in sorted(counts.items()):
        pct = 100 * count / len(all_rows)
        print(f"  {cat}: {count} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
