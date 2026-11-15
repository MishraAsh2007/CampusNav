import { useEffect, useMemo, useState } from 'react';
import { Check, Crosshair, MoveVertical, Route, TrendingUp } from 'lucide-react';
import type { BarrierType, Building, UserReportPayload } from '../types';
import { Sheet, cx } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
  buildings: Building[];
  initialBuildingId: string | null;
  pickedPoint: { lat: number; lng: number } | null;
  onPickOnMap: () => void;
  onSubmit: (p: UserReportPayload) => Promise<void>;
}

const TYPES: { id: BarrierType; label: string; icon: JSX.Element }[] = [
  { id: 'elevator', label: 'Elevator', icon: <MoveVertical className="h-4 w-4" /> },
  { id: 'ramp', label: 'Ramp', icon: <TrendingUp className="h-4 w-4" /> },
  { id: 'path', label: 'Path or curb cut', icon: <Route className="h-4 w-4" /> },
];

const STATUSES = [
  { id: 'broken', label: 'Not working' },
  { id: 'blocked', label: 'Blocked (snow, ice, cars)' },
] as const;

export function ReportSheet({ open, onClose, buildings, initialBuildingId, pickedPoint, onPickOnMap, onSubmit }: Props) {
  const [type, setType] = useState<BarrierType>('elevator');
  const [status, setStatus] = useState<(typeof STATUSES)[number]['id']>('broken');
  const [buildingId, setBuildingId] = useState<string>(initialBuildingId ?? '');
  const [liftId, setLiftId] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setBuildingId(initialBuildingId ?? '');
      setDone(false);
      setError('');
    }
  }, [open, initialBuildingId]);

  const b = buildings.find((x) => x.id === buildingId);
  const lifts = b?.elevators.list ?? [];
  const lift = lifts.find((l) => l.id === liftId) ?? lifts[0];
  const where = type === 'elevator' && lift?.lat !== undefined && lift?.lng !== undefined
    ? {lat: lift.lat, lng: lift.lng} : pickedPoint;

  const title = useMemo(() => {
    const t = TYPES.find((x) => x.id === type)!.label;
    const place = type === 'elevator' && lift ? `${b?.name} ${lift.name.toLowerCase()}` : b?.name ?? 'Campus';
    const s = status === 'blocked' ? 'blocked' : 'not working';
    return `${place}${type === 'elevator' && lift ? '' : ` ${t.toLowerCase()}`} ${s}`;
  }, [type, status, b, lift]);

  if (!open) return null;

  const submit = async () => {
    if (!where) return;
    setBusy(true);
    setError('');
    try { await onSubmit({
      lat: where.lat,
      lng: where.lng,
      type,
      status,
      title,
      description: details.trim(),
      building_id: b?.id,
      connector_id: type === 'elevator' ? lift?.connector_id : undefined,
      reporter_device_id: 'web',
      timestamp: new Date().toISOString()
    });
    setDone(true);
    setTimeout(onClose, 1400);
    } catch (e) {setError(e instanceof Error ? e.message : 'Report could not be saved.');}
    finally {setBusy(false);}
  };

  return (
    <Sheet
      open
      onClose={onClose}
      eyebrow="Report"
      title="What's not working?"
      footer={
        done ? null : (
          <button className="btn-primary w-full !py-3 text-[15px]" disabled={!where || busy} onClick={submit}>
            {busy ? 'Sending…' : 'Send report'}
          </button>
        )
      }
    >
      {done ? (
        <div className="py-12 text-center animate-pop">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-go-soft text-go">
            <Check className="h-7 w-7" />
          </div>
          <p className="text-[17px] font-medium text-ink">Thanks. Routes are updating.</p>
          <p className="mt-1 text-[13px] text-ink-3">The backend saved your report. Routing uses it where it matches a mapped path; interior elevator connections are not mapped yet.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {error && <p role="alert" className="rounded-xl bg-stop-soft p-3 text-sm">{error}</p>}
          {!where && <p className="text-sm">Select a mapped elevator, or choose the exact problem location on the map. A building center is not a path location.</p>}
          <div className="grid grid-cols-2 gap-1.5">
            {TYPES.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setType(t.id)}
                aria-pressed={type === t.id}
                className={cx(
                  'flex items-center gap-2 rounded-2xl px-3 py-2.5 text-left text-[13px] transition',
                  type === t.id ? 'bg-ink text-white' : 'bg-black/[0.04] text-ink hover:bg-black/[0.06]'
                )}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Condition">
            {STATUSES.map((s) => (
              <button
                key={s.id}
                role="radio"
                aria-checked={status === s.id}
                onClick={() => setStatus(s.id)}
                className={cx(
                  'rounded-full px-3 py-1.5 text-[13px] transition',
                  status === s.id ? 'bg-stop text-white' : 'bg-black/[0.04] text-ink-2'
                )}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            <label className="eyebrow block" htmlFor="rep-b">
              Where
            </label>
            <select id="rep-b" className="field" value={buildingId} onChange={(e) => setBuildingId(e.target.value)}>
              <option value="">Outdoors / not a building</option>
              {buildings.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
            {type === 'elevator' && lifts.length > 0 && (
              <select className="field" value={lift?.id} onChange={(e) => setLiftId(e.target.value)} aria-label="Which elevator">
                {lifts.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name} ({l.floors})
                  </option>
                ))}
              </select>
            )}
            <button onClick={onPickOnMap} className="btn-ghost -ml-2 !px-2 text-[13px]">
              <Crosshair className="h-4 w-4" />
              {pickedPoint ? `Pinned at ${pickedPoint.lat.toFixed(5)}, ${pickedPoint.lng.toFixed(5)}` : 'Drop a pin on the map instead'}
            </button>
          </div>

          <div>
            <label className="eyebrow mb-2 block" htmlFor="rep-d">
              Details (optional)
            </label>
            <textarea
              id="rep-d"
              rows={3}
              className="field resize-none"
              placeholder="e.g. Push plate does nothing; use the east doors."
              value={details}
              onChange={(e) => setDetails(e.target.value)}
            />
            <p className="mt-2 text-[12px] text-ink-3">Will post as: “{title}”</p>
          </div>

        </div>
      )}
    </Sheet>
  );
}
