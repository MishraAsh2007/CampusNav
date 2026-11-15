import { CheckCircle2, Clock, ExternalLink, Phone, ShieldCheck, Siren, ThumbsUp, Users } from 'lucide-react';
import type { Closure } from '../types';
import { formatFreshness } from '../data/mockClosures';
import type { Incident } from '../services/incidents';
import { isSampleData, SEVERITY_HINT } from '../services/incidents';
import { Sheet, cx } from './ui';
import { BusRoutes, SeverityBadge } from './IncidentBits';

interface Props {
  incident: Incident | null;
  onClose: () => void;
  onConfirm: (c: Closure) => void;
  onResolve: (inc: Incident) => void;
}

const typeLabel: Record<Closure['type'], string> = {
  elevator: 'Elevator',
  automatic_door: 'Automatic door',
  ramp: 'Ramp',
  path: 'Path',
  construction: 'Construction'
};

const day = (iso?: string) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : null;

export function ClosureSheet({ incident: inc, onClose, onConfirm, onResolve }: Props) {
  if (!inc) return null;
  const c = inc.primary;
  const roadOnly = inc.isRoad && inc.all.every((x) => x.affects === 'road');
  const confirmTarget = inc.community[0] ?? c;

  return (
    <Sheet
      open
      onClose={onClose}
      side="center"
      eyebrow={`${roadOnly ? 'Road closure' : typeLabel[c.type]} · ${inc.all.every((x) => x.status === 'degraded') ? 'Use caution' : 'Out of service'}`}
      title={c.title}
      footer={
        <div className="flex gap-2">
          <button className="btn-quiet flex-1" onClick={() => onConfirm(confirmTarget)}>
            <ThumbsUp className="h-4 w-4" /> Still a problem
          </button>
          <button className="btn-primary flex-1" onClick={() => onResolve(inc)}>
            <CheckCircle2 className="h-4 w-4" /> It works now
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div
          className={cx(
            'flex items-start gap-2.5 rounded-2xl px-3.5 py-3 text-[13px]',
            inc.severity === 'high' ? 'bg-stop text-white' : inc.severity === 'official' ? 'bg-sky-soft text-sky-ink' : 'bg-black/[0.04] text-ink-2'
          )}
        >
          {inc.severity === 'high' ? <Siren className="mt-0.5 h-4 w-4 shrink-0" /> : inc.severity === 'official' ? <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" /> : <Users className="mt-0.5 h-4 w-4 shrink-0" />}
          <span>
            <span className="font-semibold">{SEVERITY_HINT[inc.severity]}.</span>{' '}
            {inc.severity === 'high'
              ? 'Two independent sources agree, so routes treat this as certain.'
              : inc.severity === 'official'
                ? 'No student has reported it yet.'
                : 'Not on the Facilities notice list. Confirm it if you see it too.'}
          </span>
        </div>

        {roadOnly ? (
          <p className="text-[13px] text-ink-3">Sidewalks stay open, so walking routes are unchanged. Buses and cars are detoured.</p>
        ) : (
          <p className="text-[13px] text-ink-3">Walking routes avoid this spot automatically.</p>
        )}

        {inc.bus && (
          <section className="rounded-2xl bg-[#eef1f7] p-3.5">
            <h3 className="mb-2 text-[12px] font-semibold text-[#33405c]">
              {inc.bus.certain ? 'Bus routes detoured' : 'Bus routes that run here'}
              {inc.bus.roads.length > 0 && <span className="font-normal"> · {inc.bus.roads.join(', ')}</span>}
            </h3>
            <BusRoutes routes={inc.bus.routes} certain={inc.bus.certain} />
            <p className="mt-2 text-[11px] leading-snug text-[#5b6b8c]">
              Matched from PVTA routes in OpenStreetMap. Stops on this stretch may be skipped; check the Transit app or{' '}
              <a className="underline" href="https://www.umass.edu/transportation/news" target="_blank" rel="noreferrer">
                UMass Transit news
              </a>
              .
            </p>
          </section>
        )}

        {inc.official.map((o) => (
          <section key={o.id} className="rounded-2xl bg-black/[0.03] p-3.5">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <span className="chip bg-sky-soft text-sky-ink">
                <ShieldCheck className="h-3 w-3" /> UMass Facilities
              </span>
              {o.reference && <span className="text-[11px] text-ink-3">{o.reference}</span>}
              {isSampleData(o) && <span className="chip bg-black/[0.05] text-ink-4">Sample</span>}
            </div>
            {o.description && <p className="text-[14px] leading-relaxed text-ink-2">{o.description}</p>}
            <dl className="mt-2 grid grid-cols-2 gap-2 text-[12px]">
              <div>
                <dt className="text-ink-4">{Date.parse(o.start_time) > Date.now() ? 'Starts' : 'Started'}</dt>
                <dd className="text-ink-2">{day(o.start_time) ?? 'Unknown'}</dd>
              </div>
              <div>
                <dt className="text-ink-4">Expected back</dt>
                <dd className="text-ink-2">{day(o.end_time) ?? 'Not given'}</dd>
              </div>
            </dl>
            {o.source_url && (
              <a href={o.source_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[12px] text-sky-ink">
                Facilities notices <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </section>
        ))}

        {inc.community.length > 0 && (
          <section className="rounded-2xl bg-black/[0.03] p-3.5">
            <div className="mb-1.5 flex items-center gap-1.5">
              <span className="chip bg-black/[0.05] text-ink-2">
                <Users className="h-3 w-3" /> {inc.confirmations} student{inc.confirmations === 1 ? '' : 's'}
              </span>
              <span className="flex items-center gap-1 text-[11px] text-ink-3">
                <Clock className="h-3 w-3" /> last confirmed {formatFreshness(inc.community.map((x) => x.last_confirmed).sort().pop()!)}
              </span>
            </div>
            {inc.community
              .filter((x) => x.description)
              .slice(0, 3)
              .map((x) => (
                <p key={x.id} className="text-[14px] leading-relaxed text-ink-2">
                  “{x.description}”
                </p>
              ))}
            <p className="mt-1.5 text-[11px] text-ink-4">Student reports expire after 48 h unless someone confirms them.</p>
          </section>
        )}

        <a href="tel:+14135456401" className="flex items-center gap-2 rounded-2xl bg-black/[0.03] px-3.5 py-3 text-[13px] text-ink-2">
          <Phone className="h-4 w-4 text-ink-3" />
          <span>
            Stuck or unsafe? UMass Facilities Service Center, 24/7: <span className="font-medium text-ink">413-545-6401</span>
          </span>
        </a>
      </div>
    </Sheet>
  );
}
