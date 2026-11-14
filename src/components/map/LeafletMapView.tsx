import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Scene } from './scene';
import { CAMPUS_CENTER } from './config';

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
  const layer = useRef<L.LayerGroup>(L.layerGroup());
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
    layer.current.addTo(m);
    m.on('click', (e: L.LeafletMouseEvent) => clickRef.current(e.latlng.lat, e.latlng.lng));
    m.on('zoomend', () => draw());
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sceneRef = useRef(scene);
  sceneRef.current = scene;

  function draw() {
    const m = map.current;
    if (!m) return;
    const s = sceneRef.current;
    const z = m.getZoom();
    const g = layer.current;
    g.clearLayers();
    for (const c of s.circles) {
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
    [...s.lines]
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
    for (const mk of s.markers) {
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
    draw();
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
  }, [scene]);

  useEffect(() => {
    el.current?.classList.toggle('au-pick-cursor', pickMode);
  }, [pickMode]);

  useEffect(() => {
    if (focus && map.current) map.current.flyTo([focus.lat, focus.lng], Math.max(map.current.getZoom(), 19), { duration: 0.6 });
  }, [focus]);

  return <div ref={el} className="h-full w-full" />;
}
