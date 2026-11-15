import { routingPreferences } from '../../services/api';
import { renderReviewedPath, targetNodes } from './indoorRouter';

const base = (import.meta.env.VITE_ROUTING_API_URL ?? import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

export async function reviewedRoute(model, targetId, preferences, {portalId, startNode} = {}) {
  if (!portalId && !startNode) throw new Error('Plan an outdoor route to a reviewed entrance first.');
  const targets = targetNodes(model, targetId);
  if (!targets.length) throw new Error('This destination has no reviewed waypoint.');
  const options = routingPreferences(preferences);
  const candidates = await Promise.all(targets.map(async nodeId => {
    const path = portalId ? '/navigation/arrive' : '/indoor/route';
    const payload = portalId ? {
      ...options, building_id: model.id, portal_id: portalId, confirmed: true, continue_indoors: true,
      destination: {building_id: model.id, node_id: nodeId},
    } : {...options, building_id: model.id, start_node_id: startNode, end_node_id: nodeId};
    const response = await fetch(base + path, {method: 'POST', signal: AbortSignal.timeout(15000),
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (portalId && result.arrival_confirmation_required) {
      return {error: 'An outage changed the entrance. Return to the map to follow the new approach.'};
    }
    const leg = portalId ? result.journey?.legs.find(item => item.kind === 'indoor') : result;
    if (!response.ok || !leg?.node_path) {
      return {error: result.message ?? result.detail?.message ?? result.question ?? 'No reviewed indoor route is available.'};
    }
    return {leg};
  }));
  const best = candidates.flatMap(item => item.leg ? [item.leg] : [])
    .sort((a, b) => a.routing_cost - b.routing_cost)[0];
  if (!best) throw new Error(candidates[0]?.error || 'No reviewed indoor route is available.');
  const route = renderReviewedPath(model, targetId, best);
  if (!route) throw new Error('The indoor map changed. Reload the map before starting this route.');
  return route;
}
