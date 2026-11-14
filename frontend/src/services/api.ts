/** Live Python API adapter. Errors never switch to mock data or another router. */
import type { Building, Closure, Place, RouteResponse, UserPreferences, UserReportPayload } from '../types';
import type { RouteBundle } from './routingEngine';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export async function apiJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, signal: AbortSignal.timeout(20000) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail?.message || `Request failed (${response.status})`);
  return data as T;
}
export interface SourceStatus {
  status: string; stale: boolean; active_count?: number; review_count?: number;
  counts?: {review?: number; imported?: number};
  source_status?: Record<string, {mode: string; observed_at: string; message: string}>;
}
export interface Health { nodes: number; edges: number; graph_source: string; synthetic: boolean }
export const getHealth = () => apiJSON<Health>('/health');
export const getBuildings = () => apiJSON<Building[]>('/buildings');
export const getNoticeStatus = () => apiJSON<SourceStatus>('/closures/status');
export const getUpcomingNotices = () => apiJSON<(Closure & {scheduled: boolean})[]>('/notices');
export const getExternalReports = () => apiJSON<{id: string; title: string; url: string; source_name: string; published_at: string | null; first_seen_at: string}[]>('/external-reports');
export const getExternalStatus = () => apiJSON<{sources: Record<string, {state: string; message: string}>}>('/external-reports/status');
let lastClosures: Closure[] = [];
export function activeClosures(list: Closure[], now = Date.now()) {
  return list.filter(c => c.status !== 'repaired' && Date.parse(c.start_time) <= now && (!c.end_time || Date.parse(c.end_time) > now));
}
export async function getClosures() {
  try {
    const [rows, status] = await Promise.all([apiJSON<Closure[]>('/closures'), getNoticeStatus()]);
    lastClosures = activeClosures(rows);
    return {closures: lastClosures, live: !status.stale, error: '', status};
  } catch (error) {
    lastClosures = activeClosures(lastClosures);
    return {closures: lastClosures, live: false, error: error instanceof Error ? error.message : 'Notice service unavailable', status: null};
  }
}
export const closuresSignature = (list: Closure[]) => JSON.stringify(list.map(c => [c.id, c.status, c.lat, c.lng, c.radius, c.start_time, c.end_time, c.last_confirmed]).sort());
export interface WireRoute {
  type: 'Feature'; geometry: {type: 'LineString'; coordinates: [number, number][]};
  properties: {total_distance: number; max_grade: number | null; warnings: string[]; directions: string[];
    uses_stairs: boolean; uses_elevator: boolean; start_snap_distance: number; end_snap_distance: number};
}
export function adaptRoute(route: WireRoute | null, ms: number): RouteResponse | null {
  if (!route) return null;
  if (route.type !== 'Feature' || route.geometry?.type !== 'LineString' || route.geometry.coordinates.length < 2) throw new Error('Invalid routing response');
  const p = route.properties;
  return {type: 'FeatureCollection',
    summary: {total_distance_m: p.total_distance, total_duration_s: Math.round(p.total_distance / 1),
      max_grade_pct: p.max_grade, avg_grade_pct: null, elevation_gain_m: null,
      is_step_free: !p.uses_stairs, stair_count: null, warnings: p.warnings, engine: 'remote', compute_ms: ms,
      elevators_used: p.uses_elevator ? ['mapped elevator connection'] : []},
    features: [{type: 'Feature', geometry: route.geometry,
      properties: {grade: p.max_grade, surface: 'unknown', is_step: p.uses_stairs, is_ramp: false,
        is_elevator: p.uses_elevator, segment_name: 'Mapped outdoor route'}}],
    steps: p.directions.map((instruction, i) => ({instruction, distance_m: 0, grade_pct: null,
      icon: i === p.directions.length - 1 ? 'destination' : 'straight'}))};
}
export interface PlanResult extends RouteBundle {engine: 'remote'; ms: number; notes: string[]; graphEdges: number}
export function closureContract(c: Closure) {
  return {lat: c.lat, lng: c.lng, radius: c.radius, type: c.type, status: c.status, source: c.source,
    asset_id: c.asset_id, building_id: c.building_id, floor_id: c.floor_id,
    start_time: c.start_time, end_time: c.end_time || null, last_confirmed: c.last_confirmed};
}
export async function planRoutes(origin: Place, destination: Place, prefs: UserPreferences, closures: Closure[]): Promise<PlanResult> {
  const t0 = performance.now();
  const result = await apiJSON<{accessible: WireRoute | null; standard: WireRoute | null;
    start_entrance: {id: string} | null; end_entrance: {id: string} | null;
    notes: string[]; failure?: string; graph_edges: number}>('/plan', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
      origin, destination, max_grade: prefs.max_grade_pct, no_stairs: prefs.no_stairs || prefs.wheelchair_required,
      need_automatic_door: prefs.need_automatic_door, closures: activeClosures(closures).map(closureContract)})});
  const ms = Math.round(performance.now() - t0);
  return {accessible: adaptRoute(result.accessible, ms), standard: adaptRoute(result.standard, ms),
    startEndpointId: result.start_entrance?.id, endEndpointId: result.end_entrance?.id,
    failure: result.failure || undefined, notes: result.notes, graphEdges: result.graph_edges, ms, engine: 'remote'};
}
export async function submitUserReport(report: UserReportPayload) {
  const {reporter_device_id: _device, ...payload} = report;
  return apiJSON<Closure>('/reports', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
}
export const confirmClosure = (id: string) => apiJSON<Closure>(`/reports/${encodeURIComponent(id)}/confirm`, {method: 'POST'});
