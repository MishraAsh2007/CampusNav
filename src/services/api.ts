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
import { readSessionCache, writeSessionCache } from './sessionCache';

const API_BASE: string = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const ROUTING_BASE: string = (import.meta.env.VITE_ROUTING_API_URL || API_BASE).replace(/\/$/, '');
const ROUTING_MODE: 'auto' | 'local' | 'remote' = (import.meta.env.VITE_ROUTING_ENGINE as 'auto' | 'local' | 'remote') || 'auto';

const CLOSURES_CACHE = `campusnav:v1:${API_BASE}:closures`;
const BUILDINGS_CACHE = `campusnav:v1:${API_BASE}:buildings`;

function isCachedClosure(value: unknown): value is Closure {
  const item = value as Closure | null;
  return !!item && typeof item.id === 'string' && typeof item.title === 'string'
    && Number.isFinite(item.lat) && Number.isFinite(item.lng)
    && typeof item.last_confirmed === 'string' && typeof item.start_time === 'string';
}

function isCachedBuilding(value: unknown): value is Building {
  const item = value as Building | null;
  return !!item && typeof item.id === 'string' && typeof item.name === 'string'
    && Number.isFinite(item.location?.lat) && Number.isFinite(item.location?.lng)
    && Array.isArray(item.entrances) && Array.isArray(item.elevators?.list)
    && item.entrances.every((entrance) => entrance && typeof entrance.name === 'string');
}

let store: Closure[] = readSessionCache(CLOSURES_CACHE, isCachedClosure)
  ?? INITIAL_CLOSURES.map((c) => ({ ...c }));
let buildingsStore: Building[] = readSessionCache(BUILDINGS_CACHE, isCachedBuilding) ?? UMASS_BUILDINGS;
let closureRevision = 0;

function saveClosures(closures: Closure[]): void {
  store = closures;
  closureRevision += 1;
  writeSessionCache(CLOSURES_CACHE, store);
}

export function getLocalBuildings(): Building[] {
  return [...buildingsStore];
}
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

export async function checkBackendHealth(): Promise<boolean> {
  const r = await fetchJson(`${API_BASE}/health`, {}, 900);
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
    last_confirmed: String(raw.last_updated ?? raw.last_confirmed ?? raw.timestamp ?? now),
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
  const revision = closureRevision;
  const r = await fetchClosuresRaw();
  if (r.ok && Array.isArray(r.data)) {
    // A GET started before a report was saved must not erase that new report.
    if (revision !== closureRevision) return { closures: [...store], live: true, ms: r.ms };
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
    saveClosures([...remote, ...localOnly]);
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

interface ApiBuilding {
  id: string;
  name: string;
  lat?: number;
  lng?: number;
  location?: Building['location'];
  entrances: (Partial<BuildingEntrance> & {
    lat: number;
    lng: number;
    name: string;
    hasAutoDoorOpener?: boolean | null;
    automatic_door?: boolean | null;
    isAccessibleToAllFloors?: boolean | null;
    IsKeyCardRequired?: boolean | null;
  })[];
  elevator_count?: number;
  elevators?: { location: string }[] | Building['elevators'];
  bathrooms?: { transfer_type: string | null }[];
}

export function normalizeBuilding(raw: ApiBuilding): Building {
  const local = UMASS_BUILDINGS.find((building) => building.id === raw.id);
  const entrances: BuildingEntrance[] = (raw.entrances ?? []).map((entrance, index) => ({
    ...entrance,
    id: entrance.id ?? `${raw.id}-e${index}`,
    step_free: entrance.step_free === true && entrance.IsKeyCardRequired !== true,
    door_type: entrance.door_type ?? (
      (entrance.hasAutoDoorOpener ?? entrance.automatic_door) === true ? 'push-button' : 'manual'
    ),
    has_ramp: entrance.has_ramp ?? false,
  }));
  const count = raw.elevator_count ?? (Array.isArray(raw.elevators) ? raw.elevators.length : 0);
  const elevators: Building['elevators'] = raw.elevators && !Array.isArray(raw.elevators)
    ? raw.elevators
    : {
        total_count: count,
        working_count: 0,
        floors_served: 'Unknown',
        status: count ? 'unknown' : 'none',
        list: [],
      };
  return {
    ...local,
    id: raw.id,
    name: raw.name,
    code: local?.code ?? raw.id,
    category: local?.category ?? 'academic',
    location: raw.location ?? { lat: Number(raw.lat), lng: Number(raw.lng) },
    entrances,
    step_free_entrances: entrances.filter((entrance) => entrance.step_free),
    door_type: entrances.some((entrance) => entrance.door_type !== 'manual') ? 'mixed' : 'manual',
    elevators,
    accessible_restrooms: raw.bathrooms?.some((bathroom) => bathroom.transfer_type != null) ?? false,
    all_floors_accessible: raw.entrances?.some((entrance) =>
      entrance.isAccessibleToAllFloors === true && entrance.IsKeyCardRequired !== true
    ) ?? false,
  };
}

export async function getBuildings(): Promise<Building[]> {
  let response = await fetchJson<ApiBuilding[]>(`${API_BASE}/buildings`, {}, 5000);
  if (response.status === 404) {
    response = await fetchJson<ApiBuilding[]>(`${API_BASE}/api/buildings`, {}, 5000);
  }
  if (response.ok && Array.isArray(response.data)) {
    buildingsStore = response.data.map(normalizeBuilding).filter((building) =>
      Number.isFinite(building.location.lat) && Number.isFinite(building.location.lng)
    );
    writeSessionCache(BUILDINGS_CACHE, buildingsStore);
  }
  return [...buildingsStore];
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
  buildings: Building[]
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

  if (ROUTING_MODE === 'remote' || (ROUTING_MODE === 'auto' && import.meta.env.VITE_ROUTING_API_URL)) {
    const start = o.accessible[0];
    const end = d.accessible.find((x) => x.id === local.endEndpointId) ?? d.accessible[0];
    const r = await fetchJson<{ step_free?: RouteResponse; shortest?: RouteResponse } & RouteResponse>(
      `${ROUTING_BASE}/api/route`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start: { lat: start.lat, lng: start.lng },
          end: { lat: end.lat, lng: end.lng },
          preferences: {
            ...prefs,
            wheelchair_preset: prefs.mobility_preset === 'power_wheelchair' ? 'power' : prefs.mobility_preset === 'manual_wheelchair' ? 'manual' : 'none'
          },
          closures: closures.filter((c) => c.status !== 'repaired')
        })
      },
      1800
    );
    const remote = r.data?.step_free ?? r.data;
    if (r.ok && validRemote(remote, end)) {
      return {
        ...local,
        accessible: { ...remote, summary: { ...remote.summary, engine: 'remote', compute_ms: r.ms } },
        standard: r.data?.shortest && validRemote(r.data.shortest, end) ? r.data.shortest : local.standard,
        engine: 'remote',
        ms: Math.round(performance.now() - t0),
        notes
      };
    }
  }
  return { ...local, engine: 'local', ms: Math.round(performance.now() - t0), notes };
}

// ---------- reports ----------

export interface ReportResult {
  closure: Closure;
  live: boolean;
  ms: number;
  /** Not sent: the backend has no endpoint for this (fixed reports, door openers). */
  browserOnly?: boolean;
}

/** Submit the report form and update the map only after the API accepts it. */
export async function postCommunityReport(report: UserReportPayload): Promise<Closure> {
  if (report.status === 'working' || !BACKEND_TYPES.includes(report.type)) {
    throw new Error('The backend currently accepts outages for elevators, ramps, paths, and construction.');
  }
  const response = await fetchJson<Record<string, unknown>>(
    `${API_BASE}/community-reports`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lat: report.lat, lng: report.lng, type: report.type,
        radius: report.type === 'elevator' ? 12 : 16,
      }),
    },
    10000,
  );
  if (!response.ok || !response.data?.id) {
    throw new Error(response.status
      ? `Report could not be saved (HTTP ${response.status}). Please try again.`
      : 'Could not confirm the report was saved. Check your connection before retrying.');
  }
  const closure = normalizeClosure(response.data);
  saveClosures([closure, ...store.filter((item) => item.id !== closure.id)]);
  return closure;
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
    saveClosures(store.map((c) => {
      const match =
        c.status !== 'repaired' &&
        c.type === report.type &&
        ((report.connector_id && c.connector_id === report.connector_id) || getDistanceMeters(c.lat, c.lng, report.lat, report.lng) < 15);
      if (!match) return c;
      override(c.id, { status: 'repaired', last_confirmed: now });
      return { ...c, status: 'repaired', last_confirmed: now };
    }));
  } else {
    saveClosures([local, ...store]);
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
    saveClosures([server, ...store.filter((c) => c.id !== local.id)]);
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
  saveClosures(store.map((c) => {
    if (c.id !== id) return c;
    const next = { ...c, last_confirmed: now, confirmations_count: c.confirmations_count + 1 };
    override(id, { last_confirmed: now, confirmations_count: next.confirmations_count });
    return next;
  }));
  confirmOnBackend(id);
  return [...store];
}

export function markClosureResolved(id: string): Closure[] {
  const now = new Date().toISOString();
  override(id, { status: 'repaired', last_confirmed: now });
  saveClosures(store.map((c) => (c.id === id ? { ...c, status: 'repaired', last_confirmed: now } : c)));
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
  saveClosures([notice, ...store.filter((x) => x.id !== notice.id)]);
  return [...store];
}

export function resetClosures(): Closure[] {
  overrides.clear();
  saveClosures(INITIAL_CLOSURES.map((c) => ({ ...c, last_confirmed: new Date(Date.now() - 3600_000).toISOString() })));
  return [...store];
}

export function getLocalClosures(): Closure[] {
  return [...store];
}
