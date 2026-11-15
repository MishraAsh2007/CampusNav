/**
 * Floor plan georeferencing: which lat/lng each floor plan image covers.
 *
 * Every floor has a strict bounding box for its image:
 *   topLeft      { lat, lng } of the image's top-left pixel (0, 0)
 *   bottomRight  { lat, lng } of the image's bottom-right pixel (width, height)
 *   width, height  the image's size in pixels
 *
 * The maths assumes a north-up image in Web Mercator (EPSG:3857), which is how ArcGIS and most GIS
 * tools export plans. x is linear in longitude; y is linear in Mercator y, not in latitude. Over one
 * building the difference is tiny, but it makes ArcGIS exports line up exactly.
 *
 * Where bounds come from:
 *   - a map file's floor `bounds` ({ topLeft, bottomRight }), used by indoorModel.js
 *   - FLOOR_PLAN_IMAGES below (optional image overrides; geometry is moved into the new image)
 *   - the built-in sample layouts (floorPlans.js): the building's OpenStreetMap footprint stretched
 *     over the plan's outer wall (sampleCalibration)
 * Map files without bounds are georeferenced from points with known coordinates instead (indoorModel.js).
 */
import { PLAN_W, PLAN_H } from './floorPlans';

const R = 6378137; // Web Mercator sphere radius, metres
const DEG = Math.PI / 180;

/** Mercator y (unitless) for a latitude. */
export const mercY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * DEG) / 2));
const latFromMercY = (m) => (2 * Math.atan(Math.exp(m)) - Math.PI / 2) / DEG;

/** EPSG:3857 metres -> { lat, lng } */
export function webMercatorToLatLng(x, y) {
  return { lat: latFromMercY(y / R), lng: x / R / DEG };
}

/** ArcGIS extent { xmin, ymin, xmax, ymax } (EPSG:3857) -> { topLeft, bottomRight } */
export function extentToCorners({ xmin, ymin, xmax, ymax }) {
  return { topLeft: webMercatorToLatLng(xmin, ymax), bottomRight: webMercatorToLatLng(xmax, ymin) };
}

// ------------------------------------------------------------------ real floor plan images

/**
 * Optional image overrides, keyed by building id then floor id. Not needed for new buildings: a map
 * file can carry `image_url`, `image_width`, `image_height` and `bounds` itself. An entry here with a
 * `url` replaces that floor's image and gives it these corner coordinates (indoorCatalog.js).
 *
 * ILC bounds below: fullExtent of UMass's ArcGIS map services (EPSG:3857).
 * Public tiles were successfully retrieved on 2026-11-15. A tile mosaic can
 * extend beyond fullExtent: use its actual extent and dimensions when filling
 * these fields. Existing graph geometry still requires review and alignment.
 */
export const FLOOR_PLAN_IMAGES = {
  ilc: {
    1: {
      url: null,
      width: null,
      height: null,
      ...extentToCorners({ xmin: -8073642.978745704, ymin: 5219678.662880072, xmax: -8073457.240743969, ymax: 5219812.081033015 }),
      source: 'https://tiles.arcgis.com/tiles/2gdL2gxYNFY2TOUb/arcgis/rest/services/Integrated_Learning_Center_First_Floor_Scaled/MapServer'
    },
    2: {
      url: null,
      width: null,
      height: null,
      ...extentToCorners({ xmin: -8073650.562904787, ymin: 5219679.272648083, xmax: -8073452.210974673, ymax: 5219819.169797759 }),
      source: 'https://tiles.arcgis.com/tiles/2gdL2gxYNFY2TOUb/arcgis/rest/services/Integrated_Learning_Center_Second_Floor_Reup/MapServer'
    }
  }
};

// ------------------------------------------------------------------ sample layouts

/** OSM building bounding boxes [south, west, north, east] (Nominatim, OpenStreetMap contributors). */
export const BUILDING_GEO = {
  ilc: [42.390711, -72.5264689, 42.3914433, -72.5253848],
  'campus-center': [42.3911535, -72.5276475, 42.3923169, -72.5263799],
  'student-union': [42.3905299, -72.5279865, 42.391225, -72.5271879],
  'dubois-library': [42.3891484, -72.528698, 42.390176, -72.5275764]
};

/** The sample plan's outer wall in pixels (floorPlans.js: X0-20 .. X1+20, TOP.y0-20 .. BOTTOM.y1+20). */
export const PLAN_WALL = { x0: 60, x1: 1140, y0: 90, y1: 710 };

/** Image bounds for a sample layout: the OSM footprint maps onto PLAN_WALL, extended to the image edges. */
function sampleCalibration(buildingId) {
  const g = BUILDING_GEO[buildingId];
  if (!g) return null;
  const [s, w, n, e] = g;
  const kx = (PLAN_WALL.x1 - PLAN_WALL.x0) / (e - w); // px per degree of longitude
  const ky = (PLAN_WALL.y1 - PLAN_WALL.y0) / (mercY(n) - mercY(s)); // px per unit of Mercator y
  return {
    kind: 'sample',
    url: null,
    width: PLAN_W,
    height: PLAN_H,
    topLeft: { lat: latFromMercY(mercY(n) + PLAN_WALL.y0 / ky), lng: w - PLAN_WALL.x0 / kx },
    bottomRight: { lat: latFromMercY(mercY(n) - (PLAN_H - PLAN_WALL.y0) / ky), lng: w + (PLAN_W - PLAN_WALL.x0) / kx }
  };
}

// ------------------------------------------------------------------ lookups

/** Bounds of a built-in sample layout (null for buildings without one). */
export function planCalibration(buildingId) {
  return sampleCalibration(buildingId);
}

/** lat/lng -> image pixel [x, y] (origin top-left, y down) for a calibration. */
export function geoToImage(cal, lat, lng) {
  if (!cal) return null;
  const { topLeft: tl, bottomRight: br } = cal;
  const x = ((lng - tl.lng) / (br.lng - tl.lng)) * cal.width;
  const y = ((mercY(tl.lat) - mercY(lat)) / (mercY(tl.lat) - mercY(br.lat))) * cal.height;
  return [x, y];
}

/** Image pixel [x, y] -> { lat, lng } for a calibration. */
export function imageToGeo(cal, [x, y]) {
  if (!cal) return null;
  const { topLeft: tl, bottomRight: br } = cal;
  const lng = tl.lng + (x / cal.width) * (br.lng - tl.lng);
  const m = mercY(tl.lat) - (y / cal.height) * (mercY(tl.lat) - mercY(br.lat));
  return { lat: latFromMercY(m), lng };
}

/** lat/lng -> sample layout pixels. */
export function geoToPlan(buildingId, lat, lng) {
  return geoToImage(planCalibration(buildingId), lat, lng);
}

/** Sample layout pixels -> lat/lng. */
export function planToGeo(buildingId, p) {
  return imageToGeo(planCalibration(buildingId), p);
}

/** Leaflet ImageOverlay bounds in L.CRS.Simple (pixel space): [[0, 0], [height, width]]. */
export function overlayBounds(cal) {
  return [
    [0, 0],
    [cal.height, cal.width]
  ];
}

/** Leaflet ImageOverlay bounds on a geographic map (EPSG:3857): [[south, west], [north, east]]. */
export function geoBounds(cal) {
  return [
    [cal.bottomRight.lat, cal.topLeft.lng],
    [cal.topLeft.lat, cal.bottomRight.lng]
  ];
}

/** Metres per pixel along the north-south axis of a calibration (for accuracy circles). */
export function metresPerPx(cal) {
  return ((cal.topLeft.lat - cal.bottomRight.lat) * 110540) / cal.height;
}
