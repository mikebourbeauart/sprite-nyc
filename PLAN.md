# Isometric NYC — Project Plan

Reference: https://cannoneyed.com/projects/isometric-nyc

---

## What's Been Done

### 3D Rendering Pipeline
- Built a Three.js web renderer (`web/`) with orthographic isometric camera using Google Maps 3D Tiles API
- Playwright automation (`export_views.py`) captures textured renders
- Camera config driven by `view.json` (azimuth -15°, elevation -45°)

### Code Written (Not Yet Tested / Used)
The following code exists in the repo but has not been put into production yet:

- **Infill templates** (`create_template.py`) — red border convention, guided/unguided modes, 50% overlap system
- **Generation API client** (`generate_tile_oxen.py`) — Oxen.ai API wrapper, 28 inference steps, currently pointed at `cannoneyed-modern-salmon-unicorn` model
- **Tile planning** (`plan_tiles.py`) — geospatial grid math, 50% overlap positions, manifest generation
- **Plan validation** (`validate_plan.py`) — alpha-blend composite to verify tile alignment
- **GCS upload** (`gcs_upload.py`) — content-addressed uploads to `sprite-nyc-assets` bucket
- **E2E generation system** (`e2e_generation/`) — SQLite state machine, quadrant seeding, core generation library, batch/single CLIs, strip planning, spiral expansion
- **Micro-tools** — web generation manager (port 8080), bounds visualizer (port 8081), color replacement, quadrant export/import
- **Training data generators** (`synthetic_data/`) — infill, inpainting, and omni dataset creators
- **Viewing** — DZI tile pyramid export, OpenSeaDragon gigapixel viewer

---

## What's Left To Do

### Phase 1 — Fine-Tune the Model

Need to fine-tune Qwen/Image-Edit on Oxen.ai to learn the pixel-art style. Per the writeup: ~40 input/output pairs, ~$12, ~4 hours.

Steps:
- Generate initial training pairs manually (render tiles with Playwright, create pixel-art versions)
- Create training dataset using `synthetic_data/create_omni_dataset.py` (controlled distribution of full/quadrant/half/middle/strip/rect variants)
- Fine-tune Qwen/Image-Edit on Oxen.ai
- Update model name in `generate_tile_oxen.py` to point at the new model
- Test single-tile generation end-to-end

### Phase 2 — Validate & Test the Generation Pipeline

All the generation code exists but hasn't been run. Need to verify it works end-to-end.

Steps:
- Test tile planning (`plan_tiles.py`) — generate a small manifest and validate with `validate_plan.py`
- Test GCS upload — confirm public URLs work with Oxen API
- Test infill template creation — verify red border convention and neighbor context
- Test single-tile generation through `generate_tile_oxen.py` with the fine-tuned model
- Test E2E flow: seed DB (`seed_tiles.py`) → generate quadrants (`generate_tile_omni.py`) → verify results in DB
- Test the web generation manager (`view_generations.py`) — interactive selection and generation triggering

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
| 3D Web Renderer | Done | Three.js + Google 3D Tiles on port 3000 |
| Playwright Export | Done | Textured render capture |
| Fine-Tuned Model | Not Started | Need training data + fine-tune on Oxen.ai |
| Training Data Gen | Code Written | 3 dataset generators, not yet used |
| Infill Templates | Code Written | Guided + unguided, red border convention |
| GCS Upload | Code Written | Content-addressed, public URLs |
| Tile Planning | Code Written | Geospatial grid math, manifest generation |
| SQLite State Machine | Code Written | Quadrant BLOB storage, generation tracking |
| Auto-Generation | Code Written | Spiral + strip planners |
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
