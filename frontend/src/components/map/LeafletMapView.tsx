import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Scene } from './scene';
import { CAMPUS_CENTER } from './config';
import { focusOffset } from './focusOffset';

interface Props {
  scene: Scene;
  pickMode: boolean;
  focus: { lat: number; lng: number; key: number } | null;
  onMapClick: (lat: number, lng: number) => void;
}

/**
 * Keyless fallback basemap (OpenStreetMap tiles). Used when no Google Maps key is configured or Google
 * rejects the key, so the demo never shows a broken map.
 */
export default function LeafletMapView({ scene, pickMode, focus, onMapClick }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const routeLayer = useRef<L.LayerGroup>(L.layerGroup());
  const closureLayer = useRef<L.LayerGroup>(L.layerGroup());
  const markerLayer = useRef<L.LayerGroup>(L.layerGroup());
  const clickRef = useRef(onMapClick);
  const lastFit = useRef('');
  clickRef.current = onMapClick;

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, { center: CAMPUS_CENTER, zoom: 17, minZoom: 14, maxZoom: 19, zoomControl: false });
    L.control.zoom({ position: 'bottomright' }).addTo(m);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(m);
    closureLayer.current.addTo(m);
    routeLayer.current.addTo(m);
    markerLayer.current.addTo(m);
    m.on('click', (e: L.LeafletMouseEvent) => clickRef.current(e.latlng.lat, e.latlng.lng));
    m.on('zoomend', () => drawMarkers());
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sceneRef = useRef(scene);
  sceneRef.current = scene;

  useEffect(() => {
    const g = closureLayer.current;
    g.clearLayers();
    for (const c of scene.circles) {
      L.circle(c.center, {
        radius: c.radius,
        color: c.color,
        weight: 1.5,
        opacity: 0.7,
        fillColor: c.color,
        fillOpacity: c.dashed ? 0.1 : 0.16,
        dashArray: c.dashed ? '4 4' : undefined,
        interactive: false
      }).addTo(g);
    }
  }, [scene.circles]);

  useEffect(() => {
    const g = routeLayer.current;
    g.clearLayers();
    [...scene.lines]
      .sort((a, b) => a.zIndex - b.zIndex)
      .forEach((l) => {
        L.polyline(l.path, {
          color: l.color,
          weight: l.weight,
          opacity: l.opacity,
          dashArray: l.dashed ? `${l.weight * 1.2} ${l.weight * 2}` : undefined,
          lineCap: 'round',
          lineJoin: 'round',
          interactive: false
        }).addTo(g);
      });
  }, [scene.lines]);

  function drawMarkers() {
    const m = map.current;
    if (!m) return;
    const z = m.getZoom();
    const g = markerLayer.current;
    g.clearLayers();
    for (const mk of sceneRef.current.markers) {
      if (mk.minZoom && z < mk.minZoom) continue;
      const icon = L.divIcon({
        className: 'au-icon',
        html: `<div style="display:inline-block;transform:translate(-50%,${mk.anchor === 'center' ? '-50%' : '-100%'})">${mk.html}</div>`,
        iconSize: [0, 0]
      });
      const marker = L.marker(mk.position, { icon, zIndexOffset: mk.zIndex * 10, title: mk.title, keyboard: !!mk.onClick, interactive: !!mk.onClick });
      if (mk.onClick) marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        mk.onClick!();
      });
      marker.addTo(g);
    }
  }

  useEffect(() => {
    drawMarkers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.markers]);

  useEffect(() => {
    const m = map.current;
    if (m && scene.bounds.length && lastFit.current !== scene.fitKey) {
      lastFit.current = scene.fitKey;
      const wide = window.innerWidth >= 1024;
      m.fitBounds(L.latLngBounds(scene.bounds), {
        paddingTopLeft: [wide ? 440 : 32, 96],
        paddingBottomRight: [48, wide ? 64 : 360],
        maxZoom: 19,
        animate: true
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.bounds, scene.fitKey]);

  useEffect(() => {
    el.current?.classList.toggle('au-pick-cursor', pickMode);
  }, [pickMode]);

  useEffect(() => {
    const m = map.current;
    if (!focus || !m) return;
    m.stop();
    const zoom = m.getZoom();
    const [x, y] = focusOffset();
    const center = m.unproject(m.project([focus.lat, focus.lng], zoom).subtract(L.point(x, y)), zoom);
    m.panTo(center, {animate: true, duration: 0.3});
  }, [focus]);

  return <div ref={el} className="h-full w-full" />;
}
