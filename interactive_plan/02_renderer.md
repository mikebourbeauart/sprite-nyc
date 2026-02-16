# 02 — Renderer Migration

## Why Replace OpenSeaDragon

OpenSeaDragon is excellent for static deep-zoom images but has no support for:
- Animated sprites composited on top of tiles
- Per-frame update loops
- WebGL-accelerated sprite batching
- Custom shaders (day/night tinting, weather effects)

## Target: PixiJS v8

PixiJS is the best fit because:
- WebGL2/WebGPU sprite batching handles thousands of sprites at 60fps
- Built-in support for sprite sheets, animated sprites, tiling sprites
- Container hierarchy maps naturally to our layer architecture
- Mature ecosystem (sound via `@pixi/sound`, particles via `@pixi/particle-emitter`)
- Active maintenance, strong TypeScript support

### Alternative Considered: Phaser
Phaser is higher-level (full game framework) but adds unnecessary weight. We don't need physics, scene management, or input systems beyond what PixiJS provides. If the project ever needs those, Phaser can be layered on top of PixiJS later.

## Layer Architecture

```
Stage (PixiJS Application)
├── TileLayer (Container)
│   ├── visible tile sprites loaded from DZI pyramid
│   └── culled/loaded based on viewport (replaces OpenSeaDragon)
├── UndergroundLayer (Container, toggleable — see 08_public_transit.md)
│   ├── SubwayLineGraphics (colored track polylines from static GTFS)
│   ├── StationMarkers (platform sprites at stops)
│   ├── TrainSprites (moving trains from real-time MTA GTFS-RT)
│   └── PlatformPassengers (waiting pedestrian sprites)
├── RoadDebugLayer (Container, toggleable)
│   └── Graphics objects drawing road edges, intersections
├── SpriteLayer (Container)
│   ├── BuildingOverlays (door markers, info popups)
│   ├── Vehicles (cars, buses, taxis — sorted by Y)
│   ├── MTA Buses (real-time positions from SIRI/GTFS-RT)
│   ├── Pedestrians (NPCs — sorted by Y)
│   └── TrafficLights (cycling signal sprites)
└── UILayer (Container, fixed to screen)
    ├── Minimap
    ├── Controls (speed, density sliders)
    ├── Underground toggle button
    └── Info panel
```

## Tile Loading Strategy

The existing pipeline exports DZI tile pyramids. We reuse these tiles directly:

```
viewer/tiles/
  tiles.dzi          ← metadata (dimensions, tile size, overlap, format)
  tiles_files/
    0/  1/  2/ ...   ← zoom levels
      0_0.png        ← individual tiles at each level
      0_1.png
      ...
```

### DZI Loader for PixiJS

```typescript
// Pseudocode — DZI tile manager
class DZITileLoader {
  private dziMeta: { width, height, tileSize, overlap, maxLevel }
  private tileCache: LRUCache<string, PIXI.Texture>
  private container: PIXI.Container

  // Called each frame or on viewport change
  updateVisibleTiles(viewport: Viewport) {
    const level = this.zoomToLevel(viewport.scale)
    const visibleTiles = this.getTilesInView(viewport.bounds, level)

    for (const { col, row } of visibleTiles) {
      const key = `${level}/${col}_${row}`
      if (!this.tileCache.has(key)) {
        this.loadTile(level, col, row)
      }
    }
    this.cullOffscreenTiles(viewport.bounds, level)
  }

  private tileURL(level: number, col: number, row: number): string {
    return `tiles_files/${level}/${col}_${row}.png`
  }
}
```

Key behaviors:
- **LRU cache** — keep ~200 tiles in GPU memory, evict oldest
- **Progressive loading** — show lower-res tiles while high-res loads
- **Viewport culling** — only load tiles visible in the current pan/zoom

### Viewport / Camera

Use `pixi-viewport` (or custom implementation) for pan/zoom:

```typescript
import { Viewport } from 'pixi-viewport'

const viewport = new Viewport({
  screenWidth: window.innerWidth,
  screenHeight: window.innerHeight,
  worldWidth: dzi.width,    // full image width in pixels
  worldHeight: dzi.height,  // full image height in pixels
})
viewport.drag().pinch().wheel().decelerate()
app.stage.addChild(viewport)
```

The viewport's world coordinates = pixel coordinates in the full stitched image. This is the coordinate space everything else maps into.

## Rendering Loop

```typescript
app.ticker.add((delta) => {
  // 1. Update tile visibility based on viewport
  tileLoader.updateVisibleTiles(viewport)

  // 2. Run simulation step
  simulation.update(delta)

  // 3. Update sprite positions from simulation state
  spriteManager.syncFromSimulation(simulation)

  // 4. Sort sprite layer by isometric depth
  spriteLayer.children.sort((a, b) => a.zIndex - b.zIndex)
})
```

## Building Occlusion

Sprites behind tall buildings must be hidden. A pre-baked depth texture (generated offline from OSM building footprints + heights) is sampled by a custom PixiJS shader at runtime. Fragments where the sprite's isometric depth exceeds the depth map value are discarded — giving per-pixel partial occlusion. See **09_building_occlusion.md** for full details.

The depth map is tiled and loaded like DZI tiles (viewport-culled, LRU cached). A spatial hash check skips the depth test for sprites on open roads away from buildings.

## Performance Considerations

| Concern | Mitigation |
|---------|-----------|
| Tile texture memory | LRU cache, max ~200 tiles loaded |
| Sprite count | Object pooling — reuse sprite objects for off-screen entities |
| Sort cost | Only sort sprites that moved this frame (dirty flag) |
| Draw calls | Sprite sheets batch into single draw calls per sheet |
| Off-screen simulation | Hybrid: full sim near camera, simplified sim far away |
| Depth occlusion | Hybrid filter — only sprites near buildings get depth-tested (see 09_building_occlusion.md) |
