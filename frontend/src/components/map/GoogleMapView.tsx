import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { AdvancedMarker, AdvancedMarkerAnchorPoint, Map, Polyline, useMap } from '@vis.gl/react-google-maps';
import type { Scene, SceneCircle, SceneLine } from './scene';
import { CAMPUS_CENTER, MAP_ID } from './config';
import { focusOffset } from './focusOffset';

interface Props {
  scene: Scene;
  pickMode: boolean;
  focus: { lat: number; lng: number; key: number } | null;
  onMapClick: (lat: number, lng: number) => void;
}

function Focus({ focus }: { focus: Props['focus'] }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !focus) return;
    const zoom = map.getZoom() ?? 17;
    const projection = map.getProjection();
    const point = projection?.fromLatLngToPoint(new google.maps.LatLng(focus.lat, focus.lng));
    const [x, y] = focusOffset();
    const center = point && projection?.fromPointToLatLng(new google.maps.Point(point.x - x / 2 ** zoom, point.y - y / 2 ** zoom));
    map.panTo(center || {lat: focus.lat, lng: focus.lng});
  }, [map, focus]);
  return null;
}

function lineProps(l: SceneLine) {
  const path = l.path.map(([lat, lng]) => ({ lat, lng }));
  if (!l.dashed) {
    return { path, strokeColor: l.color, strokeOpacity: l.opacity, strokeWeight: l.weight, zIndex: l.zIndex };
  }
  return {
    path,
    strokeOpacity: 0,
    zIndex: l.zIndex,
    icons: [
      {
        icon: { path: 'M 0,-1 0,1', strokeOpacity: l.opacity, strokeColor: l.color, strokeWeight: l.weight, scale: 1 },
        offset: '0',
        repeat: `${l.weight * 3}px`
      }
    ]
  };
}

const RouteLines = memo(function RouteLines({ lines }: { lines: SceneLine[] }) {
  return <>{lines.map((line) => <Polyline key={line.id} {...lineProps(line)} clickable={false} />)}</>;
});

function Circles({ circles }: { circles: SceneCircle[] }) {
  const map = useMap();
  const refs = useRef<google.maps.Circle[]>([]);
  useEffect(() => {
    if (!map) return;
    refs.current.forEach((c) => c.setMap(null));
    refs.current = circles.map(
      (c) =>
        new google.maps.Circle({
          map,
          center: { lat: c.center[0], lng: c.center[1] },
          radius: c.radius,
          strokeColor: c.color,
          strokeOpacity: 0.7,
          strokeWeight: 1.5,
          fillColor: c.color,
          fillOpacity: c.dashed ? 0.1 : 0.16,
          clickable: false,
          zIndex: 0
        })
    );
    return () => refs.current.forEach((c) => c.setMap(null));
  }, [map, circles]);
  return null;
}

function FitBounds({ scene }: { scene: Scene }) {
  const map = useMap();
  const last = useRef('');
  useEffect(() => {
    if (!map || !scene.bounds.length || last.current === scene.fitKey) return;
    last.current = scene.fitKey;
    const b = new google.maps.LatLngBounds();
    scene.bounds.forEach(([lat, lng]) => b.extend({ lat, lng }));
    const wide = window.innerWidth >= 1024;
    map.fitBounds(b, { top: 96, bottom: wide ? 64 : 360, left: wide ? 440 : 32, right: 48 });
    const z = map.getZoom();
    if (z && z > 19) map.setZoom(19);
  }, [map, scene.fitKey, scene.bounds]);
  return null;
}

export default function GoogleMapView({ scene, pickMode, focus, onMapClick }: Props) {
  const [zoom, setZoom] = useState(17);
  const markers = useMemo(() => scene.markers.filter((m) => !m.minZoom || zoom >= m.minZoom), [scene.markers, zoom]);

  return (
    <Map
      mapId={MAP_ID}
      defaultCenter={{ lat: CAMPUS_CENTER[0], lng: CAMPUS_CENTER[1] }}
      defaultZoom={17}
      minZoom={14}
      maxZoom={21}
      gestureHandling="greedy"
      disableDefaultUI
      zoomControl
      zoomControlOptions={typeof google !== 'undefined' ? { position: google.maps.ControlPosition.RIGHT_BOTTOM } : undefined}
      clickableIcons={false}
      colorScheme="LIGHT"
      draggableCursor={pickMode ? 'crosshair' : undefined}
      onZoomChanged={(e) => setZoom(e.detail.zoom)}
      onClick={(e) => {
        const ll = e.detail.latLng;
        if (ll) onMapClick(ll.lat, ll.lng);
      }}
      className="h-full w-full"
    >
      <RouteLines lines={scene.lines} />
      <Circles circles={scene.circles} />
      {markers.map((m) => (
        <AdvancedMarker
          key={m.id}
          position={{ lat: m.position[0], lng: m.position[1] }}
          zIndex={m.zIndex}
          title={m.title}
          anchorPoint={m.anchor === 'center' ? AdvancedMarkerAnchorPoint.CENTER : AdvancedMarkerAnchorPoint.BOTTOM}
          onClick={m.onClick}
          clickable={!!m.onClick}
        >
          <div dangerouslySetInnerHTML={{ __html: m.html }} />
        </AdvancedMarker>
      ))}
      <FitBounds scene={scene} />
      <Focus focus={focus} />
    </Map>
  );
}
