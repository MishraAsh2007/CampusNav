import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { Circle, CircleMarker, ImageOverlay, MapContainer, Marker, Polyline, Tooltip, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import ViewToggleFab from './ViewToggleFab';
import { POS } from './layout';

/**
 * 2D bird's-eye indoor map. Pixel-space only: Leaflet runs in L.CRS.Simple with the floor plan image as
 * an ImageOverlay, so nothing here touches GPS coordinates or the outdoor map directly. GPS arrives
 * already converted to plan pixels (see indoorGps.js).
 *
 * Coordinates: route points are image pixels [x, y] with the origin top-left and y down. CRS.Simple has
 * y up, so a pixel maps to LatLng [height - y, x]. In CRS.Simple distances are in pixels, so a Circle's
 * radius is in pixels too.
 *
 * Props
 *   imageUrl      floor plan image for a single-floor building (shorthand for `floors`)
 *   width,height  image size in px (default 1200 x 800)
 *   floors        [{ id, label, level, imageUrl, width?, height?, rooms? }]   multi-floor buildings
 *                 rooms: [{ id, name, x, y, area? }]  points in the floor's pixels (area = optional outline)
 *   paths         { [floorId]: [x, y][] }   full route on each floor
 *   steps, active steps with `floor` and `pts` (pixels); the active one is highlighted
 *   destination   { name, x, y, floor }
 *   building      title
 *   gps           { pos: [x,y], floorId?, accuracyPx, label, follow, offRoute } | null   live position in plan pixels
 *   onSwitch3D    show the round "3D" button (bottom right, above the zoom controls)
 *   onExit        back to the outdoor map
 *   onSelectRoom  (room) => void   tap a room on the plan to route there (optional)
 *   overlay       node shown top-left on large screens (e.g. <RouteWarningsPanel compact />)
 *   floorHint     { floorId, key } switch the visible floor whenever `key` changes (altitude floor detection)
 *   bottomInset   px covered by the directions card at the bottom (phones), kept clear when fitting the plan
 */

const DEFAULT_W = 1200;
const DEFAULT_H = 800;
const MIN_ZOOM = -2.5;
const MAX_ZOOM = 3;

function toLatLng([x, y], h) {
  return [h - y, x];
}

/**
 * Space the map must leave for the overlays: header + toolbar on top, the control column on the right,
 * and the directions card (left on desktop, bottom on phones; `bottomInset` is its measured height).
 */
function cardPadding(bottomInset) {
  const wide = window.innerWidth >= 1024;
  return { paddingTopLeft: [wide ? 440 : 16, 124], paddingBottomRight: [72, wide ? 24 : bottomInset + 16] };
}

function MapBehaviour({ bounds, here, follow, onMap, bottomInset }) {
  const map = useMap();
  const followed = useRef(false);
  const pad = useMemo(() => cardPadding(bottomInset), [bottomInset]);

  useEffect(() => {
    onMap(map);
  }, [map, onMap]);

  useEffect(() => {
    map.fitBounds(bounds, { ...pad, animate: false });
    followed.current = false;
  }, [map, bounds, pad]);

  useEffect(() => {
    if (!here) return;
    if (follow) {
      // Like a maps app: first fix zooms in on you, after that the map glides along with you
      if (!followed.current) {
        map.flyTo(here, Math.max(map.getZoom(), 0), { duration: 0.8 });
        followed.current = true;
      } else {
        map.panInside(here, { ...pad, animate: true });
      }
    } else {
      map.panInside(here, { ...pad, animate: true });
    }
  }, [map, here, follow, pad]);

  return null;
}

// Room tooltips only where there is a mouse; on touch screens they stick after a tap
const canHover = typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches;

const dot = (bg, ring) =>
  L.divIcon({
    className: 'au-icon',
    html: `<div style="transform:translate(-50%,-50%)" class="relative flex h-6 w-6 items-center justify-center"><span class="absolute inline-flex h-full w-full animate-ping rounded-full ${ring} opacity-60"></span><span class="relative inline-flex h-5 w-5 rounded-full border-[3px] border-white ${bg} shadow-lg"></span></div>`,
    iconSize: [0, 0]
  });
const gpsIcon = dot('bg-blue-600', 'bg-blue-500');
const stepIcon = dot('bg-slate-800', 'bg-slate-500');

const destIcon = L.divIcon({
  className: 'au-icon',
  html: '<div style="transform:translate(-50%,-100%)" class="flex flex-col items-center"><span class="flex h-9 w-9 items-center justify-center rounded-full border-[3px] border-white bg-emerald-600 text-[16px] text-white shadow-lg">🏁</span><span class="-mt-1 h-3 w-1 rounded-b bg-emerald-700"></span></div>',
  iconSize: [0, 0]
});

export default function IndoorNavigator2D({
  imageUrl,
  width = DEFAULT_W,
  height = DEFAULT_H,
  floors: floorsProp,
  paths = {},
  steps = [],
  active = 0,
  destination,
  building,
  gps = null,
  onSwitch3D,
  onExit,
  onSelectRoom,
  overlay,
  floorHint = null,
  bottomInset = 0
}) {
  const floors = useMemo(() => floorsProp ?? [{ id: 'main', label: 'Floor plan', imageUrl, width, height }], [floorsProp, imageUrl, width, height]);
  const step = steps[active];
  const routeFloors = Object.keys(paths);
  const [map, setMap] = useState(null);
  const [zoom, setZoom] = useState(0);

  // Follow the active step's floor; the user can still peek at another floor
  const [viewFloorId, setViewFloorId] = useState(step?.floor ?? floors[0].id);
  useEffect(() => {
    if (step?.floor) setViewFloorId(step.floor);
  }, [step?.floor]);
  // Floor detected from GPS altitude (or the Floor 1 default): switch to it when it changes
  useEffect(() => {
    if (floorHint?.floorId && floors.some((f) => f.id === floorHint.floorId)) setViewFloorId(floorHint.floorId);
  }, [floorHint?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!map) return;
    const update = () => setZoom(map.getZoom());
    update();
    map.on('zoomend', update);
    return () => {
      map.off('zoomend', update);
    };
  }, [map]);

  const fl = floors.find((f) => f.id === viewFloorId) ?? floors[0];
  // Tall buildings scroll the floor picker: keep the shown floor in view
  const floorNav = useRef(null);
  useEffect(() => {
    const nav = floorNav.current;
    const btn = nav?.querySelector('[data-current]');
    if (!nav || !btn) return;
    const offset = btn.getBoundingClientRect().left - nav.getBoundingClientRect().left + nav.scrollLeft;
    nav.scrollTo({ left: offset - nav.clientWidth / 2 + btn.clientWidth / 2, behavior: 'smooth' });
  }, [fl.id]);
  const W = fl.width ?? DEFAULT_W;
  const H = fl.height ?? DEFAULT_H;
  const bounds = useMemo(() => L.latLngBounds([0, 0], [H, W]), [H, W]);
  // Generous pan limits: the plan has to be able to sit to the right of the directions card
  const maxBounds = useMemo(() => L.latLngBounds([-H * 0.6, -W * 0.7], [H * 1.4, W * 1.4]), [H, W]);
  const ll = (p) => toLatLng(p, H);

  const floorPath = paths[fl.id] ?? (fl.id === 'main' ? Object.values(paths)[0] : null);
  const floorSteps = steps.map((s, i) => ({ s, i })).filter(({ s }) => (s.floor ?? 'main') === fl.id || (fl.id === 'main' && !s.floor));
  const done = floorSteps.filter(({ s, i }) => i < active && s.pts?.length > 1);
  const activeOnFloor = step && (step.floor ?? fl.id) === fl.id;

  // GPS is drawn on the floor it was placed on (altitude, else the current step's floor)
  const gpsHere = gps?.pos && (gps.floorId ? gps.floorId === fl.id : activeOnFloor) ? ll(gps.pos) : null;
  const stepHere = activeOnFloor && step.pts?.[0] ? ll(step.pts[0]) : null;
  const here = gpsHere ?? stepHere;
  const hereKey = here ? `${Math.round(here[0])},${Math.round(here[1])}` : null;
  const herePos = useMemo(() => here, [hereKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const btn = 'flex h-11 w-11 items-center justify-center text-[20px] font-semibold text-slate-900 transition hover:bg-slate-100 disabled:opacity-30';
  const pad = cardPadding(bottomInset);

  return (
    <div className="relative h-full w-full bg-[#e9e7e2]">
      <div className="absolute inset-0 isolate z-0">
        <MapContainer
          key={fl.id}
          crs={L.CRS.Simple}
          bounds={bounds}
          maxBounds={maxBounds}
          maxBoundsViscosity={0.8}
          minZoom={MIN_ZOOM}
          maxZoom={MAX_ZOOM}
          // Smooth, maps-style zooming: fractional levels, gentle wheel steps, pinch on touch screens
          zoomSnap={0.05}
          zoomDelta={0.5}
          wheelPxPerZoomLevel={90}
          wheelDebounceTime={20}
          touchZoom
          bounceAtZoomLimits
          doubleClickZoom
          zoomControl={false}
          attributionControl={false}
          className="h-full w-full !bg-[#e9e7e2]"
        >
          <ImageOverlay url={fl.imageUrl} bounds={bounds} />
          <MapBehaviour bounds={bounds} here={herePos} follow={!!gps?.follow && !!gpsHere} onMap={setMap} bottomInset={bottomInset} />

          {onSelectRoom &&
            (fl.rooms ?? []).map((r) => (
              <CircleMarker
                key={r.id}
                // Rooms are points (map data) or outlines (sample layouts); either way a finger-sized target
                center={ll(r.area ? [r.area.x + r.area.w / 2, r.area.y + r.area.h / 2] : [r.x, r.y])}
                radius={r.area ? Math.min(r.area.w, r.area.h) / 4 : 22}
                pathOptions={{ stroke: false, fillOpacity: 0 }}
                eventHandlers={{ click: () => onSelectRoom(r) }}
              >
                {canHover && (
                  <Tooltip direction="top" opacity={0.95}>
                    Route to {r.name}
                  </Tooltip>
                )}
              </CircleMarker>
            ))}

          {floorPath && (
            <>
              <Polyline positions={floorPath.map(ll)} pathOptions={{ color: '#ffffff', weight: 14, opacity: 1, lineCap: 'round', lineJoin: 'round' }} />
              <Polyline positions={floorPath.map(ll)} pathOptions={{ color: '#0a84ff', weight: 7, opacity: 0.35, dashArray: '2 12', lineCap: 'round' }} />
            </>
          )}
          {done.map(({ s }) => (
            <Polyline key={`d-${s.id}`} positions={s.pts.map(ll)} pathOptions={{ color: '#2a9d64', weight: 7, opacity: 0.9, lineCap: 'round' }} />
          ))}
          {activeOnFloor && step.pts?.length > 1 && <Polyline positions={step.pts.map(ll)} pathOptions={{ color: '#0a5fd8', weight: 9, opacity: 1, lineCap: 'round' }} />}

          {destination && (destination.floor ?? fl.id) === fl.id && <Marker position={ll([destination.x, destination.y])} icon={destIcon} title={destination.name} />}

          {/* GPS: accuracy circle + current location pointer */}
          {gpsHere && gps.accuracyPx > 0 && (
            <Circle center={gpsHere} radius={gps.accuracyPx} pathOptions={{ color: '#0a84ff', weight: 1, fillColor: '#0a84ff', fillOpacity: 0.12 }} interactive={false} />
          )}
          {gpsHere && (
            <Marker position={gpsHere} icon={gpsIcon} zIndexOffset={1000} title={gps.label}>
              <Tooltip permanent direction="top" offset={[0, -16]} className="!rounded-full !border-0 !bg-blue-600 !px-3 !py-1 !text-[12px] !font-semibold !text-white !shadow-lg before:!hidden">
                📍 {gps.label}
              </Tooltip>
            </Marker>
          )}
          {!gpsHere && stepHere && (
            <Marker position={stepHere} icon={stepIcon} zIndexOffset={900} title="Current location">
              <Tooltip permanent direction="top" offset={[0, -16]} className="!rounded-full !border-0 !bg-slate-900 !px-3 !py-1 !text-[12px] !font-semibold !text-white !shadow-lg before:!hidden">
                📍 Current location · step {active + 1}
              </Tooltip>
            </Marker>
          )}
        </MapContainer>
      </div>

      {/* Compact top bar: back, title (truncated), floor picker */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-[1000] flex items-center gap-2 px-3 sm:px-4" style={{ paddingTop: POS.headerTop }}>
        {onExit && (
          <button
            type="button"
            onClick={onExit}
            aria-label="Back to outdoor map"
            title="Back to outdoor map"
            className="pointer-events-auto flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white text-[20px] font-semibold text-slate-950 shadow-lg ring-1 ring-black/10 transition hover:bg-slate-100"
          >
            ←
          </button>
        )}
        <div className="pointer-events-auto min-w-[96px] flex-1 sm:flex-none">
          <div className="max-w-full rounded-2xl bg-slate-950/85 px-3 py-1.5 text-white backdrop-blur sm:max-w-[360px]">
            <div className="truncate text-[10px] font-medium uppercase tracking-wider text-white/70 sm:text-[11px]">{building ?? 'Floor plan'}</div>
            <div className="truncate text-[14px] font-semibold leading-tight sm:text-[15px]">{destination ? `To ${destination.name}` : fl.label}</div>
          </div>
        </div>

        {floors.length > 1 && (
          <nav
            ref={floorNav}
            aria-label="Floors"
            className="pointer-events-auto ml-auto flex max-w-[48%] shrink-0 gap-0.5 overflow-x-auto rounded-full bg-white p-1 shadow-lg ring-1 ring-black/10 [scrollbar-width:none] sm:max-w-[420px]"
          >
            {[...floors].sort((a, b) => (a.level ?? 0) - (b.level ?? 0)).map((f) => {
              const onRoute = routeFloors.includes(f.id);
              const current = f.id === fl.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setViewFloorId(f.id)}
                  aria-pressed={current}
                  aria-label={`${f.label}${onRoute ? ' (on your route)' : ''}`}
                  title={f.label}
                  data-current={current || undefined}
                  className={`relative h-9 min-w-[36px] shrink-0 rounded-full px-2.5 text-[14px] font-bold transition ${current ? 'bg-slate-950 text-white' : 'text-slate-800 hover:bg-slate-100'}`}
                >
                  {f.short ?? f.id}
                  {onRoute && <span className={`absolute right-1 top-1 h-1.5 w-1.5 rounded-full ${current ? 'bg-sky-300' : 'bg-blue-600'}`} aria-hidden="true" />}
                </button>
              );
            })}
          </nav>
        )}
      </header>

      {overlay && (
        <div className="absolute left-4 z-[1000] hidden w-[300px] lg:block" style={{ top: POS.noticeTop }}>
          {overlay}
        </div>
      )}

      {/* Peeking at another floor: one tap back to the floor you are on (bottom-left, above the steps) */}
      {step && !activeOnFloor && (
        <button
          type="button"
          onClick={() => setViewFloorId(step.floor)}
          className="absolute left-3 z-[1000] max-w-[calc(100%-6rem)] truncate rounded-full bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white shadow-lg sm:left-4"
          style={{ bottom: POS.aboveLeft }}
        >
          You are on {floors.find((f) => f.id === step.floor)?.label ?? step.floor} · show it
        </button>
      )}

      {/* Right column, bottom: 3D button above the map controls (zoom in / out, center on me, whole floor) */}
      <div className="absolute right-3 z-[1000] flex flex-col items-center gap-3 sm:right-4" style={{ bottom: POS.aboveRight }}>
        {onSwitch3D && <ViewToggleFab to="3d" onClick={onSwitch3D} />}
        <div className="flex flex-col overflow-hidden rounded-2xl bg-white shadow-lg ring-1 ring-black/10">
          <button type="button" className={btn} aria-label="Zoom in" onClick={() => map?.zoomIn(0.5)} disabled={zoom >= MAX_ZOOM}>
            +
          </button>
          <button type="button" className={`${btn} border-t border-slate-200`} aria-label="Zoom out" onClick={() => map?.zoomOut(0.5)} disabled={zoom <= MIN_ZOOM}>
            −
          </button>
          <button
            type="button"
            className={`${btn} border-t border-slate-200 text-[18px] ${gpsHere ? 'text-blue-600' : ''}`}
            aria-label="Center on current location"
            title="Center on current location"
            onClick={() => here && map?.flyTo(here, Math.max(map.getZoom(), 1), { duration: 0.6 })}
            disabled={!here}
          >
            ◎
          </button>
          <button type="button" className={`${btn} border-t border-slate-200 text-[16px]`} aria-label="Show whole floor" title="Show whole floor" onClick={() => map?.flyToBounds(bounds, { ...pad, duration: 0.6 })}>
            ⤢
          </button>
        </div>
      </div>
    </div>
  );
}
