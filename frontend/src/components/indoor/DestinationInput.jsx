import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { lobbyId } from './indoorModel';
import { useIndoorEntries } from './indoorCatalog';

/**
 * Universal destination search across every building with an indoor map (indoorCatalog.js), its
 * floors and its rooms. Buildings, names and aliases come from the data, so new buildings (dorms
 * included) are searchable without code changes.
 *
 *   "ILC"              -> the building
 *   "ILC 311"          -> room S311 in the ILC
 *   "Du Bois Floor 3"  -> that floor, or "Floor 3 isn't mapped yet" if there is no plan for it
 *   "ballroom"         -> rooms with that name in any building
 *
 * Props
 *   onSelect(target)  target = { type: 'building' | 'floor' | 'room', buildingId, buildingName,
 *                                roomId (room id, or "<floor>:@lobby" for a floor, null for a building),
 *                                floorId, label, lat, lng }
 *   scopeBuildingId   only search inside this building (used inside the indoor views)
 *   value             label to show when not typing (the current destination)
 *   placeholder, className, compact
 *   autoFocus         focus (and open the list) on mount
 *   onDismiss         called when the input loses focus (after a pick, Escape, or tapping away)
 */

// Extra nicknames people use. Optional: every building also gets aliases from its own name and code.
const NICKNAMES = {
  'campus-center': ['murray d lincoln', 'lincoln'],
  'student-union': ['union'],
  'dubois-library': ['dubois', 'library'],
  library: ['dubois', 'library']
};

const FILLER = /\b(room|rm|rooms|in|at|the|to|go|take me|building|bldg|#)\b/g;
const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
const compact = (s) => norm(s).replace(/\s/g, '');
// Words too generic to stand for a building on their own
const GENERIC = new Set(['the', 'of', 'and', 'hall', 'center', 'centre', 'building', 'house', 'campus', 'student', 'learning', 'w', 'e', 'b', 'lincoln', 'murray', 'd']);

/** Aliases from data: full name, name without "the"/punctuation, code, initials, distinctive words and word pairs. */
function aliasesFor(entry) {
  const name = norm(entry.name);
  const words = name.split(' ').filter(Boolean);
  const out = new Set([name, norm(entry.code ?? ''), norm(entry.buildingId.replace(/-/g, ' '))]);
  const initials = words.filter((w) => !['of', 'and', 'the'].includes(w)).map((w) => w[0]).join('');
  if (initials.length >= 2) out.add(initials);
  for (let i = 0; i + 1 < words.length; i++) out.add(`${words[i]} ${words[i + 1]}`);
  for (const w of words) if (w.length >= 4 && !GENERIC.has(w)) out.add(w);
  for (const n of NICKNAMES[entry.buildingId] ?? NICKNAMES[entry.model.id] ?? []) out.add(n);
  out.delete('');
  return [...out];
}

/** Split "du bois floor 3" into { entry, rest: 'floor 3' } (longest alias wins). */
function detectBuilding(q, entries) {
  let best = null;
  for (const e of entries) {
    for (const a of e.aliases) {
      const re = new RegExp(`(^| )${a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/ /g, ' ?')}( |$)`);
      const hit = re.exec(q);
      if (hit && (!best || a.length > best.len)) best = { entry: e, len: a.length, rest: (q.slice(0, hit.index) + ' ' + q.slice(hit.index + hit[0].length)).trim() };
    }
  }
  return best ? { entry: best.entry, rest: best.rest } : { entry: null, rest: q };
}

/** "floor 3", "3rd floor", "level 1", "lower level", "ll", "concourse" -> { level, token } */
function detectFloor(rest) {
  if (/\b(lower level|basement|ll)\b/.test(rest)) return { level: -1, token: 'Lower Level', rest: rest.replace(/\b(lower level|basement|ll)\b/, '').trim() };
  if (/\b(concourse|ground floor|ground)\b/.test(rest)) return { level: 0, token: 'Concourse', rest: rest.replace(/\b(concourse|ground floor|ground)\b/, '').trim() };
  const m = /\b(?:floor|level|fl|lvl|flr)\s*(\d+)\b/.exec(rest) || /\b(\d+)(?:st|nd|rd|th)\s*(?:floor|level|fl)?\b/.exec(rest);
  return m ? { level: Number(m[1]), token: `Floor ${m[1]}`, rest: (rest.slice(0, m.index) + rest.slice(m.index + m[0].length)).trim() } : { level: null, token: null, rest };
}

/**
 * entries: resolved catalog entries [{ buildingId, model, name, code, location }]
 */
export function searchDestinations(query, scopeBuildingId, catalogEntries = []) {
  const entries = catalogEntries.map((e) => ({ ...e, aliases: aliasesFor(e) }));
  const q = norm(query);
  const scoped = scopeBuildingId ? entries.filter((e) => e.buildingId === scopeBuildingId) : entries;
  const results = [];
  const where = (e) => (e.location ? { lat: e.location.lat, lng: e.location.lng } : { lat: 0, lng: 0 });
  const codeOf = (e) => e.code ?? e.buildingId.toUpperCase();
  const building = (e) => ({ type: 'building', key: `b:${e.buildingId}`, buildingId: e.buildingId, buildingName: e.name, roomId: null, floorId: null, label: e.name, hint: `${e.model.floors.length} mapped floor${e.model.floors.length === 1 ? '' : 's'}`, code: codeOf(e), ...where(e) });
  const floorResult = (e, f) => ({ type: 'floor', key: `f:${e.buildingId}:${f.id}`, buildingId: e.buildingId, buildingName: e.name, roomId: lobbyId(f.id), floorId: f.id, label: `${codeOf(e)} ${f.label}`, hint: 'Arrive at the elevator lobby', code: codeOf(e), ...where(e) });
  const roomResult = (e, r) => ({ type: 'room', key: `r:${e.buildingId}:${r.id}`, buildingId: e.buildingId, buildingName: e.name, roomId: r.id, floorId: r.floor, label: `${codeOf(e)} ${r.name}`, hint: r.floorLabel, code: codeOf(e), manual: r.door === 'manual', restroom: r.type === 'restroom', ...where(e) });
  const hasLobby = (e, f) => e.model.hasElevator && [...e.model.nodes.values()].some((n) => n.floor === f.id && n.kind === 'elevator_stop');
  const floorMatches = (f, fl) => f.level === fl.level || norm(f.id) === norm(fl.token ?? '') || (f.aliases ?? []).some((a) => norm(a) === norm(fl.token ?? ''));

  if (!q) {
    if (!scopeBuildingId) scoped.forEach((e) => results.push(building(e)));
    scoped.forEach((e) => e.model.floors.filter((f) => hasLobby(e, f)).forEach((f) => results.push(floorResult(e, f))));
    return results.slice(0, 12);
  }

  const det = scopeBuildingId ? { entry: scoped[0] ?? null, rest: q } : detectBuilding(q, entries);
  const searchIn = det.entry ? [det.entry] : scoped;
  const fl = detectFloor(det.rest);
  const text = norm(fl.rest.replace(FILLER, ' '));
  const textC = compact(text);
  const wantsRestroom = /\b(restroom|bathroom|toilet|washroom|wc)\b/.test(text);

  if (det.entry && !scopeBuildingId && !text && fl.level == null) results.push(building(det.entry));

  for (const e of searchIn) {
    const floors = e.model.floors;
    // Floor search
    if (fl.level != null) {
      const f = floors.find((x) => floorMatches(x, fl));
      if (!f) {
        if (det.entry || scopeBuildingId)
          results.push({ type: 'info', key: `i:${e.buildingId}:${fl.token}`, label: `${fl.token} isn't mapped yet in ${e.name}`, hint: `Mapped: ${floors.map((x) => x.label).join(', ')}` });
        continue;
      }
      if (!text && hasLobby(e, f)) results.push(floorResult(e, f));
    }
    // Room search
    for (const r of e.model.rooms) {
      const f = e.model.floorById.get(r.floor);
      if (fl.level != null && !floorMatches(f, fl)) continue;
      if (!text) {
        if (det.entry && fl.level == null) continue; // "ILC" alone: show the building and its floors first
        if (fl.level != null) results.push(roomResult(e, r));
        continue;
      }
      const name = norm(r.name);
      const nameC = compact(r.name);
      const aliasHit = (r.aliases ?? []).some((a) => compact(a) === textC);
      let score = 0;
      if (wantsRestroom && r.type === 'restroom') score = 3;
      else if (nameC === textC || aliasHit) score = 4;
      else if (/\d/.test(textC) && nameC.replace(/^[a-z]+/, '').startsWith(textC)) score = 4; // "311" -> "S311"
      else if (nameC.startsWith(textC)) score = 3;
      else if (nameC.includes(textC)) score = 2;
      else if (text.split(' ').every((w) => name.includes(w))) score = 1;
      if (score) results.push({ ...roomResult(e, r), score });
    }
    if (det.entry && !text && fl.level == null) floors.filter((f) => hasLobby(e, f)).forEach((f) => results.push(floorResult(e, f)));
  }

  // Building names typed without a room ("stud", "lib")
  if (!det.entry && !scopeBuildingId) {
    for (const e of entries) if (e.aliases.some((a) => a.startsWith(q)) || norm(e.name).includes(q)) results.unshift(building(e));
  }

  const seen = new Set();
  return results
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (b.r.score ?? 5) - (a.r.score ?? 5) || a.i - b.i)
    .map(({ r }) => r)
    .filter((r) => (seen.has(r.key) ? false : seen.add(r.key)))
    .slice(0, 12);
}

const ICON = { building: '🏛️', floor: '🛗', room: '🚪', info: 'ℹ️' };

export default function DestinationInput({ onSelect, scopeBuildingId, value, placeholder, className = '', compact: small = false, autoFocus = false, onDismiss }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const inputRef = useRef(null);
  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);
  const listId = useId();
  const { entries } = useIndoorEntries();
  const results = useMemo(() => searchDestinations(query, scopeBuildingId, entries), [query, scopeBuildingId, entries]);
  const selectable = (r) => r && r.type !== 'info';

  const choose = (r) => {
    if (!selectable(r)) return;
    const { key: _k, hint: _h, code: _c, score: _s, manual: _m, restroom: _r, ...target } = r;
    onSelect?.(target);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className={`relative ${className}`}>
      <div className={`flex items-center gap-2 rounded-full bg-white/95 shadow-lg ring-1 backdrop-blur transition ${open ? 'ring-2 ring-blue-600' : 'ring-black/10'} ${small ? 'px-3 py-1.5' : 'px-4 py-2.5'}`}>
        <span aria-hidden="true" className="text-slate-500">
          🔎
        </span>
        <input
          ref={inputRef}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={scopeBuildingId ? 'Search rooms in this building' : 'Search buildings and rooms'}
          autoComplete="off"
          spellCheck={false}
          value={open ? query : value ?? query}
          placeholder={placeholder ?? (scopeBuildingId ? 'Go to another room, e.g. 311, Floor 2' : 'Search a building or room, e.g. ILC 311')}
          onFocus={() => {
            setOpen(true);
            setHi(0);
          }}
          onBlur={() =>
            setTimeout(() => {
              setOpen(false);
              onDismiss?.();
            }, 120)
          }
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHi(0);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setHi((h) => Math.min(h + 1, results.length - 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setHi((h) => Math.max(h - 1, 0));
            } else if (e.key === 'Enter') {
              e.preventDefault();
              choose(results[hi] && selectable(results[hi]) ? results[hi] : results.find(selectable));
            } else if (e.key === 'Escape') {
              setOpen(false);
              inputRef.current?.blur();
            }
            e.stopPropagation(); // keep N / P / R / WASD shortcuts from firing while typing
          }}
          className={`min-w-0 flex-1 bg-transparent text-slate-900 outline-none placeholder:text-slate-400 ${small ? 'text-[13px]' : 'text-[15px]'}`}
        />
        {open && query && (
          <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setQuery('')} aria-label="Clear search" className="text-[16px] leading-none text-slate-400 hover:text-slate-700">
            ×
          </button>
        )}
      </div>

      {open && (
        <ul id={listId} role="listbox" className="absolute inset-x-0 top-full z-[1100] mt-2 max-h-80 overflow-y-auto rounded-3xl bg-white p-1.5 text-slate-900 shadow-2xl ring-1 ring-black/10">
          {results.length === 0 && <li className="px-3 py-3 text-[14px] text-slate-500">No match for “{query}”. Try a room number, “Floor 2”, or a building name.</li>}
          {results.map((r, i) => (
            <li
              key={r.key}
              role="option"
              aria-selected={i === hi}
              aria-disabled={!selectable(r)}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setHi(i)}
              onClick={() => choose(r)}
              className={`flex items-center gap-3 rounded-2xl px-3 py-2.5 ${selectable(r) ? 'cursor-pointer' : 'cursor-default bg-amber-50'} ${i === hi && selectable(r) ? 'bg-blue-50' : ''}`}
            >
              <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-[15px]">
                {r.restroom ? '♿' : ICON[r.type]}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium">{r.label}</span>
                {r.hint && <span className="block truncate text-[12px] text-slate-500">{r.hint}</span>}
              </span>
              {r.manual && <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">manual door</span>}
              {r.type === 'building' && <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">indoor map</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
