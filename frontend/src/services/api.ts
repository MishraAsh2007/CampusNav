/**
 * Data + routing gateway.
 *
 * Live mode: talks to Role 4 (closures, buildings, reports) and Role 1 (routing) over the shared contracts.
 * Offline mode: the same calls are served from an in-memory store and the in-browser router, so the demo
 * never depends on Wi-Fi.
 */
import { Building, BuildingEntrance, Closure, Place, RouteResponse, UserPreferences, UserReportPayload } from '../types';
import { INITIAL_CLOSURES } from '../data/mockClosures';
import { routeSteps, type WireManeuver } from './routeSteps';
import { UMASS_BUILDINGS } from '../data/mockBuildings';
import { computeRoutes, Endpoint, getDistanceMeters, loadCampusGraph, RouteBundle } from './routingEngine';

const integrated = import.meta.env.VITE_CAMPUSNAV_INTEGRATED === '1';
const API_BASE: string = integrated ? '' : (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const ROUTING_BASE: string = integrated ? '' : (import.meta.env.VITE_ROUTING_API_URL || API_BASE).replace(/\/$/, '');
export const INDOOR_API_BASE = integrated ? '' : (import.meta.env.VITE_INDOOR_API_URL || ROUTING_BASE).replace(/\/$/, '');
export const DEMO_MODE = import.meta.env.VITE_CAMPUSNAV_DEMO === '1';
const ROUTING_MODE: 'auto' | 'local' | 'remote' = DEMO_MODE ? 'local'
  : (import.meta.env.VITE_ROUTING_ENGINE as 'auto' | 'local' | 'remote') || 'auto';

let store: Closure[] = INITIAL_CLOSURES.map((c) => ({ ...c }));
/** Edits made in this browser (fixed / confirmed) win over a backend that has not caught up yet. */
const overrides = new Map<string, Partial<Closure>>();

function override(id: string, patch: Partial<Closure>) {
  overrides.set(id, { ...(overrides.get(id) ?? {}), ...patch });
}

/** Barrier types backend/main.py accepts. */
const BACKEND_TYPES: string[] = ['elevator', 'ramp', 'path', 'construction'];

async function fetchJson<T>(url: string, init: RequestInit = {}, timeoutMs = 1500): Promise<{ ok: boolean; data?: T; ms: number; status?: number; message?: string; stale?: boolean }> {
  const t0 = performance.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });
    const ms = Math.round(performance.now() - t0);
    if (res.status === 204) return { ok: true, ms, status: res.status };
    const body = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, ms, status: res.status,
      message: typeof body?.detail === 'string' ? body.detail : body?.detail?.message };
    return { ok: true, data: body as T, ms, status: res.status, stale: res.headers.get('X-Closures-Stale') === 'true' };
  } catch {
    return { ok: false, ms: Math.round(performance.now() - t0) };
  } finally {
    clearTimeout(timer);
  }
}

export async function apiJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  const result = await fetchJson<T>(INDOOR_API_BASE + path, init, 15000);
  if (!result.ok || !result.data) throw new Error(result.message || 'The indoor routing service could not complete this request.');
  return result.data;
}
export function activeClosures(rows: Closure[]) {
  const now = Date.now();
  return rows.filter(c => c.status !== 'repaired' && (!c.start_time || Date.parse(c.start_time) <= now)
    && (!c.end_time || Date.parse(c.end_time) > now));
}
export function closureContract(c: Closure) {
  return {lat: c.lat, lng: c.lng, radius: c.radius, type: c.type === 'construction' ? 'path' : c.type,
    status: c.status, source: c.source, start_time: c.start_time, end_time: c.end_time || null,
    last_confirmed: c.last_confirmed, building_id: c.building_id, asset_id: c.asset_id, floor_id: c.floor_id};
}
export function simulatedClosures(rows: Closure[]) {
  return activeClosures(rows).filter(c => c.id.startsWith('local-') && BACKEND_TYPES.includes(c.type)).map(closureContract);
}

export interface SourceStatus {
  status: string; stale: boolean; counts?: {review?: number; imported?: number};
  source_status?: Record<string, {mode: string; observed_at: string; message: string}>;
}
export const getNoticeStatus = () => apiJSON<SourceStatus>('/closures/status');
export const getUpcomingNotices = () => apiJSON<(Closure & {scheduled: boolean})[]>('/notices');
export const getExternalReports = () => apiJSON<{id: string; title: string; url: string; source_name: string; published_at: string | null; first_seen_at: string}[]>('/external-reports');
export const getExternalStatus = () => apiJSON<{sources: Record<string, {state: string; message: string}>}>('/external-reports/status');

type RoutingPaths = Set<string>;
const discoveredRoutes = new Map<string, { expires: number; paths: Promise<RoutingPaths> }>();

export function routingPaths(base = ROUTING_BASE): Promise<RoutingPaths> {
  const cached = discoveredRoutes.get(base);
  if (cached && Date.now() < cached.expires) return cached.paths;
  const paths = (async () => {
    if (ROUTING_MODE === 'local') return new Set<string>();
    const health = await fetchJson<{ routes?: string[] }>(`${base}/health`);
    if (Array.isArray(health.data?.routes)) return new Set(health.data.routes);
    if (!health.status || health.status >= 500) return new Set<string>();
    const api = await fetchJson<{ paths?: Record<string, { get?: unknown; post?: unknown }> }>(`${base}/openapi.json`);
    return new Set(Object.entries(api.data?.paths ?? {})
      .filter(([path, operations]) => path === '/indoor/status' ? operations.get : operations.post)
      .map(([path]) => path));
  })();
  discoveredRoutes.set(base, { expires: Date.now() + 15000, paths });
  return paths;
}

const missingEndpoint = (result: {status?: number; message?: string}) =>
  result.status === 405 || (result.status === 404 && (!result.message || result.message === 'Not Found'));

// ---------- closures ----------

/** Role 4 stores raw report statuses; map them onto the closure contract. */
export function normalizeClosure(raw: Record<string, unknown>): Closure {
  const s = String(raw.status ?? 'closed');
  const status: Closure['status'] =
    s === 'repaired' || s === 'working' || s === 'fixed' ? 'repaired' : s === 'degraded' || s === 'blocked_partial' ? 'degraded' : 'closed';
  return {
    id: String(raw.id ?? raw._id ?? `closure-${Math.random().toString(36).slice(2)}`),
    lat: Number(raw.lat),
    lng: Number(raw.lng),
    radius: Number(raw.radius ?? 15),
    type: (raw.type as Closure['type']) ?? 'path',
    status,
    // Backend sources: official | community | demo. Role 3's file also uses reddit.
    source: raw.source === 'official' || raw.source === 'verified' ? (raw.source as Closure['source']) : 'community',
    title: String(raw.title ?? TYPE_TITLES[String(raw.type)] ?? 'Reported barrier'),
    description: raw.description ? String(raw.description) : raw.details ? String(raw.details) : undefined,
    building_name: raw.building_name ? String(raw.building_name) : undefined,
    connector_id: raw.connector_id || raw.asset_id ? String(raw.connector_id || raw.asset_id) : undefined,
    building_id: raw.building_id ? String(raw.building_id) : undefined,
    asset_id: raw.asset_id ? String(raw.asset_id) : undefined,
    floor_id: raw.floor_id ? String(raw.floor_id) : undefined,
    affects: raw.affects === 'road' || raw.affects === 'both' || raw.affects === 'pedestrians' ? raw.affects : undefined,
    road_name: raw.road_name ? String(raw.road_name) : undefined,
    bus_routes: Array.isArray(raw.bus_routes) ? raw.bus_routes.map(String) : undefined,
    source_url: raw.source_url ? String(raw.source_url) : undefined,
    reference: raw.reference ? String(raw.reference) : undefined,
    start_time: String(raw.start_time ?? raw.timestamp ?? ''),
    end_time: raw.end_time ? String(raw.end_time) : undefined,
    last_confirmed: String(raw.last_confirmed ?? raw.timestamp ?? ''),
    confirmations_count: Number(raw.confirmations_count ?? 1)
  };
}

export interface ClosuresResult {
  closures: Closure[];
  scheduled: Closure[] | null;
  live: boolean;
  received: boolean;
  ms: number;
}

/**
 * The team backend (backend/main.py) serves /closures: official notices and community reports in one
 * feed, told apart by `source`. The older contract used /api/*.
 * Try the backend's paths first and remember which one answered.
 */
let closuresPath: string | null = null;
async function fetchClosuresRaw() {
  for (const p of closuresPath ? [closuresPath] : ['/closures', '/api/closures']) {
    const r = await fetchJson<Record<string, unknown>[]>(`${API_BASE}${p}`, {}, 1200);
    if (r.ok) {
      closuresPath = p;
      return r;
    }
    if (closuresPath) return r;
  }
  return { ok: false, ms: 0 } as Awaited<ReturnType<typeof fetchJson<Record<string, unknown>[]>>>;
}

const TYPE_TITLES: Record<string, string> = {
  elevator: 'Elevator reported out of service',
  ramp: 'Ramp reported blocked',
  path: 'Path reported blocked',
  construction: 'Construction blocking the path',
  automatic_door: 'Automatic door reported broken'
};

export async function getClosures(): Promise<ClosuresResult> {
  if (DEMO_MODE) return { closures: [...store], scheduled: [], live: false, received: true, ms: 0 };
  const [r, notices] = await Promise.all([
    fetchClosuresRaw(),
    fetchJson<Record<string, unknown>[]>(`${API_BASE}/notices`),
  ]);
  const now = Date.now();
  const scheduled = notices.ok && Array.isArray(notices.data)
    ? notices.data.filter(row => row.scheduled === true).map(normalizeClosure)
      .filter(c => Date.parse(c.start_time) > now).sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time))
    : null;
  if (r.ok && Array.isArray(r.data)) {
    const remote = r.data
      .map((raw) => normalizeClosure(raw))
      .filter((c) => Number.isFinite(c.lat) && Number.isFinite(c.lng))
      .map((c) => {
        const o = overrides.get(c.id);
        // Only apply our edit while it is newer than what the server says
        return o && (!o.last_confirmed || o.last_confirmed > c.last_confirmed) ? { ...c, ...o } : c;
      });
    // Keep local-only reports the server has not echoed yet
    const localOnly = store.filter((c) => c.id.startsWith('local-') && !remote.some((x) => x.id === c.id));
    store = [...remote, ...localOnly];
    return { closures: [...store], scheduled, live: !r.stale, received: true, ms: r.ms };
  }
  return { closures: store.filter(c => !c.end_time || Date.parse(c.end_time) > now),
    scheduled, live: false, received: false, ms: r.ms };
}

export function closuresSignature(list: Closure[]): string {
  return list
    .map((c) => `${c.id}:${c.status}:${c.last_confirmed}:${c.confirmations_count}:${c.asset_id}:${c.floor_id}`)
    .sort()
    .join('|');
}

// ---------- buildings ----------

/**
 * A building as Role 4 stores it (backend/main.py `Building`): flat lat/lng, entrances with
 * hasAutoDoorOpener / IsKeyCardRequired / isAccessibleToAllFloors, elevators and bathrooms as arrays.
 * The older contract shape (location, door_type, step_free_entrances) is accepted too.
 */
export interface ApiBuilding {
  id: string;
  name: string;
  code?: string;
  category?: Building['category'];
  lat?: number;
  lng?: number;
  location?: { lat: number; lng: number };
  entrances?: (Partial<BuildingEntrance> & {
    name: string;
    lat: number;
    lng: number;
    step_free?: boolean | null;
    hasAutoDoorOpener?: boolean;
    automatic_door?: boolean;
    IsKeyCardRequired?: boolean;
    keycard_required?: boolean;
    isAccessibleToAllFloors?: boolean;
  })[];
  step_free_entrances?: BuildingEntrance[];
  elevator_count?: number;
  elevators?: Building['elevators'] | unknown[];
  bathrooms?: { transfer_type?: string | null }[];
  accessible_restrooms?: boolean;
  all_floors_accessible?: boolean;
}

const CATEGORIES: Building['category'][] = ['academic', 'student_services', 'dining', 'library', 'residential', 'recreation', 'administration'];

/** Backend building -> the map UI's Building. Same mapping as the frontend-backend branch. */
export function normalizeBuilding(raw: ApiBuilding): Building {
  const local = UMASS_BUILDINGS.find((b) => b.id === raw.id);
  const rawEntrances: NonNullable<ApiBuilding['entrances']> = raw.entrances ?? (raw.step_free_entrances ?? []).map((e) => ({ ...e, step_free: true }));
  const entrances: BuildingEntrance[] = rawEntrances.map((e, i) => ({
    ...(local?.entrances.find((x) => x.id === e.id) ?? {}),
    ...e,
    id: e.id ?? `${raw.id}-e${i}`,
    step_free: e.step_free === true && (e.keycard_required ?? e.IsKeyCardRequired) !== true,
    door_type: e.door_type ?? ((e.hasAutoDoorOpener ?? e.automatic_door) === true ? 'push-button' : 'manual'),
    has_ramp: e.has_ramp ?? false
  }));
  const count = raw.elevator_count ?? (Array.isArray(raw.elevators) ? raw.elevators.length : 0);
  const elevators: Building['elevators'] =
    raw.elevators && !Array.isArray(raw.elevators)
      ? raw.elevators
      : // Outages arrive as closures, so with no report an elevator counts as working
        local?.elevators ?? { total_count: count, working_count: count, floors_served: 'Unknown', status: count ? 'all_operational' : 'none', list: [] };
  const usable = raw.entrances || raw.step_free_entrances ? entrances : local?.entrances ?? [];
  return {
    ...(local ?? {}),
    id: raw.id,
    name: raw.name,
    code: raw.code ?? local?.code ?? raw.id.toUpperCase(),
    category: raw.category && CATEGORIES.includes(raw.category) ? raw.category : local?.category ?? 'academic',
    location: raw.location ?? { lat: Number(raw.lat), lng: Number(raw.lng) },
    entrances: usable,
    step_free_entrances: usable.filter((e) => e.step_free),
    door_type: usable.some((e) => e.door_type !== 'manual') ? 'mixed' : 'manual',
    elevators,
    accessible_restrooms: raw.accessible_restrooms ?? raw.bathrooms?.some((b) => b.transfer_type != null) ?? local?.accessible_restrooms ?? false,
    all_floors_accessible:
      raw.all_floors_accessible ??
      (raw.entrances?.some((e) => e.isAccessibleToAllFloors === true && e.IsKeyCardRequired !== true) || local?.all_floors_accessible || false)
  };
}

/**
 * Buildings from Role 4 (GET /buildings; older contract: /api/buildings). Anything added to the backend,
 * dorms included, shows up on the map with no frontend change. Built-in buildings the backend doesn't
 * have yet are kept so the offline demo still works.
 */
export async function getBuildings(): Promise<Building[]> {
  if (DEMO_MODE) return UMASS_BUILDINGS;
  let r = await fetchJson<ApiBuilding[]>(`${API_BASE}/buildings`, {}, 1500);
  if (!r.ok && r.status === 404) r = await fetchJson<ApiBuilding[]>(`${API_BASE}/api/buildings`, {}, 1500);
  if (r.ok && Array.isArray(r.data) && r.data.length) {
    const remote = r.data
      .map(normalizeBuilding)
      .filter((b) => Number.isFinite(b.location.lat) && Number.isFinite(b.location.lng));
    return [...remote, ...UMASS_BUILDINGS.filter(b => !remote.some(x => x.id === b.id || x.name === b.name))];
  }
  return UMASS_BUILDINGS;
}

// ---------- routing ----------

export interface EntranceChoice {
  endpoints: Endpoint[];
  note?: string;
}

/** Pick the entrances that actually work for this person today. */
export function usableEntrances(b: Building, prefs: UserPreferences, closures: Closure[]): EntranceChoice {
  const needsStepFree = prefs.wheelchair_required || prefs.no_stairs;
  const doorIssue = (en: BuildingEntrance) =>
    closures.find(
      (c) => c.type === 'automatic_door' && c.status !== 'repaired' && getDistanceMeters(c.lat, c.lng, en.lat, en.lng) <= Math.max(15, c.radius)
    );
  const toEp = (en: BuildingEntrance, penalty = 0): Endpoint => ({
    lat: en.lat,
    lng: en.lng,
    label: `${b.name}, ${en.name.charAt(0).toLowerCase()}${en.name.slice(1)}`,
    id: en.id,
    penalty
  });

  let list = b.entrances.filter((en) => !needsStepFree || en.step_free);
  if (prefs.need_automatic_door) {
    const powered = list.filter((en) => en.door_type !== 'manual' && doorIssue(en)?.status !== 'closed');
    if (powered.length) list = powered;
  }
  if (list.length) {
    return {
      endpoints: list.map((en) => {
        const issue = doorIssue(en);
        let p = 0;
        if (prefs.need_automatic_door && en.door_type === 'push-button') p += 10;
        if (issue) p += issue.status === 'closed' ? 120 : 40;
        return toEp(en, p);
      })
    };
  }
  if (b.entrances.length) {
    return { endpoints: b.entrances.map((en) => toEp(en)), note: `${b.name} has no step-free entrance on record.` };
  }
  return { endpoints: [{ lat: b.location.lat, lng: b.location.lng, label: b.name }] };
}

function endpointsFor(place: Place, buildings: Building[], prefs: UserPreferences, closures: Closure[]) {
  const b = place.building_id ? buildings.find((x) => x.id === place.building_id) : undefined;
  if (!b || !b.entrances.length) {
    const ep: Endpoint = { lat: place.lat, lng: place.lng, label: place.name };
    return { accessible: [ep], standard: [ep] };
  }
  const choice = usableEntrances(b, prefs, closures);
  const standard = b.entrances.map((en) => ({ lat: en.lat, lng: en.lng, label: `${b.name}, ${en.name.charAt(0).toLowerCase()}${en.name.slice(1)}`, id: en.id }));
  return { accessible: choice.endpoints, standard, note: choice.note };
}

export type JourneyEndpoint = {kind: 'drawing' | 'indoor'; building_id: string; node_id: string} |
  {kind: 'outdoor'; lat: number; lng: number};
export interface JourneyLeg {
  kind: 'indoor' | 'portal' | 'outdoor'; building_id?: string;
  indoor_node_id?: string; portal_id?: string; entrance_id?: string;
  route?: WireRoute; geometry?: {type: string; coordinates: number[] | number[][]};
  [key: string]: unknown;
}
export interface JourneyResult {
  legs: JourneyLeg[]; warnings: string[]; total_distance: number | null;
  known_distance_m?: number; physical_verification?: boolean; complete: boolean;
}
export interface PlanResult extends RouteBundle {
  engine: 'local' | 'remote';
  journey?: JourneyResult;
  ms: number;
  notes: string[];
  /** Where the accessible route reaches the destination building. The indoor route starts here. */
  arrivalPoint?: { entranceId: string | null; lat: number; lng: number; source: 'engine' | 'local'; portalId?: string; indoorNodeId?: string; label?: string };
}

/** What the person is heading to inside the destination building (from the room search). */
export interface IndoorIntent {
  origin?: JourneyEndpoint;
  destination?: JourneyEndpoint;
  acceptDrawing?: boolean;
  residentAccess?: boolean;
  /** Room or floor label, echoed by the engine */
  room?: string | null;
  /** The room is on another floor than the entrance: the engine then prefers doors near a working elevator */
  needsElevator?: boolean;
  reviewedBuildingId?: string;
  nodeId?: string;
}

type Point = {lat: number; lng: number};
type Entrance = Point & {id: string | null; name?: string};
type WireRoute = {
  type: 'Feature';
  geometry: {type: 'LineString'; coordinates: [number, number][]};
  properties: {total_distance: number; max_grade: number | null; uses_stairs: boolean;
    uses_elevator: boolean; warnings: string[]; directions: string[]; snapped_end: Point;
    maneuvers?: WireManeuver[]};
};
type OutdoorPlan = {
  accessible: WireRoute | null; standard: WireRoute | null;
  start_entrance: Entrance | null; end_entrance: Entrance | null;
  indoor_arrival?: {node_id: string; label: string; portal_id: string} | null;
  notes: string[]; failure?: string | null;
};
type ReviewedPlan = {
  status: string; message?: string; question?: string;
  arrival_context?: {building_id: string; portal_id: string};
  journey?: {legs: Array<{kind: string; route?: WireRoute}>; warnings: string[]};
};
type LegacyPlan = {
  step_free?: RouteResponse & {found?: boolean};
  shortest?: RouteResponse | null;
  origin?: {exit_id?: string};
  destination?: {entrance_id?: string; end?: Point; standard_end?: Point; warnings?: string[]};
};

function endsNear(route: RouteResponse | null | undefined, end: Point): route is RouteResponse {
  const features = route?.features ?? [];
  const coordinates = features[features.length - 1]?.geometry?.coordinates;
  const last = coordinates?.[coordinates.length - 1];
  return !!route?.summary && !!last && getDistanceMeters(last[1], last[0], end.lat, end.lng) < 120;
}

export function adaptWireRoute(route: WireRoute | null | undefined, ms: number): RouteResponse | null {
  if (!route || route.geometry?.coordinates.length < 2) return null;
  const p = route.properties;
  return {
    type: 'FeatureCollection',
    summary: {
      total_distance_m: p.total_distance, total_duration_s: Math.round(p.total_distance / 1.15),
      max_grade_pct: p.max_grade, avg_grade_pct: null, elevation_gain_m: null,
      is_step_free: !p.uses_stairs, stair_count: p.uses_stairs ? null : 0,
      warnings: p.warnings, engine: 'remote', compute_ms: ms,
    },
    features: [{type: 'Feature', geometry: route.geometry, properties: {
      grade: p.max_grade ?? 0, surface: 'unknown', is_step: false,
      is_ramp: false, is_elevator: false, segment_name: 'Mapped outdoor route',
    }}],
    steps: routeSteps(p),
  };
}

export const routingPreferences = (prefs: UserPreferences) => ({
  max_grade: prefs.max_grade_pct,
  no_stairs: prefs.no_stairs || prefs.wheelchair_required,
  need_automatic_door: prefs.need_automatic_door,
});

async function requestRemotePlan(
  origin: Place, destination: Place, prefs: UserPreferences, indoor: IndoorIntent, closures: Closure[],
  paths: RoutingPaths, indoorPaths: RoutingPaths
): Promise<PlanResult | null> {
  const post = (body: unknown): RequestInit => ({
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const place = ({lat, lng, name, building_id, entrance_id}: Place) => ({lat, lng, name, building_id, entrance_id});
  // Only explicit browser simulations may influence a demo route. The server uses its own live feed.
  const simulated = closures.filter(c => c.id.startsWith('local-') && c.status !== 'repaired'
      && BACKEND_TYPES.includes(c.type) && c.start_time && c.last_confirmed)
    .map(c => ({lat: c.lat, lng: c.lng, radius: c.radius, type: c.type === 'construction' ? 'path' : c.type,
      source: c.source, status: c.status, start_time: c.start_time, end_time: c.end_time ?? null,
      last_confirmed: c.last_confirmed, building_id: c.building_id, asset_id: c.asset_id, floor_id: c.floor_id}));
  const options = routingPreferences(prefs);
  const [walk, reviewed] = await Promise.all([
    fetchJson<OutdoorPlan>(`${ROUTING_BASE}/plan`, post({
      ...options, origin: place(origin), destination: place(destination), closures: simulated,
    }), 12000),
    indoor.reviewedBuildingId && indoorPaths.has('/navigation/plan') && indoorPaths.has('/navigation/arrive')
      ? fetchJson<ReviewedPlan>(`${INDOOR_API_BASE}/navigation/plan`, post({
      ...options,
      origin: origin.building_id ? {building_id: origin.building_id} : {outdoor: {lat: origin.lat, lng: origin.lng}},
      origin_entrance_id: origin.entrance_id,
      destination: {building_id: indoor.reviewedBuildingId, node_id: indoor.nodeId},
    }), 12000) : null,
  ]);
  if (reviewed && missingEndpoint(reviewed)) indoorPaths.delete('/navigation/plan');
  if (missingEndpoint(walk)) paths.delete('/plan');
  if ((!walk.status || missingEndpoint(walk)) && (!reviewed?.status || missingEndpoint(reviewed))) return null;
  const standard = adaptWireRoute(walk.data?.standard, walk.ms);
  if (reviewed && !missingEndpoint(reviewed)) {
    const body = reviewed.data;
    const outdoor = body?.journey?.legs.find(leg => leg.kind === 'outdoor')?.route;
    const point = outdoor?.properties.snapped_end;
    return {
      accessible: adaptWireRoute(outdoor, reviewed.ms), standard, engine: 'remote', ms: reviewed.ms,
      startEndpointId: walk.data?.start_entrance?.id ?? undefined,
      notes: body?.journey?.warnings ?? [],
      failure: body?.status === 'route_ready' ? undefined : body?.message || body?.question
        || reviewed.message || 'No reviewed route to this indoor destination.',
      arrivalPoint: body?.arrival_context && point
        ? {...point, entranceId: null, source: 'engine', portalId: body.arrival_context.portal_id} : undefined,
    };
  }
  const end = walk.data?.end_entrance;
  return {
    accessible: adaptWireRoute(walk.data?.accessible, walk.ms), standard, engine: 'remote', ms: walk.ms,
    startEndpointId: walk.data?.start_entrance?.id ?? undefined,
    endEndpointId: end?.id ?? undefined,
    arrivalPoint: end ? {lat: end.lat, lng: end.lng, entranceId: end.id, source: 'engine',
      indoorNodeId: walk.data?.indoor_arrival?.node_id, label: walk.data?.indoor_arrival?.label,
      portalId: walk.data?.indoor_arrival?.portal_id} : undefined,
    notes: walk.data?.notes ?? [],
    failure: walk.data?.failure || walk.message || (!walk.ok ? 'Routing service is unavailable.' : undefined),
  };
}

export async function planRoutes(
  origin: Place,
  destination: Place,
  prefs: UserPreferences,
  closures: Closure[],
  buildings: Building[],
  indoor: IndoorIntent = {}
): Promise<PlanResult> {
  const t0 = performance.now();
  if (!DEMO_MODE && (indoor.origin || indoor.destination)) {
    const result = await apiJSON<JourneyResult>('/journey', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        origin: indoor.origin || {kind: 'outdoor', lat: origin.lat, lng: origin.lng},
        destination: indoor.destination || {kind: 'outdoor', lat: destination.lat, lng: destination.lng},
        max_grade: prefs.max_grade_pct, no_stairs: prefs.no_stairs || prefs.wheelchair_required,
        need_automatic_door: prefs.need_automatic_door,
        accept_drawing_only: !!indoor.acceptDrawing, resident_access_confirmed: !!indoor.residentAccess,
        closures: simulatedClosures(closures),
      }),
    });
    const outside = result.legs.find(leg => leg.kind === 'outdoor')?.route || null;
    const portals = result.legs.filter(leg => leg.kind === 'portal');
    const destId = indoor.destination && indoor.destination.kind !== 'outdoor' ? indoor.destination.building_id : undefined;
    const arrival = destId ? [...portals].reverse().find(leg => leg.building_id === destId) : undefined;
    const coords = outside?.geometry.coordinates;
    const end = coords?.[coords.length - 1];
    const ms = Math.round(performance.now() - t0);
    return {accessible: adaptWireRoute(outside, ms), standard: null, ms, engine: 'remote',
      startEndpointId: portals[0]?.entrance_id,
      endEndpointId: arrival?.entrance_id, journey: result,
      notes: [...result.warnings, ...(result.total_distance === null ? ['Indoor distance is unknown. Map distance describes the outdoor portion only.'] : [])],
      arrivalPoint: end && arrival ? {entranceId: arrival.entrance_id || null,
        indoorNodeId: arrival.indoor_node_id, label: String(arrival.entrance_label || ''), lat: end[1], lng: end[0], source: 'engine'} : undefined};
  }

  const paths = await routingPaths();
  if (ROUTING_MODE !== 'local') {
    const indoorPaths = indoor.reviewedBuildingId ? await routingPaths(INDOOR_API_BASE) : paths;
    const remote = paths.has('/plan') ? await requestRemotePlan(origin, destination, prefs, indoor, closures, paths, indoorPaths) : null;
    if (remote) return remote;
  }
  const G = await loadCampusGraph();
  const o = endpointsFor(origin, buildings, prefs, closures);
  const d = endpointsFor(destination, buildings, prefs, closures);
  const landmarks = buildings.map((b) => ({ name: b.code === 'LIB' ? 'the library' : `the ${b.name}`.replace('the W.E.B.', 'W.E.B.'), lat: b.location.lat, lng: b.location.lng }));

  const local = computeRoutes(G, {
    starts: o.accessible,
    ends: d.accessible,
    standardStarts: o.standard,
    standardEnds: d.standard,
    originLabel: origin.name,
    destLabel: destination.name,
    prefs,
    closures,
    landmarks
  });
  const notes = [o.note, d.note].filter(Boolean) as string[];
  if (paths.has('/api/route')) {
    const start = o.accessible[0];
    const end = d.accessible.find(entry => entry.id === local.endEndpointId) ?? d.accessible[0];
    const from = buildings.find(b => b.id === origin.building_id);
    const to = buildings.find(b => b.id === destination.building_id);
    const result = await fetchJson<LegacyPlan>(`${ROUTING_BASE}/api/route`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        ...(from?.entrances.length ? {origin: {building: from, needs_elevator: false}} : {start: {lat: start.lat, lng: start.lng}}),
        ...(to?.entrances.length ? {destination: {building: to, needs_elevator: !!indoor.needsElevator, room: indoor.room ?? null}}
          : {end: {lat: end.lat, lng: end.lng}}),
        preferences: {...prefs, wheelchair_preset: prefs.mobility_preset === 'power_wheelchair' ? 'power'
          : prefs.mobility_preset === 'manual_wheelchair' ? 'manual' : 'none'},
        closures: closures.filter(c => c.status !== 'repaired'),
      }),
    }, 4500);
    if (missingEndpoint(result)) paths.delete('/api/route');
    const reply = result.data;
    const arrival = reply?.destination;
    const accessible = reply?.step_free;
    const noRoute = accessible?.found === false;
    const route = !noRoute && endsNear(accessible, arrival?.end ?? end)
      ? {...accessible, summary: {...accessible.summary, engine: 'remote' as const, compute_ms: result.ms}} : null;
    if (noRoute || route) {
      return {
        ...local, engine: 'remote', ms: result.ms, notes: [...notes, ...(arrival?.warnings ?? [])],
        accessible: route,
        standard: endsNear(reply?.shortest, arrival?.standard_end ?? end) ? reply.shortest : local.standard,
        failure: noRoute ? accessible?.summary?.warnings?.[0] ?? 'No step-free route matches your needs.' : undefined,
        startEndpointId: reply?.origin?.exit_id ?? local.startEndpointId,
        endEndpointId: arrival?.entrance_id ?? local.endEndpointId,
        arrivalPoint: !noRoute && arrival?.end
          ? {...arrival.end, entranceId: arrival.entrance_id ?? null, source: 'engine'} : undefined,
      };
    }
  }
  if (ROUTING_MODE === 'remote') return {
    accessible: null, standard: null, notes: [], engine: 'remote',
    failure: 'Routing service is unavailable. Start the integrated CampusNav server with start-server.cmd.',
    ms: Math.round(performance.now() - t0),
  };
  // The in-browser graph covers central campus only ([south, west, north, east], ~150 m margin)
  const bb = G.meta.bbox;
  const outside = (p: Place) => !!bb && (p.lat < bb[0] - 0.0014 || p.lat > bb[2] + 0.0014 || p.lng < bb[1] - 0.0018 || p.lng > bb[3] + 0.0018);
  const offMap = [origin, destination].filter(outside);

  if (offMap.length) {
    // Snapping to the nearest mapped path would draw a misleading route. Say what is needed instead.
    return {
      ...local,
      accessible: null,
      standard: null,
      failure: `${offMap.map((p) => p.name).join(' and ')} ${offMap.length > 1 ? 'are' : 'is'} outside the in-browser router's map, which covers central campus. Start the main routing engine (see README) to route there.`,
      engine: 'local',
      ms: Math.round(performance.now() - t0),
      notes
    };
  }
  const localEnd = d.accessible.find((x) => x.id === local.endEndpointId);
  return {
    ...local,
    engine: 'local',
    ms: Math.round(performance.now() - t0),
    notes,
    arrivalPoint: localEnd ? { entranceId: localEnd.id ?? null, lat: localEnd.lat, lng: localEnd.lng, source: 'local' } : undefined
  };
}

// ---------- reports ----------

export interface ReportResult {
  closure: Closure;
  live: boolean;
  ms: number;
  /** Not sent: the backend has no endpoint for this (fixed reports, door openers). */
  browserOnly?: boolean;
}

export async function submitUserReport(report: UserReportPayload): Promise<ReportResult> {
  const now = new Date().toISOString();
  const status: Closure['status'] = report.status === 'working' ? 'repaired' : report.status === 'blocked' && report.type === 'path' ? 'degraded' : 'closed';
  const local: Closure = {
    id: `local-${Date.now()}`,
    lat: report.lat,
    lng: report.lng,
    radius: report.type === 'elevator' || report.type === 'automatic_door' ? 12 : 16,
    type: report.type,
    status,
    source: 'community',
    title: report.title,
    description: report.description,
    connector_id: report.connector_id,
    start_time: now,
    last_confirmed: now,
    confirmations_count: 1
  };

  const browserOnly = ROUTING_MODE === 'local' || report.reporter_device_id === 'judge-demo'
    || !BACKEND_TYPES.includes(report.type);
  if (status === 'repaired') {
    const demo = report.reporter_device_id === 'judge-demo';
    const matches = store.filter(c => (c.source === 'community' || demo && c.id.startsWith('local-'))
      && c.status !== 'repaired' && c.type === report.type
      && (report.connector_id ? c.connector_id === report.connector_id
        : getDistanceMeters(c.lat, c.lng, report.lat, report.lng) < 15)
      && (!browserOnly || c.id.startsWith('local-')));
    const t0 = performance.now();
    if (demo) {
      const ids = new Set(matches.map(c => c.id));
      store = store.filter(c => !ids.has(c.id));
    } else {
      for (const match of matches) await markClosureResolved(match.id);
    }
    return {closure: local, live: !browserOnly && matches.length > 0, ms: Math.round(performance.now() - t0),
      browserOnly: browserOnly || matches.length === 0};
  }
  if (browserOnly) {
    store = [local, ...store];
    return {closure: local, live: false, ms: 0, browserOnly: true};
  }
  const r = await fetchJson<Record<string, unknown>>(`${API_BASE}/reports`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
      lat: report.lat, lng: report.lng, type: report.type, status: report.status,
      timestamp: report.timestamp, title: report.title, description: report.description,
      building_id: report.building_id, connector_id: report.connector_id,
    }),
  }, 10000);
  if (!r.ok || !r.data?.id) throw new Error(r.message || 'The report could not be saved.');
  const saved = normalizeClosure(r.data);
  store = [saved, ...store.filter(c => c.id !== saved.id)];
  return {closure: saved, live: true, ms: r.ms};
}

export async function confirmClosure(id: string): Promise<Closure[]> {
  const current = store.find(c => c.id === id && c.source === 'community');
  if (!current) return [...store];
  if (id.startsWith('local-') || ROUTING_MODE === 'local') {
    const patch = {last_confirmed: new Date().toISOString(), confirmations_count: current.confirmations_count + 1};
    override(id, patch);
    store = store.map(c => c.id === id ? {...c, ...patch} : c);
    return [...store];
  }
  const r = await fetchJson<Record<string, unknown>>(
    `${API_BASE}/reports/${encodeURIComponent(id)}/confirm`, {method: 'POST'}, 10000,
  );
  if (!r.ok || !r.data) throw new Error(r.message || 'The report could not be confirmed.');
  const saved = normalizeClosure(r.data);
  store = store.map(c => c.id === saved.id ? saved : c);
  return [...store];
}

export async function markClosureResolved(id: string): Promise<Closure[]> {
  const current = store.find(c => c.id === id && c.source === 'community');
  if (!current) return [...store];
  if (!id.startsWith('local-') && ROUTING_MODE !== 'local') {
    const r = await fetchJson(`${API_BASE}/api/data/community-reports/${encodeURIComponent(id)}`, {method: 'DELETE'}, 10000);
    if (!r.ok && r.status !== 404) throw new Error(r.message || 'The report could not be resolved.');
  }
  overrides.delete(id);
  store = store.filter(c => c.id !== id);
  return [...store];
}

/**
 * Adds an official notice in this browser only (judge demo). Real official notices come from Role 3's
 * pipeline via the backend; the admin key they need must never ship in frontend code.
 */
export function addLocalOfficialNotice(c: Closure): Closure[] {
  const now = new Date().toISOString();
  const notice: Closure = { ...c, id: `local-${c.id}`, start_time: now, last_confirmed: now, status: 'closed' };
  overrides.delete(notice.id);
  store = [notice, ...store.filter((x) => x.id !== notice.id)];
  return [...store];
}

export function resetClosures(): Closure[] {
  overrides.clear();
  store = ROUTING_MODE === 'local' ? INITIAL_CLOSURES.map(c => ({...c})) : store.filter(c => !c.id.startsWith('local-'));
  return [...store];
}

export function getLocalClosures(): Closure[] {
  return [...store];
}
