import { useId, useMemo, useRef, useState } from 'react';
import { ArrowUpDown, Bus, Crosshair, MapPin, ParkingCircle } from 'lucide-react';
import type { Place } from '../types';
import type { PickablePlace } from '../data/places';
import { cx, useClickOutside } from './ui';

interface PickerProps {
  label: string;
  dot: 'a' | 'b';
  value: Place | null;
  options: PickablePlace[];
  onChange: (p: Place) => void;
  onPickOnMap: () => void;
  picking: boolean;
}

function PlacePicker({ label, dot, value, options, onChange, onPickOnMap, picking }: PickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const wrap = useRef<HTMLDivElement>(null);
  const listId = useId();
  useClickOutside(wrap, () => setOpen(false), open);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.name.toLowerCase().includes(q) || o.code.toLowerCase() === q || o.subtitle.toLowerCase().includes(q));
  }, [options, query]);

  const choose = (o: PickablePlace) => {
    onChange({ name: o.name, lat: o.lat, lng: o.lng, building_id: o.building_id });
    setOpen(false);
    setQuery('');
  };

  return (
    <div ref={wrap} className="relative">
      <div className={cx('flex items-center gap-3 rounded-2xl px-3 py-2 transition', open ? 'bg-white ring-2 ring-sky/40' : 'bg-black/[0.04]')}>
        <span className={cx('h-2.5 w-2.5 shrink-0 rounded-full ring-[3px]', dot === 'a' ? 'bg-ink ring-ink/15' : 'bg-go ring-go/20')} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-[11px] text-ink-3">{label}</div>
          <input
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-label={label}
            className="w-full bg-transparent text-[15px] font-medium text-ink outline-none placeholder:text-ink-4"
            placeholder={picking ? 'Tap the map…' : 'Search buildings'}
            value={open ? query : value?.name ?? ''}
            onFocus={() => {
              setOpen(true);
              setActive(0);
            }}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              setOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, filtered.length - 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === 'Enter' && filtered[active]) {
                e.preventDefault();
                choose(filtered[active]);
                (e.target as HTMLInputElement).blur();
              }
            }}
          />
        </div>
        <button
          type="button"
          onClick={onPickOnMap}
          title="Choose on map"
          aria-label={`Choose ${label.toLowerCase()} on map`}
          className={cx('btn h-8 w-8 !p-0', picking ? 'bg-sky text-white' : 'text-ink-3 hover:bg-black/[0.05]')}
        >
          <Crosshair className="h-4 w-4" />
        </button>
      </div>
      {open && (
        <ul
          id={listId}
          role="listbox"
          className="scroll-soft absolute left-0 right-0 top-full z-30 mt-2 max-h-72 overflow-y-auto rounded-2xl bg-white p-1.5 shadow-lift animate-pop"
        >
          {filtered.length === 0 && <li className="px-3 py-3 text-[13px] text-ink-3">No match. Try a building code like ILC.</li>}
          {filtered.map((o, i) => (
            <li
              key={`${o.kind}-${o.name}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(o)}
              onMouseEnter={() => setActive(i)}
              className={cx('flex cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2', i === active && 'bg-black/[0.04]')}
            >
              <span className="flex h-8 w-10 shrink-0 items-center justify-center rounded-lg bg-black/[0.05] text-[11px] font-semibold text-ink-2">
                {o.kind === 'bus' ? <Bus className="h-4 w-4" /> : o.code === 'P' ? <ParkingCircle className="h-4 w-4" /> : o.kind === 'spot' ? <MapPin className="h-4 w-4" /> : o.code}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] text-ink">{o.name}</span>
                <span className="block truncate text-[12px] text-ink-3">{o.subtitle}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Props {
  origin: Place | null;
  destination: Place | null;
  options: PickablePlace[];
  onOrigin: (p: Place) => void;
  onDestination: (p: Place) => void;
  onSwap: () => void;
  picking: 'origin' | 'destination' | null;
  onPick: (which: 'origin' | 'destination' | null) => void;
}

export function TripPlanner({ origin, destination, options, onOrigin, onDestination, onSwap, picking, onPick }: Props) {
  return (
    <div className="relative space-y-2">
      <PlacePicker
        label="From"
        dot="a"
        value={origin}
        options={options}
        onChange={onOrigin}
        picking={picking === 'origin'}
        onPickOnMap={() => onPick(picking === 'origin' ? null : 'origin')}
      />
      <PlacePicker
        label="To"
        dot="b"
        value={destination}
        options={options}
        onChange={onDestination}
        picking={picking === 'destination'}
        onPickOnMap={() => onPick(picking === 'destination' ? null : 'destination')}
      />
      <button
        type="button"
        onClick={onSwap}
        aria-label="Swap start and destination"
        className="absolute right-12 top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-white text-ink-2 shadow-float ring-1 ring-hairline transition hover:scale-105 active:scale-95"
      >
        <ArrowUpDown className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
