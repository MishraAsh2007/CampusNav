/**
 * Sample indoor route for the ILC (step text, distances, doors and surfaces are mocked for the demo).
 *
 * Step shape:
 *   id, text            spoken + shown instruction
 *   kind                'straight' | 'turn-left' | 'turn-right' | 'door' | 'elevator' | 'arrive'
 *   distanceFt          straight steps
 *   surface             'tile' | 'carpet' | 'wet-tile'   floor along this step
 *   door                'manual' | 'automatic'           door steps
 *   floorFrom, floorTo  elevator steps (numbers; floorFromLabel / floorToLabel for 'C', 'LL' ...)
 *   label               sign text shown in the simulation
 *   panorama            optional equirectangular 360° image URL for this step (overrides imageUrl)
 */
export const SAMPLE_INDOOR_ROUTE = {
  id: 'ilc',
  building: 'Integrative Learning Center',
  destination: 'Room 331',
  steps: [
    { id: 's1', kind: 'door', door: 'automatic', surface: 'wet-tile', label: 'South entrance', text: 'Press the accessible push plate to open the south entrance door.' },
    { id: 's2', kind: 'straight', distanceFt: 50, surface: 'tile', label: 'Atrium', text: 'Go straight 50 feet through the atrium.' },
    { id: 's3', kind: 'turn-right', surface: 'tile', label: 'Elevators', text: 'Turn right toward the elevators.' },
    { id: 's4', kind: 'straight', distanceFt: 25, surface: 'tile', label: 'East elevator lobby', text: 'Go straight 25 feet to the east elevator lobby.' },
    { id: 's5', kind: 'elevator', floorFrom: 1, floorTo: 3, surface: 'tile', label: 'East Elevator', text: 'Take the East Elevator to Floor 3.' },
    { id: 's6', kind: 'straight', distanceFt: 40, surface: 'carpet', label: 'Floor 3 lounge', text: 'Go straight 40 feet across the carpeted lounge.' },
    { id: 's7', kind: 'turn-left', surface: 'carpet', label: 'Rooms 320 to 340', text: 'Turn left at the sign for rooms 320 to 340.' },
    { id: 's8', kind: 'door', door: 'manual', surface: 'carpet', label: 'Corridor door', text: 'Push through the heavy manual corridor door. It has no automatic opener.' },
    { id: 's9', kind: 'straight', distanceFt: 30, surface: 'tile', label: 'Corridor', text: 'Go straight 30 feet down the corridor.' },
    { id: 's10', kind: 'arrive', surface: 'tile', label: 'Room 331', text: 'You have arrived at Room 331, on your right.' }
  ]
};

/**
 * Sample indoor routes, keyed by the building ids used on the outdoor map (src/data/mockBuildings.ts).
 * Step distances, doors and surfaces are plausible demo values, not surveyed measurements.
 */
export const INDOOR_ROUTES = {
  ilc: SAMPLE_INDOOR_ROUTE,

  'campus-center': {
    building: 'Lincoln Campus Center',
    destination: 'Campus Center Auditorium (Level 1)',
    steps: [
      { id: 'cc1', kind: 'door', door: 'automatic', surface: 'wet-tile', label: 'Concourse west entrance', text: 'Press the push plate at the west concourse entrance, by the garage.' },
      { id: 'cc2', kind: 'straight', distanceFt: 60, surface: 'tile', label: 'Concourse', text: 'Go straight 60 feet along the concourse, past the food court.' },
      { id: 'cc3', kind: 'turn-left', surface: 'tile', label: 'Elevators', text: 'Turn left toward the concourse elevators.' },
      { id: 'cc4', kind: 'straight', distanceFt: 20, surface: 'tile', label: 'Elevator lobby', text: 'Go straight 20 feet to the elevator lobby.' },
      { id: 'cc5', kind: 'elevator', floorFrom: 0, floorTo: 1, floorFromLabel: 'C', surface: 'tile', label: 'Concourse Elevator', text: 'Take the concourse elevator up one level to Level 1.' },
      { id: 'cc6', kind: 'straight', distanceFt: 45, surface: 'carpet', label: 'Level 1 lobby', text: 'Go straight 45 feet across the carpeted lobby.' },
      { id: 'cc7', kind: 'turn-right', surface: 'carpet', label: 'Auditorium', text: 'Turn right at the auditorium sign.' },
      { id: 'cc8', kind: 'door', door: 'manual', surface: 'carpet', label: 'Auditorium doors', text: 'Push through the heavy auditorium doors. Ask staff to hold them if needed.' },
      { id: 'cc9', kind: 'arrive', surface: 'carpet', label: 'Auditorium', text: 'You have arrived. Wheelchair seating is in the front row.' }
    ]
  },

  'student-union': {
    building: 'Student Union',
    destination: 'Student Union Ballroom (Level 3)',
    steps: [
      { id: 'su1', kind: 'door', door: 'automatic', surface: 'wet-tile', label: 'West entrance', text: 'Enter through the automatic west entrance doors.' },
      { id: 'su2', kind: 'straight', distanceFt: 35, surface: 'tile', label: 'Main lobby', text: 'Go straight 35 feet into the main lobby.' },
      { id: 'su3', kind: 'turn-right', surface: 'tile', label: 'Central atrium', text: 'Turn right toward the central atrium.' },
      { id: 'su4', kind: 'straight', distanceFt: 30, surface: 'tile', label: 'Atrium elevator', text: 'Go straight 30 feet to the glass atrium elevator.' },
      { id: 'su5', kind: 'elevator', floorFrom: 1, floorTo: 3, surface: 'tile', label: 'Atrium Elevator', text: 'Take the central atrium elevator to Level 3.' },
      { id: 'su6', kind: 'straight', distanceFt: 40, surface: 'carpet', label: 'Ballroom foyer', text: 'Go straight 40 feet through the carpeted ballroom foyer.' },
      { id: 'su7', kind: 'arrive', surface: 'carpet', label: 'Ballroom', text: 'You have arrived at the Ballroom. The accessible entrance is the left double door.' }
    ]
  },

  'dubois-library': {
    building: 'W.E.B. Du Bois Library',
    destination: 'Assistive Technology Center (Lower Level)',
    steps: [
      { id: 'lib1', kind: 'door', door: 'automatic', surface: 'wet-tile', label: 'Main lobby entrance', text: 'Press the push plate at the main lobby entrance.' },
      { id: 'lib2', kind: 'straight', distanceFt: 40, surface: 'tile', label: 'Lobby', text: 'Go straight 40 feet past the information desk.' },
      { id: 'lib3', kind: 'turn-left', surface: 'tile', label: 'Elevators', text: 'Turn left toward the low-rise elevator bank.' },
      { id: 'lib4', kind: 'straight', distanceFt: 20, surface: 'tile', label: 'Elevator lobby', text: 'Go straight 20 feet to the low-rise elevators.' },
      { id: 'lib5', kind: 'elevator', floorFrom: 1, floorTo: 0, floorToLabel: 'LL', surface: 'tile', label: 'Low-rise Elevator', text: 'Take a low-rise elevator down to the Lower Level.' },
      { id: 'lib6', kind: 'straight', distanceFt: 70, surface: 'carpet', label: 'Learning Commons', text: 'Go straight 70 feet through the carpeted Learning Commons.' },
      { id: 'lib7', kind: 'turn-right', surface: 'carpet', label: 'Assistive Technology', text: 'Turn right at the Assistive Technology Center sign.' },
      { id: 'lib8', kind: 'arrive', surface: 'carpet', label: 'Assistive Technology Center', text: 'You have arrived at the Assistive Technology Center.' }
    ]
  }
};

/** Route for a building id, or null if there is no indoor route for it yet. */
export function indoorRouteFor(buildingId) {
  return INDOOR_ROUTES[buildingId] ?? null;
}

/** Indoor friction tags present on a route, worked out from its steps. */
export function surfacesFromSteps(steps) {
  const tags = new Set();
  for (const s of steps) {
    if (s.kind === 'door' && s.door === 'manual') tags.add('heavy-door');
    if (s.surface === 'carpet') tags.add('carpet');
    if (s.surface === 'wet-tile') tags.add('wet-tile');
  }
  return [...tags];
}

export const SAMPLE_WEATHER = { condition: 'Snowing', tempF: 27 };
