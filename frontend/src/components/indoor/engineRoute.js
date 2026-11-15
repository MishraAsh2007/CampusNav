import { INDOOR_API_BASE } from '../../services/api';
import { renderReviewedPath } from './indoorRouter';

/**
 * Route inside a building with the Role 1 engine (POST /api/indoor-route) and draw exactly that route.
 *
 * Used for maps the engine served itself (`status: "engine"` from GET /indoor/maps/{id}): its node and
 * edge ids match the map, so `renderReviewedPath` can draw the engine's path with this viewer's visuals.
 * The engine applies the elevator outage rules (car counts, banks, "one out, unknown which").
 */
export async function engineRoute(model, targetId, preferences, { entrance, closures = [] } = {}) {
  const lobby = typeof targetId === 'string' && targetId.endsWith(':@lobby');
  const body = {
    building_id: model.id,
    ...(lobby ? { floor: targetId.slice(0, -':@lobby'.length) } : { node_id: targetId }),
    entrance: entrance && Number.isFinite(entrance.lat) ? { lat: entrance.lat, lng: entrance.lng } : undefined,
    preferences: { step_free: !!(preferences?.no_stairs || preferences?.wheelchair_required) },
    closures: closures.filter((c) => c.status !== 'repaired'),
  };
  let result;
  try {
    const response = await fetch(`${INDOOR_API_BASE}/api/indoor-route`, {
      method: 'POST',
      signal: AbortSignal.timeout(15000),
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    result = await response.json();
  } catch {
    throw new Error('The indoor routing service did not answer.');
  }
  if (result?.status !== 'ok' || !result.node_path) {
    throw new Error(result?.message ?? result?.detail ?? 'No indoor route is available.');
  }
  const route = renderReviewedPath(model, targetId, {
    node_path: result.node_path,
    steps: result.edge_ids.map((edge_id) => ({ edge_id })),
  });
  if (!route) throw new Error('The indoor map changed. Reload the page before starting this route.');
  return { ...route, engineWarnings: result.warnings ?? [], engineSteps: result.steps ?? [] };
}
