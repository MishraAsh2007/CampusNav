/**
 * Built-in SAMPLE floor plans for 4 buildings. They are only used when no real indoor map exists for a
 * building (see indoorCatalog.js); a map file in data/indoor/ or the indoor API replaces them.
 * sampleMaps.js converts these into the same IndoorMap v1 format real map files use.
 *
 * Every floor is a 1200 x 800 image with a central corridor (the "spine"). Rooms sit above and below it.
 * Coordinates are pixels with the origin at the top-left, y pointing down, matching the image.
 * Layouts are illustrative, not surveyed plans.
 */

export const PLAN_W = 1200;
export const PLAN_H = 800;
export const FT_PER_PX = 0.12; // 1040 px corridor ≈ 125 ft
export const SPINE_Y = 400;
const SPINE_HALF = 45;
const TOP = { y0: 110, y1: SPINE_Y - SPINE_HALF };
const BOTTOM = { y0: SPINE_Y + SPINE_HALF, y1: 690 };
const X0 = 80;
const X1 = 1120;
/** Outer wall lines (entrances sit on them) and the corridor's usable x range */
export const TOP_WALL_Y = TOP.y0 - 20;
export const BOTTOM_WALL_Y = BOTTOM.y1 + 20;
export const X_MIN = X0;
export const X_MAX = X1;

/**
 * Lay rooms out along one side of the corridor.
 * cells: [name, widthUnits, extras?]  (extras: { door: 'manual' | 'automatic', type: 'restroom' | 'service' })
 */
function row(cells, side, floorId) {
  const band = side === 'top' ? TOP : BOTTOM;
  const units = cells.reduce((n, c) => n + c[1], 0);
  const unit = (X1 - X0) / units;
  let x = X0;
  return cells.map(([name, u, extra = {}]) => {
    const w = u * unit;
    const room = {
      id: `${floorId}:${name}`,
      name,
      floor: floorId,
      x,
      y: band.y0,
      w,
      h: band.y1 - band.y0,
      side,
      door: extra.door ?? (extra.type === 'service' ? undefined : 'automatic'),
      type: extra.type ?? 'room',
      // doorway on the corridor wall, centred on the room
      doorX: x + w / 2,
      doorY: side === 'top' ? band.y1 : band.y0
    };
    x += w;
    return room;
  });
}

function floor(id, label, level, top, bottom, opts = {}) {
  const rooms = [...row(top, 'top', id), ...row(bottom, 'bottom', id)];
  const elevatorRoom = rooms.find((r) => r.type === 'elevator');
  return {
    id,
    label,
    level,
    surface: opts.surface ?? 'tile',
    rooms: rooms.filter((r) => r.type !== 'elevator'),
    elevator: elevatorRoom ? { x: elevatorRoom.doorX, y: elevatorRoom.doorY, room: elevatorRoom, name: opts.elevatorName ?? 'Elevator' } : null,
    entrance: opts.entrance ?? null // { x, name, door }
  };
}

const E = { type: 'elevator' };
const RR = { type: 'restroom' };
const SV = { type: 'service' };
const MANUAL = { door: 'manual' };

export const INDOOR_BUILDINGS = {
  ilc: {
    id: 'ilc',
    name: 'Integrative Learning Center',
    entryFloor: '1',
    floors: [
      floor(
        '1',
        'Floor 1',
        1,
        [['S110 Lecture Hall', 3], ['S120', 2], ['S131 Auditorium', 3, MANUAL], ['Café', 2]],
        [['S140', 2], ['Restrooms', 1, RR], ['East Elevator', 1, E], ['Lobby', 3, SV], ['N151', 2], ['N155', 2]],
        { entrance: { x: 600, name: 'South entrance', door: 'automatic' }, elevatorName: 'East Elevator' }
      ),
      floor(
        '2',
        'Floor 2',
        2,
        [['S211', 2], ['S220 Classroom', 3], ['S231', 2], ['S240 Studio', 3, MANUAL]],
        [['N250', 2], ['Restrooms', 1, RR], ['East Elevator', 1, E], ['Study Lounge', 3], ['N260', 2], ['N265', 2]],
        { elevatorName: 'East Elevator' }
      ),
      floor(
        '3',
        'Floor 3',
        3,
        [['S311', 2], ['S320', 2], ['S331', 2], ['S335 Seminar', 2, MANUAL], ['S340', 2]],
        [['Lounge', 2], ['Restrooms', 1, RR], ['East Elevator', 1, E], ['N345 Media Lab', 3, MANUAL], ['N350', 4]],
        { surface: 'carpet', elevatorName: 'East Elevator' }
      )
    ]
  },

  'campus-center': {
    id: 'campus-center',
    name: 'Lincoln Campus Center',
    entryFloor: 'C',
    floors: [
      floor(
        'C',
        'Concourse',
        0,
        [['Food Court', 4], ['Copy Center', 2], ['Bookstore', 4]],
        [['Lockers', 2, SV], ['Restrooms', 1, RR], ['Concourse Elevator', 1, E], ['Lounge', 3], ['Info Desk', 2], ['ATM Lobby', 2, SV]],
        { entrance: { x: 150, name: 'West concourse entrance', door: 'automatic' }, elevatorName: 'Concourse Elevator' }
      ),
      floor(
        '1',
        'Level 1',
        1,
        [['Auditorium', 4, MANUAL], ['Room 101', 2], ['Room 162', 2], ['Room 165', 2]],
        [['Room 168', 2], ['Restrooms', 1, RR], ['Concourse Elevator', 1, E], ['Room 174', 2], ['Room 175', 2], ['Lounge', 3]],
        { surface: 'carpet', elevatorName: 'Concourse Elevator' }
      )
    ]
  },

  'student-union': {
    id: 'student-union',
    name: 'Student Union',
    entryFloor: '1',
    floors: [
      floor(
        '1',
        'Level 1',
        1,
        [['Info Desk', 2], ['Café', 3], ['Room 101', 2], ['Room 104', 2], ['Craft Center', 2]],
        [['Main Lobby', 3, SV], ['Atrium Elevator', 1, E], ['Restrooms', 1, RR], ['Room 112', 2], ['Room 115', 2], ['Student Activities', 3]],
        { entrance: { x: 1050, name: 'West entrance', door: 'automatic' }, elevatorName: 'Atrium Elevator' }
      ),
      floor(
        '3',
        'Level 3',
        3,
        [['Ballroom', 6, MANUAL], ['Room 301', 2], ['Room 302', 2]],
        [['Ballroom Foyer', 3], ['Atrium Elevator', 1, E], ['Restrooms', 1, RR], ['Room 311', 2], ['Room 315', 2], ['Room 318', 3]],
        { surface: 'carpet', elevatorName: 'Atrium Elevator' }
      )
    ]
  },

  'dubois-library': {
    id: 'dubois-library',
    name: 'W.E.B. Du Bois Library',
    entryFloor: '1',
    floors: [
      floor(
        '1',
        'Floor 1',
        1,
        [['Circulation Desk', 3], ['Periodicals', 3], ['Procrastination Station Café', 3], ['Room 120', 2]],
        [['Lobby', 3, SV], ['Information Desk', 2], ['Low-rise Elevators', 1, E], ['Restrooms', 1, RR], ['Room 130', 2], ['Room 135', 2]],
        { entrance: { x: 260, name: 'Main lobby entrance', door: 'automatic' }, elevatorName: 'Low-rise Elevators' }
      ),
      floor(
        'LL',
        'Lower Level',
        -1,
        [['Learning Commons', 5], ['Assistive Technology Center', 3], ['Writing Center', 2]],
        [['Group Study Rooms', 3], ['Help Desk', 2], ['Low-rise Elevators', 1, E], ['Restrooms', 1, RR], ['Digital Media Lab', 2, MANUAL], ['Room LL40', 2]],
        { surface: 'carpet', elevatorName: 'Low-rise Elevators' }
      )
    ]
  }
};

// ------------------------------------------------------------------ floor plan images

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);

/** Clean architectural-style SVG plan for a floor, as a data URL usable by Leaflet's ImageOverlay. */
export function floorPlanImage(fl) {
  const parts = [];
  parts.push(`<rect width="${PLAN_W}" height="${PLAN_H}" fill="#f4f2ee"/>`);
  // building shell
  parts.push(`<rect x="${X0 - 20}" y="${TOP.y0 - 20}" width="${X1 - X0 + 40}" height="${BOTTOM.y1 - TOP.y0 + 40}" rx="6" fill="#ffffff" stroke="#2b2b2b" stroke-width="10"/>`);
  // corridor
  const corr = fl.surface === 'carpet' ? '#efe9f4' : '#f7f7f5';
  parts.push(`<rect x="${X0}" y="${SPINE_Y - SPINE_HALF}" width="${X1 - X0}" height="${SPINE_HALF * 2}" fill="${corr}"/>`);
  if (fl.surface !== 'carpet') {
    for (let x = X0; x < X1; x += 30) parts.push(`<line x1="${x}" y1="${SPINE_Y - SPINE_HALF}" x2="${x}" y2="${SPINE_Y + SPINE_HALF}" stroke="#e6e4df" stroke-width="1"/>`);
  }
  const labels = []; // drawn last so the entrance never covers a room name
  const all = [...fl.rooms, ...(fl.elevator ? [fl.elevator.room] : [])];
  for (const r of all) {
    const fill = r.type === 'elevator' ? '#e7e3f7' : r.type === 'restroom' ? '#e4f1fb' : r.type === 'service' ? '#f1efe9' : '#fbfaf8';
    parts.push(`<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="${fill}" stroke="#3a3a3a" stroke-width="4"/>`);
    // doorway gap + swing
    const dw = Math.min(46, r.w * 0.5);
    parts.push(`<line x1="${r.doorX - dw / 2}" y1="${r.doorY}" x2="${r.doorX + dw / 2}" y2="${r.doorY}" stroke="${corr}" stroke-width="7"/>`);
    if (r.type !== 'elevator') {
      const dir = r.side === 'top' ? -1 : 1;
      parts.push(`<path d="M ${r.doorX - dw / 2} ${r.doorY} A ${dw} ${dw} 0 0 ${r.side === 'top' ? 1 : 0} ${r.doorX + dw / 2} ${r.doorY + dir * dw}" fill="none" stroke="#9a9a9a" stroke-width="1.5" stroke-dasharray="4 3"/>`);
    }
    const cx = r.x + r.w / 2;
    const cy = r.y + r.h / 2;
    if (r.type === 'elevator') {
      parts.push(`<rect x="${cx - 26}" y="${cy - 34}" width="52" height="68" rx="6" fill="#6e56cf"/>`);
      parts.push(`<path d="M ${cx - 10} ${cy - 8} l 10 -14 l 10 14 z M ${cx - 10} ${cy + 8} l 10 14 l 10 -14 z" fill="#fff"/>`);
    } else if (r.type === 'restroom') {
      parts.push(`<text x="${cx}" y="${cy + 12}" text-anchor="middle" font-size="34" font-family="Inter, Arial, sans-serif">♿</text>`);
    }
    const label = r.type === 'elevator' ? 'Elevator' : r.name;
    const words = label.split(' ');
    const lines = [];
    let cur = '';
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (next.length * 10 > r.w - 16 && cur) {
        lines.push(cur);
        cur = w;
      } else cur = next;
    }
    lines.push(cur);
    const ly = r.type === 'elevator' || r.type === 'restroom' ? r.y + (r.side === 'top' ? 34 : r.h - 22) : cy - ((lines.length - 1) * 22) / 2 + 7;
    lines.forEach((ln, i) =>
      labels.push(`<text x="${cx}" y="${ly + i * 22}" text-anchor="middle" font-size="18" font-weight="600" fill="#2b2b2b" font-family="Inter, Arial, sans-serif">${esc(ln)}</text>`)
    );
    if (r.door === 'manual') labels.push(`<text x="${cx}" y="${r.side === 'top' ? r.y + r.h - 14 : r.y + 24}" text-anchor="middle" font-size="13" fill="#9a6400" font-family="Inter, Arial, sans-serif">manual door</text>`);
  }
  for (const ent of fl.entrances ?? (fl.entrance ? [fl.entrance] : [])) {
    const ex = ent.x;
    const north = ent.side === 'top';
    const ey = north ? TOP.y0 - 20 : BOTTOM.y1 + 20;
    parts.push(
      north
        ? `<rect x="${ex - 40}" y="${ey}" width="80" height="${TOP.y1 - ey}" fill="${corr}"/>`
        : `<rect x="${ex - 40}" y="${BOTTOM.y0}" width="80" height="${BOTTOM.y1 - BOTTOM.y0 + 20}" fill="${corr}"/>`
    );
    parts.push(`<line x1="${ex - 38}" y1="${ey}" x2="${ex + 38}" y2="${ey}" stroke="#0a84ff" stroke-width="10"/>`);
    labels.push(`<text x="${ex}" y="${north ? ey - 14 : ey + 40}" text-anchor="middle" font-size="16" font-weight="700" fill="#0a5fb4" font-family="Inter, Arial, sans-serif">${esc(ent.name)}</text>`);
  }
  parts.push(...labels);
  parts.push(`<text x="${X0 - 10}" y="58" font-size="30" font-weight="700" fill="#1d1d1f" font-family="Inter, Arial, sans-serif">${esc(fl.label)}</text>`);
  parts.push(`<text x="${X1 + 10}" y="58" text-anchor="end" font-size="15" fill="#6e6e73" font-family="Inter, Arial, sans-serif">Sample layout · not to scale</text>`);
  // north arrow + scale bar
  const sb = 25 / FT_PER_PX; // 25 ft
  parts.push(`<line x1="${X1 - sb}" y1="${PLAN_H - 30}" x2="${X1}" y2="${PLAN_H - 30}" stroke="#1d1d1f" stroke-width="4"/>`);
  parts.push(`<text x="${X1 - sb / 2}" y="${PLAN_H - 40}" text-anchor="middle" font-size="14" fill="#1d1d1f" font-family="Inter, Arial, sans-serif">25 ft</text>`);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PLAN_W}" height="${PLAN_H}" viewBox="0 0 ${PLAN_W} ${PLAN_H}">${parts.join('')}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

