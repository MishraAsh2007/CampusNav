import { AlertTriangle, Bus, CheckCircle2, DoorOpen, Eye, EyeOff, Footprints, Info, RefreshCw } from 'lucide-react';
import type { Building, RouteResponse, UserPreferences } from '../types';
import { ElevationProfile } from './ElevationProfile';
import { cx } from './ui';

interface Props {
  accessible: RouteResponse | null;
  standard: RouteResponse | null;
  failure?: string;
  notes: string[];
  tab: 'accessible' | 'standard';
  onTab: (t: 'accessible' | 'standard') => void;
  showStandard: boolean;
  onToggleStandard: () => void;
  prefs: UserPreferences;
  arrivalEntrance: { building: Building; name: string; door: string } | null;
  destinationBuilding: Building | null;
  engine: 'local' | 'remote';
  graphEdges: number;
  loading: boolean;
  justRerouted: boolean;
}

const mins = (s: number) => Math.max(1, Math.round(s / 60));

export function RouteSummary(p: Props) {
  const a = p.accessible;
  const s = p.standard;

  if (p.loading && !a && !s) {
    return (
      <div className="space-y-2" aria-busy>
        <div className="h-16 rounded-3xl bg-gradient-to-r from-black/[0.03] via-black/[0.06] to-black/[0.03] bg-[length:200%_100%] animate-shimmer" />
        <div className="h-10 rounded-2xl bg-black/[0.03]" />
      </div>
    );
  }

  if (!a) {
    return (
      <div className="rounded-3xl bg-stop-soft p-4 animate-rise" role="alert">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-stop" />
          <div className="space-y-2 text-[13px] text-ink-2">
            <p className="text-[15px] font-medium text-ink">No route that fits your needs</p>
            <p>{p.failure ?? 'Try relaxing the slope limit.'}</p>
            <p>
              UMass runs an{' '}
              <a
                className="font-medium text-sky-ink underline underline-offset-2"
                href="https://www.umass.edu/disability-services/current-students/physical-access-accommodations"
                target="_blank"
                rel="noreferrer"
              >
                Accessible Van Service
              </a>{' '}
              for students with permanent or temporary mobility impairments.
            </p>
          </div>
        </div>
        {s && (
          <p className="mt-3 flex items-center gap-1.5 border-t border-black/5 pt-3 text-[12px] text-ink-3">
            <Bus className="h-3.5 w-3.5" /> A regular map would say {mins(s.summary.total_duration_s)} min with {s.summary.stair_count} steps.
          </p>
        )}
      </div>
    );
  }

  const stairsAvoided = a.avoided?.filter((x) => x.kind === 'stairs').reduce((n, x) => n + (x.step_count ?? 0), 0) ?? 0;
  const steepAvoided = a.avoided?.filter((x) => x.kind === 'steep') ?? [];
  const extra = s ? a.summary.total_distance_m - s.summary.total_distance_m : 0;
  const reroute = a.summary.warnings.find((w) => w.startsWith('Rerouted'));
  const otherWarnings = a.summary.warnings.filter((w) => w !== reroute);
  const restroomMissing = p.prefs.need_accessible_restroom && p.destinationBuilding && !p.destinationBuilding.accessible_restrooms;

  return (
    <div className="space-y-3">
      {reroute && (
        <div
          className={cx('flex items-start gap-2.5 rounded-2xl bg-lift-soft px-3.5 py-3 text-[13px] text-lift-ink', p.justRerouted && 'animate-pop')}
          role="status"
          aria-live="polite"
        >
          <RefreshCw className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{reroute}</span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2" role="tablist" aria-label="Route options">
        <button
          role="tab"
          aria-selected={p.tab === 'accessible'}
          onClick={() => p.onTab('accessible')}
          className={cx(
            'rounded-3xl p-3.5 text-left transition duration-300 ease-soft',
            p.tab === 'accessible' ? 'bg-go-soft ring-2 ring-go/50' : 'bg-black/[0.03] hover:bg-black/[0.05]'
          )}
        >
          <span className="flex items-center gap-1.5 text-[12px] font-medium text-go-ink">
            <CheckCircle2 className="h-3.5 w-3.5" /> Works for you
          </span>
          <span className="mt-1 block font-display text-[26px] font-semibold leading-none tracking-tight text-ink tabular-nums">
            {mins(a.summary.total_duration_s)}
            <span className="ml-0.5 text-[15px] font-medium text-ink-3"> min</span>
          </span>
          <span className="mt-1.5 block text-[12px] text-ink-3 tabular-nums">
            {a.summary.total_distance_m} m · max {a.summary.max_grade_pct}%
          </span>
        </button>
        {s && (
          <button
            role="tab"
            aria-selected={p.tab === 'standard'}
            onClick={() => p.onTab('standard')}
            className={cx(
              'rounded-3xl p-3.5 text-left transition duration-300 ease-soft',
              p.tab === 'standard' ? 'bg-stop-soft ring-2 ring-stop/40' : 'bg-black/[0.03] hover:bg-black/[0.05]'
            )}
          >
            <span className="flex items-center gap-1.5 text-[12px] font-medium text-stop-ink">
              <Footprints className="h-3.5 w-3.5" /> Regular map
            </span>
            <span className="mt-1 block font-display text-[26px] font-semibold leading-none tracking-tight text-ink tabular-nums">
              {mins(s.summary.total_duration_s)}
              <span className="ml-0.5 text-[15px] font-medium text-ink-3"> min</span>
            </span>
            <span className="mt-1.5 block text-[12px] text-ink-3 tabular-nums">
              {s.summary.stair_count ? `${s.summary.stair_count} steps` : 'no stairs'} · max {s.summary.max_grade_pct}%
            </span>
          </button>
        )}
      </div>

      {(stairsAvoided > 0 || steepAvoided.length > 0) && (
        <div className="rounded-2xl bg-black/[0.03] px-3.5 py-3 text-[13px] text-ink-2">
          <p>
            Skips{' '}
            {stairsAvoided > 0 && <strong className="font-semibold text-ink">{stairsAvoided} steps</strong>}
            {stairsAvoided > 0 && steepAvoided.length > 0 && ' and '}
            {steepAvoided.length > 0 && (
              <strong className="font-semibold text-ink">
                {steepAvoided.length} slope{steepAvoided.length > 1 ? 's' : ''} over {p.prefs.max_grade_pct}%
              </strong>
            )}{' '}
            that a regular map would use{extra > 5 ? `, for ${extra} m more walking.` : extra < -5 ? '.' : ', at about the same distance.'}
          </p>
          <ul className="mt-1.5 space-y-0.5 text-[12px] text-ink-3">
            {a.avoided
              ?.filter((x) => x.kind === 'stairs')
              .slice(0, 3)
              .map((x, i) => <li key={i}>· {x.label}</li>)}
          </ul>
        </div>
      )}

      {p.arrivalEntrance && (
        <div className="flex items-start gap-2.5 px-1 text-[13px] text-ink-2">
          <DoorOpen className="mt-0.5 h-4 w-4 shrink-0 text-go" />
          <span>
            Arrive at the <span className="font-medium text-ink">{p.arrivalEntrance.name.toLowerCase()}</span> ({p.arrivalEntrance.door} door).
          </span>
        </div>
      )}

      {[...otherWarnings, ...p.notes, ...(restroomMissing ? [`${p.destinationBuilding!.name} has no accessible restroom on record.`] : [])].map((w, i) => (
        <div key={i} className="flex items-start gap-2.5 rounded-2xl bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn-ink">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{w}</span>
        </div>
      ))}

      {a.profile && p.tab === 'accessible' && <ElevationProfile profile={a.profile} maxGrade={a.summary.max_grade_pct} gain={a.summary.elevation_gain_m} />}
      {s?.profile && p.tab === 'standard' && <ElevationProfile profile={s.profile} maxGrade={s.summary.max_grade_pct} gain={s.summary.elevation_gain_m} color="#e5484d" />}

      <div className="flex items-center justify-between gap-2 px-1">
        <button onClick={p.onToggleStandard} className="btn-ghost -ml-2 !px-2 !py-1 text-[12px]">
          {p.showStandard ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          {p.showStandard ? 'Hide regular route' : 'Compare on map'}
        </button>
        <span className="flex items-center gap-1 text-[11px] text-ink-4" title="Routing engine and graph size">
          <Info className="h-3 w-3" />
          {p.engine === 'remote' ? 'Role 1 engine' : `${(a.summary.compute_ms ?? 0) < 1 ? '<1' : a.summary.compute_ms} ms`} · {p.graphEdges.toLocaleString()} paths
        </span>
      </div>
    </div>
  );
}
