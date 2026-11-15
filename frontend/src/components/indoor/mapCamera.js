export const clampZoom = zoom => Math.max(100, Math.min(300, zoom));

export function mapUnitsPerPixel(bounds, viewport, zoom) {
  return Math.max(bounds[2] / Math.max(1, viewport.width), bounds[3] / Math.max(1, viewport.height)) * 100 / zoom;
}

export function gestureCenter(points) {
  const pair = points.slice(0, 2);
  return {x: pair.reduce((sum, p) => sum + p.x, 0) / pair.length,
    y: pair.reduce((sum, p) => sum + p.y, 0) / pair.length,
    distance: pair.length === 2 ? Math.hypot(pair[1].x - pair[0].x, pair[1].y - pair[0].y) : 0};
}

// Keep the map point under the fingers fixed while dragging or pinching.
export function beginMapGesture(points, bounds, viewport, camera) {
  const center = gestureCenter(points);
  const units = mapUnitsPerPixel(bounds, viewport, camera.zoom);
  return {zoom: camera.zoom, distance: center.distance, anchor: {
    x: bounds[0] + bounds[2] / 2 + camera.x + (center.x - viewport.left - viewport.width / 2) * units,
    y: bounds[1] + bounds[3] / 2 + camera.y + (center.y - viewport.top - viewport.height / 2) * units,
  }};
}

export function moveMapGesture(gesture, points, bounds, viewport) {
  const center = gestureCenter(points);
  const zoom = clampZoom(gesture.distance > 0 && center.distance > 0 ? gesture.zoom * center.distance / gesture.distance : gesture.zoom);
  const units = mapUnitsPerPixel(bounds, viewport, zoom);
  return {zoom,
    x: gesture.anchor.x - bounds[0] - bounds[2] / 2 - (center.x - viewport.left - viewport.width / 2) * units,
    y: gesture.anchor.y - bounds[1] - bounds[3] / 2 - (center.y - viewport.top - viewport.height / 2) * units,
  };
}
