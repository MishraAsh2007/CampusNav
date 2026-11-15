import { useState } from 'react';
import type { NavigationResult } from '../../services/api';
import IndoorStepPanel from './IndoorStepPanel';

export function ReviewedDirections({ result, onDone }: {result: NavigationResult; onDone: () => void}) {
  const [active, setActive] = useState(0);
  const legs = result.journey?.legs ?? [];
  const entry = legs.find(leg => leg.kind === 'portal' && leg.direction === 'enter');
  const indoor = legs.flatMap(leg => leg.kind === 'indoor' ? leg.steps : []);
  const steps = [
    ...(entry?.kind === 'portal' ? [{id: entry.portal_id, text: entry.instruction, kind: 'door'}] : []),
    ...indoor.map(step => ({id: step.edge_id, text: step.instruction, kind: step.kind, distanceM: step.distance_m})),
  ];
  const current = indoor[active - (entry ? 1 : 0)];
  const floor = current?.from_floor ?? indoor[0]?.from_floor;
  const lines = indoor.filter(step => step.from_floor === floor && step.geometry);
  const points = lines.flatMap(step => step.geometry!.coordinates);
  const xs = points.map(p => p[0]);
  const ys = points.map(p => p[1]);
  const minX = Math.min(...xs), minY = Math.min(...ys);
  const width = Math.max(1, Math.max(...xs) - minX);
  const height = Math.max(1, Math.max(...ys) - minY);
  return <section className="space-y-3 rounded-2xl bg-white p-3" aria-label="Reviewed indoor route">
    <div className="flex items-center justify-between gap-2">
      <h2 className="font-semibold">Indoor directions</h2>
      <button type="button" className="btn-quiet" onClick={onDone}>Close</button>
    </div>
    {points.length > 0 && <figure>
      <figcaption className="text-sm">Mapped route on floor {floor}</figcaption>
      <svg className="h-32 w-full text-go" role="img" aria-label={`Route on floor ${floor}`}
        viewBox={`${minX - width * 0.1} ${minY - height * 0.1} ${width * 1.2} ${height * 1.2}`}>
        {lines.map(step => <polyline key={step.edge_id} fill="none" stroke="currentColor"
          strokeOpacity={step === current ? 1 : 0.45} strokeWidth={step === current ? 5 : 3}
          strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"
          points={step.geometry!.coordinates.map(point => point.join(',')).join(' ')} />)}
      </svg>
    </figure>}
    {steps.length ? <IndoorStepPanel steps={steps} active={active} onGo={setActive} onDone={onDone}
      autoSpeak={false} className="rounded-2xl border border-black/10" /> : <p>You are at the mapped destination.</p>}
    {[...new Set(result.journey?.warnings ?? [])].map(warning => <p key={warning} className="text-sm text-ink-3">{warning}</p>)}
  </section>;
}
