/** Types for IndoorFlow.jsx so the TypeScript app (App.tsx) can import it. */
import type { FC } from 'react';
import type { Closure, UserPreferences } from '../../types';
import type { IndoorMapModel } from './indoorCatalog';

export type ViewState = 'outdoor' | 'transition_modal' | 'indoor_2d' | 'indoor_3d';

export interface IndoorFlowProps {
  viewState: ViewState;
  onViewStateChange: (next: ViewState) => void;
  /** Indoor map for the destination building, from useIndoorCatalog().forBuilding(id) */
  map: IndoorMapModel | null;
  /** Outdoor building id (the one in destination.building_id) */
  buildingId: string | null | undefined;
  weather?: { condition: string; tempF?: number };
  highContrast?: boolean;
  /** Room id (or "<floor>:@lobby") chosen in the destination search; preselected in the arrival modal */
  targetRoomId?: string | null;
  /**
   * Entrance where the outdoor route ends (from the routing engine when it answered). The indoor route
   * starts at its exact matched indoor landmark. Without a match, the user selects a start.
   */
  entrance?: IndoorEntrance | null;
  /** Live closures: elevators reported out of service are avoided indoors */
  closures?: Closure[];
  preferences: UserPreferences;
  startNodeId?: string;
  consent?: {resident?: boolean};
}

export interface IndoorEntrance {
  id?: string | null;
  portalId?: string;
  indoorNodeId?: string;
  handoffMessage?: string;
  lat: number;
  lng: number;
  name: string;
  door: 'automatic' | 'manual';
  source: 'engine' | 'local';
}

declare const IndoorFlow: FC<IndoorFlowProps>;
export default IndoorFlow;
