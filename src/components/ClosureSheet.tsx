import { CheckCircle2, Clock, Phone, ThumbsUp } from 'lucide-react';
import type { Closure } from '../types';
import { formatFreshness } from '../data/mockClosures';
import { Sheet } from './ui';
import { SourceBadge } from './OutageList';

interface Props {
  closure: Closure | null;
  onClose: () => void;
  onConfirm: (c: Closure) => void;
  onResolve: (c: Closure) => void;
}

const typeLabel: Record<Closure['type'], string> = {
  elevator: 'Elevator',
  automatic_door: 'Automatic door',
  ramp: 'Ramp',
  path: 'Path',
  construction: 'Construction'
};

export function ClosureSheet({ closure: c, onClose, onConfirm, onResolve }: Props) {
  if (!c) return null;
  return (
    <Sheet
      open
      onClose={onClose}
      side="center"
      eyebrow={`${typeLabel[c.type]} · ${c.status === 'degraded' ? 'Use caution' : 'Out of service'}`}
      title={c.title}
      footer={
        <div className="flex gap-2">
          <button className="btn-quiet flex-1" onClick={() => onConfirm(c)}>
            <ThumbsUp className="h-4 w-4" /> Still a problem
          </button>
          <button className="btn-primary flex-1" onClick={() => onResolve(c)}>
            <CheckCircle2 className="h-4 w-4" /> It works now
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-3">
          <SourceBadge c={c} />
          <span className="chip bg-black/[0.05] text-ink-2">
            <Clock className="h-3 w-3" /> confirmed {formatFreshness(c.last_confirmed)}
          </span>
          {c.end_time && <span>Expected fix {new Date(c.end_time).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</span>}
        </div>
        {c.description && <p className="text-[15px] leading-relaxed text-ink-2">{c.description}</p>}
        <p className="text-[13px] text-ink-3">Routes avoid this spot automatically. Confirming keeps the report fresh; it expires after 24 h otherwise.</p>
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
