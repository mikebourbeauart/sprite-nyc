# Isometric NYC — Project Plan

Reference: https://cannoneyed.com/projects/isometric-nyc

---

## What's Been Done

### 3D Rendering Pipeline (Working)
- Three.js web renderer (`web/`) with orthographic isometric camera using Google Maps 3D Tiles API
- Playwright automation (`export_views.py`, `batch_export.py`) captures textured renders
- Camera config driven by `view.json` (azimuth -15°, elevation -45°)

### Tile Planning & Batch Rendering (Working)
- **Tile planning** (`plan_tiles.py`) — camera-aligned stepping (accounts for azimuth rotation), 50% overlap, manifest generation
- **Batch export** (`batch_export.py`) — grid and landmarks modes, single Playwright session, auto-cleans stale artifacts
- **Plan validation** (`validate_plan.py`) — stitches tiles into full composite for visual inspection
- Tested with 3×3 grid centered on lower Manhattan

### Batch Generation Pipeline (Written, Needs Retrained Model)
- **Batch generate** (`batch_generate.py`) — builds composite templates with full-grid context, cardinal-first spiral order, extracts target tile from model result
- **Composite templates** — target tile's red border is ~1/4 of the 2048×2048 composite, surrounded by pixel art from already-generated neighbors
- **GCS upload** (`gcs_upload.py`) — content-addressed uploads to `sprite-nyc-assets` bucket
- **Generation API client** (`generate_tile_oxen.py`) — Oxen.ai API wrapper, 28 inference steps

### Training Data (Ready for Retraining)
- 40 render/generation pairs at `output/training_renders/` (renders 1024×1024, generations 2048×2048)
- **Omni dataset** (`synthetic_data/omni_v02/`) — 240 examples at 1024×1024, 6 variant types (full, quadrant, half, middle, rect_strip, rect_infill)
- Fixed render/generation size mismatch bug — `create_omni_dataset.py` now downscales to the smaller dimension to avoid zoom artifacts in red-bordered regions

### Code Written (Not Yet Tested)
- **E2E generation system** (`e2e_generation/`) — SQLite state machine, quadrant seeding, core generation library, batch/single CLIs, strip planning, spiral expansion
- **Micro-tools** — web generation manager (port 8080), bounds visualizer (port 8081), color replacement, quadrant export/import
- **Viewing** — DZI tile pyramid export, OpenSeaDragon gigapixel viewer

---

## What's Left To Do

### Phase 1 — Fine-Tune the Model ✓

Steps:
- ~~Generate initial training pairs (40 render/generation pairs)~~ ✓
- ~~Create training dataset with `create_omni_dataset.py`~~ ✓ (240 examples at 1024×1024)
- ~~Fix render/generation size mismatch in training data~~ ✓
- ~~Fine-tune Qwen/Image-Edit on Oxen.ai with `omni_v02` dataset~~ ✓
- Update model name in `generate_tile_oxen.py` to point at the new model
- Test single-tile generation end-to-end

### Phase 2 — Validate & Test the Batch Generation Pipeline ← CURRENT

`batch_generate.py` is rewritten with composite templates but needs testing with the retrained model.

Steps:
- ~~Test tile planning (`plan_tiles.py`) — camera-aligned stepping~~ ✓
- ~~Test batch rendering (`batch_export.py`) — 3×3 grid~~ ✓
- ~~Test GCS upload — confirm public URLs work with Oxen API~~ ✓
- **Run `batch_generate.py` on test_grid with retrained model**
- Verify composite templates produce correct red border ratio (~1/4 of image)
- Verify spiral order generates good neighbor context cascade
- Validate results with `validate_plan.py` composite stitching
- Test E2E flow if needed: seed DB (`seed_tiles.py`) → generate quadrants → verify results
- Fix `seed_tiles.py` azimuth stepping bug (same issue that was fixed in `plan_tiles.py`)

### Phase 3 — Small-Scale Generation Run

Generate a small area to validate quality and seam handling before scaling.

Steps:
- Pick a small NYC region (e.g., a few blocks)
- Seed the SQLite DB with quadrant grid
- Run spiral or strip planner on the area
- Review results for style consistency, seam quality, and artifacts
- Use color replacement tool and export/import workflow to fix issues
- Export to DZI and verify in OpenSeaDragon viewer

### Phase 4 — Scale to Self-Hosted Inference

Oxen.ai hosted API is expensive and slow at scale (~40k tiles needed). Per the writeup: Lambda AI H100 GPUs achieve 200+ generations/hour at <$3/hour.

Steps:
- Export fine-tuned model weights from Oxen.ai
- Set up inference server on Lambda AI H100 VM
- Create new generation client (or update existing) to call self-hosted endpoint
- Add retry logic with exponential backoff
- Add parallel generation queue (multiple concurrent API calls)
- Support running multiple model instances simultaneously

### Phase 5 — On-Demand Rendering

Currently renders must be pre-captured. `generate_omni.py:160` has a TODO for on-demand Playwright rendering.

Steps:
- Implement `render_quadrant()` — launch Playwright, navigate to web renderer with correct view config, capture render
- Store renders in DB for reuse
- Enable generation pipeline to render on-the-fly as needed

### Phase 6 — Full-Scale Generation

Run generation across all of NYC.

Steps:
- Define bounds covering target NYC area
- Seed full quadrant grid
- Run automated generation (spiral/strip planners)
- Monitor progress via generation manager UI and bounds visualizer
- Handle edge cases as they arise (water, trees, artifacts)

### Phase 7 — Edge Cases & Quality

The writeup identifies water and trees as major challenges.

**Water:**
- Build water classification tool (binary classifier for water/partial-water/land quadrants)
- Integrate with generation pipeline for different prompts or post-processing
- Use color replacement tool for automated water color correction

**Trees:**
- Identified as pathological for current image models — no automated solution found in the writeup
- Manual correction via export/import to external editors (Affinity Photo etc.)

**Automated QA:**
- Edge-matching verification between adjacent quadrants
- Seam detection at generation boundaries
- Artifact flagging in generation manager UI
- Note: the writeup found that even advanced models couldn't reliably detect these issues

### Phase 8 — Polish & Deployment

Steps:
- Upgrade bounds visualizer to polygon boundary editor for defining final export edges
- Add per-quadrant model/prompt configuration for different tile types
- Add negative prompting support
- Final DZI export with polygon-clipped edges
- Deploy gigapixel viewer

---

## Current Pipeline Status

| Component | Status | Notes |
|-----------|--------|-------|
| 3D Web Renderer | **Done** | Three.js + Google 3D Tiles on port 3000 |
| Playwright Export | **Done** | `batch_export.py` — grid + landmarks modes |
| Tile Planning | **Done** | Camera-aligned stepping, 50% overlap, manifest |
| Plan Validation | **Done** | Stitched composites for visual inspection |
| Training Data | **Done** | 240 examples at 1024×1024 in `omni_v02/` |
| Fine-Tuned Model | **In Progress** | Needs retraining on fixed omni_v02 dataset |
| Batch Generation | **Needs Testing** | Composite templates written, awaiting retrained model |
| GCS Upload | **Working** | Content-addressed, public URLs |
| Infill Templates | Code Written | `create_template.py` — superseded by `batch_generate.py` composites for batch pipeline |
| SQLite State Machine | Code Written | Quadrant BLOB storage, generation tracking |
| Auto-Generation | Code Written | Spiral + strip planners (`seed_tiles.py` has azimuth bug) |
| Generation Manager UI | Code Written | Web app on port 8080 |
| Bounds Visualizer | Code Written | Web app on port 8081 |
| Color Replacement | Code Written | Soft-blend, for water correction |
| Export/Import Editing | Code Written | Round-trip to external editors |
| DZI Tile Export | Code Written | Multi-level pyramid for OpenSeaDragon |
| Gigapixel Viewer | Code Written | OpenSeaDragon with keyboard/touch controls |
| Self-Hosted Inference | Not Started | Lambda AI H100 setup needed |
| Retry / Parallelism | Not Started | No fault tolerance or concurrency |
| On-Demand Rendering | Not Started | TODO in generate_omni.py:160 |
| Water Classifier | Not Started | No automated detection |
| Automated QA | Not Started | No seam/artifact detection |
| Polygon Bounds Editor | Not Started | Only rectangular bounds currently |
