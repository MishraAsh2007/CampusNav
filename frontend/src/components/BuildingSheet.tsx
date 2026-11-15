import { AlertTriangle, Bath, Baby, ExternalLink, MapPin, MoveVertical, Navigation, Quote } from 'lucide-react';
import type { Building, Closure } from '../types';
import { Sheet, cx } from './ui';
import { entranceState } from './map/scene';
import { GooglePlaceAccess } from './GooglePlaceAccess';
import { useMapProvider } from './map/MapsProvider';

interface Props {
  building: Building | null;
  closures: Closure[];
  focusEntranceId: string | null;
  onClose: () => void;
  onStart: (b: Building) => void;
  onGo: (b: Building) => void;
  onReport: (b: Building) => void;
}

const stateLabel = {
  ok: ['Step-free · powered door', 'bg-go-soft text-go-ink'],
  manual: ['Step-free · manual door', 'bg-warn-soft text-warn-ink'],
  broken: ['Door reported broken', 'bg-stop-soft text-stop-ink'],
  no: ['Steps at entrance', 'bg-black/[0.05] text-ink-3']
} as const;

export function BuildingSheet({ building: b, closures, focusEntranceId, onClose, onStart, onGo, onReport }: Props) {
  const { provider } = useMapProvider();
  if (!b) return null;
  const liftDown = b.elevators.list.filter(
    (l) => l.status === 'out_of_service' || closures.some((c) => c.status === 'closed' && c.connector_id && c.connector_id === l.connector_id)
  );
  const working = b.elevators.total_count - liftDown.length;

  return (
    <Sheet
      open
      onClose={onClose}
      eyebrow={b.code}
      title={b.name}
      footer={
        <div className="flex gap-2">
          <button className="btn-quiet flex-1" onClick={() => onStart(b)}>
            <MapPin className="h-4 w-4" /> Start here
          </button>
          <button className="btn-primary flex-1" onClick={() => onGo(b)}>
            <Navigation className="h-4 w-4" /> Directions
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        {!b.all_floors_accessible && (
          <div className="flex items-start gap-2.5 rounded-2xl bg-warn-soft px-3.5 py-3 text-[13px] text-warn-ink">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>Not every floor is reachable without stairs. Check your room before you go.</span>
          </div>
        )}

        <section>
          <h3 className="eyebrow mb-2">Entrances</h3>
          <ul className="space-y-1.5">
            {b.entrances.map((e) => {
              const st = entranceState(b, e, closures);
              const [label, tone] = stateLabel[st];
              return (
                <li key={e.id} className={cx('rounded-2xl p-3 transition', focusEntranceId === e.id ? 'bg-sky-soft ring-2 ring-sky/30' : 'bg-black/[0.03]')}>
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[14px] text-ink">{e.name}</span>
                    <span className={cx('chip shrink-0', tone)}>{label}</span>
                  </div>
                  {(e.has_ramp || e.notes) && (
                    <p className="mt-1 text-[12px] text-ink-3">
                      {e.has_ramp && `Ramp${e.ramp_grade_pct ? ` about ${e.ramp_grade_pct}%` : ''}. `}
                      {e.notes}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="eyebrow">Elevators</h3>
            {b.elevators.total_count > 0 && (
              <span className={cx('chip', liftDown.length ? 'bg-stop-soft text-stop-ink' : 'bg-go-soft text-go-ink')}>
                {working} of {b.elevators.total_count} working
              </span>
            )}
          </div>
          {b.elevators.list.length ? (
            <ul className="divide-y divide-hairline rounded-2xl bg-black/[0.03] px-3">
              {b.elevators.list.map((l) => {
                const down = liftDown.includes(l);
                return (
                  <li key={l.id} className="flex items-center gap-3 py-2.5">
                    <MoveVertical className={cx('h-4 w-4', down ? 'text-stop' : 'text-ink-3')} />
                    <span className="flex-1 text-[14px] text-ink">
                      {l.name} <span className="text-ink-3">· {l.floors}</span>
                    </span>
                    <span className={cx('text-[12px] font-medium', down ? 'text-stop-ink' : 'text-go-ink')}>{down ? 'Out of service' : 'Working'}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[13px] text-ink-3">{b.elevators.floors_served}</p>
          )}
        </section>

        <section className="flex flex-wrap gap-1.5">
          <span className={cx('chip', b.accessible_restrooms ? 'bg-go-soft text-go-ink' : 'bg-black/[0.05] text-ink-3')}>
            <Bath className="h-3 w-3" /> {b.accessible_restrooms ? 'Accessible restroom' : 'No accessible restroom listed'}
          </span>
          {b.lactation_room && (
            <span className="chip bg-black/[0.05] text-ink-2">
              <Baby className="h-3 w-3" /> Lactation room
            </span>
          )}
        </section>

        {b.notes && <p className="text-[14px] leading-relaxed text-ink-2">{b.notes}</p>}

        {provider === 'google' && <GooglePlaceAccess building={b} />}

        {b.student_reports?.length ? (
          <section>
            <h3 className="eyebrow mb-2">What students have said</h3>
            <ul className="space-y-2">
              {b.student_reports.map((r, i) => (
                <li key={i} className="rounded-2xl bg-black/[0.03] p-3">
                  <p className="flex gap-2 text-[13px] leading-relaxed text-ink-2">
                    <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-4" />
                    {r.text}
                  </p>
                  <a href={r.url} target="_blank" rel="noreferrer" className="mt-1.5 flex items-center gap-1 pl-5 text-[11px] text-sky-ink">
                    {r.source}, {r.year} <ExternalLink className="h-3 w-3" />
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <button onClick={() => onReport(b)} className="btn-ghost w-full justify-start !px-2 text-stop-ink">
          <AlertTriangle className="h-4 w-4" /> Report a broken door, elevator or ramp here
        </button>

        <p className="text-[11px] leading-snug text-ink-4">
          Positions from OpenStreetMap. Door and elevator details are CampusNav seed data; check the{' '}
          <a className="underline" href="https://www.umass.edu/planning-design-construction/maps-and-tours" target="_blank" rel="noreferrer">
            UMass Campus Accessibility Map
          </a>
          .
        </p>
      </div>
    </Sheet>
  );
}
