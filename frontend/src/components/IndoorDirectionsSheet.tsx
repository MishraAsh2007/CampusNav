import { FormEvent, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CircleDot, DoorOpen, Flag, Footprints, MoveVertical } from 'lucide-react';
import { Sheet, cx } from './ui';
import { getIndoorDirections, IndoorDirections, indoorDirectionsAvailable, closuresSignature } from '../services/api';
import type { Closure, UserPreferences } from '../types';

/** One side of the trip: the building, the door at that end, and what the user is heading to or leaving from. */
export interface IndoorLeg {
  buildingId: string;
  buildingName: string;
  door: { lat: number; lng: number; name?: string } | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  arrive: IndoorLeg | null;
  /** Start building of the trip, for "leaving" directions */
  leave: IndoorLeg | null;
  /** Room or floor picked in the search bar, used as the starting text */
  initialRoom?: string;
  initialFloor?: string | null;
  prefs: UserPreferences;
  closures: Closure[];
}

/** True once the routing server is known to offer indoor directions; the trigger button hides until then. */
export function useIndoorDirectionsAvailable(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    let live = true;
    indoorDirectionsAvailable().then((v) => live && setOk(v));
    return () => {
      live = false;
    };
  }, []);
  return ok;
}

function StepIcon({ text, first, last }: { text: string; first: boolean; last: boolean }) {
  const cls = 'h-4 w-4';
  if (/^(Enter|Leave) through/.test(text)) return <DoorOpen className={cls} />;
  if (/^Take the/.test(text)) return <MoveVertical className={cls} />;
  if (last) return <Flag className={cls} />;
  if (first) return <CircleDot className={cls} />;
  return <Footprints className={cls} />;
}

const tone = (text: string, last: boolean) =>
  /^Take the/.test(text) ? 'bg-lift-soft text-lift-ink' : last ? 'bg-go text-white' : 'bg-black/[0.05] text-ink-2';

export function IndoorDirectionsSheet({ open, onClose, arrive, leave, initialRoom, initialFloor, prefs, closures }: Props) {
  const [direction, setDirection] = useState<'to_room' | 'to_exit'>('to_room');
  const [text, setText] = useState(initialRoom ?? '');
  const [query, setQuery] = useState(initialRoom ?? '');
  const [result, setResult] = useState<IndoorDirections | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  // A new room picked in the search bar replaces what is typed here
  useEffect(() => {
    setText(initialRoom ?? '');
    setQuery(initialRoom ?? '');
  }, [initialRoom]);
  useEffect(() => {
    if (!open) setDirection('to_room');
  }, [open]);

  const leg = direction === 'to_room' ? arrive : leave;
  // Re-ask when outage data changes so a newly reported elevator shows up
  const closureKey = closuresSignature(closures);
  const prefKey = `${prefs.no_stairs}|${prefs.wheelchair_required}`;
  const asked = query.trim();

  useEffect(() => {
    const mine = ++seq.current;
    if (!open || !leg || !asked) {
      setResult(null);
      setLoading(false);
      return;
    }
    setResult(null);
    setLoading(true);
    getIndoorDirections({
      buildingId: leg.buildingId,
      door: leg.door,
      room: asked,
      floor: asked === initialRoom ? initialFloor : null,
      direction,
      prefs,
      closures,
    }).then((r) => {
      if (mine !== seq.current) return;
      setResult(r);
      setLoading(false);
    });
    return () => {++seq.current;};
    // prefs and closures are tracked through prefKey and closureKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, leg?.buildingId, leg?.door?.lat, leg?.door?.lng, asked, direction, closureKey, prefKey, initialFloor]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(text);
  };

  const steps = result?.status === 'ok' ? result.steps ?? [] : [];
  const door = result?.entrance ?? result?.exit;
  const failed = result && result.status !== 'ok';

  return (
    <Sheet open={open} onClose={onClose} eyebrow="Indoor directions" title={leg ? leg.buildingName : 'Indoor directions'}>
      {leave && arrive && (
        <div className="mb-3 grid grid-cols-2 gap-1 rounded-2xl bg-black/[0.05] p-1 text-[13px] font-semibold" role="tablist">
          {(['to_room', 'to_exit'] as const).map((d) => (
            <button
              key={d}
              type="button"
              role="tab"
              aria-selected={direction === d}
              onClick={() => setDirection(d)}
              className={cx('rounded-xl px-3 py-2 transition', direction === d ? 'bg-white text-ink shadow' : 'text-ink-3')}
            >
              {d === 'to_room' ? 'Arriving' : 'Leaving'}
            </button>
          ))}
        </div>
      )}

      <form onSubmit={submit} className="mb-4 flex gap-2">
        <label className="sr-only" htmlFor="indoor-room">
          {direction === 'to_room' ? 'Room or floor' : 'Where you are inside'}
        </label>
        <input
          id="indoor-room"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={direction === 'to_room' ? 'Room or floor, e.g. N151 or 4th floor' : 'Your room or floor'}
          className="min-w-0 flex-1 rounded-2xl border border-hairline bg-white px-3.5 py-2.5 text-base text-ink outline-none focus:border-ink-3"
        />
        <button type="submit" className="btn btn-primary">
          Go
        </button>
      </form>

      {!asked && <p className="text-[13px] text-ink-3">Enter a room or floor to get step-by-step directions inside the building.</p>}
      {loading && (
        <p className="text-[13px] text-ink-3" role="status">
          Finding the way…
        </p>
      )}

      {!loading && failed && (
        <div className="rounded-2xl bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn-ink" role="alert">
          {result.message ?? 'No indoor route available.'}
        </div>
      )}

      {!loading && result?.status === 'ok' && (
        <>
          <div className="mb-3 text-[13px] text-ink-3">
            {door?.name ? `${direction === 'to_room' ? 'Enter by' : 'Leave by'} the ${door.name}` : ''}
            {result.total_ft ? ` · about ${result.total_ft} ft` : ''}
          </div>
          <ol className="space-y-2">
            {steps.map((s, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className={cx('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl', tone(s, i === steps.length - 1))}>
                  <StepIcon text={s} first={i === 0} last={i === steps.length - 1} />
                </span>
                <span className="pt-1 text-[14px] leading-snug text-ink">{s}</span>
              </li>
            ))}
          </ol>
          {!!result.warnings?.length && (
            <ul className="mt-4 space-y-2">
              {result.warnings.map((w, i) => (
                <li key={i} className="flex gap-2 rounded-2xl bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn-ink">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {!loading && !!result?.elevators?.length && (
        <div className="mt-4">
          <div className="eyebrow mb-1.5">Elevators</div>
          <ul className="space-y-1 text-[13px]">
            {result.elevators.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-3">
                <span className="text-ink-2">{e.label}</span>
                <span className={cx('rounded-full px-2 py-0.5 text-[11px] font-semibold', e.usable ? 'bg-go/10 text-go-ink' : 'bg-stop-soft text-stop-ink')}>
                  {e.usable ? 'No blocking report' : 'May be out'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-5 text-[11px] text-ink-4">Indoor maps are simplified sketches, so distances are approximate.</p>
    </Sheet>
  );
}
