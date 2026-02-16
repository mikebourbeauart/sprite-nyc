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

## Approach: Isometric Depth Map

Generate a depth texture offline from OSM building data. At runtime, a custom PixiJS shader on each sprite samples the depth texture — if the sprite's isometric depth is further from the camera than the building surface at that pixel, the fragment is discarded.

### How Isometric Depth Works

In our projection (azimuth -15°, elevation -45°), every point on screen maps to an isometric depth value:

```
depth = worldY * cos(azimuthRad) + worldX * sin(azimuthRad)
```

Higher depth = further from camera = rendered behind.

A building at ground position (bx, by) with height H projects upward on screen. Its front face (the part visible to the camera) has a ground-level depth, but it visually occupies screen pixels that correspond to deeper ground positions behind it. The depth map encodes: "at this screen pixel, the closest surface has depth D." Sprites with depth > D are occluded.

## Offline Depth Map Generation

### Input

- OSM building footprints from `scene.json` (already projected to screen space)
- Building heights: `building:levels` tag × 3m/level, or `height` tag, or default estimate (12m for residential, 40m for commercial)

### Isometric Extrusion

Each building footprint is extruded upward in isometric screen space to produce its visible silhouette:

```python
def extrude_building(footprint_screen, height_meters, meters_per_px_y, elevation):
    """
    Given a building's screen-space footprint polygon and its height,
    compute the screen-space silhouette (footprint + upward extrusion).
    """
    # In our isometric projection, vertical height maps to a screen-space
    # Y offset (upward on screen = negative Y)
    height_px = height_meters * abs(sin(elevation)) / meters_per_px_y

    # The silhouette is the union of:
    # 1. The original footprint
    # 2. The footprint shifted up by height_px
    # 3. The connecting edges (the visible front faces)
    roof_polygon = [(x, y - height_px) for (x, y) in footprint_screen]

    # Compute the convex hull or union of footprint + roof
    silhouette = polygon_union(footprint_screen, roof_polygon)
    return silhouette
```

### Rendering the Depth Map

For each building, fill its extruded silhouette in the depth map with the building's front-face depth value:

```python
def render_depth_map(buildings, world_width, world_height, scale=0.25):
    """
    Render a depth texture at 1/4 world resolution.
    Each pixel stores a normalized depth value (0.0 = closest, 1.0 = farthest).
    """
    dm_width = int(world_width * scale)
    dm_height = int(world_height * scale)

    # Initialize with max depth (ground plane depth at each pixel)
    depth_map = np.zeros((dm_height, dm_width), dtype=np.float32)

    for y in range(dm_height):
        for x in range(dm_width):
            # Ground depth at this screen position
            wx, wy = x / scale, y / scale
            depth_map[y, x] = isometric_depth(wx, wy)

    # For each building, set pixels within its silhouette to
    # the building's FRONT face depth (which is closer to camera)
    for building in buildings:
        silhouette = extrude_building(
            building.screen_polygon,
            building.height_meters,
            meters_per_px_y,
            elevation_rad
        )
        front_depth = building_front_depth(building)

        # All pixels inside the silhouette get the front depth
        # (which is LESS than the ground behind it → sprites behind are occluded)
        scaled_silhouette = [(x * scale, y * scale) for (x, y) in silhouette]
        fill_polygon(depth_map, scaled_silhouette, front_depth)

    return depth_map
```

The key insight: inside a building's silhouette, the depth value is set to the building's **front face depth** (closer to camera). Any sprite whose depth is greater than this (i.e., behind the building) gets discarded at those pixels.

### Tiled Output

The full world depth map could be enormous. Tile it to match the DZI tile structure:

```
interactive/assets/depth/
  level_N/            ← matches a DZI zoom level
    0_0.png           ← 256x256 grayscale tiles
    0_1.png
    ...
```

Use a single DZI zoom level (e.g., the one closest to 1:4 world scale). Each tile is a 256x256 grayscale PNG where pixel intensity encodes normalized depth (0 = near, 255 = far).

Estimated total size: ~5-15MB for a large map area at 1/4 resolution.

### Tool

```
tools/
  generate_depth_map.py    ← reads scene.json buildings, outputs depth tiles
```

```bash
uv run python tools/generate_depth_map.py \
  --scene interactive/assets/scene.json \
  --view view.json \
  --output interactive/assets/depth/ \
  --scale 0.25
```

## Runtime: Custom PixiJS Shader

### Depth-Tested Sprite Filter

PixiJS v8 supports custom filters (WebGL2/WebGPU). The depth occlusion filter samples the depth texture and discards fragments behind buildings.

```typescript
import { Filter, GlProgram, Texture } from 'pixi.js'

const DEPTH_OCCLUSION_VERT = `
  in vec2 aPosition;
  in vec2 aUV;
  out vec2 vUV;
  out vec2 vWorldPos;

  uniform mat3 uTransformMatrix;
  uniform mat3 uProjectionMatrix;

  void main() {
    gl_Position = vec4((uProjectionMatrix * uTransformMatrix * vec3(aPosition, 1.0)).xy, 0.0, 1.0);
    vUV = aUV;
    vWorldPos = (uTransformMatrix * vec3(aPosition, 1.0)).xy;
  }
`

const DEPTH_OCCLUSION_FRAG = `
  in vec2 vUV;
  in vec2 vWorldPos;
  out vec4 finalColor;

  uniform sampler2D uTexture;
  uniform sampler2D uDepthMap;
  uniform float uSpriteDepth;       // isometric depth of this sprite
  uniform vec2 uDepthMapOffset;     // viewport offset into depth map
  uniform vec2 uDepthMapScale;      // world-to-depth-map coordinate scale
  uniform vec2 uDepthRange;         // [minDepth, maxDepth] for normalization

  void main() {
    vec4 color = texture(uTexture, vUV);
    if (color.a < 0.01) discard;

    // Sample depth map at this fragment's world position
    vec2 depthUV = (vWorldPos - uDepthMapOffset) * uDepthMapScale;
    float sceneDepth = texture(uDepthMap, depthUV).r;

    // Denormalize: depth map stores 0-1, map back to world depth range
    float sceneDepthWorld = mix(uDepthRange.x, uDepthRange.y, sceneDepth);

    // If sprite is behind the scene surface at this pixel, discard
    if (uSpriteDepth > sceneDepthWorld) {
      discard;
    }

    finalColor = color;
  }
`

class DepthOcclusionFilter extends Filter {
  constructor(depthTexture: Texture) {
    const glProgram = GlProgram.from({
      vertex: DEPTH_OCCLUSION_VERT,
      fragment: DEPTH_OCCLUSION_FRAG,
    })
    super({ glProgram, resources: { uDepthMap: depthTexture.source } })
  }

  set spriteDepth(value: number) {
    this.uniforms.uSpriteDepth = value
  }
}
```

### Applying the Filter

Two strategies for applying the depth test:

**Option A: Per-sprite filter (simple, fewer sprites)**
```typescript
function syncSpriteOcclusion(sprite: PIXI.Sprite, entity: Entity) {
  const depth = computeSortDepth(entity.x, entity.y)
  const filter = sprite.filters?.[0] as DepthOcclusionFilter
  filter.spriteDepth = depth
}
```

Each sprite gets its own filter instance with its depth value. Fine for hundreds of sprites, but each filter is a separate draw call — breaks batching.

**Option B: Container-level filter with depth attribute (batched)**
```typescript
// Apply a single filter to the entire SpriteLayer container
// Pass per-sprite depth via a vertex attribute
spriteLayer.filters = [depthOcclusionFilter]

// Each sprite encodes its depth in its tint alpha or a custom attribute
// The shader reads depth per-fragment from the vertex interpolation
```

More complex setup but maintains PixiJS batching. **Recommended for thousands of sprites.**

**Option C: Hybrid — only filter sprites near buildings**
```typescript
function needsOcclusion(entity: Entity, buildings: Building[]): boolean {
  // Quick spatial hash check: is this entity near any building?
  return nearbyBuildings(entity.x, entity.y).length > 0
}

// Only apply filter to sprites that are actually near buildings
// Most sprites on open roads skip the depth test entirely
```

Best real-world performance — most sprites never go behind buildings and don't need the filter at all. **Recommended approach.**

### Depth Map Tile Loading

Load depth map tiles the same way as DZI tiles — only fetch tiles within the current viewport:

```typescript
class DepthMapLoader {
  private cache: LRUCache<string, PIXI.Texture> = new LRUCache(50)

  updateForViewport(viewport: Viewport) {
    // Determine which depth tiles overlap the visible area
    const level = this.depthLevel  // fixed zoom level (e.g., 1/4 scale)
    const visibleTiles = this.getTilesInView(viewport.bounds, level)

    for (const { col, row } of visibleTiles) {
      if (!this.cache.has(`${col}_${row}`)) {
        this.loadTile(col, row)
      }
    }
  }

  getDepthAt(worldX: number, worldY: number): number {
    // Sample the depth value at a world position
    // Used by the hybrid approach to check if occlusion filter is needed
    const tile = this.getTileForPosition(worldX, worldY)
    if (!tile) return Infinity  // no depth data → no occlusion
    return sampleTexture(tile, worldX, worldY)
  }
}
```

## Edge Cases

### Partial Occlusion

A sprite partially behind a building should be partially visible — the shader handles this per-fragment. The front half of a car peeking out from behind a building is rendered, the back half is discarded.

### Building Height Estimation

Not all OSM buildings have height data. Fallback heuristic:

| `building` tag | Estimated height |
|---|---|
| `residential` | 12m (4 floors) |
| `commercial` | 25m (8 floors) |
| `office` | 40m (13 floors) |
| `skyscraper` | 150m |
| `house` | 8m (2-3 floors) |
| `church`, `cathedral` | 20m |
| (no tag / default) | 10m |

If `building:levels` is present, use `levels * 3.0m`. If `height` tag is present, use it directly.

### Sprite Anchor Point vs. Fragment Depth

The shader uses a single `uSpriteDepth` per sprite (based on the entity's ground position). This means a tall sprite (like a bus) uses the same depth for all its pixels. For small sprites (16x12 cars) this is imperceptible. For larger sprites, could pass depth as a vertex attribute that varies across the quad — but probably unnecessary at this scale.

### Underground Layer

The underground subway overlay (08_public_transit.md) renders on top of everything and is **not** affected by the depth map. It's a visual overlay, not a spatially-sorted layer.

## Integration

| Document | Update |
|---|---|
| **02_renderer.md** | Add depth map loading to the render loop, note filter on SpriteLayer |
| **03_data_sources.md** | Add building heights as extracted data |
| **06_integration.md** | Add `tools/generate_depth_map.py` to project structure, `depth/` to assets |
| **07_milestones.md** | Add depth occlusion as a Tier 2 milestone |

## Implementation Order

1. **Generate depth map offline** — `generate_depth_map.py` reads `scene.json` buildings, produces tiled grayscale PNGs
2. **Basic shader** — per-sprite filter, verify occlusion works on a few test sprites near known buildings
3. **Hybrid spatial check** — only apply filter to sprites near buildings (spatial hash lookup)
4. **Batched approach** — if performance needs it, move to container-level filter with per-vertex depth
