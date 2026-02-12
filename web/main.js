import * as THREE from "three";
import {
  TilesRenderer,
  Ellipsoid,
  GoogleCloudAuthPlugin,
  GeoUtils,
} from "3d-tiles-renderer";

// ── Globals ──────────────────────────────────────────────────────────
let renderer, camera, scene, tiles;
let viewConfig = null;
const statusEl = document.getElementById("status");
const canvas = document.getElementById("canvas");

// WGS-84 ellipsoid constants
const WGS84_RADIUS = 6378137;
const WGS84_FLATTENING = 1 / 298.257223563;
const WGS84_POLAR = WGS84_RADIUS * (1 - WGS84_FLATTENING);
const WGS84 = new Ellipsoid(WGS84_RADIUS, WGS84_RADIUS, WGS84_POLAR);
const GOOGLE_TILES_URL = "https://tile.googleapis.com/v1/3dtiles/root.json";

// ── Helpers ──────────────────────────────────────────────────────────

function setStatus(msg) {
  statusEl.textContent = msg;
  console.log(`[status] ${msg}`);
}

const deg2rad = (d) => (d * Math.PI) / 180;

// ── Load view config ─────────────────────────────────────────────────

async function loadViewConfig() {
  const params = new URLSearchParams(window.location.search);
  const configPath = params.get("config") || "/view.json";
  const resp = await fetch(configPath);
  if (!resp.ok) throw new Error(`Failed to load config from ${configPath}`);
  return resp.json();
}

// ── Setup Three.js ───────────────────────────────────────────────────

function setupRenderer(width, height) {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
}

/**
 * Create an orthographic camera in the Three.js Y-up frame,
 * positioned isometrically above the given lat/lng.
 *
 * The 3d-tiles-renderer lib uses the geo frame internally
 * (Z = up in Cesium) but Three.js uses Y = up. The Ellipsoid
 * methods handle this swap via GeoUtils.swapToGeoFrame.
 */
function setupCamera(cfg) {
  const { width, height, view_height_meters: viewHeight } = cfg;
  const aspect = width / height;
  const halfH = viewHeight / 2;
  const halfW = halfH * aspect;

  camera = new THREE.OrthographicCamera(
    -halfW, halfW, halfH, -halfH, 1, 1000000
  );

  const latRad = deg2rad(cfg.center.lat);
  const lngRad = deg2rad(cfg.center.lng);
  const azRad = deg2rad(cfg.azimuth);     // -15° → slight rotation
  const elRad = deg2rad(-cfg.elevation);   // -45° → we want to look DOWN, so negate

  // Get ECEF position of the center point on the surface
  const centerPos = new THREE.Vector3();
  WGS84.getCartographicToPosition(latRad, lngRad, 0, centerPos);

  // Get the East-North-Up frame at the center
  const enuFrame = new THREE.Matrix4();
  WGS84.getEastNorthUpFrame(latRad, lngRad, enuFrame);

  // Build the camera direction in local ENU coordinates:
  //   East  = +X in ENU
  //   North = +Y in ENU
  //   Up    = +Z in ENU
  //
  // Azimuth measured from North toward East:
  //   dirEast  = sin(az)
  //   dirNorth = cos(az)
  // Elevation measured from horizon toward Up:
  //   horizontal component = cos(el)
  //   vertical component   = sin(el)
  const dirLocal = new THREE.Vector3(
    Math.sin(azRad) * Math.cos(elRad),  // East
    Math.cos(azRad) * Math.cos(elRad),  // North
    Math.sin(elRad)                     // Up
  ).normalize();

  // Transform local direction to world (ECEF) space
  // The ENU frame matrix has position embedded; we only want the rotation part
  const enuRotOnly = enuFrame.clone();
  enuRotOnly.setPosition(0, 0, 0);
  const dirWorld = dirLocal.clone().applyMatrix4(enuRotOnly);

  // Camera distance — far enough above the scene
  const camDist = 10000;

  // Camera position = center + direction * distance
  camera.position.copy(centerPos).addScaledVector(dirWorld, camDist);

  // Camera up = the "Up" axis from ENU, transformed to world
  const upLocal = new THREE.Vector3(0, 0, 1);
  const upWorld = upLocal.applyMatrix4(enuRotOnly).normalize();
  camera.up.copy(upWorld);

  camera.lookAt(centerPos);
  camera.updateProjectionMatrix();

  console.log("[camera] center ECEF:", centerPos.toArray().map(v => v.toFixed(0)));
  console.log("[camera] position:", camera.position.toArray().map(v => v.toFixed(0)));
  console.log("[camera] up:", camera.up.toArray().map(v => v.toFixed(3)));
}

// ── Setup 3D Tiles ───────────────────────────────────────────────────

function setupTiles(apiKey) {
  tiles = new TilesRenderer(GOOGLE_TILES_URL);
  tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: apiKey }));

  tiles.setCamera(camera);
  tiles.setResolutionFromRenderer(camera, renderer);

  // Tune loading
  tiles.errorTarget = 20;
  tiles.parseQueue.maxJobs = 10;
  tiles.downloadQueue.maxJobs = 30;

  scene = new THREE.Scene();
  scene.add(tiles.group);

  // Lighting
  const ambient = new THREE.AmbientLight(0xffffff, 1.2);
  scene.add(ambient);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(1, 2, 3).normalize();
  scene.add(dir);
}

// ── Render loop ──────────────────────────────────────────────────────

let frameCount = 0;

function animate() {
  requestAnimationFrame(animate);

  tiles.update();

  renderer.render(scene, camera);
  frameCount++;

  if (frameCount % 60 === 0) {
    // Use the rootTileSet and loading stats
    const downloading = tiles.downloadQueue?.items?.length ?? 0;
    const parsing = tiles.parseQueue?.items?.length ?? 0;
    const visible = tiles.visibleTiles?.size ?? 0;
    const active = tiles.activeTiles?.size ?? 0;
    setStatus(
      `Visible: ${visible} | Active: ${active} | DL: ${downloading} | Parse: ${parsing} | Frame: ${frameCount}`
    );
  }
}

// ── Export helpers (called from Playwright) ───────────────────────────

window.waitForTilesReady = (stableFrames = 30) => {
  return new Promise((resolve) => {
    let stableCount = 0;
    let lastActive = -1;

    const check = () => {
      const downloading = tiles.downloadQueue?.items?.length ?? 0;
      const parsing = tiles.parseQueue?.items?.length ?? 0;
      const busy = downloading + parsing;

      if (busy === 0 && lastActive === 0) {
        stableCount++;
      } else {
        stableCount = 0;
      }
      lastActive = busy;

      if (stableCount >= stableFrames) {
        resolve();
      } else {
        requestAnimationFrame(check);
      }
    };
    requestAnimationFrame(check);
  });
};

window.exportPNG = () => {
  renderer.render(scene, camera);
  return canvas.toDataURL("image/png");
};

window.getViewConfig = () => viewConfig;

// Expose tiles globally for Playwright status checks
window.getTiles = () => tiles;

// ── Initialization ───────────────────────────────────────────────────

async function main() {
  try {
    setStatus("Loading view config…");
    viewConfig = await loadViewConfig();

    const { width, height } = viewConfig;

    const params = new URLSearchParams(window.location.search);
    const apiKey = params.get("key") || import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
    if (!apiKey) {
      setStatus("ERROR: No Google Maps API key. Pass ?key=YOUR_KEY");
      return;
    }

    setStatus("Setting up renderer…");
    setupRenderer(width, height);
    setupCamera(viewConfig);
    setupTiles(apiKey);

    setStatus("Loading tiles…");
    animate();

    // Listen for tile load events
    tiles.addEventListener("load-tile-set", () => {
      console.log("[tiles] Root tileset loaded");
    });
    tiles.addEventListener("tiles-load-start", () => {
      console.log("[tiles] Started loading tiles");
    });
    tiles.addEventListener("tiles-load-end", () => {
      console.log("[tiles] All tiles loaded");
    });
  } catch (err) {
    setStatus(`ERROR: ${err.message}`);
    console.error(err);
  }
}

main();
