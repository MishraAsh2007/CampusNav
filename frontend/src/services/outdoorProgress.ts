import type {RouteResponse} from '../types';
import {getDistanceMeters} from './routingEngine';
import {routeStepPosition} from './routeSteps';

export interface Fix {lat: number; lng: number; accuracy: number; timestamp: number}
type Vertex = {lat: number; lng: number; d: number};
export interface RouteGeometry {
  segments: {a: Vertex; b: Vertex}[];
  stepStart: (number | null)[];
  total: number;
  end: Vertex | null;
}

/** Project onto actual segments only, without inventing bridges between features. */
export function locate(geo: RouteGeometry, p: {lat: number; lng: number}, from = 0, to = geo.total) {
  let best: {along: number; off: number} | null = null;
  const mLat = 111320, mLng = mLat * Math.cos(p.lat * Math.PI / 180);
  for (const {a, b} of geo.segments) {
    if (b.d < from || a.d > to) continue;
    const ax = (a.lng - p.lng) * mLng, ay = (a.lat - p.lat) * mLat;
    const dx = (b.lng - a.lng) * mLng, dy = (b.lat - a.lat) * mLat;
    const length = b.d - a.d;
    const low = length ? Math.max(0, (from - a.d) / length) : 0;
    const high = length ? Math.min(1, (to - a.d) / length) : 1;
    const t = Math.max(low, Math.min(high, dx * dx + dy * dy ? -(ax * dx + ay * dy) / (dx * dx + dy * dy) : 0));
    const off = Math.hypot(ax + t * dx, ay + t * dy);
    if (!best || off < best.off) best = {along: a.d + t * length, off};
  }
  return best;
}

/** A backend may return one GeoJSON feature for many maneuver instructions. */
export function routeGeometry(route: RouteResponse | null): RouteGeometry {
  const geo: RouteGeometry = {segments: [], stepStart: [], total: 0, end: null};
  for (const feature of route?.features ?? []) {
    let previous: Vertex | null = null;
    for (const [lng, lat] of feature.geometry.coordinates) {
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {previous = null; continue;}
      if (previous) geo.total += getDistanceMeters(previous.lat, previous.lng, lat, lng);
      const point: Vertex = {lat, lng, d: geo.total};
      if (previous) geo.segments.push({a: previous, b: point});
      previous = point;
      geo.end = point;
    }
  }
  let from = 0;
  geo.stepStart = (route?.steps ?? []).map((step, index) => {
    const point = routeStepPosition(route, index);
    if (!point) return null;
    const projected = locate(geo, point, from);
    if (!projected || projected.off > 20) return null;
    from = step.icon === 'destination' ? geo.total : projected.along;
    return from;
  });
  return geo;
}

export const usableFix = (fix: Fix | null, now = Date.now()): fix is Fix => !!fix
  && Number.isFinite(fix.lat) && Number.isFinite(fix.lng) && Math.abs(fix.lat) <= 90 && Math.abs(fix.lng) <= 180
  && Number.isFinite(fix.accuracy) && fix.accuracy > 0 && fix.accuracy <= 25
  && Number.isFinite(fix.timestamp) && now - fix.timestamp >= -2000 && now - fix.timestamp <= 15000;

/** Require a recent accurate fix, and proximity to the real endpoint for arrival. */
export function gpsProgress(geo: RouteGeometry, fix: Fix | null, active: number, now = Date.now()) {
  if (!usableFix(fix, now)) return null;
  const start = geo.stepStart[active];
  if (start == null) return null;
  const future = geo.stepStart.slice(active + 1, active + 4).filter((v): v is number => v != null);
  const where = locate(geo, fix, Math.max(0, start - 20), Math.min(geo.total, (future[future.length - 1] ?? start) + 20));
  if (!where) return null;
  const offRoute = where.off > 25 + fix.accuracy;
  let next = active;
  const last = geo.stepStart.length - 1;
  if (!offRoute) {
    while (next + 1 < last && geo.stepStart[next + 1] != null && geo.stepStart[next + 1]! <= where.along + 5) next++;
    if (geo.end && where.along >= geo.total - 8
        && getDistanceMeters(fix.lat, fix.lng, geo.end.lat, geo.end.lng) <= 10) next = last;
  }
  return {...where, next, offRoute};
}
