import { useEffect, useId, useMemo, useRef, useState } from 'react';

/**
 * Shown over the outdoor map when a route ends at a building with indoor navigation.
 *
 * Props
 *   open          boolean
 *   buildingName  string
 *   rooms         [{ id, name, floor, floorLabel, type }]
 *   initialRoomId optional preselected room
 *   onClose       () => void            stay outside
 *   onLaunch      (mode: '2d' | '3d', roomId) => void
 *   error         message when the chosen room has no step-free route (e.g. elevator out of service)
 *   mapNote       small caveat about the map (sample layout, draft)
 */
export default function BuildingTransitionModal({ open, buildingName, rooms, initialRoomId, onClose, onLaunch, error = null, mapNote = null, startControl = null, allow3D = true, hasOutdoorArrival = true, startReady = true }) {
  const [query, setQuery] = useState('');
  const [roomId, setRoomId] = useState(initialRoomId ?? null);
  const [listOpen, setListOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const inputRef = useRef(null);
  const dialogRef = useRef(null);
  const titleId = useId();
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    setRoomId(initialRoomId ?? null);
    setQuery('');
    const focusTimer = setTimeout(() => {
      // Keep the phone keyboard closed until the user chooses to search.
      if (window.matchMedia('(min-width: 1024px)').matches) inputRef.current?.focus();
      else dialogRef.current?.focus();
    }, 50);
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(focusTimer);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, initialRoomId, onClose]);

  const selected = rooms.find((r) => r.id === roomId) ?? null;
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? rooms.filter(
          (r) =>
            r.name.toLowerCase().includes(q) ||
            r.floorLabel.toLowerCase().includes(q) ||
            (r.aliases ?? []).some((a) => String(a).toLowerCase() === q) ||
            (q.includes('bath') || q.includes('toilet') ? r.type === 'restroom' : false)
        )
      : rooms;
    return list.slice(0, 60);
  }, [rooms, query]);

  if (!open) return null;

  const choose = (r) => {
    setRoomId(r.id);
    setQuery('');
    setListOpen(false);
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm sm:items-center sm:p-6" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[calc(100dvh-24px)] w-full max-w-lg overflow-y-auto overscroll-contain rounded-t-[2rem] bg-white p-5 pb-[max(20px,env(safe-area-inset-bottom))] text-slate-950 shadow-2xl ring-1 ring-black/10 sm:rounded-[2rem] sm:p-6"
      >
        <div className="mb-5 flex items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-600 text-[24px] text-white" aria-hidden="true">
            🏛️
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-emerald-700">{hasOutdoorArrival ? 'Continue indoors' : 'Plan indoor directions'}</p>
            <h2 id={titleId} className="mt-0.5 text-[22px] font-semibold leading-tight tracking-tight">
              {hasOutdoorArrival ? `Continue inside ${buildingName}` : `Navigate inside ${buildingName}`}
            </h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Stay outside" className="rounded-full bg-slate-100 px-3 py-1.5 text-[18px] leading-none text-slate-700 hover:bg-slate-200">
            ×
          </button>
        </div>

        {startControl}
        <label htmlFor={listId + '-input'} className="mb-2 block text-[14px] font-semibold text-slate-800">
          Which room do you want to go to?
        </label>
        <div className="relative">
          <div className={`flex items-center gap-2 rounded-2xl border-2 px-3.5 py-3 transition ${listOpen ? 'border-blue-600' : 'border-slate-200'}`}>
            <span aria-hidden="true" className="text-slate-500">
              🔎
            </span>
            <input
              ref={inputRef}
              id={listId + '-input'}
              role="combobox"
              aria-expanded={listOpen}
              aria-controls={listId}
              aria-autocomplete="list"
              autoComplete="off"
              value={listOpen ? query : selected ? `${selected.name} · ${selected.floorLabel}` : query}
              placeholder="Room number or name, e.g. S331, Ballroom, Restrooms"
              onFocus={() => {
                if (!roomId) setListOpen(true);
                setHi(0);
              }}
              onClick={() => setListOpen(true)}
              onBlur={() => setTimeout(() => setListOpen(false), 120)}
              onChange={(e) => {
                setQuery(e.target.value);
                setListOpen(true);
                setHi(0);
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault();
                  if (listOpen) setHi((h) => Math.min(h + 1, results.length - 1));
                  else setListOpen(true);
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault();
                  setHi((h) => Math.max(h - 1, 0));
                } else if (e.key === 'Enter' && listOpen && results[hi]) {
                  e.preventDefault();
                  choose(results[hi]);
                }
              }}
              className="min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-slate-400"
            />
          </div>
          {listOpen && (
            <ul id={listId} role="listbox" className="absolute inset-x-0 top-full z-10 mt-2 max-h-64 overflow-y-auto rounded-2xl bg-white p-1.5 shadow-2xl ring-1 ring-black/10">
              {results.length === 0 && <li className="px-3 py-3 text-[14px] text-slate-500">No room matches “{query}”.</li>}
              {results.map((r, i) => (
                <li
                  key={r.id}
                  role="option"
                  aria-selected={r.id === roomId}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setHi(i)}
                  onClick={() => choose(r)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-[15px] ${i === hi ? 'bg-blue-50' : ''}`}
                >
                  <span className="flex items-center gap-2">
                    <span aria-hidden="true">{r.type === 'restroom' ? '♿' : '🚪'}</span>
                    <span className="font-medium text-slate-900">{r.name}</span>
                    {r.door === 'manual' && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">manual door</span>}
                  </span>
                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[12px] font-semibold text-slate-700">{r.floorLabel}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            disabled={!selected || !startReady}
            onClick={() => onLaunch?.('2d', roomId)}
            className="flex flex-col items-start gap-1 rounded-3xl bg-slate-950 p-4 text-left text-white shadow-lg transition hover:bg-slate-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span aria-hidden="true" className="text-[22px]">
              🗺️
            </span>
            <span className="text-[16px] font-semibold">{allow3D ? '2D Floor Plan' : 'Start indoor directions'}</span>
            <span className="text-[13px] text-white/70">{allow3D ? "Bird's Eye View" : 'Landmarks, floors and elevators'}</span>
          </button>
          {allow3D && (<button
            type="button"
            disabled={!selected || !startReady}
            onClick={() => onLaunch?.('3d', roomId)}
            className="flex flex-col items-start gap-1 rounded-3xl bg-blue-600 p-4 text-left text-white shadow-lg transition hover:bg-blue-500 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span aria-hidden="true" className="text-[22px]">
              🧭
            </span>
            <span className="text-[16px] font-semibold">3D Immersive View</span>
            <span className="text-[13px] text-white/80">First-person, wheelchair height</span>
          </button>)}
        </div>
        {error && selected?.id === initialRoomId && (
          <p role="alert" className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-[14px] font-medium text-red-800 ring-1 ring-red-200">
            ⚠️ {error}
          </p>
        )}
        <p className="mt-3 text-center text-[12px] text-slate-500">
          {selected ? (allow3D ? 'You can switch between 2D and 3D at any time.' : 'Follow the steps with Next and Back. Indoor GPS is unavailable.') : 'Choose a room to start indoor directions.'}
          {mapNote && <span className="block text-slate-400">{mapNote}</span>}
        </p>
      </div>
    </div>
  );
}
