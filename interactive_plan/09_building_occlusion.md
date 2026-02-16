# 09 — Building Occlusion (Pre-Baked Depth Texture)

## Problem

Sprites (cars, pedestrians) are rendered on a layer above the static pixel-art tiles. When a sprite is on a road that passes behind a tall building from the camera's perspective, the sprite draws on top of the building rather than being hidden by it. At close zoom this breaks the illusion.

```
  What we get (wrong):          What we want:

  ┌──────────┐                  ┌──────────┐
  │ building │  🚕 ← visible   │ building │
  │          │     on top       │          │  🚕 ← hidden behind
  └──────────┘                  └──────────┘
       road behind                   road behind
```

## Approach: Height Map from Orthographic 3D Render

Rather than estimating building heights from OSM tags, render the actual Google 3D tile geometry from a top-down orthographic camera to produce a height map. This captures real building heights, roof shapes, and foliage canopy — no estimation needed.

The height map is then used at runtime to determine occlusion volumes: for each screen pixel, if there's a structure of height H at that ground position, sprites at ground level behind it (in isometric depth terms) should be hidden.

### Why 3D Render Instead of OSM Tags

- Google 3D tiles have measured geometry — real roof heights, not guesses
- Captures structures not in OSM (sheds, construction, awnings)
- Captures foliage canopy shape and height
- No dependency on OSM tagging quality (many NYC buildings lack `height` or `building:levels`)

## Offline Height Map Generation

### Step 1: Orthographic Top-Down Render

Use the existing Three.js + Google 3D Tiles renderer (`web/`) with a modified camera:

```typescript
// Modified camera for height map capture
const camera = new THREE.OrthographicCamera(
  -extentX / 2, extentX / 2,   // left, right (meters)
  extentY / 2, -extentY / 2,   // top, bottom (meters)
  0.1, 500                      // near, far (meters above ground)
)
camera.position.set(centerX, centerY, 400)  // straight down
camera.lookAt(centerX, centerY, 0)
camera.up.set(0, 1, 0)  // north = up
```

Render to a depth buffer. The depth value at each pixel = distance from camera = inverse height of the surface:

```typescript
// Depth render target
const depthTarget = new THREE.WebGLRenderTarget(width, height, {
  type: THREE.FloatType,
  format: THREE.RedFormat,
})

// Custom depth material that writes world-space height
const depthMaterial = new THREE.ShaderMaterial({
  vertexShader: `
    varying float vHeight;
    void main() {
      vHeight = (modelMatrix * vec4(position, 1.0)).z;  // world Z = height
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    varying float vHeight;
    void main() {
      gl_FragColor = vec4(vHeight / 300.0, 0.0, 0.0, 1.0);  // normalize to 0-1
    }
  `,
})
```

This produces a texture where each pixel stores the height (in meters) of whatever geometry is at that ground position. Ground = ~0, building roofs = 10-300m, tree canopy = 5-20m.

### Step 2: Capture via Playwright

Same approach as the existing `batch_export.py` — Playwright drives the Three.js renderer:

```python
# tools/capture_height_map.py
# Reuses the existing web renderer with a top-down camera override

async def capture_height_map(page, center_lat, center_lng, extent_meters, output_path):
    """
    Navigate to the web renderer with top-down orthographic camera,
    capture the depth buffer as a height map image.
    """
    await page.goto(f'http://localhost:3000/heightmap?'
                    f'lat={center_lat}&lng={center_lng}'
                    f'&extent={extent_meters}')
    await page.wait_for_selector('#render-complete')

    # Read back the height data as a float texture
    height_data = await page.evaluate('window.getHeightMapData()')
    save_height_map(height_data, output_path)
```

The render can be tiled for large areas (same grid as the existing tile plan), or done as one large capture if the area fits.

### Step 3: Classify Occluders

The raw height map contains everything — buildings, ground, foliage, water. Different structure types need different occlusion shapes:

```
Height map pixel → classify → occlusion volume

Buildings:    rectangular column (roof height → ground)
Foliage:      cone/tapered column (canopy height → trunk at ground)
Ground:       no occlusion (height ≈ 0)
```

#### Building Footprint Masking

Cross-reference the height map with OSM building footprints from `scene.json`:

```python
def classify_height_map(height_map, building_footprints, ground_threshold=2.0):
    """
    For each pixel in the height map:
    - If inside a building footprint → 'building' (rectangular occlusion)
    - If height > threshold but NOT in a building → 'foliage' (conical occlusion)
    - Otherwise → 'ground' (no occlusion)
    """
    classification = np.zeros_like(height_map, dtype=np.uint8)
    building_mask = rasterize_polygons(building_footprints, height_map.shape)

    classification[building_mask & (height_map > ground_threshold)] = BUILDING
    classification[~building_mask & (height_map > ground_threshold)] = FOLIAGE
    # Everything else stays GROUND (0)

    return classification
```

### Step 4: Generate Occlusion Map

From the classified height map, produce the final occlusion texture used at runtime. This encodes, for each screen pixel in the isometric view, the isometric depth of the frontmost occluding surface.

#### Building Occlusion (Rectangular Column)

A building at ground position (gx, gy) with roof height H creates a rectangular occlusion volume. In the isometric projection, this volume projects to a screen-space region that extends upward from the footprint. Any sprite at ground level whose isometric depth is greater than the building's front-face depth, and whose screen position falls within this projection, is occluded.

```
  Top-down height map:        Isometric occlusion projection:

  ┌───────┐ H=40m                    ╱─────╲  ← roof edge
  │building│                        ╱ front ╲
  │footprnt│                       ╱  face   ╲
  └───────┘                       │  occluded │
                                  │   zone    │
                                  └───────────┘ ← ground footprint
```

```python
def building_occlusion_column(footprint_screen, height_meters, elevation_rad, meters_per_px_y):
    """
    Extrude building footprint upward in isometric screen space.
    Returns the screen-space polygon of the full visible silhouette.
    The occlusion depth within this polygon = building's front-face depth.
    """
    height_px = height_meters * abs(math.sin(elevation_rad)) / meters_per_px_y

    # Roof polygon = footprint shifted up on screen
    roof = [(x, y - height_px) for (x, y) in footprint_screen]

    # Silhouette = union of footprint + roof + connecting edges
    silhouette = polygon_union(footprint_screen, roof)
    return silhouette
```

#### Foliage Occlusion (Conical / Tapered)

Trees are wide at canopy height and taper to a narrow trunk at ground level. The occlusion volume is a cone: at the canopy height it has the full canopy radius, at ground level it shrinks to roughly the trunk radius (~0.3m).

```
  Top-down height map:        Isometric occlusion projection:

    ●●●●● H=12m                     ╱╲  ← canopy (wide)
    ●tree●                          ╱  ╲
    ●●●●●                          │    │  ← tapers
                                    │  │   ← trunk (narrow)
                                    │  │
```

```python
def foliage_occlusion_cone(center_screen, canopy_radius_px, height_meters,
                            elevation_rad, meters_per_px_y):
    """
    Tapered occlusion: full radius at canopy height, shrinks to trunk_radius at ground.
    Returns a set of (polygon, depth) pairs for different height slices.
    """
    height_px = height_meters * abs(math.sin(elevation_rad)) / meters_per_px_y
    trunk_radius_px = canopy_radius_px * 0.1  # trunk ≈ 10% of canopy width

    # Discretize into N height slices
    slices = []
    N_SLICES = 4
    for i in range(N_SLICES):
        t = i / (N_SLICES - 1)  # 0 = ground, 1 = canopy top
        radius = lerp(trunk_radius_px, canopy_radius_px, t)
        y_offset = height_px * t
        # Circle at this height slice, shifted up on screen
        cx, cy = center_screen
        circle = approximate_circle(cx, cy - y_offset, radius)
        slices.append(circle)

    # Union of all slices = tapered silhouette
    return polygon_union_all(slices)
```

**TBD**: The exact cone shape and trunk ratio may need tuning once we see the actual 3D tile foliage. Google's 3D tiles sometimes model trees as flat photo textures, sometimes as geometry — the canopy shape in the height map will vary.

### Output: Tiled Occlusion Depth Map

The final output is a tiled depth map matching the DZI structure:

```
interactive/assets/occlusion/
  level_N/            ← matches a DZI zoom level (e.g., 1:4 scale)
    0_0.png           ← 256x256 tiles, 16-bit grayscale
    0_1.png
    ...
```

Each pixel stores: **the isometric depth of the closest occluding surface at this screen position.** Ground-level pixels store their own ground depth (no occlusion). Building/foliage pixels store the front-face depth of the occluder.

Two-channel encoding for the occlusion map:
- **R channel**: normalized isometric depth of the occluder (0 = near, 255 = far)
- **G channel**: occluder type (0 = ground/none, 128 = building, 255 = foliage)

The type channel allows the runtime shader to apply different occlusion behavior per type (hard cutoff for buildings, soft fade for foliage).

### Tool

```bash
# 1. Capture height map from 3D tiles (requires web renderer running on port 3000)
uv run python tools/capture_height_map.py \
  --view view.json \
  --output interactive/assets/heightmap/

# 2. Classify + generate occlusion depth map
uv run python tools/generate_occlusion_map.py \
  --heightmap interactive/assets/heightmap/ \
  --scene interactive/assets/scene.json \
  --view view.json \
  --output interactive/assets/occlusion/ \
  --scale 0.25
```

## Runtime: Custom PixiJS Shader

### Depth-Tested Sprite Filter

PixiJS v8 supports custom filters (WebGL2/WebGPU). The occlusion filter samples the depth texture and discards fragments behind buildings, with optional soft fade for foliage.

```typescript
import { Filter, GlProgram, Texture } from 'pixi.js'

const OCCLUSION_FRAG = `
  in vec2 vUV;
  in vec2 vWorldPos;
  out vec4 finalColor;

  uniform sampler2D uTexture;
  uniform sampler2D uOcclusionMap;
  uniform float uSpriteDepth;       // isometric depth of this sprite
  uniform vec2 uOcclusionOffset;    // viewport offset into occlusion map
  uniform vec2 uOcclusionScale;     // world-to-occlusion coordinate scale
  uniform vec2 uDepthRange;         // [minDepth, maxDepth] for normalization

  void main() {
    vec4 color = texture(uTexture, vUV);
    if (color.a < 0.01) discard;

    // Sample occlusion map at this fragment's world position
    vec2 occUV = (vWorldPos - uOcclusionOffset) * uOcclusionScale;
    vec4 occSample = texture(uOcclusionMap, occUV);

    float occDepth = mix(uDepthRange.x, uDepthRange.y, occSample.r);
    float occType = occSample.g;  // 0 = none, ~0.5 = building, ~1.0 = foliage

    // No occluder at this pixel
    if (occType < 0.1) {
      finalColor = color;
      return;
    }

    // Sprite is in front of occluder — render normally
    if (uSpriteDepth <= occDepth) {
      finalColor = color;
      return;
    }

    // Sprite is behind occluder
    if (occType > 0.7) {
      // Foliage: soft fade (partial visibility through leaves)
      float behindAmount = (uSpriteDepth - occDepth) / 20.0;  // fade over 20 depth units
      float foliageAlpha = clamp(1.0 - behindAmount * 0.7, 0.0, 1.0);
      finalColor = vec4(color.rgb, color.a * foliageAlpha);
    } else {
      // Building: hard occlusion
      discard;
    }
  }
`

class OcclusionFilter extends Filter {
  constructor(occlusionTexture: Texture) {
    const glProgram = GlProgram.from({
      vertex: OCCLUSION_VERT,  // same as before — passes vWorldPos
      fragment: OCCLUSION_FRAG,
    })
    super({ glProgram, resources: { uOcclusionMap: occlusionTexture.source } })
  }

  set spriteDepth(value: number) {
    this.uniforms.uSpriteDepth = value
  }
}
```

### Foliage Behavior

Buildings use hard `discard` — sprites behind them are fully hidden. Foliage uses a **soft fade**: sprites behind trees are partially visible (reduced alpha), simulating seeing through leaves. The fade amount depends on how far behind the tree the sprite is — a sprite just behind gets mostly visible, one well behind fades more.

This is configurable — the `0.7` threshold and `20.0` fade distance in the shader can be tuned once we see real results.

### Applying the Filter

**Recommended: Hybrid — only filter sprites near occluders**

```typescript
function needsOcclusion(entityX: number, entityY: number): boolean {
  // Quick check: sample the occlusion map type channel at entity position
  // If type > 0 in any nearby pixel, this entity needs the filter
  return occlusionLoader.hasOccluderNear(entityX, entityY, radius: 64)
}

// Only apply filter to sprites near buildings/foliage
// Most sprites on open roads skip the depth test entirely
```

For thousands of sprites, most will be on open roads and skip the filter. Only sprites near buildings or under tree canopy pay the shader cost.

For batching at scale, move to a container-level filter with per-sprite depth passed as a vertex attribute (see 04_simulation.md performance notes).

### Occlusion Map Tile Loading

Same pattern as DZI tile loading — viewport-culled, LRU-cached:

```typescript
class OcclusionMapLoader {
  private cache: LRUCache<string, PIXI.Texture> = new LRUCache(50)

  updateForViewport(viewport: Viewport) {
    const visibleTiles = this.getTilesInView(viewport.bounds)
    for (const { col, row } of visibleTiles) {
      if (!this.cache.has(`${col}_${row}`)) {
        this.loadTile(col, row)
      }
    }
  }

  hasOccluderNear(worldX: number, worldY: number, radius: number): boolean {
    // Sample type channel in a small area around the position
    // Returns true if any building or foliage occluder is nearby
  }
}
```

## Edge Cases

### Partial Occlusion

The shader works per-fragment. A car partially behind a building has its visible half rendered and its hidden half discarded. This is the main advantage of the depth map approach over coarser methods.

### Bridges and Overpasses

The height map will capture bridge geometry at its elevation. Sprites on roads beneath bridges should be occluded. This works naturally — the bridge surface has a height, creating an occlusion column. However, sprites ON the bridge should not be occluded by the bridge itself. **TBD**: may need a ground-elevation channel to distinguish "sprite on bridge" from "sprite under bridge." Revisit if the map area includes bridges.

### Google 3D Tile LOD

The Three.js renderer loads different LODs of Google 3D tiles based on zoom level. For the height map capture, force the highest available LOD to get accurate building geometry:

```typescript
// In the height map capture mode
tileset.maximumScreenSpaceError = 1  // force highest detail
```

### Height Map Resolution

At 1:4 scale, a building footprint that's 20m × 20m (≈30px × 30px on the map) becomes ~8×8 pixels in the height map. Sufficient for occlusion — we don't need sub-meter precision.

### Underground Layer

The underground subway overlay (08_public_transit.md) renders on top of everything as a visual overlay and is **not** affected by occlusion. It's an illustrative layer, not a spatially-sorted one.

## Integration

| Document | Update |
|---|---|
| **02_renderer.md** | Add occlusion map loading to render loop, note filter on SpriteLayer |
| **06_integration.md** | Add `tools/capture_height_map.py`, `tools/generate_occlusion_map.py` to project structure; add `occlusion/` and `heightmap/` to assets |
| **07_milestones.md** | Add occlusion as a Tier 2 milestone |

## Implementation Order

1. **Height map capture** — add a `/heightmap` route to the web renderer with top-down orthographic camera + depth shader. Capture via Playwright.
2. **Classification** — cross-reference height map with OSM building footprints to separate buildings from foliage.
3. **Occlusion map generation** — extrude buildings (rectangular) and foliage (conical) into isometric depth values. Tile the output.
4. **Basic shader** — per-sprite filter, verify occlusion on a few test sprites near known buildings.
5. **Foliage tuning** — adjust cone shape, soft fade parameters based on real visual results.
6. **Hybrid spatial check** — only apply filter to sprites near occluders.
7. **Batched approach** — if performance needs it, move to container-level filter with per-vertex depth.
