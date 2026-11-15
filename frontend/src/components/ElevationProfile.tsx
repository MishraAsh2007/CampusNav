import { useId, useMemo } from 'react';

interface Props {
  profile: { d: number; z: number }[];
  color?: string;
  maxGrade: number;
  gain: number;
}

/** Small elevation chart for the route, so a hill is visible before you are on it. */
export function ElevationProfile({ profile, color = '#2a9d64', maxGrade, gain }: Props) {
  const gid = useId();
  const { d, area, minZ, maxZ } = useMemo(() => {
    const pts = profile.filter((p, i) => i === 0 || p.d >= profile[i - 1].d);
    const total = Math.max(1, pts[pts.length - 1]?.d ?? 1);
    const zs = pts.map((p) => p.z);
    const lo = Math.min(...zs);
    const hi = Math.max(...zs);
    const span = Math.max(4, hi - lo); // keep flat routes looking flat
    const W = 300;
    const H = 52;
    const x = (v: number) => (v / total) * W;
    const y = (z: number) => H - 6 - ((z - lo) / span) * (H - 14);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.d).toFixed(1)},${y(p.z).toFixed(1)}`).join(' ');
    return { d: line, area: `${line} L${W},${H} L0,${H} Z`, minZ: lo, maxZ: hi };
  }, [profile]);

  if (profile.length < 2) return null;
  return (
    <figure className="rounded-2xl bg-black/[0.03] px-3 pt-2.5 pb-2" aria-label={`Elevation profile: ${gain} m of climbing, steepest ${maxGrade}%`}>
      <figcaption className="mb-1 flex items-baseline justify-between text-[11px] text-ink-3">
        <span>Elevation</span>
        <span className="tabular-nums">
          ↑ {gain} m · {Math.round(minZ)}–{Math.round(maxZ)} m
        </span>
      </figcaption>
      <svg viewBox="0 0 300 52" preserveAspectRatio="none" className="h-12 w-full" aria-hidden>
        <defs>
          <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gid})`} />
        <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      </svg>
    </figure>
  );
}
