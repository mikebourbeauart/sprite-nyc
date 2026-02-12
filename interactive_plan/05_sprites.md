# 05 — Sprites & Animation

## Isometric Direction System

The map uses azimuth -15°, elevation -45°. Sprites need directional variants to face the correct way as they move along roads.

### 8-Direction System

```
     NW   N   NE
       \  |  /
   W ── · ── E
       /  |  \
     SW   S   SE
```

Each sprite needs 8 facing directions. For the isometric view:
- **N** = moving toward top-right of screen
- **S** = moving toward bottom-left
- **E** = moving toward bottom-right
- **W** = moving toward top-left

Map entity heading (radians) to sprite direction:

```typescript
function headingToDirection(heading: number): Direction {
  // Adjust for azimuth rotation
  const adjusted = heading + degToRad(15)  // compensate -15° azimuth
  const index = Math.round(adjusted / (Math.PI / 4)) % 8
  return DIRECTIONS[index]  // ['N','NE','E','SE','S','SW','W','NW']
}
```

## Sprite Sheet Format

### Layout

Each entity type gets one sprite sheet PNG with all directions and animation frames:

```
┌────┬────┬────┬────┬────┬────┬────┬────┐
│ N  │ N  │ NE │ NE │ E  │ E  │ SE │ SE │  ← car (2 frames per dir)
│ f0 │ f1 │ f0 │ f1 │ f0 │ f1 │ f0 │ f1 │
├────┼────┼────┼────┼────┼────┼────┼────┤
│ S  │ S  │ SW │ SW │ W  │ W  │ NW │ NW │
│ f0 │ f1 │ f0 │ f1 │ f0 │ f1 │ f0 │ f1 │
└────┴────┴────┴────┴────┴────┴────┴────┘
```

### Sprite Sizes (in pixels)

| Entity Type | Sprite Size | Animation Frames |
|-------------|-------------|-----------------|
| Sedan | 16×12 | 2 (idle, moving) |
| Taxi | 16×12 | 2 |
| Bus | 24×12 | 2 |
| Truck | 20×14 | 2 |
| Pedestrian | 8×10 | 4 (walk cycle) |
| Traffic light | 6×12 | 3 (red, yellow, green) |

### Walk Cycle

Pedestrians use a 4-frame walk animation per direction (32 frames total):

```
Frame 0: stand (right foot forward)
Frame 1: step (left foot passing)
Frame 2: stand (left foot forward)
Frame 3: step (right foot passing)
```

Animation speed tied to movement speed — faster walking = faster cycle.

## Sprite Generation Approaches

### Option A: Hand-Pixel (Highest Quality)

Draw sprites manually in Aseprite or Piskel at the correct isometric angle. This guarantees pixel-perfect consistency with the map aesthetic.

Effort: ~2-4 hours per entity type (8 directions × N frames).

### Option B: AI-Assisted Generation

Use the existing Oxen.ai fine-tuned model to generate sprite candidates:

1. Create a template showing the map at close zoom with a red-bordered region where the sprite should appear
2. Prompt the model to generate a car/person in that region
3. Extract and clean up the sprite manually

This leverages the model's learned pixel-art style but may need manual cleanup.

### Option C: 3D Pre-Render → Pixel Art

1. Model vehicles/people in a simple 3D tool (MagicaVoxel is ideal for pixel-art style)
2. Render from the exact isometric angle (azimuth -15°, elevation -45°)
3. Downscale to target sprite size
4. Apply pixel-art cleanup (reduce colors, sharpen edges)

This approach ensures correct perspective and is easy to iterate on.

### Recommended: Start with Option A for MVP

A minimal set of hand-drawn sprites is fastest to get on screen:
- 1 car sprite (sedan) × 8 directions × 2 frames = 16 sprites
- 1 pedestrian sprite × 8 directions × 4 frames = 32 sprites
- 1 traffic light × 3 states = 3 sprites

Total: ~51 small sprites. Achievable in a day.

## Color Palette

Match the map's pixel-art aesthetic. Sample dominant colors from existing generated tiles:

```
Cars:
  Yellow taxi:  #F2C94C, #D4A934, #8B6914  (highlight, base, shadow)
  White sedan:  #E8E8E8, #C0C0C0, #808080
  Red sedan:    #E84040, #B03030, #701818
  Blue sedan:   #4080E8, #3060B0, #183870
  Black sedan:  #505050, #303030, #181818

Pedestrians:
  Skin tones:   #F2D4B0, #D4A878, #8B6B4A (varied)
  Clothing:     randomized from a palette of 12-15 colors

Traffic lights:
  Post:         #404040, #282828
  Red:          #FF3030
  Yellow:       #FFD030
  Green:        #30FF50
```

## Depth Sorting

Isometric rendering requires correct back-to-front sorting. The sort key for each sprite:

```typescript
// Higher sortY = rendered later = appears in front
function computeSortDepth(worldX: number, worldY: number): number {
  // In our isometric system (azimuth -15°, elevation -45°):
  // Objects further "south-east" in world space appear in front
  const azRad = degToRad(-15)
  return worldY * Math.cos(azRad) + worldX * Math.sin(azRad)
}
```

Apply this to the PixiJS `zIndex` property:

```typescript
sprite.zIndex = computeSortDepth(entity.x, entity.y)
spriteLayer.sortableChildren = true
```

## Sprite Pooling

To avoid GC pressure from creating/destroying sprites:

```typescript
class SpritePool {
  private available: PIXI.Sprite[] = []
  private active: Map<number, PIXI.Sprite> = new Map()

  acquire(entityId: number, texture: PIXI.Texture): PIXI.Sprite {
    const sprite = this.available.pop() || new PIXI.Sprite()
    sprite.texture = texture
    sprite.visible = true
    this.active.set(entityId, sprite)
    return sprite
  }

  release(entityId: number) {
    const sprite = this.active.get(entityId)
    if (sprite) {
      sprite.visible = false
      this.active.delete(entityId)
      this.available.push(sprite)
    }
  }
}
```

Pre-allocate ~600 sprite objects at startup (200 vehicles + 400 pedestrians).
