/**
 * Renderer-agnostic description of everything drawn on the map.
 * GoogleMapView and LeafletMapView both draw a Scene, so the two basemaps can never drift apart.
 */
import type { Building, BuildingEntrance, Closure, Place, RouteResponse } from '../../types';
import { getDistanceMeters } from '../../services/routingEngine';
import { closureIcon, ICONS } from './icons';

export type LatLng = [number, number];

export interface SceneLine {
  id: string;
  path: LatLng[];
  color: string;
  weight: number;
  opacity: number;
  dashed?: boolean;
  zIndex: number;
  title?: string;
}

export interface SceneMarker {
  id: string;
  position: LatLng;
  html: string;
  zIndex: number;
  /** Anchor: 'center' or 'bottom' */
  anchor: 'center' | 'bottom';
  title: string;
  onClick?: () => void;
  minZoom?: number;
}

export interface SceneCircle {
  id: string;
  center: LatLng;
  radius: number;
  color: string;
  dashed?: boolean;
}

export interface Scene {
  lines: SceneLine[];
  markers: SceneMarker[];
  circles: SceneCircle[];
  /** Bounds to frame when fitKey changes. */
  bounds: LatLng[];
  fitKey: string;
}

export interface SceneInput {
  buildings: Building[];
  closures: Closure[];
  accessible: RouteResponse | null;
  standard: RouteResponse | null;
  ghost: RouteResponse | null;
  showStandard: boolean;
  origin: Place | null;
  destination: Place | null;
  chosenEntranceIds: string[];
  selectedBuildingId: string | null;
  highContrast: boolean;
  onSelectBuilding: (b: Building) => void;
  onSelectClosure: (c: Closure) => void;
  onSelectEntrance: (b: Building, e: BuildingEntrance) => void;
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

function routeLatLngs(r: RouteResponse): LatLng[][] {
  return r.features.map((f) => f.geometry.coordinates.map(([lng, lat]) => [lat, lng] as LatLng));
}

export function entranceState(b: Building, e: BuildingEntrance, closures: Closure[]): 'ok' | 'manual' | 'no' | 'broken' | 'unknown' {
  if (e.step_free === false) return 'no';
  if (e.step_free === null || e.door_type === 'unknown') return 'unknown';
  const issue = closures.find(
    (c) => c.status !== 'repaired' && c.type === 'automatic_door' && getDistanceMeters(c.lat, c.lng, e.lat, e.lng) <= Math.max(15, c.radius)
  );
  if (issue) return 'broken';
  void b;
  return e.door_type === 'manual' ? 'manual' : 'ok';
}

export function buildingAccess(b: Building, closures: Closure[]): 'good' | 'partial' | 'limited' {
  const working = b.entrances.filter((e) => entranceState(b, e, closures) === 'ok').length;
  const brokenLift = closures.some((c) => c.status === 'closed' && c.type === 'elevator' && b.elevators.list.some((l) => l.connector_id && l.connector_id === c.connector_id));
  if (!working || !b.all_floors_accessible) return 'limited';
  if (brokenLift || b.entrances.some((e) => entranceState(b, e, closures) === 'broken')) return 'partial';
  return 'good';
}

export function buildScene(i: SceneInput): Scene {
  const lines: SceneLine[] = [];
  const markers: SceneMarker[] = [];
  const circles: SceneCircle[] = [];
  const bounds: LatLng[] = [];
  const hc = i.highContrast;

  // Previous route after a reroute, shown briefly so the shift is visible
  if (i.ghost) {
    routeLatLngs(i.ghost).forEach((path, k) =>
      lines.push({ id: `ghost-${k}`, path, color: '#8e8e93', weight: 5, opacity: 0.55, dashed: true, zIndex: 1, title: 'Previous route' })
    );
  }

  if (i.standard && i.showStandard) {
    i.standard.features.forEach((f, k) => {
      const path = f.geometry.coordinates.map(([lng, lat]) => [lat, lng] as LatLng);
      path.forEach((p) => bounds.push(p));
      const stairs = f.properties.is_step;
      lines.push({
        id: `std-${k}`,
        path,
        color: stairs ? (hc ? '#b00000' : '#e5484d') : hc ? '#b00000' : '#f2777a',
        weight: stairs ? 6 : 4,
        opacity: stairs ? 0.95 : 0.8,
        dashed: !stairs,
        zIndex: 2,
        title: 'Regular map route'
      });
      if (stairs && f.properties.step_count) {
        markers.push({
          id: `std-stairs-${k}`,
          position: path[Math.floor(path.length / 2)],
          html: `<div class="au-tag stairs">${ICONS.stairs}${f.properties.step_count} steps</div>`,
          zIndex: 40,
          anchor: 'center',
          title: `${f.properties.step_count} steps`
        });
      }
    });
  }

  if (i.accessible) {
    i.accessible.features.forEach((f, k) => {
      const path = f.geometry.coordinates.map(([lng, lat]) => [lat, lng] as LatLng);
      path.forEach((p) => bounds.push(p));
      const lift = f.properties.is_elevator;
      lines.push({ id: `acc-case-${k}`, path, color: hc ? '#000000' : '#ffffff', weight: lift ? 11 : 10, opacity: 1, zIndex: 3 });
      lines.push({
        id: `acc-${k}`,
        path,
        color: lift ? '#6e56cf' : hc ? '#0047ff' : '#2a9d64',
        weight: lift ? 7 : 6,
        opacity: 1,
        zIndex: 4,
        title: lift ? 'Elevator' : 'Your accessible route'
      });
      if (lift) {
        markers.push({
          id: `acc-lift-${k}`,
          // Label the elevator where you board it; the far end often sits under the destination pin
          position: path[0],
          html: `<div class="au-tag lift">${ICONS.elevator}Elevator</div>`,
          zIndex: 45,
          anchor: 'center',
          title: f.properties.segment_name
        });
      }
    });
  }

  // Closures
  for (const c of i.closures) {
    if (c.status === 'repaired') continue;
    const degraded = c.status === 'degraded';
    circles.push({ id: `cz-${c.id}`, center: [c.lat, c.lng], radius: c.radius, color: degraded ? '#f0a020' : '#e5484d', dashed: degraded });
    const fresh = Date.now() - new Date(c.last_confirmed).getTime() < 2 * 3600_000;
    markers.push({
      id: `c-${c.id}`,
      position: [c.lat, c.lng],
      html: `<div class="au-closure ${degraded ? 'degraded' : ''} ${fresh ? 'live' : ''}" aria-label="${esc(c.title)}">${closureIcon(c.type)}</div>`,
      zIndex: 60,
      anchor: 'center',
      title: c.title,
      onClick: () => i.onSelectClosure(c)
    });
  }

  // Buildings + entrances
  for (const b of i.buildings) {
    const access = buildingAccess(b, i.closures);
    const sel = b.id === i.selectedBuildingId;
    markers.push({
      id: `b-${b.id}`,
      position: [b.location.lat, b.location.lng],
      html: `<div class="au-building ${access} ${sel ? 'selected' : ''}"><span class="dot">${access === 'good' ? '✓' : access === 'partial' ? '!' : '–'}</span>${esc(b.code)}</div>`,
      zIndex: sel ? 30 : 10,
      anchor: 'center',
      title: `${b.name}: ${access === 'good' ? 'source documents step-free access; check current status' : access === 'partial' ? 'reported access issue' : 'access data limited or unverified'}`,
      onClick: () => i.onSelectBuilding(b)
    });
    for (const e of b.entrances) {
      const st = entranceState(b, e, i.closures);
      const chosen = i.chosenEntranceIds.includes(e.id);
      markers.push({
        id: `e-${e.id}`,
        position: [e.lat, e.lng],
        html: `<div class="au-entrance ${st} ${chosen ? 'chosen' : ''}"></div>`,
        zIndex: chosen ? 50 : 20,
        anchor: 'center',
        title: `${b.name}, ${e.name}: ${st === 'unknown' ? 'entrance access unverified' : st === 'ok' ? 'step-free, powered door' : st === 'manual' ? 'step-free, manual door' : st === 'broken' ? 'door reported broken' : 'not step-free'}`,
        onClick: () => i.onSelectEntrance(b, e),
        minZoom: chosen || sel ? undefined : 17
      });
    }
  }

  if (i.origin) {
    markers.push({ id: 'pin-a', position: [i.origin.lat, i.origin.lng], html: '<div class="au-pin a">A</div>', zIndex: 80, anchor: 'center', title: `Start: ${i.origin.name}` });
    bounds.push([i.origin.lat, i.origin.lng]);
  }
  if (i.destination) {
    markers.push({ id: 'pin-b', position: [i.destination.lat, i.destination.lng], html: '<div class="au-pin b">B</div>', zIndex: 80, anchor: 'center', title: `Destination: ${i.destination.name}` });
    bounds.push([i.destination.lat, i.destination.lng]);
  }

  const fitKey = `${i.origin?.lat},${i.origin?.lng}|${i.destination?.lat},${i.destination?.lng}|${i.accessible?.summary.total_distance_m ?? 0}|${i.showStandard ? 1 : 0}`;
  return { lines, markers, circles, bounds, fitKey };
}
