/**
 * Sprite NYC — OpenSeaDragon gigapixel viewer.
 *
 * Loads the DZI tile pyramid exported by export_tiles.py and provides
 * a smooth pan/zoom experience with touch support.
 */

(function () {
  "use strict";

  // ── Configuration ────────────────────────────────────────────────
  const DZI_PATH = "tiles.dzi";

  // ── Initialize viewer ────────────────────────────────────────────
  const viewer = OpenSeadragon({
    id: "viewer",
    tileSources: DZI_PATH,
    prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",

    // Disable default controls (we have custom ones)
    showNavigationControl: false,
    showNavigator: false,

    // Zoom settings
    minZoomLevel: 0.5,
    maxZoomLevel: 20,
    defaultZoomLevel: 1,
    zoomPerClick: 1.5,
    zoomPerScroll: 1.3,

    // Smooth animations
    animationTime: 0.4,
    springStiffness: 10,

    // Performance
    immediateRender: true,
    imageLoaderLimit: 4,
    maxImageCacheCount: 500,

    // Touch support
    gestureSettingsTouch: {
      pinchRotate: false,
      flickEnabled: true,
      flickMinSpeed: 100,
      flickMomentum: 0.3,
    },

    // Appearance
    background: "#0a0a0a",
    opacity: 1,

    // Constrain panning
    constrainDuringPan: true,
    visibilityRatio: 0.5,
  });

  // ── Custom controls ──────────────────────────────────────────────
  document.getElementById("zoomIn").addEventListener("click", function () {
    const zoom = viewer.viewport.getZoom();
    viewer.viewport.zoomTo(zoom * 1.5);
  });

  document.getElementById("zoomOut").addEventListener("click", function () {
    const zoom = viewer.viewport.getZoom();
    viewer.viewport.zoomTo(zoom / 1.5);
  });

  document.getElementById("home").addEventListener("click", function () {
    viewer.viewport.goHome();
  });

  // ── Loading state ────────────────────────────────────────────────
  const loadingEl = document.getElementById("loading");

  viewer.addHandler("open", function () {
    loadingEl.classList.add("hidden");
  });

  viewer.addHandler("open-failed", function (event) {
    loadingEl.textContent =
      "Failed to load tiles. Run export_tiles.py first.";
  });

  // ── Keyboard shortcuts ───────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    switch (e.key) {
      case "+":
      case "=":
        viewer.viewport.zoomTo(viewer.viewport.getZoom() * 1.3);
        break;
      case "-":
        viewer.viewport.zoomTo(viewer.viewport.getZoom() / 1.3);
        break;
      case "0":
        viewer.viewport.goHome();
        break;
    }
  });
})();
