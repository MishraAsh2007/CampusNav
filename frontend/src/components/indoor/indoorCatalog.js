/**
 * Live indoor maps come from the source-backed routing API. Sample layouts are
 * restricted to explicit demo mode; an unavailable API leaves live indoor maps unavailable.
 *
 *   1. The indoor API (campus_routing): GET {VITE_INDOOR_API_URL}/indoor/status, then
 *      GET /indoor/maps/{building_id} for each routable building.
 *   2. The built-in sample layouts (sampleMaps.js) for ILC, Campus Center, Student Union and Du Bois.
 *      These are loaded only when VITE_CAMPUSNAV_DEMO=1.
 *
 * Maps are matched to outdoor buildings (Role 4's GET /buildings) by id, then by name, then by distance.
 * A map with no matching outdoor building still becomes a destination on the map, built from the map's
 * own entrances. So a dorm needs just its map file (and ideally a backend building entry).
 */
import { createContext, useContext, useMemo, useSyncExternalStore } from 'react';
import { isNavigable, normalizeIndoorMap } from './indoorModel';
import { sampleIndoorMaps } from './sampleMaps';
import { drawingDisplayMap } from './backendIndoor';
import { FLOOR_PLAN_IMAGES } from './floorCalibration';
import { isWithdrawnIndoorMap } from './indoorMapPolicy';
import { DEMO_MODE, INDOOR_API_BASE, routingPaths } from '../../services/api';

const SAMPLES = DEMO_MODE ? 'prefer' : 'off';
const DATA_FILES = import.meta.glob('/data/indoor/*.json', { import: 'default' });
const PRIORITY = SAMPLES === 'prefer' ? { sample: 3, api: 2, data: 1 } : { api: 3, data: 2, sample: 1 };

let state = { models: [], loading: true, errors: [] };
const listeners = new Set();
const set = (patch) => {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
};

async function fetchJson(url, ms = 2500) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

/** Optional image overrides from floorCalibration.js (only entries with a url). */
function overridesFor(buildingId) {
  const o = FLOOR_PLAN_IMAGES[buildingId];
  if (!o) return {};
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v?.url && v.width > 0 && v.height > 0));
}

function toModel(raw, source) {
  try {
    if (!DEMO_MODE && (source === 'sample' || raw?.synthetic)) return null;
    const m = normalizeIndoorMap(raw, { source, imageOverrides: overridesFor(raw?.building_id) });
    return !isWithdrawnIndoorMap(m) && isNavigable(m) ? m : null;
  } catch (err) {
    console.warn(`[CampusNav] Skipping indoor map ${raw?.building_id ?? '?'} (${source}):`, err);
    return null;
  }
}

let started = false;
export function loadIndoorCatalog() {
  if (started) return;
  started = true;
  const models = SAMPLES === 'off' ? [] : sampleIndoorMaps().map((m) => toModel(m, 'sample')).filter(Boolean);
  set({ models, loading: true });
  if (DEMO_MODE) {
    set({ loading: false });
    return;
  }
  const fromFiles = Promise.all(Object.values(DATA_FILES).map(async load => {
    const raw = await load().catch(() => null);
    return raw?.version === 1 && raw.building_id && raw.status === 'reviewed' && !raw.synthetic ? toModel(raw, 'data') : null;
  }));
  const fromApi = routingPaths(INDOOR_API_BASE).then(async paths => {
    if (!paths.has('/indoor/status')) return [];
    const source = paths.has('/navigation/plan') && paths.has('/navigation/arrive') ? 'api' : 'data';
    const s = await fetchJson(`${INDOOR_API_BASE}/indoor/status`);
    const ids = (s?.buildings ?? []).filter((b) => b.routable === true).map((b) => b.building_id);
    const maps = await Promise.all(ids.map((id) => fetchJson(`${INDOOR_API_BASE}/indoor/maps/${encodeURIComponent(id)}`, 5000)));
    return maps.map((m) => (m ? toModel(m, source) : null));
  });

  const fromDrawing = SAMPLES === 'prefer' ? Promise.resolve([]) : Promise.all([
    fetchJson(`${INDOOR_API_BASE}/plan-wayfinding`, 5000),
    fetchJson(`${INDOOR_API_BASE}/journey/portals`, 5000),
  ]).then(async ([catalog, registry]) => {
    const maps = await Promise.all((catalog?.buildings || []).map(async b => {
      const raw = await fetchJson(`${INDOOR_API_BASE}/plan-wayfinding/${encodeURIComponent(b.building_id)}`, 5000);
      return raw ? drawingDisplayMap(raw, registry?.portals || []) : null;
    }));
    return maps.filter(Boolean);
  });

  Promise.all([fromFiles, fromApi, fromDrawing]).then(([files, api, drawing]) => {
    set({ models: [...state.models, ...files.filter(Boolean), ...api.filter(Boolean), ...drawing], loading: false });
  });
}

const subscribe = (l) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const snapshot = () => state;

// ------------------------------------------------------------------ matching to outdoor buildings

const normName = (s) => String(s ?? '').toLowerCase().replace(/^the\s+/, '').replace(/[^a-z0-9]/g, '');
const metres = (a, b) => Math.hypot((a.lat - b.lat) * 110540, (a.lng - b.lng) * 111320 * Math.cos((a.lat * Math.PI) / 180));

function matchBuilding(model, buildings) {
  const byId = buildings.find((b) => b.id === model.id);
  if (byId) return byId;
  const n = normName(model.name);
  const byName = buildings.find((b) => normName(b.name) === n) ?? buildings.find((b) => n.length >= 6 && (normName(b.name).includes(n) || n.includes(normName(b.name))));
  if (byName) return byName;
  if (model.centroid) {
    const near = buildings.map((b) => ({ b, d: metres(b.location, model.centroid) })).sort((x, y) => x.d - y.d)[0];
    if (near && near.d < 45) return near.b;
  }
  return null;
}

const RESIDENTIAL = /\b(residence|residential|dorm|dormitory|apartments?|house|tower)\b|sacl|residen/i;

/** A destination built from the map alone, for buildings the backend doesn't list yet. */
function buildingFromModel(m) {
  const entrances = m.entrances
    .filter((e) => e.geo)
    .map((e) => ({ id: e.id, name: e.name, lat: e.geo.lat, lng: e.geo.lng, step_free: e.stepFree, door_type: e.door === 'manual' ? 'manual' : e.door === 'push-button' ? 'push-button' : 'automatic', has_ramp: false }));
  if (!m.centroid) return null;
  const words = m.name.replace(/[^A-Za-z0-9 ]/g, ' ').split(/\s+/).filter((w) => w && !/^(the|of|and|hall|building)$/i.test(w));
  const residential = RESIDENTIAL.test(m.name) || m.sources.some((s) => RESIDENTIAL.test(`${s.id} ${s.url ?? ''}`));
  return {
    id: m.id,
    name: m.name,
    code: (words.length > 1 ? words.map((w) => w[0]).join('') : (words[0] ?? m.id).slice(0, 4)).toUpperCase(),
    category: residential ? 'residential' : 'academic',
    location: m.centroid,
    entrances,
    step_free_entrances: entrances.filter((e) => e.step_free),
    door_type: entrances.some((e) => e.door_type !== 'manual') ? 'mixed' : 'manual',
    elevators: { total_count: m.assets.size, working_count: m.assets.size, floors_served: m.floors.map((f) => f.id).join(', '), status: m.assets.size ? 'all_operational' : 'none', list: [] },
    accessible_restrooms: m.rooms.some((r) => r.type === 'restroom'),
    all_floors_accessible: m.hasElevator || m.floors.length === 1,
    notes: 'Added from its indoor map.'
  };
}

/**
 * Resolve the loaded maps against the outdoor buildings.
 * Returns { ready, entries: [{ buildingId, model, name, code }], forBuilding(id), extraBuildings }
 * `buildingId` is always the outdoor building id the rest of the app uses.
 */
export function resolveCatalog(models, buildings) {
  const chosen = new Map(); // outdoor id -> model
  const extra = [];
  for (const m of models) {
    if (isWithdrawnIndoorMap(m)) continue;
    if (!DEMO_MODE && (m.source === 'sample' || m.synthetic || (m.routingKind !== 'drawing' && m.status !== 'reviewed'))) continue;
    const b = matchBuilding(m, buildings);
    const id = b?.id ?? m.id;
    const cur = chosen.get(id);
    if (!cur || PRIORITY[m.source] > PRIORITY[cur.source]) chosen.set(id, m);
  }
  for (const [id, m] of chosen) {
    if (!buildings.some((b) => b.id === id)) {
      const b = buildingFromModel(m);
      if (b) extra.push(b);
      else chosen.delete(id);
    }
  }
  const all = [...buildings, ...extra];
  const entries = [...chosen].map(([buildingId, model]) => {
    const b = all.find((x) => x.id === buildingId);
    return { buildingId, model, name: b?.name ?? model.name, code: b?.code ?? buildingId.toUpperCase(), location: b?.location ?? model.centroid };
  });
  return {
    entries,
    forBuilding: (id) => (id ? chosen.get(id) ?? null : null),
    extraBuildings: extra
  };
}

/** Loaded maps, resolved against these outdoor buildings. Starts loading on first use. */
export function useIndoorCatalog(buildings) {
  loadIndoorCatalog();
  const s = useSyncExternalStore(subscribe, snapshot);
  return useMemo(() => ({ ...resolveCatalog(s.models, buildings), loading: s.loading }), [s, buildings]);
}

/** The resolved catalog for components deep in the tree (search box, indoor views). */
export const IndoorCatalogContext = createContext({ entries: [], forBuilding: () => null, extraBuildings: [], loading: true });
export const useIndoorEntries = () => useContext(IndoorCatalogContext);
