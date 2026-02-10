"""
Create inpainting training examples from render→generation pairs.

For each pair, generates ~3 examples per rectangle type (5 types),
yielding ~15 examples per pair. With ~8 pairs that gives ~120 total.

Rectangle types:
  1. Vertical band   — full-height strip
  2. Horizontal band  — full-width strip
  3. Vertical rect    — tall rectangle
  4. Horizontal rect  — wide rectangle
  5. Inner square     — centered square

Each rectangle covers < 50% of the total image area.
A 2px red border is drawn around the rendered region.

Usage:
    python -m sprite_nyc.synthetic_data.create_inpainting_examples \
        --dataset-dir synthetic_data/datasets/v04/ \
        --output-dir synthetic_data/inpainting_v04/
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

import click
from PIL import Image, ImageDraw


BORDER_COLOR = (255, 0, 0, 255)
BORDER_WIDTH = 2
MAX_AREA_FRAC = 0.5

PROMPT = (
    "Fill in the outlined section with the missing pixels "
    "corresponding to the <sprite nyc pixel art> style. "
    "The red border indicates the region to be inpainted."
)


def _rand_band_vertical(w: int, h: int) -> tuple[int, int, int, int]:
    """Full-height vertical strip."""
    max_bw = int(w * MAX_AREA_FRAC)
    bw = random.randint(w // 6, max_bw)
    x0 = random.randint(0, w - bw)
    return x0, 0, x0 + bw, h


def _rand_band_horizontal(w: int, h: int) -> tuple[int, int, int, int]:
    """Full-width horizontal strip."""
    max_bh = int(h * MAX_AREA_FRAC)
    bh = random.randint(h // 6, max_bh)
    y0 = random.randint(0, h - bh)
    return 0, y0, w, y0 + bh


def _rand_rect_vertical(w: int, h: int) -> tuple[int, int, int, int]:
    """Tall rectangle (height > width)."""
    max_area = int(w * h * MAX_AREA_FRAC)
    rw = random.randint(w // 6, w // 2)
    max_rh = min(h, max_area // max(rw, 1))
    rh = random.randint(max(rw + 1, h // 4), max(max_rh, rw + 2))
    x0 = random.randint(0, w - rw)
    y0 = random.randint(0, h - rh)
    return x0, y0, x0 + rw, y0 + rh


def _rand_rect_horizontal(w: int, h: int) -> tuple[int, int, int, int]:
    """Wide rectangle (width > height)."""
    max_area = int(w * h * MAX_AREA_FRAC)
    rh = random.randint(h // 6, h // 2)
    max_rw = min(w, max_area // max(rh, 1))
    rw = random.randint(max(rh + 1, w // 4), max(max_rw, rh + 2))
    x0 = random.randint(0, w - rw)
    y0 = random.randint(0, h - rh)
    return x0, y0, x0 + rw, y0 + rh


def _rand_inner_square(w: int, h: int) -> tuple[int, int, int, int]:
    """Centered-ish square."""
    max_side = int(min(w, h) * (MAX_AREA_FRAC ** 0.5))
    side = random.randint(min(w, h) // 4, max_side)
    x0 = random.randint(0, w - side)
    y0 = random.randint(0, h - side)
    return x0, y0, x0 + side, y0 + side


RECT_GENERATORS = {
    "vband": _rand_band_vertical,
    "hband": _rand_band_horizontal,
    "vrect": _rand_rect_vertical,
    "hrect": _rand_rect_horizontal,
    "square": _rand_inner_square,
}


def create_inpainting_image(
    render: Image.Image,
    generation: Image.Image,
    rect: tuple[int, int, int, int],
) -> Image.Image:
    """
    Create an inpainting training image: the generation with a
    rectangular region replaced by the render + red border.
    """
    result = generation.copy().convert("RGBA")
    x0, y0, x1, y1 = rect

    # Paste render region
    region = render.crop((x0, y0, x1, y1))
    result.paste(region, (x0, y0))

    # Draw red border
    draw = ImageDraw.Draw(result)
    for i in range(BORDER_WIDTH):
        draw.rectangle([x0 + i, y0 + i, x1 - 1 - i, y1 - 1 - i], outline=BORDER_COLOR)

    return result


def process_pair(
    render_path: Path,
    generation_path: Path,
    output_dir: Path,
    name: str,
    examples_per_type: int = 3,
    seed: int | None = None,
) -> list[dict]:
    """Generate inpainting examples for one pair."""
    if seed is not None:
        random.seed(seed)

    render = Image.open(render_path).convert("RGBA")
    generation = Image.open(generation_path).convert("RGBA")
    w, h = render.size

    rows = []
    for rtype, gen_fn in RECT_GENERATORS.items():
        for i in range(examples_per_type):
            rect = gen_fn(w, h)

            inpainting = create_inpainting_image(render, generation, rect)

            inp_name = f"{name}_{rtype}_{i}.png"
            inp_path = output_dir / "inpainting" / inp_name
            inp_path.parent.mkdir(parents=True, exist_ok=True)
            inpainting.save(inp_path)

            gen_out = output_dir / "generations" / f"{name}.png"
            gen_out.parent.mkdir(parents=True, exist_ok=True)
            if not gen_out.exists():
                generation.save(gen_out)

            rows.append(
                {
                    "inpainting": f"inpainting/{inp_name}",
                    "generation": f"generations/{name}.png",
                    "prompt": PROMPT,
                }
            )

    return rows


@click.command()
@click.option("--dataset-dir", required=True, help="Directory with renders/ and generations/")
@click.option("--output-dir", required=True, help="Output directory")
@click.option("--examples-per-type", default=3, help="Examples per rectangle type per pair")
@click.option("--seed", default=42, type=int, help="Random seed")
def main(dataset_dir: str, output_dir: str, examples_per_type: int, seed: int) -> None:
    """Generate inpainting training examples."""
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

    print(f"Found {len(pairs)} pairs, {examples_per_type} examples/type × 5 types")

    all_rows: list[dict] = []
    for idx, name in enumerate(pairs):
        print(f"  Processing {name}…")
        rows = process_pair(
            render_files[name],
            gen_files[name],
            od,
            name,
            examples_per_type=examples_per_type,
            seed=seed + idx,
        )
        all_rows.extend(rows)

    csv_path = od / "inpainting_dataset.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["inpainting", "generation", "prompt"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {csv_path}")


if __name__ == "__main__":
    main()
