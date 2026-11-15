/** Types for indoorCatalog.js so the TypeScript app (App.tsx) can use it. */
import type { Context } from 'react';
import type { Building } from '../../types';

/** A normalised indoor map (indoorModel.js). Opaque to the TypeScript side except for these fields. */
export interface IndoorMapModel {
  id: string;
  name: string;
  status: string;
  sample: boolean;
  source: 'api' | 'data' | 'sample';
  entryFloor: string;
  routingKind?: 'drawing' | 'indoor';
  residentAccessRequired?: boolean;
  nodes: Map<string, {id: string; label: string; floor: string; kind: string}>;
  floors: { id: string; label: string; level: number }[];
  rooms: { id: string; name: string; floor: string; floorLabel: string; type: string }[];
}

export interface IndoorCatalogEntry {
  /** Outdoor building id (destination.building_id) */
  buildingId: string;
  model: IndoorMapModel;
  name: string;
  code: string;
  location: { lat: number; lng: number } | null;
}

export interface IndoorCatalog {
  entries: IndoorCatalogEntry[];
  forBuilding: (buildingId: string | null | undefined) => IndoorMapModel | null;
  /** Buildings that only exist as indoor maps (not in the backend yet): shown as map destinations */
  extraBuildings: Building[];
  loading: boolean;
}

export function loadIndoorCatalog(): void;
export function useIndoorCatalog(buildings: Building[]): IndoorCatalog;
export const IndoorCatalogContext: Context<IndoorCatalog>;
export function useIndoorEntries(): IndoorCatalog;
