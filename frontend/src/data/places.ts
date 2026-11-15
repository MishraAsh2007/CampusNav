import type { Building, Place } from '../types';

export interface PickablePlace extends Place {
  code: string;
  kind: 'building' | 'spot' | 'bus';
  subtitle: string;
}

/** Non-building origins/destinations: outdoor spots and PVTA stops (positions from OpenStreetMap). */
export const SPOTS: PickablePlace[] = [
  { name: 'Campus Center upper terrace', code: 'CC', kind: 'spot', subtitle: 'Top of the Blue Wall stairs', lat: 42.391519, lng: -72.526563 },
  { name: 'ILC bus stop (North Pleasant St)', code: 'BUS', kind: 'bus', subtitle: 'PVTA', lat: 42.3909194, lng: -72.5253653 },
  { name: 'Morrill Science Center bus stop', code: 'BUS', kind: 'bus', subtitle: 'PVTA', lat: 42.391554, lng: -72.525248 },
  { name: 'Boyden bus stop (Commonwealth Ave)', code: 'BUS', kind: 'bus', subtitle: 'PVTA', lat: 42.386314, lng: -72.531143 },
  { name: 'Campus Center parking garage', code: 'P', kind: 'spot', subtitle: 'Accessible parking', lat: 42.3912, lng: -72.52855 }
];

export function buildingPlaces(buildings: Building[]): PickablePlace[] {
  return buildings.map((b) => ({
    name: b.name,
    code: b.code,
    kind: 'building',
    subtitle: b.step_free_entrances.length ? `${b.step_free_entrances.length} source-documented step-free entrances` : 'Mapped entrances; step-free door access unverified',
    lat: b.location.lat,
    lng: b.location.lng,
    building_id: b.id
  }));
}

export const DEMO_TRIP = {
  origin: { name: 'Student Union', lat: 42.39087, lng: -72.5276, building_id: 'student-union' } as Place,
  destination: { name: 'Campus Center upper terrace', lat: 42.391519, lng: -72.526563 } as Place
};
