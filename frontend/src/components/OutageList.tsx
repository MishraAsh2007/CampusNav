import { useState } from 'react';
import { ChevronDown, ShieldCheck, Users } from 'lucide-react';
import type { Closure } from '../types';
import { formatFreshness } from '../data/mockClosures';
import { closureIcon } from './map/icons';
import { cx } from './ui';

interface Props {
  closures: Closure[];
  onSelect: (c: Closure) => void;
  live: boolean;
  lastSync: number | null;
}

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

export function OutageList({ closures, onSelect, live, lastSync }: Props) {
  const [open, setOpen] = useState(false);
  const active = closures.filter((c) => c.status !== 'repaired');
  return (
    <section aria-labelledby="out-h">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between px-1 py-1">
        <h3 id="out-h" className="eyebrow flex items-center gap-2">
          On campus today · {active.length} issue{active.length === 1 ? '' : 's'}
          <span className={cx('inline-block h-1.5 w-1.5 rounded-full', live ? 'bg-go' : 'bg-warn')} aria-hidden />
        </h3>
        <ChevronDown className={cx('h-4 w-4 text-ink-4 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="animate-fade">
          <ul className="mt-1.5 space-y-1">
            {active.map((c) => (
              <li key={c.id}>
                <button onClick={() => onSelect(c)} className="flex w-full items-start gap-3 rounded-2xl px-1.5 py-2 text-left transition hover:bg-black/[0.03]">
                  <span
                    className={cx('flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white', c.status === 'degraded' ? 'bg-warn' : 'bg-stop')}
                    dangerouslySetInnerHTML={{ __html: closureIcon(c.type) }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] leading-snug text-ink">{c.title}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
                      <SourceBadge c={c} />
                      <span>{c.source === 'official' ? 'notice observed' : 'reported'} {formatFreshness(c.last_confirmed)}</span>
                    </span>
                  </span>
                </button>
              </li>
            ))}
            {!active.length && <li className="px-2 py-3 text-[13px] text-ink-3">No mapped active closures in the saved data. This does not establish that every campus asset is working.</li>}
          </ul>
          <p className="mt-2 px-1 text-[11px] text-ink-4">
            {live ? 'Live from the CampusNav backend' : 'Offline: showing cached reports'}
            {lastSync ? ` · cache checked ${formatFreshness(new Date(lastSync).toISOString())}` : ''}. Community reports expire after 24 h unless reconfirmed. Official notices keep their own schedule.
          </p>
        </div>
      )}
    </section>
  );
}
