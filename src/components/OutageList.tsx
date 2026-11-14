import { useMemo, useState } from 'react';
import { ChevronDown, ShieldCheck, Users } from 'lucide-react';
import type { Closure } from '../types';
import { formatFreshness } from '../data/mockClosures';
import { closureIcon, ICONS } from './map/icons';
import type { Incident } from '../services/incidents';
import { isSampleData } from '../services/incidents';
import { BusRoutes, SeverityBadge, SourceSummary } from './IncidentBits';
import { cx } from './ui';

interface Props {
  incidents: Incident[];
  onSelect: (inc: Incident) => void;
  live: boolean;
  lastSync: number | null;
}

/** Kept for other components that show a single closure's source */
export function SourceBadge({ c }: { c: Closure }) {
  return c.source === 'official' ? (
    <span className="chip bg-sky-soft text-sky-ink">
      <ShieldCheck className="h-3 w-3" /> UMass Facilities
    </span>
  ) : (
    <span className="chip bg-black/[0.05] text-ink-2">
      <Users className="h-3 w-3" /> {c.confirmations_count} student{c.confirmations_count === 1 ? '' : 's'}
    </span>
  );
}

type Filter = 'all' | 'official' | 'community' | 'roads';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'official', label: 'Facilities' },
  { id: 'community', label: 'Students' },
  { id: 'roads', label: 'Roads & buses' }
];

const matches = (inc: Incident, f: Filter) =>
  f === 'all' ? true : f === 'official' ? inc.official.length > 0 : f === 'community' ? inc.community.length > 0 : inc.isRoad || !!inc.bus;

export function OutageList({ incidents, onSelect, live, lastSync }: Props) {
  const [open, setOpen] = useState(true);
  const [filter, setFilter] = useState<Filter>('all');
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, incidents.filter((i) => matches(i, f.id)).length])) as Record<Filter, number>, [incidents]);
  const shown = incidents.filter((i) => matches(i, filter));
  const high = incidents.filter((i) => i.severity === 'high').length;

  return (
    <section aria-labelledby="out-h">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between px-1 py-1">
        <h3 id="out-h" className="eyebrow flex items-center gap-2">
          On campus today · {incidents.length} issue{incidents.length === 1 ? '' : 's'}
          {high > 0 && <span className="rounded-full bg-stop px-1.5 py-px text-[10px] font-semibold normal-case tracking-normal text-white">{high} high alert</span>}
          <span className={cx('inline-block h-1.5 w-1.5 rounded-full', live ? 'bg-go' : 'bg-warn')} aria-hidden />
        </h3>
        <ChevronDown className={cx('h-4 w-4 text-ink-4 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="animate-fade">
          <div className="mt-1.5 flex flex-wrap gap-1" role="tablist" aria-label="Filter issues">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                role="tab"
                aria-selected={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={cx(
                  'rounded-full px-2.5 py-1 text-[12px] transition',
                  filter === f.id ? 'bg-ink text-white' : 'bg-black/[0.04] text-ink-2 hover:bg-black/[0.07]'
                )}
              >
                {f.label}
                <span className={cx('ml-1 tabular-nums', filter === f.id ? 'text-white/60' : 'text-ink-4')}>{counts[f.id]}</span>
              </button>
            ))}
          </div>
          <ul className="mt-2 space-y-1">
            {shown.map((inc) => {
              const c = inc.primary;
              const roadOnly = inc.isRoad && inc.all.every((x) => x.affects === 'road');
              return (
                <li key={inc.id}>
                  <button
                    onClick={() => onSelect(inc)}
                    className={cx(
                      'flex w-full items-start gap-3 rounded-2xl px-1.5 py-2 text-left transition hover:bg-black/[0.03]',
                      inc.severity === 'high' && 'bg-stop-soft/60 hover:bg-stop-soft'
                    )}
                  >
                    <span
                      className={cx(
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white',
                        roadOnly ? 'bg-[#5b6b8c]' : inc.severity === 'high' ? 'bg-[#c4262b]' : inc.all.every((x) => x.status === 'degraded') ? 'bg-warn' : 'bg-stop'
                      )}
                      dangerouslySetInnerHTML={{ __html: roadOnly ? ICONS.bus : closureIcon(c.type) }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="mb-1 flex flex-wrap items-center gap-1.5">
                        <SeverityBadge severity={inc.severity} />
                        {inc.all.some(isSampleData) && <span className="chip bg-black/[0.04] text-ink-4">Sample</span>}
                      </span>
                      <span className="block text-[14px] leading-snug text-ink">{c.title}</span>
                      {inc.bus && (
                        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
                          <span className="font-medium text-[#33405c]">{inc.bus.certain ? 'Buses detoured:' : 'Buses that may be affected:'}</span>
                          <BusRoutes routes={inc.bus.routes} certain={inc.bus.certain} compact />
                        </span>
                      )}
                      <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
                        <SourceSummary inc={inc} />
                        <span>updated {formatFreshness(inc.lastConfirmed)}</span>
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
            {!shown.length && (
              <li className="px-2 py-3 text-[13px] text-ink-3">
                {filter === 'roads' ? 'No road closures or bus detours on campus right now.' : 'Nothing here. Everything we know of is working.'}
              </li>
            )}
          </ul>
          <p className="mt-2 px-1 text-[11px] leading-snug text-ink-4">
            {live ? 'Live from the CampusNav backend' : 'Offline: showing cached and sample reports'}
            {lastSync ? ` · synced ${formatFreshness(new Date(lastSync).toISOString())}` : ''}. <strong className="font-medium text-ink-3">High alert</strong> means UMass
            Facilities and students both report it. Bus routes are matched from OpenStreetMap;{' '}
            <a className="underline" href="https://www.umass.edu/transportation/news" target="_blank" rel="noreferrer">
              UMass Transit news
            </a>{' '}
            has official detours.
          </p>
        </div>
      )}
    </section>
  );
}
