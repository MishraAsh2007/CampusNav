# Next indoor candidates: source audit, November 14, 2026

**Implementation update:** the three scoped candidates below are now implemented as
drawing-based backend pilots. See [coverage, commands and remaining limits](ADDITIONAL_INDOOR_PILOTS.md).
The original research notes below describe the pre-implementation assessment.

No current pilot is complete whole-building navigation. Campus Center's 31/31
audit counts selected graph landmarks; it does not mean all rooms/floors exist.
Oak has 34 first-floor wing landmarks disconnected from its exit target. ILC
lacks floor-plan assets on 3/4 and has no fourth-floor destination; Du Bois has
simplified corridors and an aggregate elevator asset. Student Union covers only
the SORC/elevator/Gallery 235 sequence. Brett and Brown remain bounded segments.

These findings are research only. No new routing map, API behavior or frontend
was implemented, and no additional changes were pushed for these candidates.

## Recommended small public-building pilot: Old Chapel

The [official project page](https://www.umass.edu/planning-design-construction/book/old-chapel-renovation-2017)
links its Green Building Tour Guide through SharePoint. The authenticated download
succeeded. The eight-page guide contains both main-floor plans on page 2, showing
the main entry, lobbies, elevator landings, common area, conference room, bathrooms,
auditorium and stage approach. The text documents the accessibility elevator and
stage ramp. Its drawing basis is the 2017 renovation.

This is a strong candidate for coverage of the two main visitor floors. It does
not provide a basement plan; the guide mentions basement kitchen/mechanical
facilities. Basement and tower navigation must remain outside the proposed scope.
Tracing and matching the outdoor approach to the correct entrance are still work
to do. This is not an implemented or physically verified complete-building route.

Downloaded source, hash and rendered review pages are in the ignored
`data/private/indoor_candidate_research/` directory.

## Recommended residence: North Apartment D

The [official residence page](https://www.umass.edu/living/housing-options/residence-directory/apartments/north-apartments)
identifies five-story buildings with elevators and links the authenticated plans.
Both of these downloaded files were visually inspected:

- `673-01.pdf`: first floor, including entrance/lobby, shared corridors, lounges,
  laundry, bathrooms and the elevator core. Its print date is October 9, 2024;
  the revision field says "No Date".
- `673-02.03.04.05.pdf`: the drawing itself explicitly labels floors 2, 3, 4 and
  5. Its revision date is September 15, 2026. The repeated shared-hall layout
  includes apartment entrance approaches and the elevator core.

The source folder is `North Apartments/North D` in the already imported UMass
residence-floor-plan library. The existing GIS-derived catalog has two entrance
records labeled step-free and keycard-controlled, plus one mapped elevator
location. Those map attributes retain the source's August 2022 edition; a point
is not a verified count of independent elevator cars.

All five floor references are available for shared-circulation tracing. The
proposed endpoints would be outside apartment entrances, not inside bedrooms or
apartments. Entrance-to-plan alignment, actual elevator service and resident
access still need confirmation before claiming current accessible navigation.
There is no North D routing graph yet.

North A is less convincing for fifth-floor coverage: its grouped filename includes
05, but its inspected drawing header lists only floors 2–4. Do not expand North A
to floor 5 solely from that filename. North B/C/D explicitly list all four upper
floors; D is a suitable next residence candidate, not the only possible one.

## Larger central-campus alternative: Goodell

[UMass's April 2025 reopening article](https://www.umass.edu/news/article/goodell-hall-officially-reopens-ribbon-cutting-open-house)
identifies student-service levels 3–6 and publishes a March 2025 plan. The original
[5326×4013 image](https://www.umass.edu/sites/default/files/2025-04/Goodell%20Floorplan%20March%202025.jpg)
was downloaded and inspected; the article's 480-pixel preview hides useful detail.
The image shows corridors, door swings, department areas and vertical cores on
all four service levels.

Goodell offers broad, current source coverage for department-level destinations.
Individual office numbers are largely absent from this color-coded directory
plan, and tracing must distinguish stairs from step-free alternatives. It is a
larger task than Old Chapel, not already complete navigation to every office.

## Suggested order

1. Old Chapel: smallest coherent public-area scope across two main floors.
2. North D: all five floor references for shared-hall-to-lobby dorm navigation.
3. Goodell: broader student-service coverage after the smaller pilot works.

Source-plan completeness, graph completeness and current physical accessibility
are separate claims. These candidates improve the first; the latter two still
require implementation and appropriate confirmation.
