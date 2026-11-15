import { ExternalLink } from 'lucide-react';
import { Sheet } from './ui';
import { CAMPUS_RESEARCH } from '../data/mockBuildings';

interface Props {
  open: boolean;
  onClose: () => void;
  graphMeta: { vertices: number; edges: number; staircases: number; total_steps: number; walkway_km: number } | null;
  provider: 'google' | 'osm';
}

export function AboutSheet({ open, onClose, graphMeta, provider }: Props) {
  return (
    <Sheet open={open} onClose={onClose} side="center" eyebrow="About" title="Maps know where ramps are. Not what's broken today.">
      <div className="space-y-5 text-[14px] leading-relaxed text-ink-2">
        <p>
          A broken elevator or a dead door opener is an inconvenience for most students. For a wheelchair user it can mean missing class. CampusNav routes around today's
          outages, on the real campus path network, and lets anyone report a problem in two taps.
        </p>

        <section>
          <h3 className="eyebrow mb-2">What students have reported</h3>
          <ul className="space-y-2">
            {CAMPUS_RESEARCH.map((r, i) => (
              <li key={i} className="rounded-2xl bg-black/[0.03] p-3">
                <p className="text-[13px] text-ink-2">{r.finding}</p>
                <a href={r.url} target="_blank" rel="noreferrer" className="mt-1 flex items-center gap-1 text-[11px] text-sky-ink">
                  {r.source} <ExternalLink className="h-3 w-3" />
                </a>
              </li>
            ))}
          </ul>
        </section>

        {graphMeta && (
          <section>
            <h3 className="eyebrow mb-2">The data underneath</h3>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                [graphMeta.edges.toLocaleString(), 'path segments'],
                [graphMeta.staircases.toString(), 'staircases'],
                [graphMeta.total_steps.toLocaleString(), 'steps mapped']
              ].map(([v, l]) => (
                <div key={l} className="rounded-2xl bg-black/[0.03] py-3">
                  <div className="font-display text-[20px] font-semibold text-ink tabular-nums">{v}</div>
                  <div className="text-[11px] text-ink-3">{l}</div>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[12px] text-ink-3">
              {graphMeta.walkway_km} km of walkways from OpenStreetMap, with step counts, handrails and surfaces. Slopes from USGS 3DEP 1 m lidar at every intersection. Basemap:{' '}
              {provider === 'google' ? 'Google Maps' : 'OpenStreetMap'}.
            </p>
          </section>
        )}

        <p className="text-[12px] text-ink-3">
          Need a ride instead? The UMass Accessible Van Service serves students with permanent or temporary mobility impairments.{' '}
          <a className="text-sky-ink underline" href="https://www.umass.edu/disability-services/current-students/physical-access-accommodations" target="_blank" rel="noreferrer">
            Disability Services
          </a>
        </p>
      </div>
    </Sheet>
  );
}
