import { Bus, ShieldCheck, Siren, Users } from 'lucide-react';
import type { Incident, Severity } from '../services/incidents';
import { SEVERITY_HINT, SEVERITY_LABEL } from '../services/incidents';
import { cx } from './ui';

const TONE: Record<Severity, string> = {
  high: 'bg-stop text-white',
  official: 'bg-sky-soft text-sky-ink',
  likely: 'bg-warn-soft text-warn-ink',
  reported: 'bg-black/[0.05] text-ink-2'
};

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span className={cx('chip', TONE[severity], className)} title={SEVERITY_HINT[severity]}>
      {severity === 'high' ? <Siren className="h-3 w-3" /> : severity === 'official' ? <ShieldCheck className="h-3 w-3" /> : <Users className="h-3 w-3" />}
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

/** "Facilities + 6 students" style source summary */
export function SourceSummary({ inc }: { inc: Incident }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {inc.official.length > 0 && (
        <span className="chip bg-sky-soft text-sky-ink">
          <ShieldCheck className="h-3 w-3" /> UMass Facilities
        </span>
      )}
      {inc.community.length > 0 && (
        <span className="chip bg-black/[0.05] text-ink-2">
          <Users className="h-3 w-3" /> {inc.confirmations} student{inc.confirmations === 1 ? '' : 's'}
        </span>
      )}
    </span>
  );
}

export function BusRoutes({ routes, certain, compact }: { routes: string[]; certain: boolean; compact?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1" aria-label={`Bus routes ${certain ? 'detoured' : 'that may be affected'}: ${routes.join(', ')}`}>
      <Bus className={cx('shrink-0 text-[#33405c]', compact ? 'h-3 w-3' : 'h-3.5 w-3.5')} aria-hidden />
      {routes.map((r) => (
        <span key={r} className="rounded-md bg-[#eef1f7] px-1.5 py-px text-[11px] font-semibold tabular-nums text-[#33405c]">
          {r}
        </span>
      ))}
    </span>
  );
}
