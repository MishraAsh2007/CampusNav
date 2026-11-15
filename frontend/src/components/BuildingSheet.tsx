import { MapPin, Navigation } from 'lucide-react';
import type { Building, Closure } from '../types';
import { Sheet } from './ui';
interface Props {
  building: Building | null; closures: Closure[]; focusEntranceId: string | null;
  onClose: () => void; onStart: (b: Building) => void; onGo: (b: Building) => void; onReport: (b: Building) => void; onSelectEntrance: (id: string | null) => void;
}
export function BuildingSheet({building: b, closures, focusEntranceId, onClose, onStart, onGo, onReport, onSelectEntrance}: Props) {
  if (!b) return null;
  return <Sheet open onClose={onClose} eyebrow={b.code} title={b.name} footer={<div className="flex gap-2">
    <button className="btn-quiet flex-1" onClick={() => onStart(b)}><MapPin className="h-4 w-4" /> Start here</button>
    <button className="btn-primary flex-1" onClick={() => onGo(b)}><Navigation className="h-4 w-4" /> Directions</button>
  </div>}><div className="space-y-4 text-sm">
    <p>{b.access_level}. Source edition: {b.source_as_of}. Current access has not been field verified.</p>
    {focusEntranceId && <p className="rounded-xl bg-sky-soft p-3">Selected entrance: {b.entrances.find(e => e.id === focusEntranceId)?.name}. Start here or Directions will use this entrance.</p>}
    <h3 className="eyebrow">Mapped entrances</h3>
    <label className="block">Route entrance<select className="mt-1 block w-full rounded-xl border p-2" value={focusEntranceId ?? ''} onChange={e => onSelectEntrance(e.target.value || null)}>
      <option value="">Choose the shortest eligible approach</option>
      {b.entrances.filter(e => !e.keycard_required).map(e => <option key={e.id} value={e.id}>{e.name} ({e.id})</option>)}
    </select></label>
    {b.entrances.map(e => <article className={`rounded-2xl p-3 ${e.id === focusEntranceId ? 'bg-sky-soft' : 'bg-black/[0.03]'}`} key={e.id}>
      <strong>{e.name}</strong><p>{e.step_free === true ? 'Source documents step-free access' : e.step_free === false ? 'Not wheelchair accessible in source' : 'Step-free access unverified'} · {e.door_type === 'unknown' ? 'Door type unknown' : `${e.door_type} door`}</p>
      {e.keycard_required && <p>Keycard required; excluded from public route choices.</p>}
      <p className="mt-1 text-xs text-ink-3">{e.notes}</p>
      {e.source_url && <a className="text-xs underline" href={e.source_url} target="_blank" rel="noreferrer">{e.source}</a>}
    </article>)}
    <h3 className="eyebrow">Elevators</h3>
    <p>{b.elevators.mapped_locations ?? b.elevators.list.length} mapped location(s). A point may represent an elevator bank; car count and floors served are unknown.</p>
    {b.elevators.list.map(l => <p key={l.id}>{l.name}: {closures.some(c => c.type === 'elevator' && c.connector_id === l.id) ? 'An active service issue is reported' : 'Operating status unknown'}</p>)}
    <p>{b.notes}</p>
    <button className="btn-quiet" onClick={() => onReport(b)}>Report an elevator or path problem</button>
    {b.source_url && <a className="block underline text-xs" href={b.source_url} target="_blank" rel="noreferrer">Open UMass accessibility map</a>}
  </div></Sheet>;
}
