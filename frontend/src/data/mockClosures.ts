import type { Closure } from '../types';

const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();
const hoursFromNow = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();

const FCS_NOTICES = 'https://www.umass.edu/facilities/service-interruptions';
const FCS_IMPACT = 'https://www.umass.edu/facilities/campus-impact-notices';

/**
 * Sample outages for offline/demo mode (ids start with "demo-" and are labelled "Sample" in the UI).
 * Live mode replaces them with the backend's /closures feed (official notices + community reports).
 * The real Facilities notice list needs a UMass login, so these show what Role 3's pipeline will post.
 * The Campus Center elevator is deliberately working at start: the judge demo breaks it.
 */
export const INITIAL_CLOSURES: Closure[] = [
  // Same door, two sources: Facilities notice + student reports -> ranked "High alert"
  {
    id: 'demo-ilc-sw-door-official',
    lat: 42.390829,
    lng: -72.526256,
    radius: 10,
    type: 'automatic_door',
    status: 'closed',
    source: 'official',
    title: 'ILC southwest entrance: door operator out of service',
    description: 'Automatic door operator awaiting replacement parts. Use the southeast entrance on North Pleasant Street.',
    building_name: 'Integrative Learning Center',
    reference: 'Service interruption (sample)',
    source_url: FCS_NOTICES,
    start_time: hoursAgo(28),
    end_time: hoursFromNow(48),
    last_confirmed: hoursAgo(20),
    confirmations_count: 1
  },
  {
    id: 'demo-ilc-sw-door',
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
    id: 'demo-npleasant-curb',
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
    id: 'demo-herter-walk-construction',
    lat: 42.38775,
    lng: -72.52745,
    radius: 9,
    type: 'construction',
    status: 'closed',
    source: 'official',
    title: 'Sidewalk work north of Herter Hall',
    description: 'Facilities is resetting pavers. Walkway fenced off until Friday.',
    building_name: 'Herter Hall',
    reference: 'Campus impact notice (sample)',
    source_url: FCS_IMPACT,
    start_time: hoursAgo(50),
    end_time: hoursFromNow(40),
    last_confirmed: hoursAgo(9),
    confirmations_count: 1
  },
  // Road work: sidewalks stay open, buses detour. Affected routes are worked out from OpenStreetMap.
  {
    id: 'demo-npleasant-roadwork',
    lat: 42.39135,
    lng: -72.52528,
    radius: 20,
    type: 'construction',
    status: 'closed',
    source: 'official',
    affects: 'road',
    road_name: 'North Pleasant Street',
    title: 'North Pleasant Street closed to traffic at the ILC',
    description: 'Utility trench across the road between the ILC and Morrill IV. Sidewalks and crosswalks stay open. Buses detour via Commonwealth Avenue.',
    reference: 'Campus impact notice (sample)',
    source_url: FCS_IMPACT,
    start_time: hoursAgo(6),
    end_time: hoursFromNow(30),
    last_confirmed: hoursAgo(2),
    confirmations_count: 1
  },
  // Official notice with no student reports, inside a building
  {
    id: 'demo-lib-elevator-inspection',
    lat: 42.389702,
    lng: -72.528172,
    radius: 12,
    type: 'elevator',
    status: 'degraded',
    source: 'official',
    title: 'Du Bois Library: one low-rise elevator out for inspection',
    description: 'State inspection of one low-rise car, 9 a.m. to noon. Other cars in the bank stay in service.',
    building_name: 'W.E.B. Du Bois Library',
    reference: 'Service interruption (sample)',
    source_url: FCS_NOTICES,
    start_time: hoursAgo(1),
    end_time: hoursFromNow(2),
    last_confirmed: hoursAgo(1),
    confirmations_count: 1
  }
];

/** Judge demo step 4: Facilities confirms the student report, making it a High alert. */
export const DEMO_ELEVATOR_OFFICIAL: Closure = {
  id: 'demo-cc-elevator-official',
  lat: 42.39146,
  lng: -72.52655,
  radius: 12,
  type: 'elevator',
  status: 'closed',
  source: 'official',
  connector_id: 'cc-concourse-elevator',
  building_name: 'Lincoln Campus Center',
  title: 'Campus Center concourse elevator out of service',
  description: 'Elevator contractor on site. Expected back in service tomorrow afternoon.',
  reference: 'Service interruption (simulated)',
  source_url: FCS_NOTICES,
  start_time: new Date().toISOString(),
  last_confirmed: new Date().toISOString(),
  confirmations_count: 1
};

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
  if (!Number.isFinite(then)) return 'at an unknown time';
  const diffMin = Math.max(0, Math.floor((Date.now() - then) / 60000));
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  const h = Math.floor(diffMin / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}
