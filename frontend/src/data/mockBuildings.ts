import type { Building, BuildingEntrance } from '../types';

/**
 * Central-campus buildings.
 *
 * Positions: OpenStreetMap building footprints and entrance nodes (osm_id where available).
 * Door types, elevator lists and ramp grades: CampusNav seed data for the demo. Role 3's pipeline and
 * community reports replace these; verify against the official UMass Campus Accessibility Map.
 * student_reports: sourced quotes/paraphrases from student journalism and UMass pages (see url).
 */

const COLLEGIAN_2023 = 'https://dailycollegian.com/2023/03/umass-campus-is-not-accessible/';
const COLLEGIAN_2018 = 'https://dailycollegian.com/2018/09/handicap-inaccessible/';
const COLLEGIAN_2013 = 'https://dailycollegian.com/2013/02/for-some-winter-weather-burdens-on-campus-handicap-accessibility/';
const UMASS_ATC = 'https://www.umass.edu/it/assistive';

type Raw = Omit<Building, 'step_free_entrances' | 'door_type'> & { door_type?: Building['door_type'] };

function finalize(b: Raw): Building {
  const sf = b.entrances.filter((e) => e.step_free);
  const types = new Set(sf.map((e) => e.door_type));
  return {
    ...b,
    step_free_entrances: sf,
    door_type: b.door_type ?? (types.size > 1 ? 'mixed' : (sf[0]?.door_type ?? 'manual'))
  };
}

const e = (x: BuildingEntrance) => x;

const RAW: Raw[] = [
  {
    id: 'campus-center',
    name: 'Lincoln Campus Center',
    code: 'CC',
    category: 'student_services',
    location: { lat: 42.39180, lng: -72.52702 },
    google_place_query: 'Murray D. Lincoln Campus Center, Amherst MA',
    entrances: [
      e({ id: 'cc-west', name: 'West concourse entrance (garage side)', lat: 42.391615, lng: -72.527451, step_free: true, door_type: 'automatic', has_ramp: false, level: 'Concourse', osm_id: 1445169880 }),
      e({ id: 'cc-east', name: 'Blue Wall entrance (east)', lat: 42.391398, lng: -72.526594, step_free: true, door_type: 'automatic', has_ramp: true, ramp_grade_pct: 4.6, osm_id: 6359546588 }),
      e({ id: 'cc-north', name: 'North entrance', lat: 42.391864, lng: -72.526543, step_free: true, door_type: 'push-button', has_ramp: false, osm_id: 8393893323 }),
      e({ id: 'cc-south', name: 'South plaza doors', lat: 42.391106, lng: -72.52632, step_free: false, door_type: 'manual', has_ramp: false, notes: 'Reached by stairs from the ILC plaza.', osm_id: 8393893332 })
    ],
    elevators: {
      total_count: 3,
      working_count: 3,
      floors_served: 'Concourse to Level 11',
      status: 'all_operational',
      list: [
        { id: 'cc-el-main', name: 'Concourse elevator bank', floors: 'C–11', status: 'operational', connector_id: 'cc-concourse-elevator' },
        { id: 'cc-el-hotel', name: 'Hotel tower elevators', floors: 'C–11', status: 'operational' },
        { id: 'cc-el-freight', name: 'Service elevator', floors: 'B–3', status: 'operational' }
      ]
    },
    accessible_restrooms: true,
    lactation_room: true,
    all_floors_accessible: true,
    notes: 'The concourse connects the garage side to the Student Union and the upper plaza. Its elevators are the short way between levels.'
  },
  {
    id: 'student-union',
    name: 'Student Union',
    code: 'SU',
    category: 'student_services',
    location: { lat: 42.39087, lng: -72.5276 },
    google_place_query: 'Student Union, UMass Amherst',
    entrances: [
      e({ id: 'su-west', name: 'West entrance', lat: 42.390822, lng: -72.527949, step_free: true, door_type: 'automatic', has_ramp: false, osm_id: 9733532733 }),
      e({ id: 'su-north', name: 'North entrance (facing Campus Center)', lat: 42.39121, lng: -72.52758, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 3.8 }),
      e({ id: 'su-south', name: 'South doors (pond side)', lat: 42.39056, lng: -72.52752, step_free: false, door_type: 'manual', has_ramp: false, notes: 'Short flights of steps from the pond path.' })
    ],
    elevators: {
      total_count: 2,
      working_count: 2,
      floors_served: 'Basement to Ballroom (Level 3)',
      status: 'all_operational',
      list: [
        { id: 'su-el-central', name: 'Central atrium elevator', floors: 'B–3', status: 'operational' },
        { id: 'su-el-ballroom', name: 'Ballroom elevator', floors: '1–3', status: 'operational' }
      ]
    },
    accessible_restrooms: true,
    lactation_room: false,
    all_floors_accessible: true
  },
  {
    id: 'ilc',
    name: 'Integrative Learning Center',
    code: 'ILC',
    category: 'academic',
    location: { lat: 42.39104, lng: -72.5259 },
    google_place_query: 'Integrative Learning Center, UMass Amherst',
    entrances: [
      e({ id: 'ilc-sw', name: 'Southwest entrance', lat: 42.390829, lng: -72.526256, step_free: true, door_type: 'automatic', has_ramp: false, level: '2', osm_id: 6382267406 }),
      e({ id: 'ilc-se', name: 'Southeast entrance (North Pleasant St)', lat: 42.390887, lng: -72.525402, step_free: true, door_type: 'automatic', has_ramp: false, level: '2', osm_id: 6382267407 }),
      e({ id: 'ilc-ne', name: 'Northeast entrance', lat: 42.391276, lng: -72.52556, step_free: true, door_type: 'push-button', has_ramp: false, osm_id: 8393893336 }),
      e({ id: 'ilc-nw', name: 'Northwest entrance', lat: 42.391339, lng: -72.526436, step_free: false, door_type: 'manual', has_ramp: false, osm_id: 14185644842 })
    ],
    elevators: {
      total_count: 3,
      working_count: 3,
      floors_served: 'Floors 1–4',
      status: 'all_operational',
      list: [
        { id: 'ilc-el-w', name: 'West atrium elevator', floors: '1–4', status: 'operational' },
        { id: 'ilc-el-e', name: 'East elevator', floors: '1–4', status: 'operational' },
        { id: 'ilc-el-s', name: 'Service elevator', floors: 'B–4', status: 'operational' }
      ]
    },
    accessible_restrooms: true,
    lactation_room: true,
    all_floors_accessible: true,
    student_reports: [
      {
        text: 'A student columnist reported one ILC automatic door broken, funnelling everyone through the other one.',
        source: 'Massachusetts Daily Collegian',
        url: COLLEGIAN_2023,
        year: 2023
      }
    ]
  },
  {
    id: 'dubois-library',
    name: 'W.E.B. Du Bois Library',
    code: 'LIB',
    category: 'library',
    location: { lat: 42.38974, lng: -72.52817 },
    google_place_query: 'W.E.B. Du Bois Library, Amherst MA',
    entrances: [
      e({ id: 'lib-main', name: 'Main lobby entrance', lat: 42.389702, lng: -72.528172, step_free: true, door_type: 'automatic', has_ramp: true, ramp_grade_pct: 4.2, osm_id: 8393893355 })
    ],
    elevators: {
      total_count: 4,
      working_count: 4,
      floors_served: 'Lower Level to Floor 26 (split banks)',
      status: 'all_operational',
      list: [
        { id: 'lib-el-low', name: 'Low-rise bank', floors: 'LL–13', status: 'operational' },
        { id: 'lib-el-high', name: 'High-rise bank', floors: '1, 14–26', status: 'operational' },
        { id: 'lib-el-lc', name: 'Learning Commons elevator', floors: 'LL–1', status: 'operational' },
        { id: 'lib-el-sc', name: 'Special Collections elevator', floors: '25–26', status: 'operational' }
      ]
    },
    accessible_restrooms: true,
    lactation_room: true,
    all_floors_accessible: true,
    notes: 'The Assistive Technology Center is on the Lower Level in the Learning Commons.',
    student_reports: [
      { text: 'One of the library automatic doors was reported broken for weeks.', source: 'Massachusetts Daily Collegian', url: COLLEGIAN_2023, year: 2023 },
      { text: 'Assistive Technology Center: Lower Level, Learning Commons.', source: 'UMass IT', url: UMASS_ATC, year: 2026 }
    ]
  },
  {
    id: 'goodell',
    name: 'Goodell Hall',
    code: 'GDL',
    category: 'administration',
    location: { lat: 42.38871, lng: -72.52922 },
    google_place_query: 'Goodell Hall, UMass Amherst',
    entrances: [
      e({ id: 'gdl-west', name: 'West entrance', lat: 42.388757, lng: -72.52964, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 4.9, osm_id: 13194425358 }),
      e({ id: 'gdl-east', name: 'East front steps', lat: 42.38869, lng: -72.52885, step_free: false, door_type: 'manual', has_ramp: false })
    ],
    elevators: {
      total_count: 1,
      working_count: 1,
      floors_served: 'Floors 1–5',
      status: 'all_operational',
      list: [{ id: 'gdl-el-1', name: 'Central elevator', floors: '1–5', status: 'operational' }]
    },
    accessible_restrooms: true,
    all_floors_accessible: true,
    notes: 'Use the west entrance for step-free access.'
  },
  {
    id: 'morrill',
    name: 'Morrill Science Center',
    code: 'MOR',
    category: 'academic',
    location: { lat: 42.3899, lng: -72.5245 },
    google_place_query: 'Morrill Science Center, UMass Amherst',
    entrances: [
      e({ id: 'mor-4n', name: 'Morrill IV North entrance', lat: 42.390656, lng: -72.524711, step_free: true, door_type: 'automatic', has_ramp: false, osm_id: 8393893342 }),
      e({ id: 'mor-2', name: 'Morrill II west entrance', lat: 42.389779, lng: -72.524732, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 5.1, osm_id: 8393893345 }),
      e({ id: 'mor-3', name: 'Morrill III entrance', lat: 42.389287, lng: -72.524534, step_free: false, door_type: 'manual', has_ramp: false, osm_id: 8393893347 })
    ],
    elevators: {
      total_count: 3,
      working_count: 3,
      floors_served: 'Wings I–IV (split levels between wings)',
      status: 'all_operational',
      list: [
        { id: 'mor-el-4', name: 'Morrill IV elevator', floors: '1–5', status: 'operational' },
        { id: 'mor-el-2', name: 'Morrill II elevator', floors: '1–4', status: 'operational' },
        { id: 'mor-el-3', name: 'Morrill III elevator', floors: '1–5', status: 'operational' }
      ]
    },
    accessible_restrooms: true,
    all_floors_accessible: true,
    notes: 'Several connected wings with split levels. Enter through Morrill IV North for the simplest step-free path.'
  },
  {
    id: 'hasbrouck',
    name: 'Hasbrouck Laboratory',
    code: 'HAS',
    category: 'academic',
    location: { lat: 42.39179, lng: -72.52589 },
    google_place_query: 'Hasbrouck Laboratory, UMass Amherst',
    entrances: [
      e({ id: 'has-se', name: 'Southeast entrance', lat: 42.391713, lng: -72.525928, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 5.0, osm_id: 1366228592 }),
      e({ id: 'has-e', name: 'East entrance', lat: 42.39182, lng: -72.525716, step_free: true, door_type: 'manual', has_ramp: false, osm_id: 8393880716 }),
      e({ id: 'has-w', name: 'West entrance', lat: 42.391815, lng: -72.526081, step_free: false, door_type: 'manual', has_ramp: false, notes: 'Tagged wheelchair=no in OpenStreetMap.', osm_id: 11999160338 })
    ],
    elevators: {
      total_count: 1,
      working_count: 1,
      floors_served: 'Floors 1–3',
      status: 'all_operational',
      list: [{ id: 'has-el-1', name: 'Main elevator', floors: '1–3', status: 'operational' }]
    },
    accessible_restrooms: false,
    all_floors_accessible: true
  },
  {
    id: 'worcester',
    name: 'Worcester Dining Commons',
    code: 'WOR',
    category: 'dining',
    location: { lat: 42.39328, lng: -72.52509 },
    google_place_query: 'Worcester Dining Commons, UMass Amherst',
    entrances: [
      e({ id: 'wor-main', name: 'Main entrance', lat: 42.393165, lng: -72.525319, step_free: true, door_type: 'automatic', has_ramp: false, osm_id: 8567645961 }),
      e({ id: 'wor-west', name: 'West entrance', lat: 42.393349, lng: -72.525508, step_free: true, door_type: 'push-button', has_ramp: false, osm_id: 14143422986 })
    ],
    elevators: {
      total_count: 1,
      working_count: 1,
      floors_served: 'Floors 1–2',
      status: 'all_operational',
      list: [{ id: 'wor-el-1', name: 'Dining elevator', floors: '1–2', status: 'operational' }]
    },
    accessible_restrooms: true,
    all_floors_accessible: true,
    student_reports: [
      { text: 'Dining halls packed with tables and chairs leave little room to move with a mobility aid.', source: 'Massachusetts Daily Collegian', url: COLLEGIAN_2023, year: 2023 }
    ]
  },
  {
    id: 'herter',
    name: 'Herter Hall',
    code: 'HER',
    category: 'academic',
    location: { lat: 42.38724, lng: -72.52717 },
    google_place_query: 'Herter Hall, UMass Amherst',
    entrances: [
      e({ id: 'her-main', name: 'Main entrance', lat: 42.387171, lng: -72.527002, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 4.0, osm_id: 12677355103 })
    ],
    elevators: {
      total_count: 1,
      working_count: 1,
      floors_served: 'Floors 1–6',
      status: 'all_operational',
      list: [{ id: 'her-el-1', name: 'Main elevator', floors: '1–6', status: 'operational' }]
    },
    accessible_restrooms: true,
    all_floors_accessible: true
  },
  {
    id: 'boyden',
    name: 'Boyden Gymnasium',
    code: 'BOY',
    category: 'recreation',
    location: { lat: 42.38639, lng: -72.53047 },
    google_place_query: 'Boyden Gym, UMass Amherst',
    entrances: [
      e({ id: 'boy-east', name: 'East entrance', lat: 42.386815, lng: -72.530291, step_free: true, door_type: 'push-button', has_ramp: true, ramp_grade_pct: 5.5, osm_id: 13194445946 }),
      e({ id: 'boy-west', name: 'West door', lat: 42.386652, lng: -72.530919, step_free: false, door_type: 'manual', has_ramp: false, notes: 'Tagged wheelchair=no in OpenStreetMap.', osm_id: 8557591252 })
    ],
    elevators: { total_count: 0, working_count: 0, floors_served: 'No elevator to all floors', status: 'none', list: [] },
    accessible_restrooms: false,
    all_floors_accessible: false,
    notes: 'Not all floors are accessible, and Boyden is a common exam location. Ask Disability Services for a relocated exam room if needed.',
    student_reports: [
      { text: 'Boyden and Totman are listed as "not all floors accessible", yet they are common testing centers at exam time.', source: 'Massachusetts Daily Collegian', url: COLLEGIAN_2018, year: 2018 }
    ]
  },
  {
    id: 'recreation-center',
    name: 'Recreation Center',
    code: 'REC',
    category: 'recreation',
    location: { lat: 42.38883, lng: -72.53168 },
    google_place_query: 'UMass Recreation Center, Commonwealth Ave, Amherst',
    entrances: [
      e({ id: 'rec-east', name: 'East main entrance', lat: 42.38884, lng: -72.53122, step_free: true, door_type: 'automatic', has_ramp: true, ramp_grade_pct: 2.5 })
    ],
    elevators: {
      total_count: 1,
      working_count: 1,
      floors_served: 'Levels 1–3',
      status: 'all_operational',
      list: [{ id: 'rec-el-1', name: 'Atrium elevator', floors: '1–3', status: 'operational' }]
    },
    accessible_restrooms: true,
    all_floors_accessible: true
  },
  {
    id: 'whitmore',
    name: 'Whitmore Administration',
    code: 'WHT',
    category: 'administration',
    location: { lat: 42.38595, lng: -72.5267 },
    google_place_query: 'Whitmore Administration Building, UMass Amherst',
    entrances: [
      e({ id: 'wht-north', name: 'North entrance', lat: 42.38634, lng: -72.52668, step_free: true, door_type: 'automatic', has_ramp: true, ramp_grade_pct: 4.5 })
    ],
    elevators: {
      total_count: 2,
      working_count: 2,
      floors_served: 'Floors 1–3',
      status: 'all_operational',
      list: [{ id: 'wht-el-1', name: 'Main elevators', floors: '1–3', status: 'operational' }]
    },
    accessible_restrooms: true,
    all_floors_accessible: true,
    notes: 'Bursar, Registrar and Financial Aid.'
  }
];

export const UMASS_BUILDINGS: Building[] = RAW.map(finalize);

/** Campus-wide research context, shown in the About sheet. */
export const CAMPUS_RESEARCH = [
  {
    finding: 'A dorm elevator stayed broken for four weeks while a wheelchair user lived on that floor.',
    source: 'Massachusetts Daily Collegian, 2023',
    url: COLLEGIAN_2023
  },
  {
    finding: 'Library and ILC automatic doors were out for weeks; campus paths are uneven and rocky.',
    source: 'Massachusetts Daily Collegian, 2023',
    url: COLLEGIAN_2023
  },
  {
    finding: 'Snow plowed onto curb cuts blocks wheelchair users and confuses guide dogs. Disability Services said it relies on reports to know where.',
    source: 'Massachusetts Daily Collegian, 2013',
    url: COLLEGIAN_2013
  },
  {
    finding: 'Boyden and Totman have inaccessible floors but are common exam locations.',
    source: 'Massachusetts Daily Collegian, 2018',
    url: COLLEGIAN_2018
  }
];
