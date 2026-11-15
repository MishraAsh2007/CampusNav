/**
 * Turns an indoor map in the team's IndoorMap v1 format (contracts/indoor-map.schema.json, produced by
 * the campus_routing / Role 3 pipeline: data/indoor/<building>.json or GET /indoor/maps/{id}) into
 * what the 2D/3D views draw and route on.
 *
 * Nothing in here knows about specific buildings. A new building (dorms included) only needs a map
 * file with floors, nodes (rooms, entrances, junctions, elevator stops) and edges.
 *
 * Display pixels: every floor gets a pixel space for Leaflet's CRS.Simple.
 *   image_pixels floors use the image's own pixels (y down).
 *   local_meters floors (and floors without image size) are scaled to fit, north up.
 * A floor without a usable image (none, or an ArcGIS MapServer URL) gets a schematic drawn from its
 * corridors and rooms.
 *
 * GPS: a floor's lat/lng <-> pixel transform comes from, in order: explicit `bounds` on the floor
 * (top-left / bottom-right lat/lng of the image), or a fit through points with known coordinates
 * (entrances with `position`, elevator stops via their asset's `position`, portal geometry).
 */
import { imageToGeo, geoToImage, metresPerPx } from './floorCalibration';

const DISPLAYABLE = /^data:image\/|\.(png|jpe?g|gif|webp|svg)(\?|#|$)/i;
export const isDisplayableImage = (url) => typeof url === 'string' && DISPLAYABLE.test(url);

const M_PER_DEG_LAT = 110540;
const mPerDegLng = (lat) => 111320 * Math.cos((lat * Math.PI) / 180);
const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const polyLen = (pts) => pts.reduce((n, p, i) => (i ? n + dist(pts[i - 1], p) : 0), 0);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** Floor order from data: explicit `level`, else parsed from id/label ("Lower Level" -1, "Concourse" 0, "3rd Floor" 3). */
export function levelOf(floor, index = 0) {
  if (Number.isFinite(floor.level)) return floor.level;
  const t = `${floor.id} ${floor.label ?? ''}`.toLowerCase();
  if (/lower[\s-]*level|\bll\b|basement|\bb\d?\b|cellar/.test(t)) {
    const m = /(?:basement|lower[\s-]*level|\bb)\s*(\d)/.exec(t);
    return -(m ? Number(m[1]) : 1);
  }
  if (/concourse|ground|\bg\b|plaza|lobby level/.test(t)) return 0;
  const m = /(-?\d+)/.exec(t);
  return m ? Number(m[1]) : index;
}

/** Floor picker label: "1st-floor" -> "1", "lower-level" -> "LL", "C" stays "C". */
function shortFloor(f) {
  if (String(f.id).length <= 3) return String(f.id);
  const t = `${f.id} ${f.label ?? ''}`.toLowerCase();
  if (/lower[\s-]*level/.test(t)) return 'LL';
  if (/basement/.test(t)) return 'B';
  if (/concourse/.test(t)) return 'C';
  if (/ground/.test(t)) return 'G';
  return Number.isFinite(f.level) ? String(f.level) : String(f.id).slice(0, 3);
}

const RESTROOM = /restroom|bathroom|toilet|washroom|\bwc\b|lavatory/i;

/** Words that name the building ("ILC", "Library", "Integrative"…), to drop from the front of labels. */
function buildingWords(building) {
  const words = String(building.name ?? '').replace(/[^A-Za-z0-9 ]/g, ' ').split(/\s+/).filter(Boolean);
  const initials = words.filter((w) => /^[A-Z]/.test(w) && !/^(of|and|the)$/i.test(w)).map((w) => w[0]).join('');
  return new Set([...words, initials, building.code, building.id].filter(Boolean).map((w) => String(w).toLowerCase()));
}

/** "ILC East Elevator" -> "East Elevator", "Library South Entrance" -> "South Entrance" */
function stripBuilding(label, building) {
  const own = buildingWords(building);
  const words = String(label ?? '').trim().split(/\s+/);
  let i = 0;
  while (i < words.length - 1 && own.has(words[i].toLowerCase().replace(/[^a-z0-9]/g, ''))) i++;
  return words.slice(i).join(' ');
}

/** "ILC N111, 1st Floor entryway" -> "N111 entryway" */
function roomName(label, building) {
  const s = stripBuilding(label, building)
    .replace(/,?\s*(?:\d+(?:st|nd|rd|th)|lower|ground)\s+(?:floor|level)\b/i, '')
    .replace(/\s+,/g, ',')
    .replace(/,\s*$/, '')
    .trim();
  return s || String(label ?? '').trim();
}

/** For "Enter through the …": "South Entrance (North Pleasant St)" -> "south entrance (North Pleasant St)" */
export function inSentence(name) {
  return String(name)
    .replace(/^([A-Z][a-z]+)\b/, (w) => w.toLowerCase())
    .replace(/\b(Entrance|Entry|Door|Doors|Elevator|Elevators|Lobby)\b/g, (w) => w.toLowerCase());
}

// ------------------------------------------------------------------ georeference

function localMetres(lat, lng, ref) {
  return [(lng - ref.lng) * mPerDegLng(ref.lat), (lat - ref.lat) * M_PER_DEG_LAT];
}
function fromLocal([e, n], ref) {
  return { lat: ref.lat + n / M_PER_DEG_LAT, lng: ref.lng + e / mPerDegLng(ref.lat) };
}

/** Pixel <-> lat/lng from the image's corner coordinates (exact for north-up images). */
function boundsGeoref(bounds, width, height) {
  const cal = { topLeft: bounds.topLeft, bottomRight: bounds.bottomRight, width, height };
  return {
    kind: 'bounds',
    toPx: (lat, lng) => geoToImage(cal, lat, lng),
    toGeo: (p) => imageToGeo(cal, p),
    mPerPx: metresPerPx(cal)
  };
}

/**
 * Similarity transform (scale, rotation, shift) through control points { px:[x,y], lat, lng }.
 * One point: assume north up at the floor's own scale. Pixels are y-down, so y is flipped first.
 */
function fitGeoref(controls, pxPerM) {
  if (!controls.length) return null;
  const ref = { lat: controls[0].lat, lng: controls[0].lng };
  const P = controls.map((c) => [c.px[0], -c.px[1]]);
  const Q = controls.map((c) => localMetres(c.lat, c.lng, ref));
  const spread = Math.max(...Q.map((q) => dist(q, Q[0])));
  let a;
  let b;
  let tx;
  let ty;
  if (controls.length >= 2 && spread >= 3) {
    const pm = [P.reduce((s, p) => s + p[0], 0) / P.length, P.reduce((s, p) => s + p[1], 0) / P.length];
    const qm = [Q.reduce((s, q) => s + q[0], 0) / Q.length, Q.reduce((s, q) => s + q[1], 0) / Q.length];
    let sa = 0;
    let sb = 0;
    let norm = 0;
    P.forEach((p, i) => {
      const u = [p[0] - pm[0], p[1] - pm[1]];
      const v = [Q[i][0] - qm[0], Q[i][1] - qm[1]];
      sa += u[0] * v[0] + u[1] * v[1];
      sb += u[0] * v[1] - u[1] * v[0];
      norm += u[0] * u[0] + u[1] * u[1];
    });
    if (norm < 1e-9) return null;
    a = sa / norm;
    b = sb / norm;
    tx = qm[0] - (a * pm[0] - b * pm[1]);
    ty = qm[1] - (b * pm[0] + a * pm[1]);
  } else {
    a = 1 / pxPerM;
    b = 0;
    tx = Q[0][0] - a * P[0][0];
    ty = Q[0][1] - a * P[0][1];
  }
  const s2 = a * a + b * b;
  return {
    kind: controls.length >= 2 && spread >= 3 ? 'fit' : 'single-point',
    toPx: (lat, lng) => {
      const [e, n] = localMetres(lat, lng, ref);
      const u = (a * (e - tx) + b * (n - ty)) / s2;
      const v = (-b * (e - tx) + a * (n - ty)) / s2;
      return [u, -v];
    },
    toGeo: ([x, y]) => fromLocal([a * x - b * -y + tx, b * x + a * -y + ty], ref),
    mPerPx: Math.sqrt(s2)
  };
}

// ------------------------------------------------------------------ schematic plan

/** A clean plan drawn from the floor's own corridors and rooms, for floors with no usable image. */
function schematicImage(floor, nodes, edges, pxPerM, sample) {
  const W = Math.round(floor.width);
  const H = Math.round(floor.height);
  // Text and symbols grow with the canvas so they stay readable when the floor is fitted to a phone
  const k = Math.max(1, Math.max(W, H) / 1000);
  const fs = (px) => Math.round(px * k);
  const corridorW = Math.max(14 * k, Math.min(46 * k, 2.2 * pxPerM));
  const parts = [`<rect width="${W}" height="${H}" fill="#f4f2ee"/>`];
  const line = (pts, stroke, w, extra = '') =>
    `<polyline points="${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')}" fill="none" stroke="${stroke}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;
  for (const e of edges) parts.push(line(e.pts, '#cfcac0', corridorW + 6));
  for (const e of edges)
    parts.push(
      e.kind === 'steps'
        ? line(e.pts, '#8a8a8a', corridorW * 0.6, 'stroke-dasharray="6 6"')
        : line(e.pts, e.kind === 'ramp' ? '#fde7c8' : '#fbfaf8', corridorW)
    );
  const labels = [];
  for (const n of nodes) {
    const [x, y] = n.px;
    if (n.kind === 'elevator_stop') {
      parts.push(`<rect x="${x - fs(15)}" y="${y - fs(18)}" width="${fs(30)}" height="${fs(36)}" rx="6" fill="#6e56cf"/>`);
      parts.push(`<path d="M ${x - fs(7)} ${y - fs(3)} l ${fs(7)} ${-fs(9)} l ${fs(7)} ${fs(9)} z M ${x - fs(7)} ${y + fs(4)} l ${fs(7)} ${fs(9)} l ${fs(7)} ${-fs(9)} z" fill="#fff"/>`);
      if (n.assetLabel) labels.push(`<text x="${x}" y="${y + fs(34)}" text-anchor="middle" font-size="${fs(13)}" font-weight="600" fill="#4b3a9e" font-family="Inter, Arial, sans-serif">${esc(n.assetLabel)}</text>`);
    } else if (n.kind === 'entrance') {
      parts.push(`<rect x="${x - fs(22)}" y="${y - fs(6)}" width="${fs(44)}" height="${fs(12)}" rx="${fs(6)}" fill="#0a84ff"/>`);
      labels.push(`<text x="${x}" y="${y - fs(14)}" text-anchor="middle" font-size="${fs(14)}" font-weight="700" fill="#0a5fb4" font-family="Inter, Arial, sans-serif">${esc(n.label ?? 'Entrance')}</text>`);
    } else if (n.kind === 'room') {
      const restroom = RESTROOM.test(n.label ?? '');
      parts.push(`<circle cx="${x}" cy="${y}" r="${fs(9)}" fill="${restroom ? '#0a84ff' : '#1d1d1f'}" stroke="#fff" stroke-width="${fs(3)}"/>`);
      labels.push(`<text x="${x}" y="${y - fs(16)}" text-anchor="middle" font-size="${fs(15)}" font-weight="600" fill="#2b2b2b" font-family="Inter, Arial, sans-serif" paint-order="stroke" stroke="#f4f2ee" stroke-width="${fs(4)}">${esc(n.name ?? n.label)}</text>`);
    } else if (n.kind === 'stair_landing') {
      parts.push(`<rect x="${x - fs(9)}" y="${y - fs(9)}" width="${fs(18)}" height="${fs(18)}" fill="#8a8a8a"/>`);
    }
  }
  parts.push(...labels);
  parts.push(`<text x="${fs(24)}" y="${fs(40)}" font-size="${fs(26)}" font-weight="700" fill="#1d1d1f" font-family="Inter, Arial, sans-serif">${esc(floor.label)}</text>`);
  parts.push(
    `<text x="${W - fs(24)}" y="${fs(40)}" text-anchor="end" font-size="${fs(13)}" fill="#6e6e73" font-family="Inter, Arial, sans-serif">${sample ? 'Sample layout' : 'Schematic from building data'} · not to scale</text>`
  );
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${parts.join('')}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

// ------------------------------------------------------------------ normalise

function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

const contentPts = (nodes, edges) =>
  [...nodes.map((n) => [n.x, n.y]), ...edges.flatMap((e) => e.geometry ?? [])].filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));

/**
 * Display space for one floor: size, raw coordinate -> pixel, pixels per metre.
 * cropBox: for image-pixel floors whose image can't be shown, draw only the area with content
 * (shared by floors of the same image size, so stacked floors stay aligned).
 */
function displaySpace(f, nodes, edges, cropBox = null) {
  const pts = contentPts(nodes, edges);
  if (cropBox) {
    const pad = 70;
    return { width: cropBox.maxX - cropBox.minX + 2 * pad, height: cropBox.maxY - cropBox.minY + 2 * pad, toPx: (x, y) => [x - cropBox.minX + pad, y - cropBox.minY + pad], measured: true };
  }
  if (f.coordinate_system !== 'local_meters' && f.image_width > 0 && f.image_height > 0) {
    return { width: f.image_width, height: f.image_height, toPx: (x, y) => [x, y], measured: true };
  }
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = xs.length ? [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)] : [0, 10, 0, 10];
  if (f.coordinate_system !== 'local_meters') {
    // Image pixels without a declared size: fit around the content
    return { width: Math.max(480, maxX + 80), height: Math.max(360, maxY + 80), toPx: (x, y) => [x, y], measured: true };
  }
  const spanX = Math.max(8, maxX - minX);
  const spanY = Math.max(8, maxY - minY);
  const s = Math.max(3, Math.min(40, 820 / Math.max(spanX, spanY)));
  const pad = 90;
  return {
    width: Math.max(480, spanX * s + 2 * pad),
    height: Math.max(360, spanY * s + 2 * pad),
    toPx: (x, y) => [pad + (x - minX) * s, pad + (maxY - y) * s], // north up
    pxPerM: s
  };
}

/**
 * IndoorMap v1 -> model. Returns null when the map can't be used (no floors / nodes / edges).
 *   source   'api' | 'data' | 'sample'
 */
export function normalizeIndoorMap(raw, { source = 'data', imageOverrides = {} } = {}) {
  if (!raw || typeof raw.building_id !== 'string' || !Array.isArray(raw.floors) || !raw.floors.length) return null;
  const rawNodes = Array.isArray(raw.nodes) ? raw.nodes : [];
  const rawEdges = Array.isArray(raw.edges) ? raw.edges : [];
  if (!rawNodes.length || !rawEdges.length) return null;

  const building = { id: raw.building_id, name: raw.name ?? raw.building_id, code: raw.code };
  const rawById = new Map(rawNodes.map((n) => [n.id, n]));
  const assets = new Map((raw.assets ?? []).map((a) => [a.id, a]));
  const portals = raw.portals ?? [];
  const floorOf = (id) => rawById.get(id)?.floor_id;

  // Image-pixel floors with no image we can draw (none, or an ArcGIS MapServer URL) and no corner
  // bounds: crop to the content, using one box per image size so stacked floors keep lining up
  const cropGroup = (f) =>
    f.coordinate_system !== 'local_meters' && f.image_width > 0 && f.image_height > 0 && !isDisplayableImage(f.image_url) && !f.bounds && !imageOverrides[f.id]
      ? `${f.image_width}x${f.image_height}`
      : null;
  const crops = new Map();
  for (const f of raw.floors) {
    const key = cropGroup(f);
    if (!key) continue;
    const pts = contentPts(
      rawNodes.filter((n) => n.floor_id === f.id),
      rawEdges.filter((e) => e.kind !== 'elevator' && floorOf(e.start) === f.id)
    );
    if (!pts.length) continue;
    const box = crops.get(key) ?? { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    for (const [x, y] of pts) Object.assign(box, { minX: Math.min(box.minX, x), minY: Math.min(box.minY, y), maxX: Math.max(box.maxX, x), maxY: Math.max(box.maxY, y) });
    crops.set(key, box);
  }

  const floors = raw.floors
    .map((f, i) => ({ ...f, level: levelOf(f, i), order: i }))
    .sort((a, b) => a.level - b.level || a.order - b.order)
    .map((f) => {
      const fn = rawNodes.filter((n) => n.floor_id === f.id);
      const fe = rawEdges.filter((e) => e.kind !== 'elevator' && floorOf(e.start) === f.id && floorOf(e.end) === f.id);
      const space = displaySpace(f, fn, fe, crops.get(cropGroup(f)) ?? null);
      // Pixels per metre from the edges' own lengths, unless the floor is already in metres
      let pxPerM = space.pxPerM;
      if (!pxPerM) {
        const ratios = fe
          .filter((e) => e.length_m > 0)
          .map((e) => polyLen((e.geometry ?? [rawById.get(e.start), rawById.get(e.end)].map((n) => [n.x, n.y])).map((p) => space.toPx(p[0], p[1]))) / e.length_m)
          .filter((r) => r > 0 && Number.isFinite(r));
        pxPerM = median(ratios) ?? 10;
      }
      return {
        id: f.id,
        label: f.label ?? `Floor ${f.id}`,
        short: shortFloor(f),
        level: f.level,
        surface: f.surface ?? 'tile',
        width: space.width,
        height: space.height,
        toPx: space.toPx,
        pxPerM,
        rawImage: f.image_url ?? null,
        coordinateSystem: f.coordinate_system ?? 'image_pixels',
        bounds: f.bounds ?? null,
        aliases: f.aliases ?? []
      };
    });
  const floorById = new Map(floors.map((f) => [f.id, f]));

  // Nodes in display pixels
  const nodes = new Map();
  for (const n of rawNodes) {
    const f = floorById.get(n.floor_id);
    if (!f || !Number.isFinite(n.x) || !Number.isFinite(n.y)) continue;
    nodes.set(n.id, { ...n, floor: f.id, px: f.toPx(n.x, n.y), name: n.kind === 'room' ? roomName(n.label, building) : n.label });
  }

  // Edges + adjacency
  const edges = [];
  const adj = new Map([...nodes.keys()].map((id) => [id, []]));
  for (const e of rawEdges) {
    const a = nodes.get(e.start);
    const b = nodes.get(e.end);
    if (!a || !b) continue;
    const f = floorById.get(a.floor);
    const pxGeom = e.kind !== 'elevator' && a.floor === b.floor && Array.isArray(e.geometry) && e.geometry.length >= 2 ? e.geometry.map((p) => f.toPx(p[0], p[1])) : null;
    const lengthM = e.length_m > 0 ? e.length_m : a.floor === b.floor ? polyLen(pxGeom ?? [a.px, b.px]) / f.pxPerM : 4;
    const edge = { ...e, pxGeom, lengthM };
    edges.push(edge);
    adj.get(a.id).push({ to: b.id, edge });
    if (e.bidirectional !== false) adj.get(b.id).push({ to: a.id, edge });
  }

  // Labels for elevator stops (from their asset) and door types for entrances (from portals)
  for (const e of edges) {
    if (e.kind !== 'elevator' || !e.asset_id) continue;
    const raw = assets.get(e.asset_id)?.label;
    const label = raw ? stripBuilding(raw, building) : null;
    for (const id of [e.start, e.end]) {
      const n = nodes.get(id);
      if (n && !n.assetId) Object.assign(n, { assetId: e.asset_id, assetLabel: label ?? 'Elevator' });
    }
  }
  const portalOf = new Map(portals.map((p) => [p.indoor_node_id, p]));

  // Georeference control points per floor
  const controls = new Map(floors.map((f) => [f.id, []]));
  for (const n of nodes.values()) {
    let pos = n.position;
    if (!pos && portalOf.get(n.id)?.geometry?.[0]) {
      const [lng, lat] = portalOf.get(n.id).geometry[0];
      pos = { lat, lng };
    }
    if (!pos && n.assetId) pos = assets.get(n.assetId)?.position ?? null;
    if (pos && Number.isFinite(pos.lat) && Number.isFinite(pos.lng)) {
      n.geo = { lat: pos.lat, lng: pos.lng };
      controls.get(n.floor).push({ px: n.px, lat: pos.lat, lng: pos.lng });
    }
  }
  for (const f of floors) {
    f.georef = f.bounds?.topLeft && f.bounds?.bottomRight ? boundsGeoref(f.bounds, f.width, f.height) : fitGeoref(controls.get(f.id), f.pxPerM);
  }
  // Floors with no known point share a stacked floor's transform (same image size and coordinates)
  for (const f of floors) {
    if (f.georef) continue;
    const twin = floors
      .filter((g) => g.georef && g.coordinateSystem === f.coordinateSystem && Math.abs(g.width - f.width) < 1 && Math.abs(g.height - f.height) < 1)
      .sort((g1, g2) => controls.get(g2.id).length - controls.get(g1.id).length)[0];
    if (twin) f.georef = twin.georef;
  }

  // Image overrides with their own corner coordinates: move this floor's geometry into the new image's
  // pixels through lat/lng (needs a georeference for the floor)
  for (const f of floors) {
    const o = imageOverrides[f.id];
    if (!o || !f.georef) continue;
    const target = boundsGeoref({ topLeft: o.topLeft, bottomRight: o.bottomRight }, o.width, o.height);
    const from = f.georef;
    const move = (p) => {
      const g = from.toGeo(p);
      return target.toPx(g.lat, g.lng);
    };
    for (const n of nodes.values()) if (n.floor === f.id) n.px = move(n.px);
    for (const e of edges) if (e.pxGeom && nodes.get(e.start).floor === f.id) e.pxGeom = e.pxGeom.map(move);
    for (const c of controls.get(f.id)) c.px = move(c.px);
    f.pxPerM = f.pxPerM * (from.mPerPx / target.mPerPx);
    Object.assign(f, { width: o.width, height: o.height, georef: target, rawImage: o.url, coordinateSystem: 'image_pixels' });
  }

  // Images: use the plan when it is a real image in this floor's pixel space, else draw a schematic
  for (const f of floors) {
    const fn = [...nodes.values()].filter((n) => n.floor === f.id);
    const fe = edges.filter((e) => e.kind !== 'elevator' && nodes.get(e.start).floor === f.id && nodes.get(e.end).floor === f.id).map((e) => ({ kind: e.kind, pts: e.pxGeom ?? [nodes.get(e.start).px, nodes.get(e.end).px] }));
    f.imageUrl = f.coordinateSystem === 'image_pixels' && isDisplayableImage(f.rawImage) ? f.rawImage : schematicImage(f, fn, fe, f.pxPerM, source === 'sample');
    f.schematic = !(f.coordinateSystem === 'image_pixels' && isDisplayableImage(f.rawImage));
  }

  // Rooms (destinations) and entrances
  const doorInto = (id) => (adj.get(id) ?? []).map((x) => x.edge).find((e) => e.kind === 'door');
  const rooms = [...nodes.values()]
    .filter((n) => n.kind === 'room')
    .map((n) => ({
      id: n.id,
      name: n.name,
      floor: n.floor,
      floorLabel: floorById.get(n.floor).label,
      x: n.px[0],
      y: n.px[1],
      type: RESTROOM.test(n.label ?? '') ? 'restroom' : 'room',
      door: doorInto(n.id)?.door_type === 'manual' ? 'manual' : 'automatic',
      aliases: n.aliases ?? [],
      // Optional room outline {x,y,w,h} in the floor's coordinates (sample layouts): a bigger tap target
      area: n.area && floorById.get(n.floor).coordinateSystem === 'image_pixels' ? n.area : null
    }))
    .sort((a, b) => floorById.get(a.floor).level - floorById.get(b.floor).level || a.name.localeCompare(b.name, undefined, { numeric: true }));
  const entrances = [...nodes.values()]
    .filter((n) => n.kind === 'entrance')
    .map((n) => {
      const portal = portalOf.get(n.id);
      const firstEdge = adj.get(n.id)?.[0]?.edge;
      const door = portal?.door_type ?? n.door_type ?? firstEdge?.door_type ?? 'unknown';
      const stepFree = portal?.step_free !== false && n.step_free !== false && firstEdge?.step_free !== false;
      return { id: n.id, name: stripBuilding(n.label ?? 'Entrance', building), floor: n.floor, px: n.px, geo: n.geo ?? null, door, stepFree };
    });

  // Entry floor: given, else the floor with the most entrances (ties: closest to ground)
  let entryFloor = raw.entry_floor && floorById.has(raw.entry_floor) ? raw.entry_floor : null;
  if (!entryFloor) {
    const count = (id) => entrances.filter((e) => e.floor === id).length;
    entryFloor = [...floors].sort((a, b) => count(b.id) - count(a.id) || Math.abs(a.level - 1) - Math.abs(b.level - 1))[0].id;
  }

  const geos = [...nodes.values()].map((n) => n.geo).filter(Boolean);
  const centroid = geos.length ? { lat: geos.reduce((s, g) => s + g.lat, 0) / geos.length, lng: geos.reduce((s, g) => s + g.lng, 0) / geos.length } : null;

  return {
    id: raw.building_id,
    name: building.name,
    status: raw.status ?? 'draft',
    synthetic: !!raw.synthetic,
    sample: source === 'sample',
    source,
    reviewedAt: raw.reviewed_at ?? null,
    sources: raw.sources ?? [],
    floors,
    floorById,
    nodes,
    edges,
    adj,
    assets,
    rooms,
    entrances,
    entryFloor,
    centroid,
    hasElevator: edges.some((e) => e.kind === 'elevator')
  };
}

/** Can people be routed in this map? Needs an entrance and something to go to. */
export function isNavigable(model) {
  return !!model && model.entrances.length > 0 && (model.rooms.length > 0 || model.hasElevator);
}

export const lobbyId = (floorId) => `${floorId}:@lobby`;

/** Rooms plus "whole floor" targets (arrive at that floor's elevator), for room pickers. */
export function destinationsOf(model) {
  if (!model) return [];
  const lobbies = model.hasElevator
    ? model.floors
        .filter((f) => [...model.nodes.values()].some((n) => n.floor === f.id && n.kind === 'elevator_stop'))
        .map((f) => ({ id: lobbyId(f.id), name: `${f.label} (elevator lobby)`, floor: f.id, floorLabel: f.label, type: 'lobby' }))
    : [];
  return [...model.rooms, ...lobbies];
}
