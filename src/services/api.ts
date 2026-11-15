/**
 * Data + routing gateway.
 *
 * Live mode: talks to Role 4 (closures, buildings, reports) and Role 1 (routing) over the shared contracts.
 * Offline mode: the same calls are served from an in-memory store and the in-browser router, so the demo
 * never depends on Wi-Fi.
 */
import { Building, BuildingEntrance, Closure, Place, RouteResponse, UserPreferences, UserReportPayload } from '../types';
import { INITIAL_CLOSURES } from '../data/mockClosures';
import { UMASS_BUILDINGS } from '../data/mockBuildings';
import { computeRoutes, Endpoint, getDistanceMeters, loadCampusGraph, RouteBundle } from './routingEngine';

const API_BASE: string = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const ROUTING_BASE: string = (import.meta.env.VITE_ROUTING_API_URL || API_BASE).replace(/\/$/, '');
const ROUTING_MODE: 'auto' | 'local' | 'remote' = (import.meta.env.VITE_ROUTING_ENGINE as 'auto' | 'local' | 'remote') || 'auto';

let store: Closure[] = INITIAL_CLOSURES.map((c) => ({ ...c }));
let backendUp = false;
/** Edits made in this browser (fixed / confirmed) win over a backend that has not caught up yet. */
const overrides = new Map<string, Partial<Closure>>();

function override(id: string, patch: Partial<Closure>) {
  overrides.set(id, { ...(overrides.get(id) ?? {}), ...patch });
}

/** Community report endpoint; falls back to '/reports' (backend on main) on the first 404. */
let reportsPath: '/community-reports' | '/reports' = '/community-reports';

/** Barrier types backend/main.py accepts. */
const BACKEND_TYPES: string[] = ['elevator', 'ramp', 'path', 'construction'];
/** Title/description/connector for reports this browser sent (the backend stores location only). */
const reportMeta = new Map<string, Partial<Closure>>();

async function fetchJson<T>(url: string, init: RequestInit = {}, timeoutMs = 1500): Promise<{ ok: boolean; data?: T; ms: number; status?: number }> {
  const t0 = performance.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal });
    const ms = Math.round(performance.now() - t0);
    if (!res.ok) return { ok: false, ms, status: res.status };
    return { ok: true, data: (await res.json()) as T, ms, status: res.status };
  } catch {
    return { ok: false, ms: Math.round(performance.now() - t0) };
  } finally {
    clearTimeout(timer);
  }
}

/** Is the routing engine answering? Same as backendUp unless VITE_ROUTING_API_URL points elsewhere. */
let routingUp = false;

export async function checkBackendHealth(): Promise<boolean> {
  const separateEngine = ROUTING_BASE !== API_BASE;
  const [r, engine] = await Promise.all([
    fetchJson(`${API_BASE}/health`, {}, 900),
    separateEngine ? fetchJson(`${ROUTING_BASE}/health`, {}, 900) : Promise.resolve(null)
  ]);
  backendUp = r.ok;
  routingUp = engine ? engine.ok : r.ok;
  return r.ok;
}

// ---------- closures ----------

/** Role 4 stores raw report statuses; map them onto the closure contract. */
export function normalizeClosure(raw: Record<string, unknown>): Closure {
  const s = String(raw.status ?? 'closed');
  const status: Closure['status'] =
    s === 'repaired' || s === 'working' || s === 'fixed' ? 'repaired' : s === 'degraded' || s === 'blocked_partial' ? 'degraded' : 'closed';
  const now = new Date().toISOString();
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
    connector_id: raw.connector_id ? String(raw.connector_id) : undefined,
    affects: raw.affects === 'road' || raw.affects === 'both' || raw.affects === 'pedestrians' ? raw.affects : undefined,
    road_name: raw.road_name ? String(raw.road_name) : undefined,
    bus_routes: Array.isArray(raw.bus_routes) ? raw.bus_routes.map(String) : undefined,
    source_url: raw.source_url ? String(raw.source_url) : undefined,
    reference: raw.reference ? String(raw.reference) : undefined,
    start_time: String(raw.start_time ?? raw.timestamp ?? now),
    end_time: raw.end_time ? String(raw.end_time) : undefined,
    last_confirmed: String(raw.last_confirmed ?? raw.timestamp ?? now),
    confirmations_count: Number(raw.confirmations_count ?? 1)
  };
}

export interface ClosuresResult {
  closures: Closure[];
  live: boolean;
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
  const r = await fetchClosuresRaw();
  if (r.ok && Array.isArray(r.data)) {
    const remote = r.data
      .map((raw) => normalizeClosure({ ...raw, ...(reportMeta.get(String(raw.id)) ?? {}) }))
      .filter((c) => Number.isFinite(c.lat) && Number.isFinite(c.lng))
      .map((c) => {
        const o = overrides.get(c.id);
        // Only apply our edit while it is newer than what the server says
        return o && (!o.last_confirmed || o.last_confirmed > c.last_confirmed) ? { ...c, ...o } : c;
      });
    // Keep local-only reports the server has not echoed yet
    const localOnly = store.filter((c) => c.id.startsWith('local-') && !remote.some((x) => x.id === c.id));
    store = [...remote, ...localOnly];
    return { closures: [...store], live: true, ms: r.ms };
  }
  return { closures: [...store], live: false, ms: r.ms };
}

export function closuresSignature(list: Closure[]): string {
  return list
    .map((c) => `${c.id}:${c.status}:${c.last_confirmed}:${c.confirmations_count}`)
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
    step_free: e.step_free === true && e.IsKeyCardRequired !== true,
    door_type: e.door_type ?? ((e.hasAutoDoorOpener ?? e.automatic_door) === true ? 'push-button' : 'manual'),
    has_ramp: e.has_ramp ?? false
  }));
  const count = raw.elevator_count ?? (Array.isArray(raw.elevators) ? raw.elevators.length : 0);
  const elevators: Building['elevators'] =
    raw.elevators && !Array.isArray(raw.elevators)
      ? raw.elevators
      : // Outages arrive as closures, so with no report an elevator counts as working
        local?.elevators ?? { total_count: count, working_count: count, floors_served: 'Unknown', status: count ? 'all_operational' : 'none', list: [] };
  const usable = entrances.length ? entrances : local?.entrances ?? [];
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
  let r = await fetchJson<ApiBuilding[]>(`${API_BASE}/buildings`, {}, 1500);
  if (!r.ok && r.status === 404) r = await fetchJson<ApiBuilding[]>(`${API_BASE}/api/buildings`, {}, 1500);
  if (r.ok && Array.isArray(r.data) && r.data.length) {
    const remote = r.data
      .map(normalizeBuilding)
      .filter((b) => Number.isFinite(b.location.lat) && Number.isFinite(b.location.lng));
    return [...remote, ...UMASS_BUILDINGS.filter((b) => !remote.some((x) => x.id === b.id))];
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

export interface PlanResult extends RouteBundle {
  engine: 'local' | 'remote';
  ms: number;
  notes: string[];
  /** Where the accessible route reaches the destination building. The indoor route starts here. */
  arrivalPoint?: { entranceId: string | null; lat: number; lng: number; source: 'engine' | 'local' };
}

/** What the person is heading to inside the destination building (from the room search). */
export interface IndoorIntent {
  /** Room or floor label, echoed by the engine */
  room?: string | null;
  /** The room is on another floor than the entrance: the engine then prefers doors near a working elevator */
  needsElevator?: boolean;
}

/** Response of the Role 1 engine's POST /api/route (routing/app/frontend_api.py). */
type RemoteRoute = RouteResponse & { found?: boolean };
interface RemotePlan {
  step_free?: RemoteRoute;
  shortest?: RemoteRoute | null;
  origin?: { exit_id?: string | null; standard_exit_id?: string | null } | null;
  destination?: {
    entrance_id?: string | null;
    end?: { lat: number; lng: number };
    standard_entrance_id?: string | null;
    standard_end?: { lat: number; lng: number };
    warnings?: string[];
  } | null;
}
function validRemote(r: unknown, end: { lat: number; lng: number }): r is RouteResponse {
  const x = r as RouteResponse | undefined;
  const coords = x?.features?.[0]?.geometry?.coordinates;
  if (!x?.summary || !Array.isArray(coords) || coords.length < 2) return false;
  const lastFeature = x.features[x.features.length - 1].geometry.coordinates;
  const [lng, lat] = lastFeature[lastFeature.length - 1];
  return getDistanceMeters(lat, lng, end.lat, end.lng) < 120;
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
  // The in-browser graph covers central campus only ([south, west, north, east], ~150 m margin)
  const bb = G.meta.bbox;
  const outside = (p: Place) => !!bb && (p.lat < bb[0] - 0.0014 || p.lat > bb[2] + 0.0014 || p.lng < bb[1] - 0.0018 || p.lng > bb[3] + 0.0018);
  const offMap = [origin, destination].filter(outside);

  if (ROUTING_MODE !== 'local' && (routingUp || ROUTING_MODE === 'remote')) {
    const start = o.accessible[0];
    const end = d.accessible.find((x) => x.id === local.endEndpointId) ?? d.accessible[0];
    // Let the Role 1 engine choose the destination entrance: it sees live elevator and closure status.
    const destBuilding = destination.building_id ? buildings.find((x) => x.id === destination.building_id) : undefined;
    const target = destBuilding && destBuilding.entrances.length
      ? { destination: { building: destBuilding, needs_elevator: !!indoor.needsElevator, room: indoor.room ?? null } }
      : { end: { lat: end.lat, lng: end.lng } };
    // Same for the start building: the engine picks the exit by the cost of the whole trip.
    const startBuilding = origin.building_id ? buildings.find((x) => x.id === origin.building_id) : undefined;
    const from = startBuilding && startBuilding.entrances.length
      ? { origin: { building: startBuilding, needs_elevator: false } }
      : { start: { lat: start.lat, lng: start.lng } };
    const r = await fetchJson<RemotePlan>(
      `${ROUTING_BASE}/api/route`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...from,
          ...target,
          preferences: {
            ...prefs,
            wheelchair_preset: prefs.mobility_preset === 'power_wheelchair' ? 'power' : prefs.mobility_preset === 'manual_wheelchair' ? 'manual' : 'none'
          },
          closures: closures.filter((c) => c.status !== 'repaired')
        })
      },
      1800
    );
    if (r.ok && r.data) {
      const plan = r.data.destination;
      // Check each route against the entrance the engine chose for it, not the one guessed here.
      const accEnd = plan?.end ?? end;
      const stdEnd = plan?.standard_end ?? end;
      const remote = r.data.step_free;
      // Read these before validRemote() narrows `remote`.
      const noRoute = remote?.found === false;
      const why = remote?.summary?.warnings?.[0] ?? 'No step-free route matches your needs.';
      const base = {
        ...local,
        standard: r.data.shortest && validRemote(r.data.shortest, stdEnd) ? r.data.shortest : local.standard,
        endEndpointId: plan?.entrance_id ?? local.endEndpointId,
        startEndpointId: r.data.origin?.exit_id ?? local.startEndpointId,
        engine: 'remote' as const,
        ms: Math.round(performance.now() - t0)
      };
      if (remote && validRemote(remote, accEnd)) {
        const second = local.accessible
          ? []
          : ['The in-browser router found no step-free route here, but the main engine did. Check slopes as you go.'];
        return {
          ...base,
          arrivalPoint: { entranceId: plan?.entrance_id ?? null, lat: accEnd.lat, lng: accEnd.lng, source: plan?.end ? 'engine' : 'local' },
          accessible: { ...remote, summary: { ...remote.summary, engine: 'remote', compute_ms: r.ms } },
          failure: undefined,
          notes: [...notes, ...second]
        };
      }
      if (noRoute) {
        // A real "no route" answer: show it instead of quietly swapping in the in-browser router's route.
        const second = local.accessible
          ? ' (The in-browser router, which uses different elevation data, did find a step-free route. It is not shown; it may cross a slope the main engine rejected.)'
          : '';
        return { ...base, accessible: null, failure: why + second, notes };
      }
    }
    // Engine unreachable, errored, or sent something unusable: fall back to the in-browser router.
  }
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

  // A "fixed" report for a known outage resolves it instead of adding a new pin
  if (status === 'repaired') {
    store = store.map((c) => {
      const match =
        c.status !== 'repaired' &&
        c.type === report.type &&
        ((report.connector_id && c.connector_id === report.connector_id) || getDistanceMeters(c.lat, c.lng, report.lat, report.lng) < 15);
      if (!match) return c;
      override(c.id, { status: 'repaired', last_confirmed: now });
      return { ...c, status: 'repaired', last_confirmed: now };
    });
  } else {
    store = [local, ...store];
  }

  // The team backend has no "fixed" endpoint and no automatic_door type: keep those in this browser.
  if (status === 'repaired' || !BACKEND_TYPES.includes(report.type)) {
    return { closure: local, live: false, ms: 0, browserOnly: true };
  }

  // backend/main.py accepts exactly {lat, lng, type, radius} and returns the closure (201).
  // Newer backend: POST /community-reports. Backend on main: POST /reports.
  const minimal = JSON.stringify({ lat: report.lat, lng: report.lng, type: report.type, radius: local.radius });
  let r = await fetchJson<Record<string, unknown>>(
    `${API_BASE}${reportsPath}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: minimal },
    1500
  );
  if (!r.ok && (r.status === 404 || r.status === 405) && reportsPath === '/community-reports') {
    r = await fetchJson<Record<string, unknown>>(`${API_BASE}/reports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: minimal }, 1500);
    if (r.ok) reportsPath = '/reports';
  }
  let serverRaw: Record<string, unknown> | undefined = r.ok ? r.data : undefined;
  if (!r.ok && (r.status === 404 || r.status === 405)) {
    // Older contract: POST /api/report returning { closure }
    r = await fetchJson<Record<string, unknown>>(
      `${API_BASE}/api/report`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) },
      1500
    );
    serverRaw = r.ok ? ((r.data?.closure as Record<string, unknown>) ?? undefined) : undefined;
  }
  if (serverRaw?.id) {
    const id = String(serverRaw.id);
    // The backend stores location only; remember the human details for this report
    reportMeta.set(id, { title: report.title, description: report.description || undefined, connector_id: report.connector_id });
    const server = normalizeClosure({ ...serverRaw, ...reportMeta.get(id) });
    store = [server, ...store.filter((c) => c.id !== local.id)];
    return { closure: server, live: true, ms: r.ms };
  }
  return { closure: local, live: r.ok, ms: r.ms };
}

/** Tell the backend a community report is still accurate (renews its 48 h expiry). Fire and forget. */
function confirmOnBackend(id: string) {
  if (id.startsWith('local-')) return;
  void fetchJson(`${API_BASE}${reportsPath}/${encodeURIComponent(id)}/confirm`, { method: 'POST' }, 1500);
}

/** "Still broken" tap: bump freshness and confirmation count. */
export function confirmClosure(id: string): Closure[] {
  const now = new Date().toISOString();
  store = store.map((c) => {
    if (c.id !== id) return c;
    const next = { ...c, last_confirmed: now, confirmations_count: c.confirmations_count + 1 };
    override(id, { last_confirmed: now, confirmations_count: next.confirmations_count });
    return next;
  });
  confirmOnBackend(id);
  return [...store];
}

export function markClosureResolved(id: string): Closure[] {
  const now = new Date().toISOString();
  override(id, { status: 'repaired', last_confirmed: now });
  store = store.map((c) => (c.id === id ? { ...c, status: 'repaired', last_confirmed: now } : c));
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
  store = INITIAL_CLOSURES.map((c) => ({ ...c, last_confirmed: new Date(Date.now() - 3600_000).toISOString() }));
  return [...store];
}

export function getLocalClosures(): Closure[] {
  return [...store];
}
