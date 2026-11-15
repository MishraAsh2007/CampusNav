import { useMemo } from 'react';
import type { Building, BuildingEntrance, Closure, Place, RouteResponse } from '../types';
import { buildScene } from './map/scene';
import type { Incident } from '../services/incidents';
import { useMapProvider } from './map/MapsProvider';
import GoogleMapView from './map/GoogleMapView';
import LeafletMapView from './map/LeafletMapView';

interface MapViewProps {
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
  pickMode: boolean;
  focus: { lat: number; lng: number; key: number } | null;
  onSelectBuilding: (b: Building) => void;
  incidents: Incident[];
  onSelectIncident: (inc: Incident) => void;
  onSelectEntrance: (b: Building, e: BuildingEntrance) => void;
  onMapClick: (lat: number, lng: number) => void;
}

export function MapView(props: MapViewProps) {
  const { provider } = useMapProvider();
  const scene = useMemo(
    () => buildScene(props),
    // Callbacks are stable (useCallback in App); data drives redraws
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      props.buildings,
      props.closures,
      props.incidents,
      props.accessible,
      props.standard,
      props.ghost,
      props.showStandard,
      props.origin,
      props.destination,
      props.chosenEntranceIds,
      props.selectedBuildingId,
      props.highContrast
    ]
  );

  return (
    <div className="absolute inset-0 isolate z-0" role="region" aria-label="Campus map">
      {provider === 'google' ? (
        <GoogleMapView scene={scene} pickMode={props.pickMode} focus={props.focus} onMapClick={props.onMapClick} />
      ) : (
        <LeafletMapView scene={scene} pickMode={props.pickMode} focus={props.focus} onMapClick={props.onMapClick} />
      )}
    </div>
  );
}
