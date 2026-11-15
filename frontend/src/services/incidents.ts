/**
 * Turns raw closures (official Facilities notices + community reports) into ranked incidents.
 *
 * One physical problem is often reported twice: Facilities posts a notice and students report it too.
 * Those are merged into one incident, and an incident confirmed by both is ranked highest.
 */
import type { Closure } from '../types';
import { getDistanceMeters } from './routingEngine';

export type Severity = 'high' | 'official' | 'likely' | 'reported';

export const SEVERITY_ORDER: Record<Severity, number> = { high: 0, official: 1, likely: 2, reported: 3 };

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: 'High alert',
  official: 'Facilities notice',
  likely: 'Likely',
  reported: 'Reported'
};

export const SEVERITY_HINT: Record<Severity, string> = {
  high: 'Confirmed by UMass Facilities and students',
  official: 'Posted by UMass Facilities',
  likely: 'Confirmed by 3 or more students',
  reported: 'Reported by a student, not yet confirmed'
};

export interface BusImpact {
  routes: string[];
  roads: string[];
  /** true when the notice says the road itself is closed; false when it only sits on a bus road */
  certain: boolean;
}

export interface Incident {
  id: string;
  severity: Severity;
  /** The closure shown first: the official notice when there is one */
  primary: Closure;
  official: Closure[];
  community: Closure[];
  all: Closure[];
  confirmations: number;
  lastConfirmed: string;
  isRoad: boolean;
  bus: BusImpact | null;
}

// ---------- bus routes (public/data/busRoutes.json, built from OpenStreetMap) ----------

export interface BusRouteData {
  routes: { ref: string; name: string; operator: string }[];
  segments: { name: string | null; refs: string[]; path: [number, number][] }[];
}

let busPromise: Promise<BusRouteData | null> | null = null;

export function loadBusRoutes(): Promise<BusRouteData | null> {
  if (!busPromise) {
    busPromise = fetch(`${import.meta.env.BASE_URL}data/busRoutes.json`)
      .then((r) => (r.ok ? (r.json() as Promise<BusRouteData>) : null))
      .catch(() => null);
  }
  return busPromise;
}

function pointToSegmentM(plat: number, plng: number, a: [number, number], b: [number, number]): number {
  const kx = 111320 * Math.cos((plat * Math.PI) / 180);
  const ky = 110540;
  const ax = (a[1] - plng) * kx;
  const ay = (a[0] - plat) * ky;
  const bx = (b[1] - plng) * kx;
  const by = (b[0] - plat) * ky;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

/** Bus road segments that pass inside a closure's radius. */
export function busSegmentsNear(c: Closure, data: BusRouteData, extra = 6) {
  const reach = Math.max(8, c.radius) + extra;
  return data.segments.filter((s) => {
    for (let i = 1; i < s.path.length; i++) {
      if (pointToSegmentM(c.lat, c.lng, s.path[i - 1], s.path[i]) <= reach) return true;
    }
    return false;
  });
}

const sortRefs = (refs: Iterable<string>) => [...new Set(refs)].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

export function busImpact(c: Closure, data: BusRouteData | null): BusImpact | null {
  const isRoad = c.affects === 'road' || c.affects === 'both';
  if (c.bus_routes?.length) {
    return { routes: sortRefs(c.bus_routes), roads: c.road_name ? [c.road_name] : [], certain: true };
  }
  // Only road work and construction can block buses
  if (!data || !(isRoad || c.type === 'construction')) return null;
  const segs = busSegmentsNear(c, data);
  if (!segs.length) return null;
  return {
    routes: sortRefs(segs.flatMap((s) => s.refs)),
    roads: c.road_name ? [c.road_name] : sortRefs(segs.map((s) => s.name).filter(Boolean) as string[]),
    certain: isRoad
  };
}

// ---------- grouping ----------

const family = (t: Closure['type']) => (t === 'elevator' ? 'elevator' : t === 'automatic_door' ? 'door' : 'ground');

function sameProblem(a: Closure, b: Closure): boolean {
  if (family(a.type) !== family(b.type)) return false;
  if (a.connector_id && b.connector_id) return a.connector_id === b.connector_id;
  return getDistanceMeters(a.lat, a.lng, b.lat, b.lng) <= Math.max(a.radius, b.radius) + 15;
}

function severityOf(official: Closure[], community: Closure[]): Severity {
  const confirmations = community.reduce((n, c) => n + Math.max(1, c.confirmations_count), 0);
  if (official.length && community.length) return 'high';
  if (official.length) return 'official';
  if (confirmations >= 3) return 'likely';
  return 'reported';
}

export function groupIncidents(closures: Closure[], bus: BusRouteData | null): Incident[] {
  const active = closures.filter((c) => c.status !== 'repaired');
  const groups: Closure[][] = [];
  for (const c of active) {
    const g = groups.find((list) => list.some((x) => sameProblem(x, c)));
    if (g) g.push(c);
    else groups.push([c]);
  }

  const incidents = groups.map((all) => {
    const official = all.filter((c) => c.source === 'official' || c.source === 'verified');
    const community = all.filter((c) => !official.includes(c));
    const primary = official[0] ?? [...community].sort((a, b) => b.confirmations_count - a.confirmations_count)[0];
    const lastConfirmed = all.map((c) => c.last_confirmed).sort().pop() ?? primary.last_confirmed;
    const impacts = all.map((c) => busImpact(c, bus)).filter(Boolean) as BusImpact[];
    const busMerged: BusImpact | null = impacts.length
      ? {
          routes: sortRefs(impacts.flatMap((i) => i.routes)),
          roads: sortRefs(impacts.flatMap((i) => i.roads)),
          certain: impacts.some((i) => i.certain)
        }
      : null;
    return {
      id: primary.id,
      severity: severityOf(official, community),
      primary,
      official,
      community,
      all,
      confirmations: community.reduce((n, c) => n + Math.max(1, c.confirmations_count), 0),
      lastConfirmed,
      isRoad: all.some((c) => c.affects === 'road' || c.affects === 'both'),
      bus: busMerged
    } satisfies Incident;
  });

  return incidents.sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || b.lastConfirmed.localeCompare(a.lastConfirmed)
  );
}

export function isSampleData(c: Closure): boolean {
  return c.id.startsWith('demo-');
}
