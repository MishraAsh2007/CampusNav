/** Arrival is an exact server-provided landmark, not a proximity or GPS guess. */
export default function IndoorStartControl({model, entrance, startNodeId, manualStart, onManualStart, onPlanOutdoor, manualEnabled = false, onEnableManual}) {
  const arrivalId = entrance?.indoorNodeId;
  const knownId = model.nodes.has(startNodeId) ? startNodeId : (model.nodes.has(arrivalId) ? arrivalId : null);
  if (knownId || (model.routingKind !== 'drawing' && entrance?.portalId)) return <div className="rounded-xl bg-emerald-50 p-3 text-emerald-900">
    <p className="text-xs font-semibold uppercase tracking-wide">{entrance ? 'From your outdoor arrival' : 'Starting landmark'}</p>
    <p className="mt-1 font-semibold">{model.nodes.get(knownId)?.label || entrance?.name || 'Your routed entrance'}</p>
    <p className="mt-1">Your indoor directions start here and include the approach to the elevator when needed.</p>
  </div>;
  return <>
    {entrance ? <div className="rounded-xl bg-amber-50 p-3 text-amber-900"><p className="font-semibold">Indoor connection unavailable for this arrival</p><p className="mt-2">The outdoor route ends at {entrance.name || 'this entrance'}, which has no matched doorway on this indoor plan. We cannot continue automatically from that stop.</p>{entrance.handoffMessage && <p className="mt-2">{entrance.handoffMessage}</p>}<button className="mt-2 min-h-11 font-semibold underline" onClick={onPlanOutdoor}>Back to outdoor route</button></div>
      : <div className="rounded-xl bg-slate-50 p-3 text-slate-700"><p>You opened indoor navigation directly, without an outdoor arrival. Plan the outdoor trip first to carry its matched entrance into these directions.</p><button className="mt-2 min-h-11 font-semibold text-emerald-800 underline" onClick={onPlanOutdoor}>Plan outdoor route to this building</button></div>}
    {!manualEnabled ? <button className="min-h-11 text-sm font-semibold text-emerald-800 underline" onClick={onEnableManual}>Start a separate indoor route from a known landmark</button> : <label className="block">Starting landmark<select aria-label="Starting indoor landmark" className="mt-1 min-h-11 w-full rounded-xl border p-2" value={manualStart} onChange={e => onManualStart(e.target.value)}>
      <option value="">Choose where to start</option>
      {[...model.nodes.values()].map(n => <option key={n.id} value={n.id}>{n.label} · floor {n.floor}</option>)}
    </select></label>}
  </>;
}
