import type { RouteResponse, RouteStep, StepIcon } from '../types';

export interface RouteStepPosition {
  lat: number;
  lng: number;
  index: number;
  instruction: string;
}

/** Use the maneuver's real coordinate; never interpolate a missing turn location. */
export function routeStepPosition(route: RouteResponse | null, index: number): RouteStepPosition | null {
  const step = route?.steps[index];
  if (!route || !step) return null;
  const first = route.features[0]?.geometry.coordinates;
  const last = route.features[route.features.length - 1]?.geometry.coordinates;
  const point = step.at ?? (step.icon === 'destination' ? last?.[last.length - 1] : index === 0 ? first?.[0] : null);
  if (!point || !Number.isFinite(point[0]) || !Number.isFinite(point[1]) || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) return null;
  return {lng: point[0], lat: point[1], index, instruction: step.instruction};
}

export interface WireManeuver {
  instruction: string;
  maneuver: string;
  distance_m: number;
  grade_pct: number | null;
  at: [number, number];
  geometry: [number, number][];
}

const icons: Record<string, StepIcon> = {
  depart: 'start', straight: 'straight', left: 'turn-left', right: 'turn-right',
  'sharp-left': 'turn-left', 'sharp-right': 'turn-right', 'u-turn': 'turn-left',
  'slight-left': 'slight-left', 'slight-right': 'slight-right', stairs: 'stairs',
  ramp: 'ramp-up', elevator: 'elevator', arrive: 'destination',
};

/** Preserve server turn locations and leg distances, including unnamed paths. */
export function routeSteps(properties: {directions: string[]; maneuvers?: WireManeuver[]}): RouteStep[] {
  if (properties.maneuvers?.length) return properties.maneuvers.map(step => ({
    instruction: step.instruction, distance_m: step.distance_m, grade_pct: step.grade_pct ?? 0,
    icon: icons[step.maneuver] || 'straight', at: step.at,
  }));
  return properties.directions.map((instruction, i) => ({instruction, distance_m: 0, grade_pct: 0,
    icon: i === properties.directions.length - 1 ? 'destination' : 'straight'}));
}
