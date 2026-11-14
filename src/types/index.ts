/**
 * CampusNav shared TypeScript definitions.
 * Mirrors contracts/closures.contract.json, route.contract.json, buildings.contract.json, report.contract.json.
 */

export type BarrierType = 'elevator' | 'ramp' | 'path' | 'construction' | 'automatic_door';
export type BarrierStatus = 'closed' | 'degraded' | 'repaired';
export type BarrierSource = 'official' | 'community' | 'verified';

export interface Closure {
  id: string;
  lat: number;
  lng: number;
  radius: number; // meters
  type: BarrierType;
  status: BarrierStatus;
  source: BarrierSource;
  title: string;
  description?: string;
  building_name?: string;
  /** Graph connector this closure disables directly (e.g. an elevator). */
  connector_id?: string;
  start_time: string;
  end_time?: string;
  last_confirmed: string; // ISO timestamp
  confirmations_count: number;
}

export type DoorType = 'automatic' | 'push-button' | 'manual' | 'mixed';

export interface BuildingEntrance {
  id: string;
  name: string;
  lat: number;
  lng: number;
  step_free: boolean;
  door_type: 'automatic' | 'push-button' | 'manual';
  has_ramp: boolean;
  ramp_grade_pct?: number;
  level?: string;
  notes?: string;
  /** OSM node id when the position comes from OpenStreetMap. */
  osm_id?: number;
}

/** @deprecated kept for contract compatibility: use BuildingEntrance */
export type StepFreeEntrance = BuildingEntrance;

export interface BuildingElevator {
  id: string;
  name: string;
  floors: string;
  status: 'operational' | 'out_of_service';
  connector_id?: string;
}

export interface Building {
  id: string;
  name: string;
  code: string;
  category: 'academic' | 'student_services' | 'dining' | 'library' | 'residential' | 'recreation' | 'administration';
  location: { lat: number; lng: number };
  entrances: BuildingEntrance[];
  /** Contract field: the step-free subset of `entrances`. */
  step_free_entrances: BuildingEntrance[];
  door_type: DoorType;
  elevators: {
    total_count: number;
    working_count: number;
    floors_served: string;
    status: 'all_operational' | 'partial_outage' | 'all_down' | 'none';
    list: BuildingElevator[];
  };
  accessible_restrooms: boolean;
  lactation_room?: boolean;
  all_floors_accessible: boolean;
  notes?: string;
  /** Research-backed context shown in the building sheet. */
  student_reports?: { text: string; source: string; url: string; year: number }[];
  google_place_query?: string;
}

// ---------- Routing ----------

export type StepIcon =
  | 'start'
  | 'straight'
  | 'turn-left'
  | 'turn-right'
  | 'slight-left'
  | 'slight-right'
  | 'ramp-up'
  | 'ramp-down'
  | 'elevator'
  | 'stairs'
  | 'crossing'
  | 'indoor'
  | 'destination';

export interface RouteStep {
  instruction: string;
  distance_m: number;
  grade_pct: number;
  icon?: StepIcon;
  accessible_landmark?: string;
  is_indoor?: boolean;
  /** [lng, lat] where the step begins, for map focus. */
  at?: [number, number];
}

export interface AvoidedBarrier {
  kind: 'stairs' | 'steep' | 'closure' | 'rough_surface' | 'kerb';
  label: string;
  at: [number, number]; // [lng, lat]
  step_count?: number;
  grade_pct?: number;
}

export interface RouteSummary {
  total_distance_m: number;
  total_duration_s: number;
  max_grade_pct: number;
  avg_grade_pct: number;
  elevation_gain_m: number;
  is_step_free: boolean;
  stair_count: number;
  warnings: string[];
  engine?: 'local' | 'remote';
  compute_ms?: number;
  elevators_used?: string[];
  closures_avoided?: string[];
  rough_surface_m?: number;
  covered_m?: number;
}

export interface RouteFeatureProperties {
  grade: number;
  surface: string;
  is_step: boolean;
  is_ramp: boolean;
  is_elevator?: boolean;
  is_indoor?: boolean;
  step_count?: number;
  segment_name: string;
}

export interface RouteGeoJSONFeature {
  type: 'Feature';
  geometry: { type: 'LineString'; coordinates: [number, number][] }; // [lng, lat]
  properties: RouteFeatureProperties;
}

export interface RouteResponse {
  type: 'FeatureCollection';
  summary: RouteSummary;
  features: RouteGeoJSONFeature[];
  steps: RouteStep[];
  /** Elevation profile: cumulative distance (m) and elevation (m). */
  profile?: { d: number; z: number }[];
  avoided?: AvoidedBarrier[];
  gemini_narrative?: string;
}

// ---------- User needs ----------

export type MobilityProfile =
  | 'manual_wheelchair'
  | 'power_wheelchair'
  | 'walker_cane'
  | 'crutches'
  | 'stroller'
  | 'low_vision'
  | 'custom';

/** Legacy alias used by the contract and older components. */
export type MobilityPreset = MobilityProfile;

export interface UserPreferences {
  mobility_preset: MobilityProfile;
  /** Wheels on the ground: blocks stairs and raised kerbs, treats max slope as a hard limit. */
  wheelchair_required: boolean;
  no_stairs: boolean;
  max_grade_pct: number;
  avoid_rough_surfaces: boolean;
  prefer_indoor: boolean;
  /** If stairs are allowed, only use ones with handrails. */
  handrails_required: boolean;
  need_automatic_door: boolean;
  need_accessible_restroom: boolean;
  avoid_construction: boolean;
  /** Prefer fewer street crossings (low vision, guide dog). */
  minimize_crossings: boolean;
}

export interface UserReportPayload {
  lat: number;
  lng: number;
  type: BarrierType;
  status: 'broken' | 'working' | 'blocked' | 'under_repair';
  title: string;
  description: string;
  building_id?: string;
  connector_id?: string;
  reporter_device_id?: string;
  timestamp: string;
}

export interface Place {
  name: string;
  lat: number;
  lng: number;
  building_id?: string;
  entrance_id?: string;
}

/** @deprecated use Place */
export type NavigationTarget = Place;
