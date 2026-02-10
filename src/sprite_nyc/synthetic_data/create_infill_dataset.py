"""
Create infill training dataset from render→generation pairs.

For each pair, generates 8 infill variants:
  - 4 half variants:  left, right, top, bottom halves
  - 4 quadrant variants: TL, TR, BL, BR

Each variant composites the "generated" pixel art for some regions and
the "render" (3D view) for others, with a 1px red border around the
rendered regions so the model learns where to fill in.

Naming convention: infill_<TL>_<TR>_<BL>_<BR>.png
  where each position = "g" (generated) or "r" (rendered)

Usage:
    python -m sprite_nyc.synthetic_data.create_infill_dataset \
        --dataset-dir synthetic_data/datasets/v04/ \
        --output-dir synthetic_data/infill_v04/
"""

from __future__ import annotations

import csv
from pathlib import Path

import click
from PIL import Image, ImageDraw


BORDER_COLOR = (255, 0, 0, 255)  # red
BORDER_WIDTH = 1

# The 8 infill variant patterns.
# Each is (TL, TR, BL, BR) where True = render region (to be filled).
VARIANTS = {
    # Half variants
    "infill_r_r_g_g": (True, True, False, False),    # top half rendered
    "infill_g_g_r_r": (False, False, True, True),    # bottom half rendered
    "infill_r_g_r_g": (True, False, True, False),    # left half rendered
    "infill_g_r_g_r": (False, True, False, True),    # right half rendered
    # Quadrant variants
    "infill_r_g_g_g": (True, False, False, False),   # TL rendered
    "infill_g_r_g_g": (False, True, False, False),   # TR rendered
    "infill_g_g_r_g": (False, False, True, False),   # BL rendered
    "infill_g_g_g_r": (False, False, False, True),   # BR rendered
}

PROMPT = (
    "Fill in the outlined section with the missing pixels "
    "corresponding to the <sprite nyc pixel art> style. "
    "The red border indicates the region to be filled."
)


def create_infill_image(
    render: Image.Image,
    generation: Image.Image,
    pattern: tuple[bool, bool, bool, bool],
) -> Image.Image:
    """
    Composite an infill training image.

    *pattern* is (TL, TR, BL, BR): True means that quadrant shows the
    render (region to be filled), False means it shows the generation.
    """
    w, h = render.size
    hw, hh = w // 2, h // 2

    # Quadrant boxes: (left, upper, right, lower)
    boxes = [
        (0, 0, hw, hh),       # TL
        (hw, 0, w, hh),       # TR
        (0, hh, hw, h),       # BL
        (hw, hh, w, h),       # BR
    ]

    result = generation.copy().convert("RGBA")
    draw = ImageDraw.Draw(result)

    for is_render, box in zip(pattern, boxes):
        if is_render:
            # Paste the render region
            region = render.crop(box)
            result.paste(region, (box[0], box[1]))

            # Draw red border around the render region
            x0, y0, x1, y1 = box
            for i in range(BORDER_WIDTH):
                draw.rectangle(
                    [x0 + i, y0 + i, x1 - 1 - i, y1 - 1 - i],
                    outline=BORDER_COLOR,
                )

    return result


def process_pair(
    render_path: Path,
    generation_path: Path,
    output_dir: Path,
    name: str,
) -> list[dict]:
    """Generate all 8 infill variants for one pair. Returns CSV rows."""
    render = Image.open(render_path).convert("RGBA")
    generation = Image.open(generation_path).convert("RGBA")

    rows = []
    for variant_name, pattern in VARIANTS.items():
        infill = create_infill_image(render, generation, pattern)

        out_name = f"{name}_{variant_name}.png"
        out_path = output_dir / "infills" / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        infill.save(out_path)

        gen_out = output_dir / "generations" / f"{name}.png"
        gen_out.parent.mkdir(parents=True, exist_ok=True)
        if not gen_out.exists():
            generation.save(gen_out)

        rows.append(
            {
                "infill": f"infills/{out_name}",
                "generation": f"generations/{name}.png",
                "prompt": PROMPT,
            }
        )

    return rows


@click.command()
@click.option("--dataset-dir", required=True, help="Directory with renders/ and generations/")
@click.option("--output-dir", required=True, help="Output directory for infill dataset")
def main(dataset_dir: str, output_dir: str) -> None:
    """Generate infill training dataset from render/generation pairs."""
    ds = Path(dataset_dir)
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    renders_dir = ds / "renders"
    gens_dir = ds / "generations"

    if not renders_dir.exists():
        raise click.ClickException(f"No renders/ directory in {ds}")
    if not gens_dir.exists():
        raise click.ClickException(f"No generations/ directory in {ds}")

    # Match pairs by filename stem
    render_files = {p.stem: p for p in renders_dir.glob("*.png")}
    gen_files = {p.stem: p for p in gens_dir.glob("*.png")}
    pairs = sorted(set(render_files) & set(gen_files))

    if not pairs:
        raise click.ClickException("No matching render/generation pairs found")

    print(f"Found {len(pairs)} pairs")

    all_rows: list[dict] = []
    for name in pairs:
        print(f"  Processing {name}…")
        rows = process_pair(render_files[name], gen_files[name], od, name)
        all_rows.extend(rows)

    # Write CSV
    csv_path = od / "infill_dataset.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["infill", "generation", "prompt"])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {csv_path}")


if __name__ == "__main__":
    main()
