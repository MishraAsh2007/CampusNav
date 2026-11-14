import type { Closure } from '../types';

const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();
const hoursFromNow = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();

/**
 * Seed outages for offline/demo mode. Live mode replaces these with Role 4's /api/closures.
 * The Campus Center elevator is deliberately working at start: the judge demo breaks it.
 */
export const INITIAL_CLOSURES: Closure[] = [
  {
    id: 'ilc-sw-door',
    lat: 42.390829,
    lng: -72.526256,
    radius: 10,
    type: 'automatic_door',
    status: 'closed',
    source: 'community',
    title: 'ILC southwest automatic door not opening',
    description: 'Push plate does nothing; the door is too heavy to open from a chair. Use the southeast entrance.',
    building_name: 'Integrative Learning Center',
    start_time: hoursAgo(30),
    last_confirmed: hoursAgo(1.5),
    confirmations_count: 6
  },
  {
    id: 'npleasant-curb',
    lat: 42.39092,
    lng: -72.5254,
    radius: 7,
    type: 'path',
    status: 'degraded',
    source: 'community',
    title: 'Curb cut at ILC bus stop partly blocked',
    description: 'Plowed slush piled on the curb ramp. Passable with care; a power chair got through.',
    start_time: hoursAgo(5),
    last_confirmed: hoursAgo(0.6),
    confirmations_count: 3
  },
  {
    id: 'herter-walk-construction',
    lat: 42.38775,
    lng: -72.52745,
    radius: 9,
    type: 'construction',
    status: 'closed',
    source: 'official',
    title: 'Sidewalk work north of Herter Hall',
    description: 'Facilities is resetting pavers. Walkway fenced off until Friday.',
    building_name: 'Herter Hall',
    start_time: hoursAgo(50),
    end_time: hoursFromNow(40),
    last_confirmed: hoursAgo(9),
    confirmations_count: 2
  }
];

/** The judge-demo outage: posted as a fake student report. */
export const DEMO_ELEVATOR_REPORT = {
  lat: 42.39146,
  lng: -72.52655,
  connector_id: 'cc-concourse-elevator',
  building_id: 'campus-center',
  title: 'Campus Center concourse elevator out of service',
  description: 'Doors will not open on the concourse level. Sign says technician called.'
};

export function formatFreshness(isoString: string): string {
  const then = new Date(isoString).getTime();
  if (!Number.isFinite(then)) return 'recently';
  const diffMin = Math.max(0, Math.floor((Date.now() - then) / 60000));
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  const h = Math.floor(diffMin / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}
