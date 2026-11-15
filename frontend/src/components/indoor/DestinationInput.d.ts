/** Types for DestinationInput.jsx so the TypeScript app (App.tsx) can import it. */
import type { FC } from 'react';

export interface DestinationTarget {
  type: 'building' | 'floor' | 'room';
  buildingId: string;
  buildingName: string;
  /** Room id, "<floorId>:@lobby" for a whole floor, or null for the building itself */
  roomId: string | null;
  floorId: string | null;
  label: string;
  lat: number;
  lng: number;
}

export interface DestinationInputProps {
  onSelect?: (target: DestinationTarget) => void;
  scopeBuildingId?: string;
  value?: string;
  placeholder?: string;
  className?: string;
  compact?: boolean;
  autoFocus?: boolean;
  onDismiss?: () => void;
}

declare const DestinationInput: FC<DestinationInputProps>;
export default DestinationInput;
export function searchDestinations(
  query: string,
  scopeBuildingId?: string,
  entries?: import('./indoorCatalog').IndoorCatalogEntry[]
): (DestinationTarget & { key: string; hint?: string })[];
